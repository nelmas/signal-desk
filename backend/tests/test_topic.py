import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.names import normalize_name
from app.topic import SourceConfig, load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("H&M", "h & m"),
        ("H&M", "H and M"),
        ("Industrivärden", "industrivarden"),
        ("Amazon.com Inc.", "amazon com inc"),
        ("  Volvo   Group ", "volvo group"),
    ],
)
def test_normalize_name_matches_variants(a: str, b: str) -> None:
    assert normalize_name(a) == normalize_name(b)


def test_stocks_topic_is_valid() -> None:
    topic = load_topic_from(STOCKS_DIR)
    companies = load_companies(topic, STOCKS_DIR)
    assert {m.key for m in topic.markets} == {"SE", "US"}
    assert len(companies) > 40
    volvo = next(c for c in companies if c.key == "volvo")
    assert volvo.listings[0].symbol == "VOLV B" and volvo.listings[0].is_primary
    assert not volvo.listings[1].is_primary
    assert "AB Volvo" in volvo.aliases  # official name is always an alias


def test_enabled_source_requires_url_and_terms() -> None:
    with pytest.raises(ValidationError, match="lacks url or terms_basis"):
        SourceConfig(key="x", name="X", kind="rss", language="en", enabled=True, url="https://x")


def _copy_topic(tmp_path: Path, extra_csv_row: str) -> Path:
    dst = tmp_path / "stocks"
    shutil.copytree(STOCKS_DIR, dst)
    with (dst / "companies.csv").open("a", encoding="utf-8") as f:
        f.write(extra_csv_row + "\n")
    return dst


def test_alias_shared_by_two_companies_is_rejected(tmp_path: Path) -> None:
    path = _copy_topic(tmp_path, "volvo-cars,Volvo Car AB,SE,Consumer Discretionary,Volvo,"
                                 "VOLCAR B@XSTO,SEK")
    with pytest.raises(ValueError, match="alias 'Volvo' used by both"):
        load_companies(load_topic_from(path), path)


def test_listing_on_unknown_exchange_is_rejected(tmp_path: Path) -> None:
    path = _copy_topic(tmp_path, "sap,SAP SE,DE,Information Technology,SAP,SAP@XETR,EUR")
    with pytest.raises(ValueError, match="XETR is not in any topic market"):
        load_companies(load_topic_from(path), path)
