"""Daily prices from Twelve Data's free plan (US stocks; 8 requests/min, 800/day).

Terms basis (twelvedata.com/terms, checked 2026-10-14): data for the customer's own
internal, non-commercial use, displayed only to the customer, stored for that use, no
redistribution. So prices are only ever shown inside this private app.

Fetched: your watchlist, the day's top-scoring companies, every idea still being
followed by the track record, and each market's benchmark (e.g. SPY). Anything that
already has the last completed session is skipped, so the hourly job usually makes no
requests at all.
"""

import datetime as dt
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    BenchmarkPrice,
    Company,
    Idea,
    IdeaOutcome,
    Listing,
    PriceDaily,
    SignalScore,
    TrackedStock,
)
from app.topic import TopicConfig

log = logging.getLogger(__name__)

API_URL = "https://api.twelvedata.com/time_series"
SOURCE = "twelvedata"
HISTORY_SESSIONS = 40  # enough for the market-reaction baseline
NEW_YORK = ZoneInfo("America/New_York")
SESSION_CLOSE = dt.time(16, 30)  # a little after the 16:00 close, for the final bar
# Ideas are followed until their longest horizon is scored; this caps the lookback.
IDEA_FOLLOW_DAYS = 45
HORIZONS = (1, 5, 20)


@dataclass
class PriceReport:
    listings: int = 0
    up_to_date: int = 0
    fetched: int = 0
    rows: int = 0
    requests: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    stopped: str | None = None


class _RateLimited(Exception):
    pass


def last_completed_session(now: dt.datetime) -> dt.date:
    """Most recent US trading day whose close is in (weekends skipped, holidays not)."""
    local = now.astimezone(NEW_YORK)
    day = local.date() if local.time() >= SESSION_CLOSE else local.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def open_idea_listings(now: dt.datetime):
    """Listings of ideas the track record hasn't finished scoring: they keep getting prices."""
    return (
        select(Idea.listing_id)
        .where(Idea.published_at >= now - dt.timedelta(days=IDEA_FOLLOW_DAYS))
        .where(
            select(func.count())
            .select_from(IdeaOutcome)
            .where(IdeaOutcome.idea_id == Idea.id)
            .scalar_subquery()
            < len(HORIZONS)
        )
    )


def top_scorers(session: Session, limit: int, mics: set[str]):
    """Today's highest-scoring companies listed in one market (`mics`)."""
    today = session.scalar(select(func.max(SignalScore.date)))
    return (
        select(SignalScore.company_id)
        .join(Listing, (Listing.company_id == SignalScore.company_id) & Listing.is_primary)
        .where(SignalScore.date == today, SignalScore.score > 0, Listing.mic.in_(mics))
        .order_by(SignalScore.score.desc())
        .limit(limit)
    )


def _targets(
    session: Session, topic: TopicConfig, top: int, now: dt.datetime
) -> list[Listing]:
    us_mics = {mic for m in topic.markets if m.key == "US" for mic in m.mics}
    watched = select(TrackedStock.company_id)
    top_ids = top_scorers(session, top, us_mics)
    open_ideas = open_idea_listings(now)
    return list(
        session.scalars(
            select(Listing)
            .join(Company)
            .where(
                Company.topic == topic.key,
                Listing.mic.in_(us_mics),
                (
                    Company.active
                    & Listing.is_primary
                    & (Company.id.in_(watched) | Company.id.in_(top_ids))
                )
                | Listing.id.in_(open_ideas),
            )
            .order_by(Listing.symbol)
        )
    )


def _fetch(
    client: httpx.Client, symbol: str, outputsize: int, settings: Settings
) -> list[dict]:
    """One time-series request. Raises _RateLimited on 429, ValueError on other errors."""
    response = client.get(
        API_URL,
        params={"symbol": symbol, "interval": "1day", "outputsize": outputsize},
        # Header, not ?apikey=, so the key never appears in logged URLs.
        headers={"Authorization": f"apikey {settings.twelve_data_api_key}"},
    )
    response.raise_for_status()
    data = response.json()
    # Twelve Data reports errors in the body, often with HTTP 200.
    if data.get("status") == "error":
        if data.get("code") == 429:
            raise _RateLimited()
        raise ValueError(str(data.get("message", "error"))[:200])
    return data.get("values") or []


