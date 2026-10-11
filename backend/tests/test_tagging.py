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
from app.models import AICall, Article, ArticleAnalysis, ArticleCompany, Company, Source
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
        "companies": keys,
        "event_type": "contract",
        "sentiment": 0.6,
        "importance": 0.7,
        "summary": "Company won an order.",
    }


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def add_article(
    session: Session, title: str, summary: str = "", raw: dict | None = None
) -> Article:
    source = session.scalars(select(Source).where(Source.key == "mfn")).one()
    n = session.scalar(select(func.count()).select_from(Article)) or 0
    article = Article(
        topic="stocks",
        source_id=source.id,
        url=f"https://example.com/{n}",
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
    index = CompanyIndex.load(db, "stocks")
    found = index.match(add_article(db, title))
    assert {index.keys[c] for c in found} == expected


def test_matcher_uses_finnhub_symbol(db: Session) -> None:
    index = CompanyIndex.load(db, "stocks")
    found = index.match(add_article(db, "Chip stocks rally", raw={"queried_symbol": "NVDA"}))
    assert {index.keys[c]: alias for c, alias in found.items()} == {"nvidia": "symbol:NVDA"}


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
        return {**tag_all(article_id, keys), "companies": [*keys, "tesla", "made-up-co"],
                "event_type": "moon_landing", "sentiment": 7, "importance": -2}

    run(db, FakeGemini(invent))
    assert company_keys(db, article) == {"volvo"}
    analysis = db.get(ArticleAnalysis, article.id)
    assert analysis.event_type == "other"
    assert float(analysis.sentiment) == 1 and float(analysis.importance) == 0


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
