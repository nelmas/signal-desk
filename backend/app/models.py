"""Database schema.

Single-user app: there is no users table. Tables that hold topic-specific data
carry a `topic` column so the same engine can run other news topics later.
"""

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONB, dt.datetime: DateTime(timezone=True)}


def created_at_column() -> Mapped[dt.datetime]:
    return mapped_column(server_default=func.now())


# --- Reference data -----------------------------------------------------------


class Company(Base):
    """An issuer. News is tagged to companies; prices belong to listings."""

    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("topic", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(50))
    key: Mapped[str] = mapped_column(String(100))  # stable slug, e.g. "volvo"
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[dt.datetime] = created_at_column()

    listings: Mapped[list["Listing"]] = relationship(back_populates="company")
    aliases: Mapped[list["CompanyAlias"]] = relationship(back_populates="company")


class Listing(Base):
    """A tradable share class on an exchange (e.g. VOLV B on XSTO)."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("symbol", "mic"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(30))  # exchange-native symbol
    mic: Mapped[str] = mapped_column(String(4))  # ISO 10383 exchange code
    currency: Mapped[str] = mapped_column(String(3))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false")

    company: Mapped[Company] = relationship(back_populates="listings")


class CompanyAlias(Base):
    """Names the AI may use for a company; matched case/accent-insensitively."""

    __tablename__ = "company_aliases"
    __table_args__ = (UniqueConstraint("company_id", "alias_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(200))
    alias_normalized: Mapped[str] = mapped_column(String(200), index=True)

    company: Mapped[Company] = relationship(back_populates="aliases")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("topic", "key"),
        CheckConstraint("kind IN ('rss', 'api', 'press_wire')", name="kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(50))
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    fetcher: Mapped[str] = mapped_column(String(50), server_default="rss")
    url: Mapped[str | None] = mapped_column(Text)
    market: Mapped[str | None] = mapped_column(String(10))
    language: Mapped[str] = mapped_column(String(5))
    is_press_release: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Why we are allowed to use this source (terms URL / note). Required by principle.
    terms_basis: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    last_fetched_at: Mapped[dt.datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = created_at_column()


# --- News ---------------------------------------------------------------------


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        CheckConstraint(
            "tag_status IN ('pending', 'no_match', 'tagged', 'irrelevant', 'failed')",
            name="tag_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of canonical URL
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # near-dup detection
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(5))
    is_press_release: Mapped[bool] = mapped_column(Boolean, server_default="false")
    published_at: Mapped[dt.datetime] = mapped_column(index=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    raw: Mapped[dict[str, Any] | None]
    # pending -> no_match (names no tracked company), tagged, irrelevant (AI: only a
    # passing mention) or failed (AI gave no usable answer after several tries).
    tag_status: Mapped[str] = mapped_column(String(20), server_default="pending", index=True)
    tag_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    analysis: Mapped["ArticleAnalysis | None"] = relationship(back_populates="article")


class ArticleAnalysis(Base):
    """AI output for one article. Model + prompt version kept for auditability."""

    __tablename__ = "article_analyses"
    __table_args__ = (
        CheckConstraint("sentiment BETWEEN -1 AND 1", name="sentiment_range"),
        CheckConstraint("importance BETWEEN 0 AND 1", name="importance_range"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    sentiment: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    importance: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[dt.datetime] = created_at_column()

    article: Mapped[Article] = relationship(back_populates="analysis")


class ArticleCompany(Base):
    """Verified article→company tags. Only rows that matched the ticker list exist."""

    __tablename__ = "article_companies"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    matched_alias: Mapped[str] = mapped_column(String(200))


# --- Market data & scoring ----------------------------------------------------


class PriceDaily(Base):
    __tablename__ = "prices_daily"

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(50))


class SignalScore(Base):
    __tablename__ = "signal_scores"
    __table_args__ = (CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),)

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    components: Mapped[dict[str, Any]]  # each factor's raw value and 0-100 sub-score
    weights: Mapped[dict[str, Any]]  # weights in effect when computed
    created_at: Mapped[dt.datetime] = created_at_column()


# --- Briefings ----------------------------------------------------------------


class Briefing(Base):
    __tablename__ = "briefings"
    __table_args__ = (
        UniqueConstraint("topic", "date", "language"),
        CheckConstraint("status IN ('draft', 'ready', 'sent', 'failed')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(50))
    date: Mapped[dt.date] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    overview: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict[str, Any] | None]  # sections: stories, sectors, ideas, holdings
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[dt.datetime] = created_at_column()
    sent_at: Mapped[dt.datetime | None]


class Story(Base):
    """A cluster of articles about the same event."""

    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(50))
    briefing_id: Mapped[int | None] = mapped_column(
        ForeignKey("briefings.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(String(50))
    rank: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[dt.datetime]
    created_at: Mapped[dt.datetime] = created_at_column()


class StoryArticle(Base):
    __tablename__ = "story_articles"

    story_id: Mapped[int] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Citation(Base):
    """Links one claim in a briefing (`ref`, e.g. "story:3:what") to a source article.

    The UI renders [n] markers from these rows; the AI cannot cite anything that
    is not here.
    """

    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("briefing_id", "ref", "article_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    briefing_id: Mapped[int] = mapped_column(ForeignKey("briefings.id", ondelete="CASCADE"))
    ref: Mapped[str] = mapped_column(String(100))
    ordinal: Mapped[int] = mapped_column(SmallInteger)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"))


# --- Ideas & track record -----------------------------------------------------


class Idea(Base):
    """A stock to research, as published in a briefing.

    Entry is the next session's open after publication (filled in later), so
    the track record never benefits from moves that happened before you could act.
    """

    __tablename__ = "ideas"
    __table_args__ = (
        CheckConstraint("confidence IN ('low', 'medium', 'high')", name="confidence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    thesis: Mapped[str] = mapped_column(Text)
    risks: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(10))
    benchmark: Mapped[str] = mapped_column(String(50))
    published_at: Mapped[dt.datetime]
    entry_date: Mapped[dt.date | None] = mapped_column(Date)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    created_at: Mapped[dt.datetime] = created_at_column()


class IdeaOutcome(Base):
    __tablename__ = "idea_outcomes"

    idea_id: Mapped[int] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True
    )
    horizon_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)  # 1, 5, 20
    exit_date: Mapped[dt.date] = mapped_column(Date)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    return_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    benchmark_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    excess_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    evaluated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# --- User data ----------------------------------------------------------------


class TrackedStock(Base):
    """Stocks always followed. `is_holding` powers "News about your holdings"."""

    __tablename__ = "tracked_stocks"

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    is_holding: Mapped[bool] = mapped_column(Boolean, server_default="false")
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class CalendarEvent(Base):
    """Scheduled events (earnings, CMDs, AGMs) for the "week ahead" section."""

    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("company_id", "event_type", "event_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50))
    event_date: Mapped[dt.date] = mapped_column(Date, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = created_at_column()


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("target_type IN ('story', 'idea')", name="target_type"),
        CheckConstraint("value IN (-1, 1)", name="value"),
        Index("ix_feedback_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[int] = mapped_column(Integer)
    value: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[dt.datetime] = created_at_column()


class Setting(Base):
    """User preferences as key → JSON (score weights, briefing time, language, ...)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]]
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# --- Operations ---------------------------------------------------------------


class AICall(Base):
    """One row per LLM call, written by the AI client wrapper. Feeds the cost monitor."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(50), index=True)  # "tag_article", "briefing"
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), index=True)
