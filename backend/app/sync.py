"""Copy the topic config (sources, companies, default settings) into the database.

Idempotent: safe to run after every edit to topic.yaml / companies.csv.
Companies removed from the CSV are deactivated, not deleted, so old articles
keep their tags.
"""

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Company, CompanyAlias, Listing, Setting, Source
from app.names import normalize_name
from app.topic import CompanySpec, TopicConfig


@dataclass
class SyncReport:
    sources: int = 0
    companies: int = 0
    listings: int = 0
    aliases_added: int = 0
    deactivated: int = 0
    settings_added: int = 0


def sync_topic(session: Session, topic: TopicConfig, companies: list[CompanySpec]) -> SyncReport:
    report = SyncReport()
    _sync_sources(session, topic, report)
    _sync_companies(session, topic, companies, report)
    _seed_settings(session, topic, report)
    session.commit()
    return report


def _sync_sources(session: Session, topic: TopicConfig, report: SyncReport) -> None:
    existing = {
        s.key: s for s in session.scalars(select(Source).where(Source.topic == topic.key))
    }
    for cfg in topic.sources:
        source = existing.get(cfg.key) or Source(topic=topic.key, key=cfg.key)
        source.name = cfg.name
        source.kind = cfg.kind
        source.url = cfg.url
        source.market = cfg.market
        source.language = cfg.language
        source.is_press_release = cfg.is_press_release
        source.terms_basis = cfg.terms_basis or ""
        source.enabled = cfg.enabled
        session.add(source)
        report.sources += 1


def _sync_companies(
    session: Session, topic: TopicConfig, specs: list[CompanySpec], report: SyncReport
) -> None:
    existing = {
        c.key: c for c in session.scalars(select(Company).where(Company.topic == topic.key))
    }
    for spec in specs:
        company = existing.get(spec.key) or Company(topic=topic.key, key=spec.key)
        company.name = spec.name
        company.country = spec.country
        company.sector = spec.sector
        company.active = True
        session.add(company)
        session.flush()  # need company.id
        report.companies += 1

        for ls in spec.listings:
            listing = session.scalar(
                select(Listing).where(Listing.symbol == ls.symbol, Listing.mic == ls.mic)
            ) or Listing(symbol=ls.symbol, mic=ls.mic)
            listing.company_id = company.id
            listing.currency = ls.currency
            listing.is_primary = ls.is_primary
            session.add(listing)
            report.listings += 1

        known = {a.alias_normalized for a in company.aliases}
        for alias in spec.aliases:
            norm = normalize_name(alias)
            if norm not in known:
                session.add(CompanyAlias(company_id=company.id, alias=alias, alias_normalized=norm))
                known.add(norm)
                report.aliases_added += 1

    removed = set(existing) - {s.key for s in specs}
    if removed:
        result = session.execute(
            update(Company)
            .where(Company.topic == topic.key, Company.key.in_(removed), Company.active)
            .values(active=False)
        )
        report.deactivated = result.rowcount


def _seed_settings(session: Session, topic: TopicConfig, report: SyncReport) -> None:
    """Insert defaults only; never overwrite what the user changed in Settings."""
    defaults = {
        "scoring_weights": topic.scoring_weights.model_dump(),
        "briefing": topic.briefing.model_dump(),
    }
    for key, value in defaults.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value=value))
            report.settings_added += 1
