import datetime as dt
import itertools
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Article,
    ArticleAnalysis,
    ArticleCompany,
    Company,
    Idea,
    IdeaOutcome,
    Listing,
    PriceDaily,
    Setting,
    SignalScore,
    Source,
)
from app.prices_se import add_weekdays, due_idea_listings
from app.radar import INSIDER_BUYING, QUIET_GOOD_NEWS, run_radar
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
NOW = dt.datetime(2026, 10, 21, 10, 0, tzinfo=dt.UTC)  # Wednesday
_ids = itertools.count(1)


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def company(db: Session, key: str) -> Company:
    return db.scalars(select(Company).where(Company.key == key)).one()


def article(db: Session, key: str, *, source: str = "mfn", event: str = "orders",
            tone: float = 0.6, hours_ago: float = 2, raw: dict | None = None) -> Article:
    n = next(_ids)
    src = db.scalars(select(Source).where(Source.key == source)).one()
    a = Article(topic="stocks", source_id=src.id, url=f"https://x.test/{n}", url_hash=f"{n:064}",
                content_hash=f"{n:064}", title=f"news {n}", tag_status="tagged", raw=raw,
                published_at=NOW - dt.timedelta(hours=hours_ago))
    db.add(a)
    db.flush()
    db.add(ArticleAnalysis(article_id=a.id, event_type=event, basis="announced",
                           sentiment=Decimal(str(tone)), importance=Decimal("0.7"), summary="s",
                           model="m", prompt_version="v"))
    db.add(ArticleCompany(article_id=a.id, company_id=company(db, key).id, matched_alias=key))
    db.flush()
    return a


def score(db: Session, key: str, value: float, *, label: str, tone: float,
          move: float = 0.3) -> None:
    db.add(SignalScore(
        company_id=company(db, key).id, date=NOW.date(), score=Decimal(str(value)), weights={},
        components={"factors": {"sentiment_shift": {"tone_24h": tone}},
                    "market": {"label": label, "return_pct": move, "typical_move_pct": 1.8}},
    ))


def us_buy(db: Session, key: str, owner: str, role: str, value: int, days_ago: float = 1):
    article(db, key, source="sec-insiders", event="insider_trade", tone=0.5,
            hours_ago=24 * days_ago, raw={"form": "4", "owner": owner, "role": role,
                                          "value_usd": value})


def radar_ideas(db: Session) -> list[tuple[str, str]]:
    rows = db.execute(select(Company.key, Idea.signal).join(Idea, Idea.company_id == Company.id)
                      .where(Idea.origin == "radar").order_by(Company.key)).all()
    return [tuple(r) for r in rows]


def test_quiet_good_news_needs_the_label_positive_tone_and_real_news(db: Session) -> None:
    article(db, "nvidia")
    score(db, "nvidia", 55, label="not_priced_in_yet", tone=0.5)
    article(db, "tesla")
    score(db, "tesla", 60, label="moving_with_news", tone=0.5)  # already moving
    article(db, "apple", tone=-0.4)
    score(db, "apple", 50, label="not_priced_in_yet", tone=-0.3)  # bad news
    us_buy(db, "microsoft", "A", "Director", 50_000)  # only an insider trade
    score(db, "microsoft", 45, label="not_priced_in_yet", tone=0.5)
    article(db, "amazon")
    score(db, "amazon", 50, label="not_priced_in_yet", tone=0.5, move=-2.5)  # it did move
    db.commit()

    report = run_radar(db, TOPIC, now=NOW)

    assert radar_ideas(db) == [("nvidia", QUIET_GOOD_NEWS)]
    idea = db.scalars(select(Idea).where(Idea.origin == "radar")).one()
    assert idea.details["score"] == 55 and len(idea.details["article_ids"]) == 1
    assert idea.benchmark == "S&P 500" and idea.confidence is None and idea.briefing_id is None
    assert [signal for signal, _ in report.logged] == [QUIET_GOOD_NEWS]


