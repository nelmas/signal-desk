"""The universe: every listed company the app can recognise in the news.

US companies come from SEC's public ticker file, Swedish ones from Finnhub's free
symbol list. Companies from companies.csv ("curated") keep their hand-written
aliases; universe companies get aliases generated from their names, minus anything
too generic or ambiguous to match safely.
"""

import re
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Company, CompanyAlias, Listing
from app.names import normalize_name
from app.topic import TopicConfig

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FINNHUB_SYMBOLS_URL = "https://finnhub.io/api/v1/stock/symbol"
SEC_EXCHANGE_MIC = {"Nasdaq": "XNAS", "NYSE": "XNYS"}

# Trailing words that are legal form or share class, not part of the name.
_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "plc", "llc", "lp", "ab", "publ", "asa", "oyj", "as", "sa", "nv", "se", "ag", "spa",
    "com", "shs", "ser", "series", "class", "cl", "a", "b", "c", "d", "sdb", "the",
    "and", "new", "s", "p",  # "Eli Lilly & Co", "Co/New", "S.A.", "S.p.A."
}
# Single words too common to match on their own (English and Swedish).
_COMMON_WORDS = set(
    """
    about after again against all also america american and any apple are back bank
    best better big block blue bridge capital care central change city clear click
    close cloud core credit data day deal design digital direct east energy equity
    every first five focus for free from fund future general global gold good great
    green group growth health here high home hope house idea image impact index
    insight just key labs land life light line link live local long main make market
    match media more most move national net new news next north note now one open
    order origin over park part partner people plan play plus point power prime pro
    real red right river rock royal safe sales same sea service share shift smart snap
    social solar south space spark star state still stock store sun target team tech
    the they three time today top total trade trust two under union unit united up
    value vision water way west what when where will wind with work world year your
    alla andra arbete bank bara bolag bra del den det dag eller fler for framtid
    gruppen har hem hus inte investor kapital kraft liv mer med mot nord norr ny nya
    och om over plus rapport ska som stad sverige svensk syd under var vision
    """.split()
)


@dataclass
class UniverseCompany:
    name: str
    country: str
    currency: str
    listings: list[tuple[str, str]]  # (symbol, mic); the first is primary
    cik: str | None = None


@dataclass
class UniverseReport:
    fetched: dict[str, int] = field(default_factory=dict)  # per market
    created: int = 0
    updated: int = 0
    listings_added: int = 0
    aliases_added: int = 0
    aliases_skipped: int = 0  # already used by another company
    deactivated: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def clean_name(name: str) -> str:
    """Normalized name without legal form or share class: "AMAZON COM INC" -> "amazon"."""
    words = normalize_name(name).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    while words and words[0] in {"the", "ab"}:
        words.pop(0)
    return " ".join(words)


def generated_aliases(name: str) -> list[str]:
    """Aliases safe enough to match in text. Single words must be distinctive."""
    out = []
    for alias in dict.fromkeys([normalize_name(name), clean_name(name)]):
        words = alias.split()
        if not words:
            continue
        if len(words) == 1 and (len(alias) < 4 or alias in _COMMON_WORDS):
            continue
        out.append(alias)
    return out


def _display_name(name: str) -> str:
    return name.title() if name.isupper() else name


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean_name(name) or normalize_name(name)).strip("-")[:90]


def fetch_us(client: httpx.Client, topic: TopicConfig, settings: Settings) -> list[UniverseCompany]:
    if not settings.sec_user_agent:
        raise ValueError("set SEC_USER_AGENT")
    response = client.get(SEC_TICKERS_URL, headers={"User-Agent": settings.sec_user_agent})
    response.raise_for_status()
    data = response.json()
    cols = {name: i for i, name in enumerate(data["fields"])}
    by_cik: dict[str, UniverseCompany] = {}
    for row in data["data"]:
        exchange, ticker = row[cols["exchange"]], row[cols["ticker"]]
        mic = SEC_EXCHANGE_MIC.get(exchange)
        if exchange not in topic.universe.us_exchanges or mic is None:
            continue
        # Share classes like BRK-B are fine; warrants, units and preferreds are not.
        if "-" in ticker and not re.fullmatch(r"[A-Z]+-[A-C]", ticker):
            continue
        cik = str(row[cols["cik"]]).zfill(10)
        company = by_cik.get(cik)
        if company is None:
            if len(by_cik) >= topic.universe.us_max_companies:
                continue  # the file is ordered roughly by size
            company = by_cik[cik] = UniverseCompany(
                name=_display_name(row[cols["name"]]), country="US", currency="USD",
                listings=[], cik=cik,
            )
        company.listings.append((ticker.replace("-", " "), mic))
    return list(by_cik.values())


