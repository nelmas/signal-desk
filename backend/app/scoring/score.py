"""The 0-100 signal score. Plain arithmetic, no AI.

Four factors, each scored 0-100, combined with the user's weights:

- news_volume: weighted articles in the last 24 hours against the company's normal day.
- event_importance: the most important thing that happened, by event type and the
  AI's importance rating.
- sentiment_shift: how far today's tone is from the company's usual tone.
- market_reaction: unusual price move and trading volume on the latest session.

Articles count by how much they can be trusted: an announcement more than a rumour,
a rumour more than an opinion piece; the main subject more than an affected company.
A factor without data (no prices yet) is left out and the weights are rescaled.
"""

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
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
    TrackedStock,
)
from app.topic import TopicConfig

BASIS_WEIGHT = {"announced": 1.0, "reported": 0.6, "commentary": 0.25}
ROLE_WEIGHT = {"subject": 1.0, "affected": 0.5}
WINDOW = dt.timedelta(hours=24)
BASELINE_DAYS = 30
VOLUME_FULL_SCORE_RATIO = 8  # 8x the normal news flow scores 100
MIN_PRICE_HISTORY = 10  # sessions needed before market reaction counts
MAX_PRICE_AGE_DAYS = 4  # covers a weekend plus a holiday


@dataclass
class Tag:
    published_at: dt.datetime
    weight: float  # basis x role
    sentiment: float
    importance: float  # 0-1, event type and AI rating combined


@dataclass
class Score:
    company_id: int
    score: float
    components: dict = field(default_factory=dict)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def news_volume(today: float, baseline_per_day: float) -> float:
    if today <= 0:
        return 0.0
    ratio = (today + 1) / (max(baseline_per_day, 0.5) + 1)
    return 100 * _clamp01(math.log2(ratio) / math.log2(VOLUME_FULL_SCORE_RATIO))


def market_reaction(closes: list[float], volumes: list[float | None]) -> dict | None:
    """Latest session's move and volume against the previous sessions. Oldest first."""
    if len(closes) < MIN_PRICE_HISTORY + 1:
        return None
    returns = [abs(b / a - 1) for a, b in zip(closes, closes[1:], strict=False) if a]
    move, typical_move = returns[-1], sum(returns[:-1]) / len(returns[:-1])
    move_part = _clamp01((move / typical_move - 1) / 3) if typical_move else 0.0
    known = [v for v in volumes[:-1] if v]
    volume_ratio = volumes[-1] / (sum(known) / len(known)) if known and volumes[-1] else None
    volume_part = _clamp01((volume_ratio - 1) / 3) if volume_ratio is not None else move_part
    return {
        "score": round(100 * (move_part + volume_part) / 2, 1),
        "return_pct": round(100 * (closes[-1] / closes[-2] - 1), 2),
        "typical_move_pct": round(100 * typical_move, 2),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
    }


def score_company(
    tags: list[Tag],
    now: dt.datetime,
    baseline_days: float,
    weights: dict[str, float],
    reaction: dict | None,
) -> tuple[float, dict]:
    window_start = now - WINDOW
    today = [t for t in tags if t.published_at >= window_start]
    before = [t for t in tags if t.published_at < window_start]

    today_weight = sum(t.weight for t in today)
    baseline = sum(t.weight for t in before) / baseline_days
    mood_now = sum(t.sentiment * t.weight for t in today) / today_weight if today else 0.0
    before_weight = sum(t.weight for t in before)
    mood_usual = sum(t.sentiment * t.weight for t in before) / before_weight if before else 0.0

    parts: dict[str, dict] = {
        "news_volume": {
            "score": round(news_volume(today_weight, baseline), 1),
            "articles_24h": len(today),
            "weighted_24h": round(today_weight, 2),
            "usual_per_day": round(baseline, 2),
        },
        "event_importance": {
            "score": round(100 * max((t.importance * t.weight for t in today), default=0), 1),
        },
        "sentiment_shift": {
            "score": round(100 * _clamp01(abs(mood_now - mood_usual)) if today else 0.0, 1),
            "tone_24h": round(mood_now, 3),
            "usual_tone": round(mood_usual, 3),
        },
    }
    if reaction is not None:
        parts["market_reaction"] = reaction

    used = {k: w for k, w in weights.items() if k in parts and w > 0}
    total_weight = sum(used.values())
    score = sum(parts[k]["score"] * w for k, w in used.items()) / total_weight if used else 0.0
    return round(score, 2), {
        "factors": parts,
        "weights_used": {k: round(w / total_weight, 4) for k, w in used.items()},
    }


