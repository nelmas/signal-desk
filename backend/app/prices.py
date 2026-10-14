"""Daily prices from Twelve Data's free plan (US stocks; 8 requests/min, 800/day).

Terms basis (twelvedata.com/terms, checked 2026-10-14): data for the customer's own
internal, non-commercial use, displayed only to the customer, stored for that use, no
redistribution. So prices are only ever shown inside this private app.

Fetched: your watchlist plus the day's top-scoring companies, for their primary
listing. A listing that already has the last completed session is skipped, so the
hourly job usually makes no requests at all.
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
from app.models import Company, Listing, PriceDaily, SignalScore, TrackedStock
from app.topic import TopicConfig

log = logging.getLogger(__name__)

API_URL = "https://api.twelvedata.com/time_series"
SOURCE = "twelvedata"
HISTORY_SESSIONS = 40  # enough for the market-reaction baseline
NEW_YORK = ZoneInfo("America/New_York")
SESSION_CLOSE = dt.time(16, 30)  # a little after the 16:00 close, for the final bar


@dataclass
class PriceReport:
    listings: int = 0
    up_to_date: int = 0
    fetched: int = 0
    rows: int = 0
    requests: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    stopped: str | None = None


def last_completed_session(now: dt.datetime) -> dt.date:
    """Most recent US trading day whose close is in (weekends skipped, holidays not)."""
    local = now.astimezone(NEW_YORK)
    day = local.date() if local.time() >= SESSION_CLOSE else local.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def _targets(session: Session, topic: TopicConfig, top: int) -> list[Listing]:
    us_mics = {mic for m in topic.markets if m.key == "US" for mic in m.mics}
    watched = select(TrackedStock.company_id)
    today = session.scalar(select(func.max(SignalScore.date)))
    top_ids = (
        select(SignalScore.company_id)
        .where(SignalScore.date == today, SignalScore.score > 0)
        .order_by(SignalScore.score.desc())
        .limit(top)
    )
    return list(
        session.scalars(
            select(Listing)
            .join(Company)
            .where(
                Company.topic == topic.key,
                Company.active,
                Listing.is_primary,
                Listing.mic.in_(us_mics),
                Company.id.in_(watched) | Company.id.in_(top_ids),
            )
            .order_by(Listing.symbol)
        )
    )


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
    listings = _targets(session, topic, settings.price_top_scorers)
    report.listings = len(listings)
    latest = dict(
        session.execute(
            select(PriceDaily.listing_id, func.max(PriceDaily.date))
            .where(PriceDaily.listing_id.in_([lst.id for lst in listings]))
            .group_by(PriceDaily.listing_id)
        ).all()
    )
    pause = 60 / settings.price_requests_per_minute

    for listing in listings:
        have = latest.get(listing.id)
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
            response = client.get(
                API_URL,
                params={
                    "symbol": listing.symbol.replace(" ", "."),  # "BRK B" -> "BRK.B"
                    "interval": "1day",
                    "outputsize": min(missing, HISTORY_SESSIONS),
                },
                # Header, not ?apikey=, so the key never appears in logged URLs.
                headers={"Authorization": f"apikey {settings.twelve_data_api_key}"},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            report.failed[listing.symbol] = f"{type(e).__name__}: {e}"[:200]
            continue
        # Twelve Data reports errors in the body, often with HTTP 200.
        if data.get("status") == "error":
            if data.get("code") == 429:
                report.stopped = "free-tier limit reached (429)"
                break
            report.failed[listing.symbol] = str(data.get("message", "error"))[:200]
            continue
        rows = _rows(listing.id, data.get("values") or [], target_day)
        if rows:
            stmt = insert(PriceDaily).values(rows)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["listing_id", "date"],
                    set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume")},
                )
            )
            session.commit()
        report.fetched += 1
        report.rows += len(rows)
    return report


def _rows(listing_id: int, values: list[dict], target_day: dt.date) -> list[dict]:
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
        rows.append(
            {
                "listing_id": listing_id,
                "date": day,
                "open": _num(v, "open"),
                "high": _num(v, "high"),
                "low": _num(v, "low"),
                "close": close,
                "volume": int(volume) if volume is not None else None,
                "source": SOURCE,
            }
        )
    return rows


def _num(values: dict, key: str) -> Decimal | None:
    try:
        return Decimal(values[key])
    except (KeyError, InvalidOperation, TypeError):
        return None
