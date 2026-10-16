import datetime as dt
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collect import collect
from app.collect.insiders_us import parse_daily_index, parse_form4, recent_business_days
from app.config import Settings
from app.models import Article, ArticleAnalysis, ArticleCompany, Company, Setting
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
SETTINGS = Settings(sec_user_agent="Test Person test@example.com")
NOW = dt.datetime(2026, 10, 16, 14, 0, tzinfo=dt.UTC)  # Friday; index for Thursday the 15th
CIKS = {
    "apple": "0000320193",
    "nvidia": "0001045810",
    "microsoft": "0000789019",
    "tesla": "0001318605",
}
FORM4 = {
    "000121415626000001": "form4_purchase.xml",
    "000199999926000002": "form4_planned_sale.xml",
    "000188888826000003": "form4_grant.xml",
}


class FakeRegisters:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        if request.url.host == "marknadssok.fi.se":
            return httpx.Response(200, content=(FIXTURES / "fi_export.csv").read_bytes())
        if path.endswith("form.20261015.idx"):
            return httpx.Response(200, content=(FIXTURES / "form_daily.idx").read_bytes())
        folder = path.rstrip("/").split("/")[-2] if path.endswith((".json", ".xml")) else ""
        if path.endswith("index.json") and folder in FORM4:
            return httpx.Response(
                200,
                json={
                    "directory": {"item": [{"name": f"{folder}-index.html"}, {"name": "doc4.xml"}]}
                },
            )
        if path.endswith("doc4.xml") and folder in FORM4:
            return httpx.Response(200, content=(FIXTURES / FORM4[folder]).read_bytes())
        return httpx.Response(404)


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    for key, cik in CIKS.items():
        session.scalars(select(Company).where(Company.key == key)).one().cik = cik
    session.commit()
    return session


def run(db: Session, fake: FakeRegisters, sources: list[str]):
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        return {
            r.key: r for r in collect(db, client, TOPIC, SETTINGS, source_keys=sources, now=NOW)
        }


def tagged(db: Session) -> dict[str, tuple[Article, ArticleAnalysis, str]]:
    rows = db.execute(
        select(Article, ArticleAnalysis, Company.key)
        .join(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
        .join(ArticleCompany, ArticleCompany.article_id == Article.id)
        .join(Company, Company.id == ArticleCompany.company_id)
    ).all()
    return {key: (a, an, key) for a, an, key in rows}


# --- parsing --------------------------------------------------------------------------


def test_daily_index_and_business_days() -> None:
    lines = parse_daily_index((FIXTURES / "form_daily.idx").read_text(encoding="latin-1"))
    assert len(lines) == 11
    assert (lines[0].form, lines[0].cik, lines[0].accession) == (
        "4",
        "0000320193",
        "0001214156-26-000001",
    )
    assert lines[7].form == "SCHEDULE 13D"
    assert recent_business_days(dt.datetime(2026, 10, 19, 14, tzinfo=dt.UTC)) == [
        dt.date(2026, 10, 16),
        dt.date(2026, 10, 15),
    ]  # Monday: Friday and Thursday


def test_form4_sums_open_market_trades_only() -> None:
    data = parse_form4((FIXTURES / "form4_purchase.xml").read_bytes())
    assert data["bought"] == [6000, 5000 * 200 + 1000 * 210]  # the tax withholding (F) is left out
    assert data["role"] == "Chief Executive Officer" and data["owner"] == "Doe Jane"
    assert data["planned"] is False and data["dates"] == ["2026-10-14", "2026-10-15"]
    assert parse_form4((FIXTURES / "form4_planned_sale.xml").read_bytes())["planned"] is True


# --- collection -------------------------------------------------------------------------


def test_sec_insiders_keep_meaningful_trades_and_stakes(db: Session) -> None:
    fake = FakeRegisters()
    result = run(db, fake, ["sec-insiders"])["sec-insiders"]
    assert result.error is None and result.new == 4  # 2 news items + 2 routine markers

    items = tagged(db)
    assert set(items) == {"apple", "tesla"}  # planned sale and grant aren't news
    apple, analysis, _ = items["apple"]
    assert (
        apple.title
        == "Apple Inc.: Chief Executive Officer Doe Jane bought 6,000 shares for $1.2 million"
    )
    assert (analysis.event_type, analysis.basis, analysis.model) == (
        "insider_trade",
        "announced",
        "rules",
    )
    assert float(analysis.sentiment) == 0.6 and float(analysis.importance) == 0.85
    assert apple.tag_status == "tagged"
    tesla, stake, _ = items["tesla"]
    assert stake.event_type == "ownership_stake" and "Activist Capital LP" in tesla.title

    routine = db.scalars(select(Article).where(Article.tag_status == "irrelevant")).all()
    assert len(routine) == 2  # NVIDIA's pre-planned sale and Microsoft's grant
    # Unknown companies, prospectuses and 13G amendments are never opened.
    assert not any("9999991" in p or "0001555555" in p for p in fake.paths)

    again = FakeRegisters()
    assert run(db, again, ["sec-insiders"])["sec-insiders"].new == 0
    assert not any(p.endswith(("index.json", ".xml")) for p in again.paths)  # nothing re-read


def test_fi_register_keeps_real_purchases_by_known_companies(db: Session) -> None:
    result = run(db, FakeRegisters(), ["fi-insider"])["fi-insider"]
    assert result.error is None and result.new == 2
    items = tagged(db)
    assert set(items) == {"volvo", "skf"}
    volvo, analysis, _ = items["volvo"]
    assert volvo.title == "AB Volvo: VD Anna Andersson köpte aktier för 4,8 miljoner kr"
    assert analysis.summary.startswith("Anna Andersson (VD) bought 15,000 shares in AB Volvo")
    assert float(analysis.sentiment) == 0.5  # CEO buying, under 10 MSEK
    skf, _, _ = items["skf"]
    assert float(items["skf"][1].importance) == 0.85  # the chair ("Styrelseordförande") is senior
    assert "Fia Fors" in skf.title and "närstående" not in skf.title
    assert "closely associated" in items["skf"][1].summary


def test_rule_summaries_follow_the_briefing_language(db: Session) -> None:
    stored = db.get(Setting, "briefing")
    stored.value = {**stored.value, "language": "sv"}
    db.commit()
    run(db, FakeRegisters(), ["fi-insider", "sec-insiders"])
    items = tagged(db)
    assert items["volvo"][1].summary.startswith(
        "Anna Andersson (VD) köpte 15 000 aktier i AB Volvo"
    )
    assert "köpte 6 000 aktier till i snitt" in items["apple"][1].summary
