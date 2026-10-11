"""Free first pass: which tracked companies does an article name?

Only articles with at least one match go to the AI, and the AI may only pick
from these matches. That is how the agent never invents a company.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article, Company, CompanyAlias, Listing
from app.names import normalize_name

MAX_ALIAS_WORDS = 6


@dataclass
class CompanyIndex:
    by_alias: dict[str, int] = field(default_factory=dict)  # normalized alias -> company id
    by_symbol: dict[str, int] = field(default_factory=dict)  # listing symbol -> company id
    keys: dict[int, str] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)

    @classmethod
    def load(cls, session: Session, topic: str) -> "CompanyIndex":
        index = cls()
        companies = session.scalars(
            select(Company).where(Company.topic == topic, Company.active)
        ).all()
        for c in companies:
            index.keys[c.id] = c.key
            index.names[c.id] = c.name
        ids = list(index.keys)
        for alias in session.scalars(select(CompanyAlias).where(CompanyAlias.company_id.in_(ids))):
            index.by_alias[alias.alias_normalized] = alias.company_id
        for listing in session.scalars(select(Listing).where(Listing.company_id.in_(ids))):
            index.by_symbol[listing.symbol] = listing.company_id
        return index

    def match(self, article: Article) -> dict[int, str]:
        """Company id -> the alias (or symbol) that matched, for title + excerpt."""
        found: dict[int, str] = {}
        words = normalize_name(f"{article.title} {article.summary or ''}").split()
        # Every run of 1..6 consecutive words is looked up, so "h and m" or
        # "jp morgan" match as whole phrases and "visade" never matches "visa".
        for size in range(MAX_ALIAS_WORDS, 0, -1):
            for i in range(len(words) - size + 1):
                phrase = " ".join(words[i : i + size])
                company_id = self.by_alias.get(phrase)
                if company_id is not None and company_id not in found:
                    found[company_id] = phrase
        # Finnhub returns news per stock symbol; trust that link too.
        symbol = (article.raw or {}).get("queried_symbol")
        if symbol in self.by_symbol:
            found.setdefault(self.by_symbol[symbol], f"symbol:{symbol}")
        return found
