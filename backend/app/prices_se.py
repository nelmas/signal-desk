"""Swedish end-of-day prices from EODHD's free plan (20 requests a day).

Terms basis (eodhd.com/financial-apis/terms-conditions, checked 2026-10-16): personal use
"for their own personal investment activities"; storing and analysing "for private,
non-commercial purposes" is allowed; displaying or granting access to others and
redistribution are not. So, like US prices, these are only shown inside this private app.

20 requests a day is enough because one request returns every day missing since the
last fetch: a stock left out today simply catches up tomorrow. In priority order:
1. the OMXS30 tracker (Facit compares Swedish ideas with it),
2. Swedish ideas the track record is still following,
3. your Swedish watchlist,
4. the day's top-scoring Swedish companies (for the price-reaction label).
Before fetching, EODHD is asked how many of today's requests are left, and one is kept
in reserve.
"""

import datetime as dt
import time
from collections.abc import Callable
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import BenchmarkPrice, Company, Listing, PriceDaily, TrackedStock
from app.prices import (
    PriceReport,
    open_idea_listings,
    store_benchmark,
    store_listing,
    top_scorers,
)
from app.topic import TopicConfig

EOD_URL = "https://eodhd.com/api/eod/{symbol}"
USER_URL = "https://eodhd.com/api/user"
STOCKHOLM = ZoneInfo("Europe/Stockholm")
SESSION_CLOSE = dt.time(18, 0)  # 17:30 close plus time for the end-of-day data
HISTORY_DAYS = 70  # calendar days for a first fetch: about 45 sessions
RESERVE = 1  # requests left unused each day, for a manual run
PAUSE_SECONDS = 1.0


class _OutOfRequests(Exception):
    pass


def last_completed_session(now: dt.datetime) -> dt.date:
    """Most recent Stockholm trading day whose close is in (weekends skipped)."""
    local = now.astimezone(STOCKHOLM)
    day = local.date() if local.time() >= SESSION_CLOSE else local.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def eodhd_symbol(symbol: str) -> str:
    """'VOLV B' -> 'VOLV-B.ST'. First North shares trade under the same exchange code."""
    return f"{symbol.replace(' ', '-')}.ST"


def requests_left(client: httpx.Client, settings: Settings) -> int:
    """Today's remaining free requests according to EODHD, minus a reserve."""
    response = client.get(USER_URL, params={"api_token": settings.eodhd_api_key, "fmt": "json"})
    if response.status_code != 200:
        raise _OutOfRequests(f"account check failed (HTTP {response.status_code})")
    data = response.json()
    limit, used = int(data.get("dailyRateLimit") or 0), int(data.get("apiRequests") or 0)
    return max(0, limit - used - RESERVE)


def _fetch(client: httpx.Client, symbol: str, since: dt.date, until: dt.date, settings: Settings):
    response = client.get(
        EOD_URL.format(symbol=symbol),
        params={"api_token": settings.eodhd_api_key, "fmt": "json",
                "from": since.isoformat(), "to": until.isoformat()},
    )
    # Never include the URL in messages: the key is a query parameter.
    if response.status_code in (402, 429):
        raise _OutOfRequests(f"free-tier limit reached (HTTP {response.status_code})")
    if response.status_code == 404:
        raise ValueError("symbol not found")
    if response.status_code >= 400:
        raise ValueError(f"HTTP {response.status_code}")
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("unexpected response")
    # Same shape as Twelve Data's, so the shared storage code reads it.
    return [
        {"datetime": r["date"], "open": str(r.get("open")), "high": str(r.get("high")),
         "low": str(r.get("low")), "close": str(r.get("close")), "volume": str(r.get("volume"))}
        for r in rows if r.get("date") and r.get("close") is not None
    ]


def _swedish_listings(session: Session, topic: TopicConfig, now: dt.datetime,
                      settings: Settings) -> list[Listing]:
    """Ideas first, then the watchlist, then top scorers; each listing once."""
    se_mics = {mic for m in topic.markets if m.key == "SE" for mic in m.mics}
    base = select(Listing).join(Company).where(Company.topic == topic.key, Listing.mic.in_(se_mics))
    groups = [
        base.where(Listing.id.in_(open_idea_listings(now))),
        base.where(Company.active, Listing.is_primary,
                   Company.id.in_(select(TrackedStock.company_id))),
        base.where(Company.active, Listing.is_primary,
                   Company.id.in_(top_scorers(session, settings.price_top_scorers_se, se_mics))),
    ]
    seen: dict[int, Listing] = {}
    for query in groups:
        for listing in session.scalars(query.order_by(Listing.symbol)):
            seen.setdefault(listing.id, listing)
    return list(seen.values())


def update_swedish_prices(
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
    if not settings.eodhd_api_key:
        report.stopped = "no EODHD_API_KEY"
        return report

    target_day = last_completed_session(now)
    benchmark = next((m.benchmark_symbol for m in topic.markets if m.key == "SE"), None)
    listings = _swedish_listings(session, topic, now, settings)
    latest = dict(session.execute(
        select(PriceDaily.listing_id, func.max(PriceDaily.date))
        .where(PriceDaily.listing_id.in_([lst.id for lst in listings]))
        .group_by(PriceDaily.listing_id)
    ).all())
    jobs: list[tuple[str, str, dt.date | None, Callable[[list[dict]], int]]] = []
    if benchmark:
        have = session.scalar(
            select(func.max(BenchmarkPrice.date)).where(BenchmarkPrice.symbol == benchmark))
        jobs.append((benchmark, f"{benchmark}.ST", have,
                     lambda v: store_benchmark(session, benchmark, v, target_day)))
    jobs += [
        (lst.symbol, eodhd_symbol(lst.symbol), latest.get(lst.id),
         lambda v, lst=lst: store_listing(session, lst.id, v, target_day))
        for lst in listings
    ]
    report.listings = len(jobs)
    pending = [j for j in jobs if j[2] is None or j[2] < target_day]
    report.up_to_date = len(jobs) - len(pending)
    if not pending:
        return report

    try:
        budget = requests_left(client, settings)
    except (_OutOfRequests, httpx.HTTPError) as e:
        report.stopped = str(e) if isinstance(e, _OutOfRequests) else type(e).__name__
        return report

    for label, symbol, have, store in pending:
        if report.requests >= budget:
            report.stopped = "today's free EODHD requests are used up; the rest catch up tomorrow"
            break
        if report.requests:
            sleep(PAUSE_SECONDS)
        first_day = target_day - dt.timedelta(days=HISTORY_DAYS)
        since = have + dt.timedelta(days=1) if have else first_day
        report.requests += 1
        try:
            values = _fetch(client, symbol, since, target_day, settings)
        except _OutOfRequests as e:
            report.stopped = str(e)
            break
        except (httpx.HTTPError, ValueError) as e:
            report.failed[label] = str(e) if isinstance(e, ValueError) else type(e).__name__
            continue
        report.rows += store(values)
        session.commit()
        report.fetched += 1
    return report
