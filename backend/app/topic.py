"""Topic configuration: everything that makes this a *stock news* agent.

A topic is a folder under `topics/` with a `topic.yaml` and a companies CSV.
Swapping the folder (sources, entities, event types, prompts) lets the same
engine run a different news agent.
"""

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from app.config import get_settings
from app.names import normalize_name


class SourceConfig(BaseModel):
    key: str
    name: str
    kind: Literal["rss", "api", "press_wire"]
    # How to read it: a generic RSS/Atom parser, or a named API client.
    fetcher: Literal["rss", "atom", "finnhub_company_news"] = "rss"
    url: str | None = None
    market: str | None = None
    language: str
    is_press_release: bool = False
    # Why we may use this source: link to terms / API licence and a short note.
    terms_basis: str | None = None
    enabled: bool = False

    @model_validator(mode="after")
    def enabled_sources_are_complete(self) -> "SourceConfig":
        if self.enabled and not (self.url and self.terms_basis):
            raise ValueError(f"source {self.key!r} is enabled but lacks url or terms_basis")
        return self


class EventType(BaseModel):
    key: str
    label: str
    importance: float = Field(ge=0, le=1)  # default weight before user feedback


class ScoringWeights(BaseModel):
    news_volume: float = Field(ge=0)
    event_importance: float = Field(ge=0)
    sentiment_shift: float = Field(ge=0)

    @model_validator(mode="after")
    def not_all_zero(self) -> "ScoringWeights":
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("at least one scoring weight must be positive")
        return self


class Market(BaseModel):
    key: str
    name: str
    mics: list[str]
    timezone: str
    benchmark: str  # name of the index ideas are compared against


class BriefingConfig(BaseModel):
    send_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str
    language: str
    max_stories: int = Field(ge=1)
    max_sectors: int = Field(ge=0)
    max_ideas: int = Field(ge=0)


class UniverseConfig(BaseModel):
    us_exchanges: list[str] = ["Nasdaq", "NYSE"]
    us_max_companies: int = Field(default=1500, ge=0)
    se_finnhub_exchange: str | None = "ST"


class TopicConfig(BaseModel):
    key: str
    name: str
    description: str
    companies_file: str
    markets: list[Market]
    # Articles in other languages are dropped at collection. Empty means keep all.
    article_languages: list[str] = []
    universe: UniverseConfig = UniverseConfig()
    sources: list[SourceConfig]
    event_types: list[EventType]
    scoring_weights: ScoringWeights
    briefing: BriefingConfig

    @model_validator(mode="after")
    def keys_unique(self) -> "TopicConfig":
        for label, keys in (
            ("market", [m.key for m in self.markets]),
            ("source", [s.key for s in self.sources]),
            ("event type", [e.key for e in self.event_types]),
        ):
            dupes = {k for k in keys if keys.count(k) > 1}
            if dupes:
                raise ValueError(f"duplicate {label} keys: {sorted(dupes)}")
        return self

    @property
    def mics(self) -> set[str]:
        return {mic for m in self.markets for mic in m.mics}

    def market_for_mic(self, mic: str) -> str | None:
        return next((m.key for m in self.markets if mic in m.mics), None)


class ListingSpec(BaseModel):
    symbol: str
    mic: str
    currency: str
    is_primary: bool


class CompanySpec(BaseModel):
    key: str
    name: str
    country: str = Field(pattern=r"^[A-Z]{2}$")
    sector: str | None
    aliases: list[str]
    listings: list[ListingSpec] = Field(min_length=1)


_LISTING = re.compile(r"^(?P<symbol>[^@]+)@(?P<mic>[A-Z]{4})$")


def _parse_company_row(row: dict[str, str]) -> CompanySpec:
    """Row format: listings are "SYMBOL@MIC" separated by "|"; the first is primary."""
    listings = []
    for i, part in enumerate(row["listings"].split("|")):
        m = _LISTING.match(part.strip())
        if not m:
            raise ValueError(f"{row['key']}: bad listing {part!r}, expected SYMBOL@MIC")
        listings.append(
            ListingSpec(
                symbol=m["symbol"].strip(),
                mic=m["mic"],
                currency=row["currency"].strip(),
                is_primary=i == 0,
            )
        )
    # The official name always counts as an alias.
    aliases = [row["name"], *(a.strip() for a in row["aliases"].split("|") if a.strip())]
    return CompanySpec(
        key=row["key"].strip(),
        name=row["name"].strip(),
        country=row["country"].strip(),
        sector=row["sector"].strip() or None,
        aliases=list(dict.fromkeys(aliases)),
        listings=listings,
    )


def load_companies(topic: TopicConfig, topic_dir: Path) -> list[CompanySpec]:
    path = topic_dir / topic.companies_file
    with path.open(encoding="utf-8", newline="") as f:
        companies = [_parse_company_row(row) for row in csv.DictReader(f)]

    seen_keys: set[str] = set()
    seen_listings: set[tuple[str, str]] = set()
    alias_owner: dict[str, str] = {}
    for c in companies:
        if c.key in seen_keys:
            raise ValueError(f"duplicate company key {c.key!r}")
        seen_keys.add(c.key)
        for listing in c.listings:
            if listing.mic not in topic.mics:
                raise ValueError(f"{c.key}: exchange {listing.mic} is not in any topic market")
            ident = (listing.symbol, listing.mic)
            if ident in seen_listings:
                raise ValueError(f"duplicate listing {listing.symbol}@{listing.mic}")
            seen_listings.add(ident)
        # An alias shared by two companies would make tagging ambiguous.
        for alias in c.aliases:
            norm = normalize_name(alias)
            owner = alias_owner.setdefault(norm, c.key)
            if owner != c.key:
                raise ValueError(f"alias {alias!r} used by both {owner!r} and {c.key!r}")
    return companies


def topic_dir(key: str | None = None) -> Path:
    settings = get_settings()
    return settings.topics_dir / (key or settings.topic)


def load_topic_from(path: Path) -> TopicConfig:
    with (path / "topic.yaml").open(encoding="utf-8") as f:
        return TopicConfig.model_validate(yaml.safe_load(f))


@lru_cache
def get_topic() -> TopicConfig:
    return load_topic_from(topic_dir())
