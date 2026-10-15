import datetime as dt
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    BenchmarkPrice,
    Briefing,
    Company,
    Idea,
    Listing,
    PriceDaily,
    SignalScore,
    TrackedStock,
)
from app.prices import last_completed_session, update_prices
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
SETTINGS = Settings(twelve_data_api_key="td-key", price_top_scorers=2)
# Wednesday 14 Oct 2026, 08:00 in New York: the last completed session is Tuesday the 13th.
NOW = dt.datetime(2026, 10, 14, 12, 0, tzinfo=dt.UTC)


class FakeTwelveData:
    def __init__(self, error: dict | None = None) -> None:
        self.error = error
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error:
            return httpx.Response(200, json=self.error)  # errors come with HTTP 200
        n = int(request.url.params["outputsize"])
        # Newest first, like the real API, including today's unfinished bar.
        days = [dt.date(2026, 10, 14) - dt.timedelta(days=i) for i in range(n + 6)]
        days = [d for d in days if d.weekday() < 5][:n]
        values = [
            {"datetime": d.isoformat(), "open": "100", "high": "101", "low": "99",
             "close": str(100 + i), "volume": "1000"}
            for i, d in enumerate(days)
        ]
        return httpx.Response(200, json={"meta": {}, "values": values, "status": "ok"})


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def company(session: Session, key: str) -> Company:
    return session.scalars(select(Company).where(Company.key == key)).one()


def watch(session: Session, *keys: str) -> None:
    for key in keys:
        session.add(TrackedStock(company_id=company(session, key).id))
    session.commit()


def run(session: Session, fake: FakeTwelveData, settings: Settings = SETTINGS):
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        return update_prices(session, client, TOPIC, settings, now=NOW, sleep=lambda s: None)


def test_last_completed_session_skips_weekends_and_open_sessions() -> None:
    assert last_completed_session(NOW) == dt.date(2026, 10, 13)
    after_close = dt.datetime(2026, 10, 14, 21, 0, tzinfo=dt.UTC)  # 17:00 New York
    assert last_completed_session(after_close) == dt.date(2026, 10, 14)
    sunday = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)
    assert last_completed_session(sunday) == dt.date(2026, 10, 16)


def test_fetches_watchlist_and_top_scorers_then_skips_when_up_to_date(db: Session) -> None:
    watch(db, "apple", "volvo")  # Volvo is Swedish: not on Twelve Data's free plan
    for key, score in (("nvidia", 80), ("tesla", 60), ("microsoft", 10)):
        db.add(SignalScore(company_id=company(db, key).id, date=dt.date(2026, 10, 14),
                           score=Decimal(score), components={}, weights={}))
    db.commit()
    fake = FakeTwelveData()

    report = run(db, fake)

    symbols = {r.url.params["symbol"] for r in fake.requests}
    assert symbols == {"SPY", "AAPL", "NVDA", "TSLA"}  # index + watchlist + top 2, US only
    assert report.requests == 4 and not report.failed
    assert all(r.headers["Authorization"] == "apikey td-key" for r in fake.requests)
    assert all("apikey" not in r.url.params for r in fake.requests)
    apple = db.scalars(select(Listing).where(Listing.symbol == "AAPL")).one()
    latest = db.scalar(select(func.max(PriceDaily.date)).where(PriceDaily.listing_id == apple.id))
    assert latest == dt.date(2026, 10, 13)  # today's unfinished bar is not stored

    assert db.scalar(select(func.max(BenchmarkPrice.date))) == dt.date(2026, 10, 13)
    again = FakeTwelveData()
    report = run(db, again)
    assert again.requests == [] and report.up_to_date == 4


def test_free_tier_limit_stops_the_run(db: Session) -> None:
    watch(db, "apple", "microsoft")
    fake = FakeTwelveData(error={"code": 429, "message": "run out of credits", "status": "error"})
    report = run(db, fake)
    assert "429" in (report.stopped or "") and len(fake.requests) == 1


def test_unknown_symbol_is_reported_and_others_continue(db: Session) -> None:
    watch(db, "apple")
    report = run(db, FakeTwelveData(error={"code": 404, "message": "symbol not found",
                                           "status": "error"}))
    assert report.failed == {"SPY": "symbol not found", "AAPL": "symbol not found"}


def test_without_key_nothing_is_fetched(db: Session) -> None:
    watch(db, "apple")
    fake = FakeTwelveData()
    report = run(db, fake, Settings(twelve_data_api_key=None))
    assert fake.requests == [] and "TWELVE_DATA_API_KEY" in (report.stopped or "")


def test_ideas_keep_getting_prices_until_scored(db: Session) -> None:
    """Microsoft isn't watched or top-scoring, but an open idea still needs its prices."""
    msft = db.scalars(select(Listing).where(Listing.symbol == "MSFT")).one()
    briefing = Briefing(topic="stocks", date=dt.date(2026, 10, 1), language="en")
    db.add(briefing)
    db.flush()
    db.add(Idea(briefing_id=briefing.id, company_id=msft.company_id, listing_id=msft.id,
                thesis="t", risks="r", confidence="low", benchmark="S&P 500",
                published_at=dt.datetime(2026, 10, 1, 6, 30, tzinfo=dt.UTC)))
    db.commit()
    fake = FakeTwelveData()
    run(db, fake)
    assert {r.url.params["symbol"] for r in fake.requests} == {"SPY", "MSFT"}
