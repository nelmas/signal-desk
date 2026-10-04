import uuid
from collections.abc import Iterator
from pathlib import Path

import pgserver
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def pg_uri(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A fresh database on an embedded Postgres (with pgvector)."""
    server = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    name = f"test_{uuid.uuid4().hex[:8]}"
    server.psql(f"CREATE DATABASE {name};")
    base = server.get_uri().rsplit("/", 1)[0]
    yield f"postgresql+psycopg://{base.removeprefix('postgresql://')}/{name}"


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def engine(pg_uri: str) -> Engine:
    command.upgrade(alembic_config(pg_uri), "head")
    return create_engine(pg_uri)


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s
    # Each test starts from empty tables.
    with engine.begin() as conn:
        tables = conn.scalars(
            text(
                "select tablename from pg_tables "
                "where schemaname = 'public' and tablename <> 'alembic_version'"
            )
        ).all()
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
