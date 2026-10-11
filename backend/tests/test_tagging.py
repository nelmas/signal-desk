import datetime as dt
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import LLMClient
from app.config import Settings
from app.models import (
    AICall,
    Article,
    ArticleAnalysis,
    ArticleCompany,
    Company,
    Source,
    TrackedStock,
)
from app.sync import sync_topic
from app.tagging import tag_pending
from app.tagging.matcher import CompanyIndex
from app.topic import load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
SETTINGS = Settings(gemini_api_key="test-key", llm_tag_requests_per_run=10)

Answer = Callable[[int, list[str]], dict[str, Any]]


class FakeGemini:
    """Answers like the Gemini REST API. `answer(article_id, candidate_keys)` builds each result."""

    def __init__(self, answer: Answer, status: int = 200) -> None:
        self.answer = answer
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"url": str(request.url), "headers": request.headers, "body": body})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "nope"}})
        text = body["contents"][0]["parts"][0]["text"]
        results = []
        pattern = r"<article id=(\d+)>.*?Candidates: ([^\n]*)"
        for article_id, candidates in re.findall(pattern, text, re.S):
            keys = [c.split(" (")[0] for c in candidates.split("; ")]
            results.append({"id": int(article_id), **self.answer(int(article_id), keys)})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps({"results": results})}]}}
                ],
                "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 120},
            },
        )


def tag_all(article_id: int, keys: list[str]) -> dict[str, Any]:
    return {
        "companies": [{"key": k, "role": "subject", "sentiment": 0.6} for k in keys],
        "event_type": "contract",
        "basis": "announced",
        "importance": 0.7,
        "summary": "Company won an order.",
    }


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def add_article(
    session: Session,
    title: str,
    summary: str = "",
    raw: dict | None = None,
    source: str = "mfn",
    url: str | None = None,
) -> Article:
    source_row = session.scalars(select(Source).where(Source.key == source)).one()
    n = session.scalar(select(func.count()).select_from(Article)) or 0
    article = Article(
        topic="stocks",
        source_id=source_row.id,
        url=url or f"https://example.com/{n}",
        url_hash=f"{n:064d}",
        content_hash=f"{n:064d}",
        title=title,
        summary=summary,
        published_at=dt.datetime(2026, 10, 9, 7, 0, tzinfo=dt.UTC) + dt.timedelta(minutes=n),
        raw=raw,
    )
    session.add(article)
    session.commit()
    return article


def run(session: Session, fake: FakeGemini, settings: Settings = SETTINGS, **kw):
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        llm = LLMClient(client, session, "test-key")
        return tag_pending(session, llm, TOPIC, settings, sleep=lambda s: None, **kw)


def company_keys(session: Session, article: Article) -> set[str]:
    return set(
        session.scalars(
            select(Company.key).join(ArticleCompany).where(ArticleCompany.article_id == article.id)
        )
    )


# --- name matching (free step) ---------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Volvo receives order for 1,000 trucks", {"volvo"}),
        ("H&M sales beat expectations", {"hm"}),
        ("Hennes & Mauritz: kvartalsrapport", {"hm"}),
        ("JP Morgan raises target for Ericsson", {"jpmorgan", "ericsson"}),
        ("Rapporten visade en tydlig förbättring", set()),  # "visade" is not "Visa"
        ("Swedish Open squash final in Stockholm", set()),
    ],
)
def test_matcher_finds_whole_names_only(db: Session, title: str, expected: set[str]) -> None:
    index = CompanyIndex.load(db, TOPIC)
    found = index.match(add_article(db, title))
    assert {index.keys[c] for c in found} == expected


def test_matcher_uses_finnhub_symbol(db: Session) -> None:
    index = CompanyIndex.load(db, TOPIC)
    found = index.match(add_article(db, "Chip stocks rally", raw={"queried_symbol": "NVDA"}))
    assert {index.keys[c]: alias for c, alias in found.items()} == {"nvidia": "symbol:NVDA"}


def keys_of(index: CompanyIndex, found: dict[int, str]) -> set[str]:
    return {index.keys[c] for c in found}


def test_text_matches_stay_in_the_articles_market_unless_watched(db: Session) -> None:
    title = "Ericsson wins 5G deal; JP Morgan arranges financing"
    article = add_article(db, title)  # MFN: a Swedish source
    index = CompanyIndex.load(db, TOPIC)
    assert keys_of(index, index.match(article, "SE")) == {"ericsson"}

    jpm = db.scalars(select(Company).where(Company.key == "jpmorgan")).one()
    db.add(TrackedStock(company_id=jpm.id))
    db.commit()
    index = CompanyIndex.load(db, TOPIC)
    assert keys_of(index, index.match(article, "SE")) == {"ericsson", "jpmorgan"}


def test_sec_filings_match_exactly_by_company_id(db: Session) -> None:
    apple = db.scalars(select(Company).where(Company.key == "apple")).one()
    apple.cik = "0000320193"
    db.commit()
    index = CompanyIndex.load(db, TOPIC)
    sec = "https://www.sec.gov/Archives/edgar/data/320193/x-index.htm"
    filing = add_article(db, "8-K - Apple Inc. (0000320193) (Filer)", source="sec-8k", url=sec)
    other = add_article(
        db, "8-K - Apple Hospitality REIT (0001418121) (Filer)", source="sec-8k", url=sec + "2"
    )
    assert index.match(filing, "US") == {apple.id: "cik:0000320193"}
    assert index.match(other, "US") == {}  # name says Apple, but it's another company


