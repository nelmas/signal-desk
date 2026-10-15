"""The track record: how each published idea actually did. Plain arithmetic, no AI.

Entry is the first market open after the briefing was published, so the record never
counts a move you couldn't have acted on. A briefing at 08:30 in Stockholm is before
New York opens, so a US idea enters at that day's open.

After 1, 5 and 20 trading days (the entry day counts as day 1) the idea is scored from
the entry open to that day's close, and so is the market's benchmark over the very
same days. Excess return = idea minus benchmark: did it beat simply owning the index?
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BenchmarkPrice, Idea, IdeaOutcome, Listing, PriceDaily
from app.topic import TopicConfig

HORIZONS = (1, 5, 20)
_OPEN = {"US": (ZoneInfo("America/New_York"), dt.time(9, 30)),
         "SE": (ZoneInfo("Europe/Stockholm"), dt.time(9, 0))}


@dataclass
class TrackReport:
    ideas: int = 0
    entered: int = 0
    scored: int = 0
    no_prices: int = 0


def entry_day(published_at: dt.datetime, market: str) -> dt.date:
    """The first trading day whose opening bell comes after publication (weekends skipped)."""
    tz, opens = _OPEN.get(market, _OPEN["US"])
    local = published_at.astimezone(tz)
    day = local.date() if local.time() < opens else local.date() + dt.timedelta(days=1)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def _pct(start: Decimal, end: Decimal) -> Decimal:
    return ((end / start) - 1) * 100


def evaluate_ideas(session: Session, topic: TopicConfig) -> TrackReport:
    report = TrackReport()
    benchmark_symbol = {m.key: m.benchmark_symbol for m in topic.markets}
    for idea in session.scalars(select(Idea).order_by(Idea.published_at)):
        report.ideas += 1
        listing = session.get(Listing, idea.listing_id)
        market = topic.market_for_mic(listing.mic) if listing else None
        done = {o.horizon_days for o in session.scalars(
            select(IdeaOutcome).where(IdeaOutcome.idea_id == idea.id))}
        if done >= set(HORIZONS):
            continue

        start = entry_day(idea.published_at, market or "US")
        sessions = session.execute(
            select(PriceDaily.date, PriceDaily.open, PriceDaily.close)
            .where(PriceDaily.listing_id == idea.listing_id, PriceDaily.date >= start)
            .order_by(PriceDaily.date)
            .limit(max(HORIZONS))
        ).all()
        if not sessions:
            report.no_prices += 1
            continue
        first = sessions[0]
        entry_price = first.open or first.close  # no open recorded: the day's close
        if idea.entry_date is None:
            idea.entry_date, idea.entry_price = first.date, entry_price
            report.entered += 1

        bench = {}
        symbol = benchmark_symbol.get(market or "")
        if symbol:
            bench = {
                row.date: row for row in session.execute(
                    select(BenchmarkPrice.date, BenchmarkPrice.open, BenchmarkPrice.close)
                    .where(BenchmarkPrice.symbol == symbol, BenchmarkPrice.date >= first.date)
                    .order_by(BenchmarkPrice.date)
                ).all()
            }
        b_start = bench.get(first.date)
        b_entry = (b_start.open or b_start.close) if b_start else None

        for h in HORIZONS:
            if h in done or len(sessions) < h:
                continue  # already scored, or not enough sessions yet
            exit_row = sessions[h - 1]
            ret = _pct(entry_price, exit_row.close)
            b_exit = bench.get(exit_row.date)
            b_ret = _pct(b_entry, b_exit.close) if (b_entry and b_exit) else None
            session.add(IdeaOutcome(
                idea_id=idea.id,
                horizon_days=h,
                exit_date=exit_row.date,
                exit_price=exit_row.close,
                return_pct=round(ret, 4),
                benchmark_return_pct=round(b_ret, 4) if b_ret is not None else None,
                excess_return_pct=round(ret - b_ret, 4) if b_ret is not None else None,
            ))
            report.scored += 1
    session.commit()
    return report