def update_prices(
    session: Session,
    client: httpx.Client,
    topic: TopicConfig,
    settings: Settings,
    *,
    now: dt.datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PriceReport:
    now = now or dt.datetime.now(dt.UTC)
    report = PriceReport()
    if not settings.twelve_data_api_key:
        report.stopped = "no TWELVE_DATA_API_KEY"
        return report

    target_day = last_completed_session(now)
    listings = _targets(session, topic, settings.price_top_scorers, now)
    latest = dict(
        session.execute(
            select(PriceDaily.listing_id, func.max(PriceDaily.date))
            .where(PriceDaily.listing_id.in_([lst.id for lst in listings]))
            .group_by(PriceDaily.listing_id)
        ).all()
    )
    benchmarks = [
        m.benchmark_symbol for m in topic.markets if m.key == "US" and m.benchmark_symbol
    ]
    bench_latest = dict(
        session.execute(
            select(BenchmarkPrice.symbol, func.max(BenchmarkPrice.date))
            .where(BenchmarkPrice.symbol.in_(benchmarks))
            .group_by(BenchmarkPrice.symbol)
        ).all()
    )
    # (label, api symbol, last stored date, function that stores the rows)
    jobs: list[tuple[str, str, dt.date | None, Callable[[list[dict]], int]]] = [
        (b, b, bench_latest.get(b), lambda v, b=b: store_benchmark(session, b, v, target_day))
        for b in benchmarks
    ] + [
        (
            lst.symbol,
            lst.symbol.replace(" ", "."),  # "BRK B" -> "BRK.B"
            latest.get(lst.id),
            lambda v, lst=lst: store_listing(session, lst.id, v, target_day),
        )
        for lst in listings
    ]
    report.listings = len(jobs)
    pause = 60 / settings.price_requests_per_minute

    for label, symbol, have, store in jobs:
        if have is not None and have >= target_day:
            report.up_to_date += 1
            continue
        if report.requests >= settings.price_requests_per_run:
            report.stopped = "request budget for this run used up"
            break
        if report.requests:
            sleep(pause)
        missing = (target_day - have).days + 3 if have else HISTORY_SESSIONS
        report.requests += 1
        try:
            values = _fetch(client, symbol, min(missing, HISTORY_SESSIONS), settings)
        except _RateLimited:
            report.stopped = "free-tier limit reached (429)"
            break
        except (httpx.HTTPError, ValueError) as e:
            message = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
            report.failed[label] = message[:200]
            continue
        report.rows += store(values)
        session.commit()
        report.fetched += 1
    return report


def _parse(values: list[dict], target_day: dt.date) -> list[dict]:
    rows = []
    for v in values:
        try:
            day = dt.date.fromisoformat(v["datetime"][:10])
            close = Decimal(v["close"])
        except (KeyError, ValueError, InvalidOperation):
            continue
        if day > target_day:
            continue  # today's bar is still moving; store it once the session has closed
        volume = _num(v, "volume")
        rows.append({
            "date": day, "open": _num(v, "open"), "high": _num(v, "high"), "low": _num(v, "low"),
            "close": close, "volume": int(volume) if volume is not None else None,
        })
    return rows


def store_listing(
    session: Session, listing_id: int, values: list[dict], target_day: dt.date
) -> int:
    rows = [{**r, "listing_id": listing_id, "source": SOURCE} for r in _parse(values, target_day)]
    if rows:
        stmt = insert(PriceDaily).values(rows)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["listing_id", "date"],
                set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume")},
            )
        )
    return len(rows)


def store_benchmark(
    session: Session, symbol: str, values: list[dict], target_day: dt.date
) -> int:
    rows = [
        {"symbol": symbol, "date": r["date"], "open": r["open"], "close": r["close"],
         "source": SOURCE}
        for r in _parse(values, target_day)
    ]
    if rows:
        stmt = insert(BenchmarkPrice).values(rows)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol", "date"],
                set_={k: stmt.excluded[k] for k in ("open", "close")},
            )
        )
    return len(rows)


def _num(values: dict, key: str) -> Decimal | None:
    try:
        return Decimal(values[key])
    except (KeyError, InvalidOperation, TypeError):
        return None
