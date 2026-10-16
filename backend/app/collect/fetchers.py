"""Network side of collection: one function per `Source.fetcher` value."""

import datetime as dt
import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.collect.parsers import FetchedItem, parse_atom, parse_finnhub_news, parse_rss
from app.config import Settings
from app.models import Source

log = logging.getLogger(__name__)

USER_AGENT = "SignalDesk/0.1 (personal news reader)"


class SourceSkipped(Exception):
    """The source can't run with the current config (e.g. missing free API key). Not an error."""


@dataclass
class FetchContext:
    """What a fetcher may need to know about the database, gathered by the collector."""

    symbols: list[str] = field(default_factory=list)  # per-stock news (Finnhub)
    company_by_cik: dict[str, int] = field(default_factory=dict)  # SEC filings
    company_by_name: dict[str, int] = field(default_factory=dict)  # normalized alias -> id
    known_urls: set[str] = field(default_factory=set)  # url hashes already stored
    language: str = "en"  # for summaries written by rules


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )


def _headers(url: str, settings: Settings) -> dict[str, str]:
    # SEC fair-access policy: requests must name a person or company and an email.
    if urlsplit(url).hostname in ("www.sec.gov", "sec.gov"):
        if not settings.sec_user_agent:
            raise SourceSkipped("set SEC_USER_AGENT (\"Your Name you@example.com\")")
        return {"User-Agent": settings.sec_user_agent}
    return {}


def fetch_source(
    client: httpx.Client,
    source: Source,
    settings: Settings,
    *,
    ctx: FetchContext,
    now: dt.datetime,
) -> list[FetchedItem]:
    if not source.url:
        raise SourceSkipped("no url")
    match source.fetcher:
        case "rss" | "atom":
            response = client.get(source.url, headers=_headers(source.url, settings))
            response.raise_for_status()
            parse = parse_rss if source.fetcher == "rss" else parse_atom
            return parse(response.content, now=now)
        case "finnhub_company_news":
            return _fetch_finnhub(client, source.url, settings, symbols=ctx.symbols, now=now)
        case "sec_insiders":
            from app.collect.insiders_us import fetch_sec_insiders

            return fetch_sec_insiders(client, _headers("https://www.sec.gov/", settings), ctx, now)
        case "fi_insider":
            from app.collect.insiders_se import fetch_fi_insider

            return fetch_fi_insider(client, source.url, ctx, now)
        case other:
            raise SourceSkipped(f"unknown fetcher {other!r}")


def _fetch_finnhub(
    client: httpx.Client, url: str, settings: Settings, *, symbols: list[str], now: dt.datetime
) -> list[FetchedItem]:
    """One call per stock. The free plan allows 60 calls/min; a 429 ends the run early."""
    if not settings.finnhub_api_key:
        raise SourceSkipped("set FINNHUB_API_KEY (free at finnhub.io)")
    # The key goes in a header so it never shows up in logged URLs.
    headers = {"X-Finnhub-Token": settings.finnhub_api_key}
    since = (now - dt.timedelta(days=2)).date().isoformat()
    until = now.date().isoformat()
    items: list[FetchedItem] = []
    for symbol in symbols:
        api_symbol = symbol.replace(" ", ".")  # "BRK B" -> "BRK.B"
        response = client.get(
            url, params={"symbol": api_symbol, "from": since, "to": until}, headers=headers
        )
        if response.status_code == 429:
            log.warning("finnhub rate limit hit after %d symbols", len(items))
            break
        response.raise_for_status()
        items.extend(parse_finnhub_news(response.json(), symbol=symbol))
    return items