def fetch_se(client: httpx.Client, topic: TopicConfig, settings: Settings) -> list[UniverseCompany]:
    exchange = topic.universe.se_finnhub_exchange
    if not exchange:
        return []
    if not settings.finnhub_api_key:
        raise ValueError("set FINNHUB_API_KEY")
    response = client.get(
        FINNHUB_SYMBOLS_URL,
        params={"exchange": exchange},
        headers={"X-Finnhub-Token": settings.finnhub_api_key},
    )
    response.raise_for_status()
    se_mics = {mic for m in topic.markets if m.key == "SE" for mic in m.mics}
    by_name: dict[str, UniverseCompany] = {}
    for row in response.json():
        mic = row.get("mic") or ""
        if row.get("type") != "Common Stock" or mic not in se_mics:
            continue
        symbol = row["symbol"].removesuffix(f".{exchange}").replace("-", " ")
        description = row.get("description") or symbol
        key = clean_name(description) or symbol
        company = by_name.setdefault(
            key,
            UniverseCompany(
                name=_display_name(description), country="SE",
                currency=row.get("currency") or "SEK", listings=[],
            ),
        )
        company.listings.append((symbol, mic))
    for company in by_name.values():
        # B shares trade most in Stockholm; list them first so they become primary.
        company.listings.sort(key=lambda listing: (not listing[0].endswith(" B"), listing[0]))
    return list(by_name.values())


def sync_universe(
    session: Session,
    topic: TopicConfig,
    companies: list[UniverseCompany],
    *,
    markets: set[str],
    report: UniverseReport | None = None,
) -> UniverseReport:
    """Upsert universe companies. Only markets in `markets` (fetched OK) can deactivate."""
    report = report or UniverseReport()
    existing = session.scalars(select(Company).where(Company.topic == topic.key)).all()
    by_cik = {c.cik: c for c in existing if c.cik}
    by_listing = {
        (listing.symbol, listing.mic): listing
        for listing in session.scalars(
            select(Listing).join(Company).where(Company.topic == topic.key)
        )
    }
    alias_owner = {
        a.alias_normalized: a.company_id
        for a in session.scalars(
            select(CompanyAlias).join(Company).where(Company.topic == topic.key)
        )
    }
    keys = {c.key for c in existing}
    seen: set[int] = set()

    for uc in companies:
        company = by_cik.get(uc.cik) if uc.cik else None
        if company is None:
            company = next(
                (by_listing[lst].company for lst in uc.listings if lst in by_listing), None
            )
        if company is None:
            key = base = _slug(uc.name) or uc.listings[0][0].lower()
            n = 2
            while key in keys:
                key, n = f"{base}-{n}", n + 1
            keys.add(key)
            company = Company(
                topic=topic.key, key=key, name=uc.name, country=uc.country, origin="universe"
            )
            session.add(company)
            session.flush()
            report.created += 1
        elif company.origin == "universe":
            company.name = uc.name
            company.active = True
            report.updated += 1
        if uc.cik and not company.cik:
            company.cik = uc.cik
            by_cik[uc.cik] = company
        seen.add(company.id)

        has_primary = any(lst.is_primary for lst in company.listings)
        for symbol, mic in uc.listings:
            if (symbol, mic) in by_listing:
                continue
            listing = Listing(
                company_id=company.id, symbol=symbol, mic=mic, currency=uc.currency,
                is_primary=not has_primary,
            )
            has_primary = True
            session.add(listing)
            by_listing[(symbol, mic)] = listing
            report.listings_added += 1

        if company.origin != "universe":
            continue  # curated companies keep their hand-written aliases
        for alias in generated_aliases(uc.name):
            owner = alias_owner.get(alias)
            if owner is not None and owner != company.id:
                report.aliases_skipped += 1  # ambiguous: first (largest) company keeps it
                continue
            if owner is None:
                session.add(
                    CompanyAlias(company_id=company.id, alias=alias, alias_normalized=alias)
                )
                alias_owner[alias] = company.id
                report.aliases_added += 1

    # Delisted: universe companies of a fetched market that no longer appear.
    # (Universe companies get their market's key as country.)
    stale = [
        c.id for c in existing
        if c.origin == "universe" and c.active and c.id not in seen and c.country in markets
    ]
    if stale:
        report.deactivated = session.execute(
            update(Company).where(Company.id.in_(stale)).values(active=False)
        ).rowcount
    session.commit()
    return report


def refresh_universe(
    session: Session, client: httpx.Client, topic: TopicConfig, settings: Settings
) -> UniverseReport:
    report = UniverseReport()
    fetched: list[UniverseCompany] = []
    ok: set[str] = set()
    for market, fetch in (("US", fetch_us), ("SE", fetch_se)):
        try:
            companies = fetch(client, topic, settings)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            report.errors[market] = f"{type(e).__name__}: {e}"[:300]
            continue
        report.fetched[market] = len(companies)
        fetched.extend(companies)
        ok.add(market)
    if fetched:
        sync_universe(session, topic, fetched, markets=ok, report=report)
    return report
