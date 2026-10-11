from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Company, CompanyAlias, Listing
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from
from app.universe import (
    UniverseCompany,
    clean_name,
    fetch_se,
    fetch_us,
    generated_aliases,
    refresh_universe,
    sync_universe,
)

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
# The Swedish fetch is off in topic.yaml (no free source yet); the code path is still tested.
TOPIC.universe.se_finnhub_exchange = "ST"
SETTINGS = Settings(sec_user_agent="Test test@example.com", finnhub_api_key="k")

SEC_JSON = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-A", "NYSE"],
        [27419, "TARGET CORP", "TGT", "NYSE"],
        [999001, "ACME WIDGETS INC", "ACME", "Nasdaq"],
        [999001, "ACME WIDGETS INC", "ACME-WT", "Nasdaq"],  # warrant: skipped
        [999002, "OTC THING INC", "OTCT", "OTC"],  # not a tracked exchange
        [999003, "TINY CO", "TINY", "NYSE"],
    ],
}
FINNHUB_JSON = [
    {"symbol": "VOLV-B.ST", "description": "VOLVO AB-B SHS", "mic": "XSTO",
     "type": "Common Stock", "currency": "SEK"},
    {"symbol": "VOLV-A.ST", "description": "VOLVO AB-A SHS", "mic": "XSTO",
     "type": "Common Stock", "currency": "SEK"},
    {"symbol": "ALLIGO-B.ST", "description": "ALLIGO AB-B", "mic": "XSTO",
     "type": "Common Stock", "currency": "SEK"},
    {"symbol": "ATORX.ST", "description": "ALLIGATOR BIOSCIENCE AB", "mic": "FNSE",
     "type": "Common Stock", "currency": "SEK"},
    {"symbol": "XACT.ST", "description": "XACT OMXS30", "mic": "XSTO",
     "type": "ETP", "currency": "SEK"},
]


def lists(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.sec.gov":
        return httpx.Response(200, json=SEC_JSON)
    return httpx.Response(200, json=FINNHUB_JSON)


@pytest.fixture
def client():
    with httpx.Client(transport=httpx.MockTransport(lists)) as c:
        yield c


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("AMAZON COM INC", "amazon"),
        ("The Coca-Cola Company", "coca cola"),
        ("VOLVO AB-B SHS", "volvo"),
        ("AT&T INC.", "at and t"),
        ("Alligator Bioscience AB (publ)", "alligator bioscience"),
        ("ELI LILLY & Co", "eli lilly"),
        ("Logitech International S.A.", "logitech international"),
        ("Lamar Advertising Co/New", "lamar advertising"),
    ],
)
def test_clean_name(raw: str, clean: str) -> None:
    assert clean_name(raw) == clean


def test_generic_single_word_names_are_not_aliases() -> None:
    assert "target" not in generated_aliases("TARGET CORP")
    assert "target corp" in generated_aliases("TARGET CORP")
    assert "nvidia" in generated_aliases("NVIDIA CORP")


def test_fetch_us_groups_share_classes_and_respects_limits(client) -> None:
    topic = TOPIC.model_copy(deep=True)
    topic.universe.us_max_companies = 4
    companies = {c.cik: c for c in fetch_us(client, topic, SETTINGS)}
    assert set(companies) == {"0000320193", "0001067983", "0000027419", "0000999001"}
    assert companies["0001067983"].listings == [("BRK B", "XNYS"), ("BRK A", "XNYS")]
    assert companies["0000999001"].listings == [("ACME", "XNAS")]


def test_fetch_se_groups_by_company_and_puts_b_shares_first(client) -> None:
    companies = {clean_name(c.name): c for c in fetch_se(client, TOPIC, SETTINGS)}
    assert set(companies) == {"volvo", "alligo", "alligator bioscience"}  # ETP skipped
    assert companies["volvo"].listings == [("VOLV B", "XSTO"), ("VOLV A", "XSTO")]
    assert companies["alligator bioscience"].listings == [("ATORX", "FNSE")]