def compute_scores(
    session: Session, topic: TopicConfig, *, now: dt.datetime | None = None
) -> list[SignalScore]:
    """Score companies with recent news and the watchlist for today (Stockholm date)."""
    now = now or dt.datetime.now(dt.UTC)
    since = now - WINDOW - dt.timedelta(days=BASELINE_DAYS)
    type_importance = {e.key: e.importance for e in topic.event_types}

    setting = session.get(Setting, "scoring_weights")
    weights = (setting.value if setting else None) or topic.scoring_weights.model_dump()

    tags: dict[int, list[Tag]] = defaultdict(list)
    rows = session.execute(
        select(
            ArticleCompany.company_id,
            ArticleCompany.role,
            ArticleCompany.sentiment,
            ArticleAnalysis.sentiment,
            ArticleAnalysis.importance,
            ArticleAnalysis.event_type,
            ArticleAnalysis.basis,
            Article.published_at,
        )
        .join(Article, Article.id == ArticleCompany.article_id)
        .join(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
        .where(Article.topic == topic.key, Article.published_at >= since)
    )
    for company_id, role, own_tone, article_tone, ai_imp, event, basis, published in rows:
        tone = own_tone if own_tone is not None else article_tone
        tags[company_id].append(
            Tag(
                published_at=published,
                weight=BASIS_WEIGHT.get(basis, 0.6) * ROLE_WEIGHT.get(role, 1.0),
                sentiment=float(tone),
                importance=0.5 * type_importance.get(event, 0.1) + 0.5 * float(ai_imp),
            )
        )

    # The baseline can't be longer than the history we have.
    first_seen = session.scalar(
        select(Article.published_at)
        .where(Article.topic == topic.key)
        .order_by(Article.published_at)
        .limit(1)
    )
    history = (now - WINDOW - first_seen).total_seconds() / 86400 if first_seen else 0
    baseline_days = max(1.0, min(float(BASELINE_DAYS), history))

    date = now.astimezone(ZoneInfo(topic.briefing.timezone)).date()
    # Thousands of universe companies have no news on a given day; scoring only those
    # with recent news, plus the watchlist, keeps the free database small.
    candidates = set(tags) | set(session.scalars(select(TrackedStock.company_id)))
    company_ids = list(
        session.scalars(
            select(Company.id).where(
                Company.topic == topic.key, Company.active, Company.id.in_(candidates)
            )
        )
    )
    reactions = _reactions(session, company_ids, now)
    rows = []
    for company_id in company_ids:
        score, components = score_company(
            tags.get(company_id, []), now, baseline_days, weights, reactions.get(company_id)
        )
        rows.append(
            {
                "company_id": company_id,
                "date": date,
                "score": Decimal(str(score)),
                "components": components,
                "weights": weights,
            }
        )
    # One statement for all rows: the job may run far from the database.
    if rows:
        stmt = insert(SignalScore).values(rows)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["company_id", "date"],
                set_={k: stmt.excluded[k] for k in ("score", "components", "weights")},
            )
        )
    session.commit()
    return [SignalScore(**row) for row in rows]


def _reactions(
    session: Session, company_ids: list[int], now: dt.datetime
) -> dict[int, dict | None]:
    """Market reaction per company from its primary listing's recent prices, in one query."""
    since = now.date() - dt.timedelta(days=(MIN_PRICE_HISTORY + 21) * 2)
    history: dict[int, list] = defaultdict(list)
    for row in session.execute(
        select(Listing.company_id, PriceDaily.date, PriceDaily.close, PriceDaily.volume)
        .join(Listing, Listing.id == PriceDaily.listing_id)
        .where(
            Listing.company_id.in_(company_ids), Listing.is_primary, PriceDaily.date >= since
        )
        .order_by(PriceDaily.date)
    ):
        history[row.company_id].append(row)
    out: dict[int, dict | None] = {}
    for company_id, prices in history.items():
        prices = prices[-(MIN_PRICE_HISTORY + 21) :]
        # A move from last week is not a reaction to today's news.
        if (now.date() - prices[-1].date).days > MAX_PRICE_AGE_DAYS:
            continue
        out[company_id] = market_reaction(
            [float(p.close) for p in prices],
            [float(p.volume) if p.volume else None for p in prices],
        )
    return out
