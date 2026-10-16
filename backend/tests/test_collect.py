import datetime as dt
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collect import collect, prune_untagged
from app.collect.dedup import canonical_url, content_hash
from app.collect.parsers import SUMMARY_MAX_CHARS, excerpt, parse_atom, parse_rss
from app.config import Settings
from app.models import Article, ArticleCompany, Company, Source
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
NOW = dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.UTC)

TOPIC = load_topic_from(STOCKS_DIR)
SETTINGS = Settings(sec_user_agent="Test Person test@example.com", finnhub_api_key="test-key")


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeFeeds:
    """Serves fixture files by host and records requests."""

    def __init__(self, fail_hosts: frozenset[str] = frozenset()) -> None:
        self.fail_hosts = fail_hosts
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.fail_hosts:
            return httpx.Response(503)
        files = {
            "mfn.se": "mfn.xml",
            "news.cision.com": "cision.xml",
            "www.sec.gov": "sec.xml",
            "finnhub.io": "finnhub_company_news.json",
        }
        if host not in files:  # sources these tests leave out (the insider registers)
            return httpx.Response(404)
        return httpx.Response(200, content=_fixture(files[host]))


@pytest.fixture
def synced(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def _run(session: Session, feeds: FakeFeeds, settings: Settings = SETTINGS, now=NOW):
    with httpx.Client(transport=httpx.MockTransport(feeds)) as client:
        return {r.key: r for r in collect(session, client, TOPIC, settings, now=now)}


# --- pure helpers -------------------------------------------------------------


def test_canonical_url_drops_tracking_and_fragment() -> None:
    assert canonical_url("HTTPS://Example.com/a/?utm_source=x&b=2&a=1#top") == (
        "https://example.com/a?a=1&b=2"
    )


def test_content_hash_tells_same_titled_reports_apart() -> None:
    title = "Interim report January-September 2026"
    assert content_hash(title, "Volvo: sales rose") != content_hash(title, "SKF: sales fell")
    assert content_hash("H&M sales up", "x") == content_hash("H and M  sales up", "x")


def test_excerpt_strips_html_and_truncates() -> None:
    assert excerpt("<p>Hi&nbsp;there</p><script>bad()</script><p>Bye</p>") == "Hi there. Bye"
    long = excerpt("word " * 500)
    assert long is not None and len(long) <= SUMMARY_MAX_CHARS + 2 and long.endswith("…")


def test_parse_rss_reads_mfn_extensions() -> None:
    items = parse_rss(_fixture("mfn.xml"), now=NOW)
    first = items[0]
    assert first.title == "Volvo receives order for 1,000 electric trucks"
    assert first.language == "en"
    assert first.summary == "Largest single order. Gothenburg – AB Volvo has received an order"
    assert first.raw["tags"] == [":regulatory", "sub:ci:order"]
    assert first.published_at == dt.datetime(2026, 10, 2, 7, 30, tzinfo=dt.UTC)
    assert items[1].title == "Volvo får order på 1 000 eldrivna lastbilar"


def test_parse_atom_reads_sec_filings() -> None:
    items = parse_atom(_fixture("sec.xml"), now=NOW)
    assert items[0].title == "8-K - Apple Inc. (0000320193) (Filer)"
    assert "Item 2.02: Results of Operations" in (items[0].summary or "")
    assert items[0].published_at == dt.datetime(2026, 10, 2, 20, 30, tzinfo=dt.UTC)
    assert items[0].raw["categories"] == ["8-K"]


# --- collection against the database --------------------------------------------


def test_collect_stores_new_articles_and_skips_duplicates(synced: Session) -> None:
    feeds = FakeFeeds()
    results = _run(synced, feeds)

    assert results["mfn"].new == 2 and results["mfn"].too_old == 1
    assert results["mfn"].other_language == 1  # Norwegian; topic keeps en + sv
    assert results["cision-se"].new == 1
    assert results["sec-8k"].new == 1 and results["sec-8k"].duplicates == 1  # listed twice
    # Every US stock returned the same article; it's stored once.
    us_stocks = 16
    assert results["finnhub-news"].fetched == us_stocks
    assert results["finnhub-news"].new == 1

    article = synced.scalars(select(Article).where(Article.language == "sv")).first()
    assert article is not None and article.is_press_release
    assert synced.scalar(select(func.count()).select_from(Article)) == 5

    again = _run(synced, feeds)
    assert sum(r.new for r in again.values()) == 0
    assert synced.scalar(select(func.count()).select_from(Article)) == 5


def test_finnhub_queries_us_primary_listings_with_key_in_header(synced: Session) -> None:
    feeds = FakeFeeds()
    _run(synced, feeds)
    finnhub = [r for r in feeds.requests if r.url.host == "finnhub.io"]
    symbols = {r.url.params["symbol"] for r in finnhub}
    assert {"AAPL", "GOOGL", "JPM"} <= symbols and "GOOG" not in symbols
    assert all(r.headers["X-Finnhub-Token"] == "test-key" for r in finnhub)
    assert all("token" not in r.url.params for r in finnhub)
    sec = next(r for r in feeds.requests if r.url.host == "www.sec.gov")
    assert sec.headers["User-Agent"] == "Test Person test@example.com"


def test_sources_without_free_keys_are_skipped_not_failed(synced: Session) -> None:
    results = _run(synced, FakeFeeds(), Settings(sec_user_agent=None, finnhub_api_key=None))
    assert "SEC_USER_AGENT" in (results["sec-8k"].skipped or "")
    assert "FINNHUB_API_KEY" in (results["finnhub-news"].skipped or "")
    assert results["mfn"].new == 2


def test_one_failing_source_does_not_stop_the_rest(synced: Session) -> None:
    results = _run(synced, FakeFeeds(fail_hosts=frozenset({"mfn.se"})))
    assert "503" in (results["mfn"].error or "")
    assert results["cision-se"].new == 1
    mfn = synced.scalars(select(Source).where(Source.key == "mfn")).one()
    assert mfn.last_error and mfn.last_fetched_at is None

    _run(synced, FakeFeeds())
    synced.refresh(mfn)
    assert mfn.last_error is None and mfn.last_fetched_at == NOW


def test_prune_keeps_tagged_and_recent_articles(synced: Session) -> None:
    _run(synced, FakeFeeds())
    articles = synced.scalars(select(Article).order_by(Article.id)).all()
    volvo = synced.scalars(select(Company).where(Company.key == "volvo")).one()
    tag = ArticleCompany(article_id=articles[0].id, company_id=volvo.id, matched_alias="Volvo")
    synced.add(tag)
    synced.commit()

    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=15)
    assert prune_untagged(synced, older_than_days=30, now=later) == 0
    assert prune_untagged(synced, older_than_days=14, now=later) == len(articles) - 1
    assert synced.scalar(select(func.count()).select_from(Article)) == 1


def test_sources_and_markets_turned_off_in_settings_are_skipped(synced: Session) -> None:
    from app.models import Setting

    synced.add(Setting(key="sources", value={"mfn": False}))
    synced.add(Setting(key="markets", value={"US": False}))
    synced.commit()
    feeds = FakeFeeds()
    results = _run(synced, feeds)
    assert results["mfn"].skipped == "turned off in Settings"
    assert results["sec-8k"].skipped == "market US turned off in Settings"
    assert results["finnhub-news"].skipped == "market US turned off in Settings"
    assert results["cision-se"].new == 1
    # Nothing from the source or market turned off is fetched; other Swedish sources run.
    hosts = {r.url.host for r in feeds.requests}
    assert hosts.isdisjoint({"mfn.se", "www.sec.gov", "finnhub.io"})
    assert "news.cision.com" in hosts
