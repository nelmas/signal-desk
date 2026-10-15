import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BenchmarkPrice, Briefing, Idea, IdeaOutcome, Listing, PriceDaily
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from
from app.track import entry_day, evaluate_ideas

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
UTC = dt.UTC


@pytest.mark.parametrize(
    ("published", "market", "entry"),
    [
        # 08:30 Stockholm = 02:30 New York: before the US open, same day.
        (dt.datetime(2026, 10, 15, 6, 30, tzinfo=UTC), "US", dt.date(2026, 10, 15)),
        # 11:00 New York: after the open, so the next day.
        (dt.datetime(2026, 10, 15, 15, 0, tzinfo=UTC), "US", dt.date(2026, 10, 16)),
        # Friday after the open: Monday.
        (dt.datetime(2026, 10, 16, 15, 0, tzinfo=UTC), "US", dt.date(2026, 10, 19)),
        # Saturday: Monday.
        (dt.datetime(2026, 10, 17, 8, 0, tzinfo=UTC), "US", dt.date(2026, 10, 19)),
        # 08:30 Stockholm is before the 09:00 open there too.
        (dt.datetime(2026, 10, 15, 6, 30, tzinfo=UTC), "SE", dt.date(2026, 10, 15)),
        (dt.datetime(2026, 10, 15, 8, 0, tzinfo=UTC), "SE", dt.date(2026, 10, 16)),
    ],
)
def test_entry_is_the_first_open_after_publication(published, market, entry) -> None:
    assert entry_day(published, market) == entry


def weekdays(start: dt.date, n: int) -> list[dt.date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


@pytest.fixture
def idea(session: Session) -> Idea:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    apple = session.scalars(select(Listing).where(Listing.symbol == "AAPL")).one()
    briefing = Briefing(topic="stocks", date=dt.date(2026, 10, 15), language="en")
    session.add(briefing)
    session.flush()
    row = Idea(briefing_id=briefing.id, company_id=apple.company_id, listing_id=apple.id,
               thesis="t", risks="r", confidence="medium", benchmark="S&P 500",
               published_at=dt.datetime(2026, 10, 15, 6, 30, tzinfo=UTC))
    session.add(row)
    session.commit()
    return row


def add_prices(session: Session, listing_id: int, days: list[dt.date]) -> None:
    """Stock: opens at 100 on day 1, then closes 1% higher each day (101, 102.01, …)."""
    for i, d in enumerate(days):
        session.add(PriceDaily(
            listing_id=listing_id, date=d, open=Decimal("100") if i == 0 else None,
            close=Decimal(str(round(100 * 1.01 ** (i + 1), 6))), source="test",
        ))
        # Index: opens at 50, closes 0.5% higher each day.
        session.add(BenchmarkPrice(
            symbol="SPY", date=d, open=Decimal("50") if i == 0 else None,
            close=Decimal(str(round(50 * 1.005 ** (i + 1), 6))), source="test",
        ))
    session.commit()


def outcomes(session: Session, idea: Idea) -> dict[int, IdeaOutcome]:
    return {o.horizon_days: o for o in session.scalars(
        select(IdeaOutcome).where(IdeaOutcome.idea_id == idea.id))}


def test_scores_each_horizon_once_enough_sessions_exist(session: Session, idea: Idea) -> None:
    days = weekdays(dt.date(2026, 10, 15), 25)
    add_prices(session, idea.listing_id, days[:3])
    report = evaluate_ideas(session, TOPIC)
    assert (report.entered, report.scored) == (1, 1)
    session.refresh(idea)
    assert idea.entry_date == dt.date(2026, 10, 15) and float(idea.entry_price) == 100
    one = outcomes(session, idea)[1]
    assert float(one.return_pct) == pytest.approx(1.0)  # 100 -> 101
    assert float(one.benchmark_return_pct) == pytest.approx(0.5)
    assert float(one.excess_return_pct) == pytest.approx(0.5)

    # More sessions arrive later: 5 and 20 days get scored, day 1 isn't duplicated.
    for d in days[3:]:
        session.add(PriceDaily(listing_id=idea.listing_id, date=d, source="test",
                               close=Decimal(str(round(100 * 1.01 ** (days.index(d) + 1), 6)))))
        session.add(BenchmarkPrice(symbol="SPY", date=d, source="test",
                                   close=Decimal(str(round(50 * 1.005 ** (days.index(d) + 1), 6)))))
    session.commit()
    assert evaluate_ideas(session, TOPIC).scored == 2
    o = outcomes(session, idea)
    # Stored to 4 decimals, hence the tolerance.
    assert o[5].exit_date == days[4]
    assert float(o[5].return_pct) == pytest.approx((1.01**5 - 1) * 100, abs=1e-3)
    assert o[20].exit_date == days[19]
    assert float(o[20].excess_return_pct) == pytest.approx((1.01**20 - 1.005**20) * 100, abs=1e-3)
    assert evaluate_ideas(session, TOPIC).scored == 0  # nothing left to do


def test_without_prices_nothing_is_scored(session: Session, idea: Idea) -> None:
    report = evaluate_ideas(session, TOPIC)
    assert report.no_prices == 1 and report.scored == 0
    session.refresh(idea)
    assert idea.entry_date is None


def test_missing_benchmark_still_scores_the_idea(session: Session, idea: Idea) -> None:
    session.add(PriceDaily(listing_id=idea.listing_id, date=dt.date(2026, 10, 15),
                           open=Decimal("100"), close=Decimal("103"), source="test"))
    session.commit()
    evaluate_ideas(session, TOPIC)
    one = outcomes(session, idea)[1]
    assert float(one.return_pct) == pytest.approx(3.0)
    assert one.benchmark_return_pct is None and one.excess_return_pct is None