def test_sync_merges_with_curated_and_adds_new_companies(db: Session, client) -> None:
    report = refresh_universe(db, client, TOPIC, SETTINGS)
    assert report.errors == {}

    apple = db.scalars(select(Company).where(Company.key == "apple")).one()
    assert apple.origin == "curated" and apple.cik == "0000320193"
    volvo = db.scalars(select(Company).where(Company.key == "volvo")).one()
    assert volvo.origin == "curated"  # matched by its listing, not duplicated

    alligator = db.scalars(select(Company).where(Company.key == "alligator-bioscience")).one()
    assert alligator.origin == "universe" and alligator.country == "SE"
    assert db.scalars(select(Listing).where(Listing.company_id == alligator.id)).one().is_primary
    aliases = set(
        db.scalars(
            select(CompanyAlias.alias_normalized).where(CompanyAlias.company_id == alligator.id)
        )
    )
    assert "alligator bioscience" in aliases

    again = refresh_universe(db, client, TOPIC, SETTINGS)
    assert again.created == 0 and again.listings_added == 0


def test_ambiguous_alias_stays_with_the_first_company(db: Session) -> None:
    sync_universe(db, TOPIC, [
        UniverseCompany("Nordic Widgets AB", "SE", "SEK", [("NWA", "XSTO")]),
        UniverseCompany("Nordic Widgets Holding", "SE", "SEK", [("NWH", "XSTO")]),
    ], markets={"SE"})
    owners = db.scalars(
        select(Company.key)
        .join(CompanyAlias)
        .where(CompanyAlias.alias_normalized == "nordic widgets")
    ).all()
    assert owners == ["nordic-widgets"]


def test_delisted_universe_companies_are_deactivated_but_curated_never(db: Session) -> None:
    sync_universe(db, TOPIC, [UniverseCompany("Gone AB", "SE", "SEK", [("GONE", "XSTO")])],
                  markets={"SE"})
    report = sync_universe(db, TOPIC, [], markets={"SE"})
    assert report.deactivated == 1
    assert db.scalars(select(Company).where(Company.key == "gone")).one().active is False
    assert db.scalars(select(Company).where(Company.key == "volvo")).one().active is True

    # Re-syncing companies.csv must not deactivate universe companies either.
    sync_universe(db, TOPIC, [UniverseCompany("Stays AB", "SE", "SEK", [("STAY", "XSTO")])],
                  markets={"SE"})
    sync_topic(db, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    assert db.scalars(select(Company).where(Company.key == "stays")).one().active is True


def test_failed_market_does_not_delist_it(db: Session) -> None:
    def sec_down(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.sec.gov":
            return httpx.Response(503)
        return httpx.Response(200, json=FINNHUB_JSON)

    sync_universe(db, TOPIC, [UniverseCompany("Us Thing Inc", "US", "USD", [("UST", "XNAS")])],
                  markets={"US"})
    with httpx.Client(transport=httpx.MockTransport(sec_down)) as c:
        report = refresh_universe(db, c, TOPIC, SETTINGS)
    assert "US" in report.errors and report.deactivated == 0


def test_sync_uses_a_handful_of_statements_not_one_per_company(db: Session) -> None:
    """The job runs far from the database; per-company round trips took 12+ minutes."""
    many = [
        UniverseCompany(f"Example Holding {i} AB", "SE", "SEK", [(f"EX{i} B", "XSTO")])
        for i in range(300)
    ]
    statements = []
    engine = db.get_bind()
    listen = lambda *args: statements.append(1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listen)
    try:
        report = sync_universe(db, TOPIC, many, markets={"SE"})
    finally:
        event.remove(engine, "before_cursor_execute", listen)
    assert report.created == 300 and report.listings_added == 300
    assert len(statements) < 30
