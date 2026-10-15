import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import LLMClient, LLMUnavailable
from app.briefing import generate_briefing, is_due, render_text
from app.briefing.generate import window_start
from app.briefing.stories import build_stories
from app.config import Settings
from app.models import (
    Article,
    ArticleAnalysis,
    ArticleCompany,
    Briefing,
    Citation,
    Company,
    Idea,
    SignalScore,
    Source,
    Story,
    StoryArticle,
    TrackedStock,
)
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
SETTINGS = Settings(gemini_api_key="k")
NOW = dt.datetime(2026, 10, 15, 6, 0, tzinfo=dt.UTC)  # 08:00 in Stockholm, after 07:00


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def company(db: Session, key: str) -> Company:
    return db.scalars(select(Company).where(Company.key == key)).one()


def tagged(db: Session, key: str, title: str, *, source: str = "mfn", hours_ago: float = 2,
           event: str = "contract", basis: str = "announced", importance: float = 0.7,
           sentiment: float = 0.5, also: str | None = None) -> int:
    src = db.scalars(select(Source).where(Source.key == source)).one()
    n = db.scalar(select(func.count()).select_from(Article)) or 0
    article = Article(topic="stocks", source_id=src.id, url=f"https://news/{n}",
                      url_hash=f"{n:064d}", content_hash=f"{n:064d}", title=title,
                      published_at=NOW - dt.timedelta(hours=hours_ago), tag_status="tagged")
    db.add(article)
    db.flush()
    db.add(ArticleAnalysis(article_id=article.id, event_type=event, basis=basis,
                           sentiment=Decimal(str(sentiment)), importance=Decimal(str(importance)),
                           summary=f"Summary of {title}", model="m", prompt_version="tag-v3"))
    db.add(ArticleCompany(article_id=article.id, company_id=company(db, key).id,
                          matched_alias=key, role="subject", sentiment=Decimal(str(sentiment))))
    if also:
        db.add(ArticleCompany(article_id=article.id, company_id=company(db, also).id,
                              matched_alias=also, role="affected", sentiment=Decimal("0")))
    db.commit()
    return article.id


def score(db: Session, key: str, value: float, tone: float = 0.5, label: str = "small_move"):
    db.add(SignalScore(
        company_id=company(db, key).id, date=dt.date(2026, 10, 15), score=Decimal(str(value)),
        components={"factors": {"sentiment_shift": {"tone_24h": tone}}, "market": {"label": label}},
        weights={},
    ))
    db.commit()


def hold(db: Session, key: str, note: str) -> None:
    db.add(TrackedStock(company_id=company(db, key).id, is_holding=True, note=note))
    db.commit()


@pytest.fixture
def news(db: Session) -> dict[str, Any]:
    ids = {
        "apple": [tagged(db, "apple", f"Apple cuts orders ({s})", source=s, event="operations",
                         basis="reported", sentiment=-0.5, importance=0.8)
                  for s in ("finnhub-news", "mfn", "cision-se")],
        "apple_ceo": [tagged(db, "apple", "Apple names new CEO", event="management_change")],
        "volvo": [tagged(db, "volvo", "Volvo wins record truck order", importance=0.9,
                         sentiment=0.7)],
        "nvidia": [tagged(db, "nvidia", "Nvidia signs supply deal", source="sec-8k",
                          importance=0.4, sentiment=0.4)],
    }
    score(db, "volvo", 70, tone=0.7, label="not_priced_in_yet")
    score(db, "apple", 60, tone=-0.4)
    score(db, "nvidia", 45, tone=0.4)
    hold(db, "nvidia", "Via fund, 5.7% of fund")
    return ids


class FakeGemini:
    def __init__(self, build) -> None:
        self.build = build
        self.prompts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["contents"][0]["parts"][0]["text"]
        self.prompts.append(prompt)
        answer = self.build(prompt)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}],
            "usageMetadata": {"promptTokenCount": 3000, "candidatesTokenCount": 800},
        })


def story_numbers(prompt: str) -> dict[str, int]:
    """Company key -> story number, from 'Story N: Name (key K, ...'."""
    return {k: int(n) for n, k in re.findall(r"Story (\d+): .*?\(key ([\w-]+),", prompt)}


