"""Network side of collection: one function per `Source.fetcher` value."""

import datetime as dt
import logging
from urllib.parse import urlsplit

import httpx

from app.collect.parsers import FetchedItem, parse_atom, parse_finnhub_news, parse_rss
from app.config import Settings
from app.models import Source

log = logging.getLogger(__name__)

USER_AGENT = "SignalDesk/0.1 (personal news reader)"


class SourceSkipped(Exception):
    """The source can't run with the current config (e.g. missing free API key). Not an error."""


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
    symbols: list[str],
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
            return _fetch_finnhub(client, source.url, settings, symbols=symbols, now=now)
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
