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
from app.prices_se import eodhd_symbol, last_completed_session, update_swedish_prices
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
SETTINGS = Settings(eodhd_api_key="secret-eod-key", price_top_scorers_se=2)
# Friday 16 Oct 2026, 11:00 in Stockholm: the last completed session is Thursday the 15th.
NOW = dt.datetime(2026, 10, 16, 9, 0, tzinfo=dt.UTC)


class FakeEODHD:
    def __init__(self, used: int = 0, status: int = 200) -> None:
        self.used = used
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/user":
            return httpx.Response(200, json={"dailyRateLimit": 20, "apiRequests": self.used})
        self.used += 1
        if self.status != 200:
            return httpx.Response(self.status, text="denied")
        start = dt.date.fromisoformat(request.url.params["from"])
        end = dt.date.fromisoformat(request.url.params["to"])
        rows, d = [], start
        while d <= end:
            if d.weekday() < 5:
                rows.append({"date": d.isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
                             "close": 100.5, "adjusted_close": 100.5, "volume": 1000})
            d += dt.timedelta(days=1)
        return httpx.Response(200, json=rows)

    def fetched(self) -> list[str]:
        paths = [r.url.path for r in self.requests]
        return [p.removeprefix("/api/eod/") for p in paths if "/eod/" in p]


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def company(db: Session, key: str) -> Company:
    return db.scalars(select(Company).where(Company.key == key)).one()


def listing(db: Session, symbol: str) -> Listing:
    return db.scalars(select(Listing).where(Listing.symbol == symbol)).one()


def run(db: Session, fake: FakeEODHD, settings: Settings = SETTINGS):
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        return update_swedish_prices(db, client, TOPIC, settings, now=NOW, sleep=lambda s: None)


def test_symbols_and_session_dates() -> None:
    assert eodhd_symbol("VOLV B") == "VOLV-B.ST"
    assert eodhd_symbol("NDA SE") == "NDA-SE.ST"
    assert last_completed_session(NOW) == dt.date(2026, 10, 15)
    evening = dt.datetime(2026, 10, 16, 17, 0, tzinfo=dt.UTC)  # 19:00 Stockholm
    assert last_completed_session(evening) == dt.date(2026, 10, 16)


def test_priority_order_and_daily_budget(db: Session) -> None:
    saab = listing(db, "SAAB B")
    briefing = Briefing(topic="stocks", date=dt.date(2026, 10, 14), language="sv")
    db.add(briefing)
    db.flush()
    db.add(Idea(briefing_id=briefing.id, company_id=saab.company_id, listing_id=saab.id,
                thesis="t", risks="r", confidence="low", benchmark="OMXS30",
                published_at=dt.datetime(2026, 10, 14, 6, 30, tzinfo=dt.UTC)))
    db.add(TrackedStock(company_id=company(db, "volvo").id))
    for key, score in (("ericsson", 70), ("skf", 60), ("apple", 90)):
        db.add(SignalScore(company_id=company(db, key).id, date=dt.date(2026, 10, 16),
                           score=Decimal(score), components={}, weights={}))
    db.commit()

    # 17 of 20 used today: 3 left, minus 1 in reserve = 2 requests.
    fake = FakeEODHD(used=17)
    report = run(db, fake)
    assert fake.fetched() == ["XACT-OMXS30.ST", "SAAB-B.ST"]  # index, then the open idea
    assert "used up" in (report.stopped or "")

    fake = FakeEODHD(used=0)  # the next day
    report = run(db, fake)
    # Already fetched ones are skipped; watchlist before top scorers; Apple isn't Swedish.
    assert fake.fetched() == ["VOLV-B.ST", "ERIC-B.ST", "SKF-B.ST"]
    assert all(r.url.params["api_token"] == "secret-eod-key" for r in fake.requests)
    assert db.scalar(select(func.max(BenchmarkPrice.date))) == dt.date(2026, 10, 15)


def test_catches_up_from_the_last_stored_day_and_skips_when_current(db: Session) -> None:
    volvo = listing(db, "VOLV B")
    db.add(TrackedStock(company_id=volvo.company_id))
    db.add(PriceDaily(listing_id=volvo.id, date=dt.date(2026, 10, 12), close=Decimal("1"),
                      source="eodhd"))
    db.add(BenchmarkPrice(symbol="XACT-OMXS30", date=dt.date(2026, 10, 15), close=Decimal("1"),
                          source="eodhd"))
    db.commit()
    fake = FakeEODHD()
    report = run(db, fake)
    eod = [r for r in fake.requests if "/eod/" in r.url.path]
    assert len(eod) == 1 and eod[0].url.params["from"] == "2026-10-13"
    assert report.rows == 3  # 13, 14 and 15 October

    again = FakeEODHD()
    assert run(db, again).up_to_date == 2 and again.requests == []  # not even the account check


def test_limit_errors_stop_and_never_show_the_key(db: Session) -> None:
    db.add(TrackedStock(company_id=company(db, "volvo").id))
    db.commit()
    report = run(db, FakeEODHD(status=402))
    assert "limit" in (report.stopped or "")
    report = run(db, FakeEODHD(status=500))
    assert "secret-eod-key" not in str(report.failed) + str(report.stopped)
    assert report.failed == {"XACT-OMXS30": "HTTP 500", "VOLV B": "HTTP 500"}


def test_without_key_nothing_is_fetched(db: Session) -> None:
    fake = FakeEODHD()
    report = run(db, fake, Settings(eodhd_api_key=None))
    assert fake.requests == [] and "EODHD_API_KEY" in (report.stopped or "")