def good_answer(ids: dict) -> Any:
    def build(prompt: str) -> dict:
        n = story_numbers(prompt)
        return {
            "overview": {"text": "Volvo won a record order; Apple reportedly cut orders.",
                         "cites": [ids["volvo"][0], ids["apple"][0]]},
            "holdings": [{"company": "nvidia", "text": "Nvidia (5.7% of your fund) signed a deal.",
                          "cites": ids["nvidia"]}],
            "stories": [
                {"story": n["volvo"], "headline": "Volvo's record order",
                 "what_happened": "Volvo won its largest order.",
                 "what_happened_cites": ids["volvo"],
                 "what_it_means": "Visibility improves.", "what_it_means_cites": [],
                 "what_next": "Could lead to more orders.", "what_next_cites": ids["volvo"]},
                {"story": n["apple"], "headline": "Apple reportedly cuts orders",
                 "what_happened": "Apple reportedly cut component orders.",
                 "what_happened_cites": ids["apple"][:2],
                 "what_it_means": "Demand may be soft.", "what_next": "Watch the next report."},
            ],
            "sectors": [{"name": "Industrials", "direction": "up", "reason": "Truck orders.",
                         "cites": ids["volvo"]}],
            "ideas": [{"company": "volvo", "why_rise": "Record order.",
                       "why_rise_cites": ids["volvo"],
                       "risks": "Cycle may turn.", "risks_cites": [], "confidence": "medium"}],
        }
    return build


def run(db: Session, fake: FakeGemini, **kw) -> Briefing:
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        return generate_briefing(
            db, LLMClient(client, db, "k", sleep=lambda s: None), TOPIC, SETTINGS, now=NOW, **kw
        )


# --- stories --------------------------------------------------------------------------


def test_articles_group_into_stories_by_company_and_event(db: Session, news) -> None:
    stories = build_stories(db, "stocks", NOW - dt.timedelta(days=1), NOW, dt.date(2026, 10, 15))
    keys = [s.key for s in stories]
    assert sorted(keys) == sorted(["apple:operations", "apple:management_change",
                                   "volvo:contract", "nvidia:contract"])
    apple = next(s for s in stories if s.key == "apple:operations")
    assert len(apple.articles) == 3 and apple.tone < 0
    nvidia = next(s for s in stories if s.key == "nvidia:contract")
    assert nvidia.is_holding and nvidia.holding_note == "Via fund, 5.7% of fund"
    assert keys[0] == "volvo:contract"  # most important, trusted and highest scored


def test_an_article_counts_once_under_its_main_company(db: Session) -> None:
    tagged(db, "volvo", "Volvo order affects SKF", also="skf")
    stories = build_stories(db, "stocks", NOW - dt.timedelta(days=1), NOW, NOW.date())
    assert [s.key for s in stories] == ["volvo:contract"]
    assert stories[0].other_companies == {company(db, "skf").id}


# --- briefing -------------------------------------------------------------------------


def test_briefing_is_written_checked_numbered_and_stored(db: Session, news) -> None:
    fake = FakeGemini(good_answer(news))
    briefing = run(db, fake)

    c = briefing.content
    assert briefing.status == "ready" and briefing.date == dt.date(2026, 10, 15)
    # Sources are numbered in reading order: overview first.
    assert c["overview"]["cites"] == [1, 2]
    assert c["sources"][0]["title"] == "Volvo wins record truck order"
    assert [s["headline"] for s in c["stories"]] == ["Volvo's record order",
                                                      "Apple reportedly cuts orders"]
    # A part without its own sources inherits the story's facts.
    assert c["stories"][0]["what_it_means"]["cites"] == c["stories"][0]["what_happened"]["cites"]
    assert c["holdings"] == [{
        "company": "nvidia", "name": "NVIDIA Corporation", "share": "5.7% of your fund",
        "text": "Summary of Nvidia signs supply deal", "cites": [3],
    }]
    assert c["ideas"][0]["market"] == "no clear price reaction yet"

    assert db.scalar(select(func.count()).select_from(Story)) == 2
    assert db.scalar(select(func.count()).select_from(StoryArticle)) == 4  # 1 Volvo + 3 Apple
    idea = db.scalars(select(Idea)).one()
    assert idea.company_id == company(db, "volvo").id and idea.benchmark == "OMXS30"
    assert {c.ordinal for c in db.scalars(select(Citation))} == set(range(1, len(c["sources"]) + 1))

    text = render_text(briefing)
    assert "NEWS ABOUT YOUR HOLDINGS" in text and "[1]" in text and "SOURCES" in text
    assert "not buy or sell advice" in text
    # The prompt offered the AI only real articles and candidates.
    assert "Nvidia signs supply deal" in fake.prompts[0]
    assert "IDEA CANDIDATES:\nVolvo" in fake.prompts[0].replace("AB Volvo", "Volvo")


