"""Collect from every enabled source and store new articles."""

import datetime as dt
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.collect.dedup import content_hash, url_hash
from app.collect.fetchers import FetchContext, SourceSkipped, fetch_source
from app.collect.parsers import FetchedItem
from app.config import Settings
from app.models import (
    Article,
    ArticleAnalysis,
    ArticleCompany,
    Citation,
    Company,
    CompanyAlias,
    Listing,
    Setting,
    Source,
    StoryArticle,
    TrackedStock,
)
from app.topic import TopicConfig
from app.user_settings import market_enabled, source_enabled

log = logging.getLogger(__name__)

# Older items are ignored: a first run shouldn't backfill weeks of news.
MAX_ITEM_AGE = dt.timedelta(days=7)
# The same headline + excerpt within this window counts as a duplicate.
CONTENT_DEDUP_WINDOW = dt.timedelta(days=3)


@dataclass
class SourceResult:
    key: str
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    too_old: int = 0
    other_language: int = 0
    skipped: str | None = None
    error: str | None = None


def collect(
    session: Session,
    client: httpx.Client,
    topic: TopicConfig,
    settings: Settings,
    *,
    source_keys: list[str] | None = None,
    now: dt.datetime | None = None,
) -> list[SourceResult]:
    now = now or dt.datetime.now(dt.UTC)
    query = select(Source).where(Source.topic == topic.key, Source.enabled).order_by(Source.key)
    if source_keys:
        query = query.where(Source.key.in_(source_keys))

    results = []
    for source in session.scalars(query).all():
        result = SourceResult(source.key)
        results.append(result)
        if not source_enabled(session, source.key):
            result.skipped = "turned off in Settings"
            continue
        if not market_enabled(session, source.market):
            result.skipped = f"market {source.market} turned off in Settings"
            continue
        try:
            items = fetch_source(
                client, source, settings, ctx=_context(session, topic, source, now), now=now
            )
        except SourceSkipped as e:
            result.skipped = str(e)
            continue
        except (httpx.HTTPError, ValueError) as e:  # ValueError covers bad XML/JSON
            result.error = f"{type(e).__name__}: {e}"[:500]
            source.last_error = result.error
            session.commit()
            log.warning("source %s failed: %s", source.key, result.error)
            continue

        result.fetched = len(items)
        _store(session, source, items, now, result, set(topic.article_languages))
        source.last_fetched_at = now
        source.last_error = None
        session.commit()
    return results


def _context(
    session: Session, topic: TopicConfig, source: Source, now: dt.datetime
) -> FetchContext:
    """Only what this source's fetcher uses, to keep the hourly run light."""
    ctx = FetchContext(language=_briefing_language(session, topic))
    if source.fetcher == "finnhub_company_news":
        ctx.symbols = _symbols(session, topic, source.market)
    if source.fetcher in ("sec_insiders", "fi_insider"):
        ctx.known_urls = set(session.scalars(
            select(Article.url_hash).where(
                Article.source_id == source.id, Article.fetched_at >= now - MAX_ITEM_AGE * 2)
        ))
    if source.fetcher == "sec_insiders":
        ctx.company_by_cik = dict(session.execute(
            select(Company.cik, Company.id).where(
                Company.topic == topic.key, Company.active, Company.cik.is_not(None))
        ).all())
    if source.fetcher == "fi_insider":
        ctx.company_by_name = dict(session.execute(
            select(CompanyAlias.alias_normalized, CompanyAlias.company_id)
            .join(Company)
            .where(Company.topic == topic.key, Company.active)
        ).all())
    return ctx


def _briefing_language(session: Session, topic: TopicConfig) -> str:
    stored = session.get(Setting, "briefing")
    return (stored.value or {}).get("language", topic.briefing.language) if stored else (
        topic.briefing.language)


