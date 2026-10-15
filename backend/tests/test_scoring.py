import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Article,
    ArticleAnalysis,
    ArticleCompany,
    Company,
    Listing,
    PriceDaily,
    Setting,
    SignalScore,
    Source,
)
from app.scoring import compute_scores
from app.scoring.score import Tag, market_reaction, news_volume, score_company
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
NOW = dt.datetime(2026, 10, 9, 10, 0, tzinfo=dt.UTC)
WEIGHTS = TOPIC.scoring_weights.model_dump()


def tag(hours_ago: float, weight: float = 1.0, sentiment: float = 0.0, importance: float = 0.5):
    return Tag(NOW - dt.timedelta(hours=hours_ago), weight, sentiment, importance)


# --- factor math ------------------------------------------------------------------


def test_news_volume_scales_with_ratio_to_normal() -> None:
    assert news_volume(0, 3) == 0
    assert news_volume(3, 3) == 0  # a normal day
    assert 0 < news_volume(6, 3) < news_volume(12, 3) < 100
    assert news_volume(100, 1) == 100


def test_quiet_company_scores_zero() -> None:
    score, parts = score_company([tag(48), tag(72)], NOW, 30, WEIGHTS, None)
    assert score == 0
    assert parts["factors"]["news_volume"]["articles_24h"] == 0


def test_burst_of_negative_news_scores_high() -> None:
    usual = [tag(24 * d + 30, sentiment=0.2) for d in range(1, 29)]  # ~1 a day, mildly positive
    burst = [tag(h, sentiment=-0.7, importance=0.9) for h in range(1, 9)]
    score, parts = score_company(usual + burst, NOW, 30, WEIGHTS, None)
    f = parts["factors"]
    assert f["news_volume"]["score"] > 60
    assert f["event_importance"]["score"] == 90
    assert f["sentiment_shift"]["score"] == 90  # from +0.2 to -0.7
    assert parts["market"] == {"label": "no_price_data"}
    # Without prices the other three weights are rescaled to sum to 1.
    assert sum(parts["weights_used"].values()) == pytest.approx(1)
    assert score > 70


def test_rumours_and_opinion_count_less_than_announcements() -> None:
    announced = score_company([tag(2, weight=1.0, importance=0.8)], NOW, 30, WEIGHTS, None)[0]
    commentary = score_company([tag(2, weight=0.25, importance=0.8)], NOW, 30, WEIGHTS, None)[0]
    assert commentary < announced


def test_market_reaction_needs_history_and_compares_to_usual() -> None:
    assert market_reaction([100.0] * 5, [1000.0] * 5) is None
    closes = [100 + (i % 2) * 0.5 for i in range(20)] + [106.0]  # calm, then +6%
    volumes = [1000.0] * 20 + [3000.0]
    r = market_reaction(closes, volumes)
    assert r["return_pct"] > 5 and r["volume_ratio"] == 3.0
    assert r["score"] > 60


# --- against the database ----------------------------------------------------------


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def add_tagged(session: Session, company_key: str, hours_ago: float, **kw) -> None:
    source = session.scalars(select(Source).where(Source.key == "mfn")).one()
    company = session.scalars(select(Company).where(Company.key == company_key)).one()
    n = len(session.scalars(select(Article.id)).all())
    article = Article(
        topic="stocks", source_id=source.id, url=f"https://x/{n}", url_hash=f"{n:064d}",
        content_hash=f"{n:064d}", title="t", published_at=NOW - dt.timedelta(hours=hours_ago),
        tag_status="tagged",
    )
    session.add(article)
    session.flush()
    session.add(ArticleAnalysis(
        article_id=article.id, event_type=kw.get("event", "contract"),
        basis=kw.get("basis", "announced"), sentiment=Decimal("0.5"),
        importance=Decimal(str(kw.get("importance", 0.6))), summary="s", model="m",
        prompt_version="tag-v3",
    ))
    session.add(ArticleCompany(
        article_id=article.id, company_id=company.id, matched_alias="x",
        role=kw.get("role", "subject"), sentiment=Decimal(str(kw.get("sentiment", 0.5))),
    ))
    session.commit()


def test_compute_scores_ranks_the_busy_company_first_and_upserts(db: Session) -> None:
    add_tagged(db, "volvo", 24 * 20)  # history so the baseline isn't empty
    for h in range(1, 6):
        add_tagged(db, "volvo", h, importance=0.9)
    add_tagged(db, "skf", 3, basis="commentary")

    scores = {s.company_id: s for s in compute_scores(db, TOPIC, now=NOW)}
    keys = dict(db.execute(select(Company.id, Company.key)).all())
    by_key = {keys[c]: float(s.score) for c, s in scores.items()}
    assert by_key["volvo"] > by_key["skf"] > 0
    assert "apple" not in by_key  # no news, not watched: no row at all
    assert len(scores) == 2

    compute_scores(db, TOPIC, now=NOW)  # same day again: update, not duplicate
    assert len(db.scalars(select(SignalScore)).all()) == 2
    row = db.scalars(
        select(SignalScore).join(Company).where(Company.key == "volvo")
    ).one()
    assert row.date == dt.date(2026, 10, 9)
    assert row.components["factors"]["news_volume"]["articles_24h"] == 5


def add_prices(session: Session, symbol: str, last_close: str, last_volume: int) -> Listing:
    """21 calm sessions up to the day before NOW, the last one as given."""
    listing = session.scalars(select(Listing).where(Listing.symbol == symbol)).one()
    for i in range(21):
        session.add(PriceDaily(
            listing_id=listing.id, date=dt.date(2026, 9, 18) + dt.timedelta(days=i),
            close=Decimal(last_close) if i == 20 else Decimal(100 + (i % 2) * 0.5),
            volume=last_volume if i == 20 else 1000, source="test",
        ))
    session.commit()
    return listing


def scored(session: Session, listing: Listing):
    return next(s for s in compute_scores(session, TOPIC, now=NOW)
                if s.company_id == listing.company_id)


def test_user_weights_apply_and_prices_do_not_change_the_score(db: Session) -> None:
    add_tagged(db, "volvo", 2)
    add_tagged(db, "skf", 2)
    volvo = add_prices(db, "VOLV B", "106", 3000)  # big move; SKF has no prices
    skf = db.scalars(select(Listing).where(Listing.symbol == "SKF B")).one()
    assert float(scored(db, volvo).score) == float(scored(db, skf).score)

    db.get(Setting, "scoring_weights").value = {
        "news_volume": 0, "event_importance": 1, "sentiment_shift": 0, "market_reaction": 5,
    }
    db.commit()
    row = scored(db, volvo)
    assert row.components["weights_used"] == {"event_importance": 1.0}
    assert float(row.score) == row.components["factors"]["event_importance"]["score"]


def test_market_label_moving_with_news(db: Session) -> None:
    add_tagged(db, "volvo", 2, sentiment=0.6)
    market = scored(db, add_prices(db, "VOLV B", "106", 3000)).components["market"]
    assert market["label"] == "moving_with_news" and market["return_pct"] > 5


def test_market_label_not_priced_in_yet(db: Session) -> None:
    for h in range(1, 7):
        add_tagged(db, "volvo", h, importance=0.9, sentiment=0.7)
    market = scored(db, add_prices(db, "VOLV B", "100.2", 1000)).components["market"]
    assert market["label"] == "not_priced_in_yet"
