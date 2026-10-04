from pathlib import Path

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app
from app.models import Company, CompanyAlias, Listing, Setting, Source
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from
from tests.conftest import alembic_config

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"


def test_models_match_migrations(engine: Engine) -> None:
    """Fails if a model changed without a new migration."""
    command.check(alembic_config(engine.url.render_as_string(hide_password=False)))


def test_sync_topic_is_idempotent(session: Session) -> None:
    topic = load_topic_from(STOCKS_DIR)
    companies = load_companies(topic, STOCKS_DIR)

    first = sync_topic(session, topic, companies)
    second = sync_topic(session, topic, companies)

    assert first.aliases_added > 0 and second.aliases_added == 0
    assert session.scalar(select(func.count()).select_from(Company)) == len(companies)
    assert session.scalar(select(func.count()).select_from(Source)) == len(topic.sources)
    primary = session.scalars(
        select(Listing).join(Company).where(Company.key == "volvo", Listing.is_primary)
    ).one()
    assert primary.symbol == "VOLV B"
    alias = session.scalars(
        select(CompanyAlias).where(CompanyAlias.alias_normalized == "h and m")
    ).one()
    assert alias.company.key == "hm"


def test_sync_keeps_user_settings_and_deactivates_removed(session: Session) -> None:
    topic = load_topic_from(STOCKS_DIR)
    companies = load_companies(topic, STOCKS_DIR)
    sync_topic(session, topic, companies)

    session.get(Setting, "briefing").value = {"send_time": "06:30"}
    session.commit()
    report = sync_topic(session, topic, [c for c in companies if c.key != "tesla"])

    assert session.get(Setting, "briefing").value == {"send_time": "06:30"}
    assert report.deactivated == 1
    tesla = session.scalars(select(Company).where(Company.key == "tesla")).one()
    assert tesla.active is False


def test_health_endpoint(session: Session) -> None:
    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).get("/api/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200 and response.json() == {"status": "ok"}