def test_insider_buying_needs_two_buyers_or_one_big_senior_purchase(db: Session) -> None:
    us_buy(db, "nvidia", "Jensen", "CEO", 300_000)  # one senior, big
    us_buy(db, "tesla", "A", "Director", 20_000)
    us_buy(db, "tesla", "B", "Director", 30_000, days_ago=10)  # two different insiders
    us_buy(db, "apple", "C", "CEO", 100_000)  # one, below the big-purchase line
    us_buy(db, "microsoft", "D", "Director", 50_000, days_ago=12)
    us_buy(db, "microsoft", "E", "Director", 50_000, days_ago=8)  # nothing new for days
    db.commit()

    run_radar(db, TOPIC, now=NOW)

    assert radar_ideas(db) == [("nvidia", INSIDER_BUYING), ("tesla", INSIDER_BUYING)]
    tesla = db.scalars(select(Idea).join(Company).where(Company.key == "tesla")).one()
    assert [b["name"] for b in tesla.details["buyers"]] == ["B", "A"]  # biggest first
    assert tesla.details["total"] == 50_000 and tesla.details["currency"] == "USD"


def test_cooldown_daily_cap_and_markets_turned_off(db: Session) -> None:
    us_buy(db, "nvidia", "Jensen", "CEO", 300_000)
    db.commit()
    run_radar(db, TOPIC, now=NOW)
    report = run_radar(db, TOPIC, now=NOW + dt.timedelta(hours=1))
    assert report.cooldown == 1 and len(radar_ideas(db)) == 1

    # Swedish hits: one per signal and day, the strongest first.
    for key, n in (("volvo", 2), ("skf", 3)):
        for i in range(n):
            article(db, key, source="fi-insider", event="insider_trade", tone=0.5,
                    raw={"register": "fi-insyn", "person": f"{key}{i}", "role": "Styrelseledamot",
                         "value_sek": 200_000})
    db.commit()
    report = run_radar(db, TOPIC, now=NOW + dt.timedelta(hours=2))
    assert ("skf", INSIDER_BUYING) in radar_ideas(db)
    assert ("volvo", INSIDER_BUYING) not in radar_ideas(db) and report.capped == 1

    db.add(Setting(key="markets", value={"US": False}))
    us_buy(db, "tesla", "T", "CEO", 900_000)
    db.commit()
    run_radar(db, TOPIC, now=NOW + dt.timedelta(hours=3))
    assert ("tesla", INSIDER_BUYING) not in radar_ideas(db)


def test_swedish_ideas_get_prices_only_on_entry_and_checkpoint_days(db: Session) -> None:
    assert add_weekdays(dt.date(2026, 10, 16), 1) == dt.date(2026, 10, 19)  # Fri -> Mon
    assert add_weekdays(dt.date(2026, 10, 19), 4) == dt.date(2026, 10, 23)
    se_mics = {m for mk in TOPIC.markets if mk.key == "SE" for m in mk.mics}
    volvo = db.scalars(select(Listing).join(Company).where(Company.key == "volvo",
                                                            Listing.is_primary)).one()
    idea = Idea(origin="user", company_id=volvo.company_id, listing_id=volvo.id, thesis="t",
                benchmark="OMXS30", published_at=dt.datetime(2026, 10, 19, 6, 0, tzinfo=dt.UTC))
    db.add(idea)
    db.commit()

    def due(day: dt.date) -> bool:
        now = dt.datetime.combine(day, dt.time(12), tzinfo=dt.UTC)
        return volvo.id in due_idea_listings(db, se_mics, now, day)

    assert due(dt.date(2026, 10, 19))  # entry day: needs its first price

    def price(day: dt.date) -> None:
        db.add(PriceDaily(listing_id=volvo.id, date=day, open=Decimal(100), close=Decimal(101),
                          source="test"))
        db.commit()

    price(dt.date(2026, 10, 19))
    idea.entry_date = dt.date(2026, 10, 19)
    db.add(IdeaOutcome(idea_id=idea.id, horizon_days=1, exit_date=dt.date(2026, 10, 19),
                       exit_price=Decimal(101), return_pct=Decimal(1)))
    db.commit()
    # The 5-day checkpoint is Friday the 23rd; no requests in between.
    assert not due(dt.date(2026, 10, 21)) and not due(dt.date(2026, 10, 22))
    assert due(dt.date(2026, 10, 23))
    price(dt.date(2026, 10, 23))
    assert not due(dt.date(2026, 10, 23))  # has it now