def test_press_releases_match_their_issuer_from_the_link(db: Session) -> None:
    index = CompanyIndex.load(db, TOPIC)
    mfn = add_article(db, "Interim report January-September 2026",
                      url="https://mfn.se/a/volvo/interim-report-q3")
    cision = add_article(db, "Delårsrapport", url="https://news.cision.com/se/ab-skf/r/delarsrapport,c1")
    assert keys_of(index, index.match(mfn, "SE")) == {"volvo"}
    assert keys_of(index, index.match(cision, "SE")) == {"skf"}


# --- AI step ---------------------------------------------------------------------------


def test_tags_matches_and_settles_non_matches_without_ai(db: Session) -> None:
    volvo = add_article(db, "Volvo receives order for 1,000 trucks")
    book = add_article(db, "New novel explores life in 1920s Gothenburg")
    fake = FakeGemini(tag_all)

    report = run(db, fake)

    assert (report.tagged, report.no_match, report.requests) == (1, 1, 1)
    db.refresh(volvo), db.refresh(book)
    assert volvo.tag_status == "tagged" and book.tag_status == "no_match"
    assert company_keys(db, volvo) == {"volvo"}
    analysis = db.get(ArticleAnalysis, volvo.id)
    assert analysis.event_type == "contract" and float(analysis.sentiment) == 0.6
    assert analysis.model == SETTINGS.llm_tag_model
    # Only the matching article was sent, and the key went in a header.
    sent = fake.calls[0]["body"]["contents"][0]["parts"][0]["text"]
    assert "Volvo" in sent and "novel" not in sent
    assert fake.calls[0]["headers"]["x-goog-api-key"] == "test-key"
    assert "key=" not in fake.calls[0]["url"]
    call = db.scalars(select(AICall)).one()
    assert call.ok and call.input_tokens == 900 and float(call.cost_usd) == 0


def test_ai_cannot_add_companies_or_event_types(db: Session) -> None:
    article = add_article(db, "Volvo receives order")

    def invent(article_id: int, keys: list[str]) -> dict[str, Any]:
        companies = [{"key": k, "role": "boss", "sentiment": 7} for k in keys]
        companies += [{"key": "tesla", "role": "subject", "sentiment": 1}, {"key": "made-up-co"}]
        return {**tag_all(article_id, keys), "companies": companies,
                "event_type": "moon_landing", "basis": "gossip", "importance": -2}

    run(db, FakeGemini(invent))
    assert company_keys(db, article) == {"volvo"}
    analysis = db.get(ArticleAnalysis, article.id)
    assert analysis.event_type == "other" and analysis.basis == "reported"
    assert float(analysis.sentiment) == 1 and float(analysis.importance) == 0
    tag = db.scalars(select(ArticleCompany).where(ArticleCompany.article_id == article.id)).one()
    assert tag.role == "subject"


def test_each_company_gets_its_own_role_and_tone(db: Session) -> None:
    article = add_article(db, "Apple cuts orders; Broadcom shares fall", source="finnhub-news")

    def split(article_id: int, keys: list[str]) -> dict[str, Any]:
        return {**tag_all(article_id, keys), "basis": "reported", "event_type": "operations",
                "companies": [{"key": "broadcom", "role": "affected", "sentiment": -0.8},
                              {"key": "apple", "role": "subject", "sentiment": -0.3}]}

    run(db, FakeGemini(split))
    tags = {
        key: (role, float(s))
        for key, role, s in db.execute(
            select(Company.key, ArticleCompany.role, ArticleCompany.sentiment)
            .join(ArticleCompany)
            .where(ArticleCompany.article_id == article.id)
        )
    }
    assert tags == {"apple": ("subject", -0.3), "broadcom": ("affected", -0.8)}
    analysis = db.get(ArticleAnalysis, article.id)
    # Article-level tone follows the main subject, not the first company listed.
    assert float(analysis.sentiment) == -0.3
    assert (analysis.basis, analysis.event_type) == ("reported", "operations")


def test_passing_mentions_are_marked_irrelevant(db: Session) -> None:
    article = add_article(db, "Ericsson wins deal; Visa named as payment partner")
    report = run(db, FakeGemini(lambda i, keys: {**tag_all(i, keys), "companies": []}))
    db.refresh(article)
    assert report.irrelevant == 1 and article.tag_status == "irrelevant"
    assert db.get(ArticleAnalysis, article.id) is None


def test_rate_limit_stops_run_and_leaves_articles_pending(db: Session) -> None:
    article = add_article(db, "Volvo receives order")
    report = run(db, FakeGemini(tag_all, status=429))
    db.refresh(article)
    assert "429" in (report.stopped or "")
    assert article.tag_status == "pending" and article.tag_attempts == 0
    assert db.scalars(select(AICall)).one().ok is False


def test_failed_answers_retry_then_give_up(db: Session) -> None:
    article = add_article(db, "Volvo receives order")
    for _ in range(3):
        run(db, FakeGemini(tag_all, status=500))
    db.refresh(article)
    assert article.tag_status == "failed" and article.tag_attempts == 3


def test_daily_budget_is_respected(db: Session) -> None:
    for i in range(40):
        add_article(db, f"Volvo order number {i}")
    tight = Settings(gemini_api_key="k", llm_tag_requests_per_run=25, llm_tag_requests_per_day=2)
    report = run(db, FakeGemini(tag_all), tight)
    assert report.requests == 2 and report.tagged == 30  # 2 batches of 15
    assert "budget" in (report.stopped or "")
    # The next run today finds the day's budget already spent.
    assert run(db, FakeGemini(tag_all), tight).requests == 0


def test_without_api_key_only_name_matching_runs(db: Session) -> None:
    add_article(db, "Volvo receives order")
    add_article(db, "Squash final")
    report = tag_pending(db, None, TOPIC, SETTINGS)
    assert report.no_match == 1 and report.requests == 0 and "GEMINI_API_KEY" in report.stopped