def test_inventions_and_unsourced_claims_are_dropped(db: Session, news) -> None:
    def bad(prompt: str) -> dict:
        n = story_numbers(prompt)
        return {
            "overview": {"text": "Everything is great.", "cites": [999999]},
            "holdings": [{"company": "made-up-co", "text": "x", "cites": news["volvo"]}],
            "stories": [
                {"story": 99, "headline": "No such story", "what_happened": "x",
                 "what_happened_cites": news["volvo"], "what_it_means": "", "what_next": ""},
                {"story": n["volvo"], "headline": "Unsourced", "what_happened": "Claim.",
                 "what_happened_cites": [999999], "what_it_means": "", "what_next": ""},
                {"story": n["apple"], "headline": "Apple", "what_happened": "Orders cut.",
                 "what_happened_cites": news["apple"], "what_it_means": "m", "what_next": "n"},
            ],
            "sectors": [{"name": "Tech", "direction": "sideways", "reason": "r", "cites": []}],
            "ideas": [
                {"company": "made-up-co", "why_rise": "x", "why_rise_cites": news["volvo"],
                 "risks": "y", "confidence": "high"},
                {"company": "apple", "why_rise": "x", "why_rise_cites": news["apple"],
                 "risks": "y", "confidence": "high"},  # negative tone: not a candidate
                {"company": "volvo", "why_rise": "x", "why_rise_cites": news["apple"],
                 "risks": "y", "confidence": "certain"},  # cites another company's news
            ],
        }

    c = run(db, FakeGemini(bad)).content
    assert c["overview"]["text"] == ""
    assert [h["company"] for h in c["holdings"]] == ["nvidia"]  # from code, not the AI
    assert [s["headline"] for s in c["stories"]] == ["Apple"]
    assert c["sectors"] == [] and c["ideas"] == []
    assert db.scalar(select(func.count()).select_from(Idea)) == 0
    dropped = c["checks"]["dropped"]
    assert "story 99: not one of the offered stories" in dropped
    assert "idea 'made-up-co': not an offered candidate" in dropped
    assert "idea 'volvo': missing reasons or its own sources" in dropped
    assert "overview: no valid sources" in dropped


def test_ideas_may_name_the_company_instead_of_its_key(db: Session, news) -> None:
    def by_name(prompt: str) -> dict:
        answer = good_answer(news)(prompt)
        answer["ideas"][0]["company"] = "AB Volvo"
        return answer

    ideas = run(db, FakeGemini(by_name)).content["ideas"]
    assert [i["company"] for i in ideas] == ["volvo"]


def test_due_after_send_time_and_once_a_day(db: Session, news) -> None:
    early = dt.datetime(2026, 10, 15, 4, 0, tzinfo=dt.UTC)  # 06:00 Stockholm
    assert not is_due(db, TOPIC, early)
    assert is_due(db, TOPIC, NOW)
    run(db, FakeGemini(good_answer(news)))
    assert not is_due(db, TOPIC, NOW + dt.timedelta(hours=3))


def test_window_covers_the_gap_since_the_last_briefing(db: Session) -> None:
    assert window_start(db, TOPIC, NOW) == NOW - dt.timedelta(hours=24)
    db.add(Briefing(topic="stocks", date=dt.date(2026, 10, 13), language="en",
                    created_at=NOW - dt.timedelta(hours=48)))
    db.commit()
    assert window_start(db, TOPIC, NOW) == NOW - dt.timedelta(hours=48)


def test_busy_model_falls_back_to_the_second_model(db: Session, news) -> None:
    good = FakeGemini(good_answer(news))
    def busy_primary(request: httpx.Request) -> httpx.Response:
        if SETTINGS.llm_briefing_model in str(request.url):
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return good(request)
    briefing = run(db, busy_primary)
    assert briefing.model == SETTINGS.llm_briefing_fallback_model
    assert briefing.content["stories"]


def test_both_models_busy_saves_nothing(db: Session, news) -> None:
    def busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "high demand"}})
    with pytest.raises(LLMUnavailable):
        run(db, busy)
    assert db.scalar(select(func.count()).select_from(Briefing)) == 0


def test_quiet_window_needs_no_ai_call(db: Session) -> None:
    fake = FakeGemini(lambda p: {})
    briefing = run(db, fake)
    assert fake.prompts == [] and briefing.content["stories"] == []
    assert "quiet window" in render_text(briefing)


def test_force_replaces_todays_briefing(db: Session, news) -> None:
    first = run(db, FakeGemini(good_answer(news)))
    assert run(db, FakeGemini(good_answer(news))).id == first.id  # no force: reused
    run(db, FakeGemini(good_answer(news)), force=True)
    assert db.scalar(select(func.count()).select_from(Briefing)) == 1
    assert db.scalar(select(func.count()).select_from(Story)) == 2