def _symbols(session: Session, topic: TopicConfig, market_key: str | None) -> list[str]:
    """Primary symbols to fetch per-stock news for: your watchlist in the source's market.

    Per-stock APIs cost one call per symbol, so the universe (thousands of companies)
    is never queried this way. With no watchlist yet, companies.csv stands in.
    """
    mics = {mic for m in topic.markets if m.key == market_key for mic in m.mics}
    if not mics:
        return []
    query = (
        select(Listing.symbol)
        .join(Company)
        .where(
            Company.topic == topic.key,
            Company.active,
            Listing.is_primary,
            Listing.mic.in_(mics),
        )
        .order_by(Listing.symbol)
    )
    watched = list(session.scalars(query.join(TrackedStock, TrackedStock.company_id == Company.id)))
    return watched or list(session.scalars(query.where(Company.origin == "curated")))


def _store(
    session: Session,
    source: Source,
    items: list[FetchedItem],
    now: dt.datetime,
    result: SourceResult,
    languages: set[str],
) -> None:
    rows: dict[str, dict] = {}  # by url_hash; also dedups within this batch
    tags: dict[str, dict | None] = {}
    for item in items:
        language = item.language or source.language
        if languages and language not in languages:
            result.other_language += 1
            continue
        published = min(item.published_at, now)  # bad clocks/timezones upstream
        if now - published > MAX_ITEM_AGE:
            result.too_old += 1
            continue
        h = url_hash(item.url)
        if h in rows:
            result.duplicates += 1
            continue
        tags[h] = item.tag
        rows[h] = {
            "tag_status": "tagged" if item.tag else (item.status or "pending"),
            "topic": source.topic,
            "source_id": source.id,
            "url": item.url,
            "url_hash": h,
            "content_hash": content_hash(item.title, item.summary),
            "title": item.title,
            "summary": item.summary,
            "language": language,
            "is_press_release": source.is_press_release,
            "published_at": published,
            "raw": item.raw or None,
        }
    if not rows:
        return

    seen_urls = set(session.scalars(select(Article.url_hash).where(Article.url_hash.in_(rows))))
    seen_content = set(
        session.scalars(
            select(Article.content_hash).where(
                Article.content_hash.in_({r["content_hash"] for r in rows.values()}),
                Article.published_at >= now - CONTENT_DEDUP_WINDOW,
            )
        )
    )
    fresh = []
    for h, row in rows.items():
        if h in seen_urls or row["content_hash"] in seen_content:
            result.duplicates += 1
            continue
        seen_content.add(row["content_hash"])
        fresh.append(row)
    if fresh:
        # ON CONFLICT covers two runs overlapping; the scheduler should prevent that anyway.
        inserted = session.execute(
            insert(Article)
            .values(fresh)
            .on_conflict_do_nothing(index_elements=["url_hash"])
            .returning(Article.id, Article.url_hash)
        ).all()
        result.new += len(inserted)
        result.duplicates += len(fresh) - len(inserted)
        _store_rule_tags(session, [(row.id, tags[row.url_hash]) for row in inserted])


def _store_rule_tags(session: Session, rows: list[tuple[int, dict | None]]) -> None:
    """Structured items (insider trades) arrive tagged by rules: store what the AI would."""
    for article_id, tag in rows:
        if not tag:
            continue
        session.add(ArticleAnalysis(
            article_id=article_id, event_type=tag["event_type"], basis=tag["basis"],
            sentiment=tag["sentiment"], importance=tag["importance"], summary=tag["summary"],
            model="rules", prompt_version="rules-v1",
        ))
        session.add(ArticleCompany(
            article_id=article_id, company_id=tag["company_id"], matched_alias=tag["matched"],
            role="subject", sentiment=tag["sentiment"],
        ))


def prune_untagged(
    session: Session, *, older_than_days: int, now: dt.datetime | None = None
) -> int:
    """Delete old articles that mention no tracked company. Keeps the free database small."""
    now = now or dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(days=older_than_days)
    count = session.execute(
        delete(Article).where(
            Article.fetched_at < cutoff,
            ~exists().where(ArticleCompany.article_id == Article.id),
            ~exists().where(StoryArticle.article_id == Article.id),
            ~exists().where(Citation.article_id == Article.id),
        )
    ).rowcount
    session.commit()
    return count
