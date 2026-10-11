"""Free first pass: which known companies does an article concern?

Only articles with at least one match go to the AI, and the AI may only pick
from these matches. That is how the agent never invents a company.

Strongest evidence first:
1. SEC filings name the filer's company id (CIK): an exact match.
2. MFN and Cision links name the issuing company: the press release is theirs.
3. Names in headline and excerpt, as whole words, within the article's own market
   (plus your watchlist, which matches everywhere), so a Swedish release mentioning
   "Target" doesn't drag in the US retailer.
4. Finnhub news is fetched per stock symbol, so that stock is a candidate.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article, Company, CompanyAlias, Listing, TrackedStock
from app.names import normalize_name
from app.topic import TopicConfig
from app.universe import clean_name

MAX_ALIAS_WORDS = 6
_SEC_CIK = re.compile(r"\((\d{10})\)")


@dataclass
class CompanyIndex:
    by_alias: dict[str, int] = field(default_factory=dict)  # normalized alias -> company id
    by_symbol: dict[str, int] = field(default_factory=dict)  # listing symbol -> company id
    by_cik: dict[str, int] = field(default_factory=dict)
    market: dict[int, str | None] = field(default_factory=dict)  # company id -> market key
    watched: set[int] = field(default_factory=set)
    keys: dict[int, str] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)

    @classmethod
    def load(cls, session: Session, topic: TopicConfig) -> "CompanyIndex":
        index = cls()
        for c in session.scalars(select(Company).where(Company.topic == topic.key, Company.active)):
            index.keys[c.id] = c.key
            index.names[c.id] = c.name
            if c.cik:
                index.by_cik[c.cik] = c.id
        ids = list(index.keys)
        for alias in session.scalars(select(CompanyAlias).where(CompanyAlias.company_id.in_(ids))):
            index.by_alias.setdefault(alias.alias_normalized, alias.company_id)
        for listing in session.scalars(
            select(Listing).where(Listing.company_id.in_(ids)).order_by(Listing.is_primary.desc())
        ):
            index.by_symbol.setdefault(listing.symbol, listing.company_id)
            if listing.is_primary or listing.company_id not in index.market:
                index.market[listing.company_id] = topic.market_for_mic(listing.mic)
        index.watched = set(session.scalars(select(TrackedStock.company_id)))
        return index

    def match(self, article: Article, market: str | None = None) -> dict[int, str]:
        """Company id -> what matched ("cik:…", "issuer:…", an alias or "symbol:…")."""
        cik = _SEC_CIK.search(article.title)
        if cik and "sec.gov" in article.url:
            company_id = self.by_cik.get(cik.group(1))
            return {company_id: f"cik:{cik.group(1)}"} if company_id else {}

        found: dict[int, str] = {}
        issuer = _issuer_slug(article.url)
        if issuer:
            for name in (normalize_name(issuer), clean_name(issuer)):
                if name in self.by_alias:
                    found[self.by_alias[name]] = f"issuer:{issuer}"
                    break

        words = normalize_name(f"{article.title} {article.summary or ''}").split()
        # Every run of 1..6 consecutive words is looked up, so "h and m" or
        # "jp morgan" match as whole phrases and "visade" never matches "visa".
        for size in range(MAX_ALIAS_WORDS, 0, -1):
            for i in range(len(words) - size + 1):
                company_id = self.by_alias.get(" ".join(words[i : i + size]))
                if company_id is None or company_id in found:
                    continue
                if market is None or self.market.get(company_id) == market or (
                    company_id in self.watched
                ):
                    found[company_id] = " ".join(words[i : i + size])

        symbol = (article.raw or {}).get("queried_symbol")
        if symbol in self.by_symbol:
            found.setdefault(self.by_symbol[symbol], f"symbol:{symbol}")
        return found


def _issuer_slug(url: str) -> str | None:
    """The company slug in press-release links: mfn.se/a/<slug>/…, news.cision.com/se/<slug>/r/…"""
    parts = urlsplit(url)
    path = [p for p in parts.path.split("/") if p]
    host = parts.hostname or ""
    if host.endswith("mfn.se") and len(path) >= 3 and path[0] == "a":
        return path[1].replace("-", " ")
    if host.endswith("cision.com") and len(path) >= 4 and path[2] == "r":
        return path[1].replace("-", " ")
    return None
