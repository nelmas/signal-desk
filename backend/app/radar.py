"""The Radar: rule-based early signals, each tracked in Facit like any idea. No AI.

Nothing free is faster than the market at reading news, so the Radar doesn't try to be.
It looks for two things markets have been found to under-react to, which can show up
before most of a move:

- quiet_good_news: strong, clearly positive news, and the share price has barely moved
  yet: the score's "not priced in yet" label, and the last session's move no bigger than
  a normal day's. Backed by at least one real news item.
- insider_buying: people inside the company buying shares with their own money: two or
  more different insiders within 30 days, or one top executive buying a large amount.

Each hit is logged as an idea (origin "radar") and enters at the next market open, so
Facit shows over time whether either signal actually beats the index. The same stock and
signal is not logged again within 20 days, and daily caps keep the free price budgets
(Swedish prices especially) intact.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collect.insiders_se import SENIOR as SENIOR_SE
from app.collect.insiders_us import SENIOR as SENIOR_US
from app.models import (
    Article,
    ArticleAnalysis,
    ArticleCompany,
    Company,
    Idea,
    Listing,
    SignalScore,
    Source,
)
from app.topic import TopicConfig
from app.user_settings import market_enabled

QUIET_GOOD_NEWS = "quiet_good_news"
INSIDER_BUYING = "insider_buying"
SIGNALS = (QUIET_GOOD_NEWS, INSIDER_BUYING)

MIN_TONE = 0.1  # the day's tone must be clearly positive
NEWS_WINDOW = dt.timedelta(hours=24)
EVIDENCE_ARTICLES = 3
INSIDER_SOURCES = ("sec-insiders", "fi-insider")
INSIDER_WINDOW = dt.timedelta(days=30)
INSIDER_FRESH = dt.timedelta(days=3)  # the latest purchase must be news, not history
MIN_INSIDERS = 2
BIG_PURCHASE = {"USD": 250_000, "SEK": 2_500_000}  # one senior insider alone counts above this
COOLDOWN = dt.timedelta(days=20)
# New hits per signal, market and day. Every hit is followed for 20 trading days, and
# Swedish prices allow 20 requests a day in all.
DAILY_CAP = {"US": 5, "SE": 1}
STOCKHOLM = ZoneInfo("Europe/Stockholm")


@dataclass
class Hit:
    company_id: int
    signal: str
    strength: float  # for ranking within a day's cap
    thesis: str
    details: dict


@dataclass
class RadarReport:
    candidates: int = 0
    logged: list[tuple[str, str]] = field(default_factory=list)  # (signal, company name)
    cooldown: int = 0
    capped: int = 0


def quiet_good_news(session: Session, now: dt.datetime) -> list[Hit]:
    """Today's companies with strong positive news the share price hasn't reacted to."""
    today = session.scalar(select(func.max(SignalScore.date)))
    if today is None:
        return []
    tone = SignalScore.components["factors"]["sentiment_shift"]["tone_24h"].as_float()
    rows = session.execute(
        select(SignalScore.company_id, SignalScore.score, SignalScore.components).where(
            SignalScore.date == today,
            SignalScore.components["market"]["label"].as_string() == "not_priced_in_yet",
            tone > MIN_TONE,
        )
    ).all()
    hits = []
    for company_id, score, components in rows:
        market = components.get("market", {})
        move, typical = market.get("return_pct"), market.get("typical_move_pct")
        if move is None or typical is None or abs(move) > typical:
            continue  # it did move; quiet volume alone doesn't make it "not priced in"
        # Real news, not only insider trades (those are the other signal's job).
        evidence = list(session.scalars(
            select(Article.id)
            .join(ArticleCompany, ArticleCompany.article_id == Article.id)
            .join(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
            .where(
                ArticleCompany.company_id == company_id,
                Article.published_at >= now - NEWS_WINDOW,
                ArticleAnalysis.event_type != "insider_trade",
                func.coalesce(ArticleCompany.sentiment, ArticleAnalysis.sentiment) > 0,
            )
            .order_by(ArticleAnalysis.importance.desc(), Article.published_at.desc())
            .limit(EVIDENCE_ARTICLES)
        ))
        if not evidence:
            continue
        day_tone = components["factors"]["sentiment_shift"]["tone_24h"]
        details = {
            "score": round(float(score), 1),
            "tone": round(float(day_tone), 2),
            "move_pct": move,
            "typical_move_pct": typical,
            "article_ids": evidence,
        }
        hits.append(Hit(
            company_id=company_id,
            signal=QUIET_GOOD_NEWS,
            strength=float(score) * (1 + float(day_tone)),
            thesis=(
                f"Strong positive news (score {float(score):.0f}, tone {float(day_tone):+.2f}) "
                f"and the share price has barely moved yet ({move:+.1f}% on the last "
                f"trading day; a normal day moves about {typical:.1f}%)."
            ),
            details=details,
        ))
    return hits


def insider_buying(session: Session, now: dt.datetime) -> list[Hit]:
    """Companies where insiders are buying: several of them, or one top executive, big."""
    rows = session.execute(
        select(ArticleCompany.company_id, Article.id, Article.published_at, Article.raw)
        .join(ArticleCompany, ArticleCompany.article_id == Article.id)
        .join(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
        .join(Source, Source.id == Article.source_id)
        .where(
            Source.key.in_(INSIDER_SOURCES),
            ArticleAnalysis.event_type == "insider_trade",
            ArticleAnalysis.sentiment > 0,  # purchases; sales are stored with negative tone
            Article.published_at >= now - INSIDER_WINDOW,
        )
        .order_by(Article.published_at)
    ).all()
    by_company: dict[int, list] = defaultdict(list)
    for row in rows:
        by_company[row.company_id].append(row)

    hits = []
    for company_id, buys in by_company.items():
        if buys[-1].published_at < now - INSIDER_FRESH:
            continue
        buyers: dict[str, dict] = {}
        for b in buys:
            raw = b.raw or {}
            us = "value_usd" in raw
            name = raw.get("owner") if us else raw.get("person")
            if not name:
                continue
            role = raw.get("role") or ""
            entry = buyers.setdefault(name, {
                "name": name, "role": role, "value": 0, "currency": "USD" if us else "SEK",
                "senior": bool((SENIOR_US if us else SENIOR_SE).search(role)),
                "article_ids": [],
            })
            entry["value"] += raw.get("value_usd" if us else "value_sek") or 0
            entry["article_ids"].append(b.id)
            entry["last"] = b.published_at.date().isoformat()
        big = [p for p in buyers.values()
               if p["senior"] and p["value"] >= BIG_PURCHASE[p["currency"]]]
        if len(buyers) < MIN_INSIDERS and not big:
            continue
        currency = next(iter(buyers.values()))["currency"]
        total = sum(p["value"] for p in buyers.values())
        hits.append(Hit(
            company_id=company_id,
            signal=INSIDER_BUYING,
            # More buyers first, then more money (SEK roughly in USD terms).
            strength=len(buyers) * 10 + total / (10 if currency == "SEK" else 1) / 1e6,
            thesis=(
                f"{len(buyers)} insider{'s' if len(buyers) > 1 else ''} bought shares for "
                f"{total:,.0f} {currency} in total in the last 30 days."
            ),
            details={
                "buyers": sorted(buyers.values(), key=lambda p: -p["value"]),
                "total": total,
                "currency": currency,
                "article_ids": [i for p in buyers.values() for i in p["article_ids"]],
            },
        ))
    return hits


def run_radar(
    session: Session, topic: TopicConfig, *, now: dt.datetime | None = None
) -> RadarReport:
    """Log today's new Radar hits as ideas for Facit."""
    now = now or dt.datetime.now(dt.UTC)
    report = RadarReport()
    hits = quiet_good_news(session, now) + insider_buying(session, now)
    report.candidates = len(hits)
    if not hits:
        return report

    listings = {
        lst.company_id: lst for lst in session.scalars(
            select(Listing).where(
                Listing.company_id.in_({h.company_id for h in hits}), Listing.is_primary
            )
        )
    }
    names = dict(session.execute(
        select(Company.id, Company.name).where(Company.id.in_({h.company_id for h in hits}))
    ).all())
    benchmark = {m.key: m.benchmark for m in topic.markets}
    recent = set(session.execute(
        select(Idea.company_id, Idea.signal).where(
            Idea.origin == "radar", Idea.published_at >= now - COOLDOWN
        )
    ).all())
    day_start = dt.datetime.combine(
        now.astimezone(STOCKHOLM).date(), dt.time(0), tzinfo=STOCKHOLM
    )
    logged_today: dict[tuple[str, str], int] = defaultdict(int)
    for signal, mic in session.execute(
        select(Idea.signal, Listing.mic)
        .join(Listing, Listing.id == Idea.listing_id)
        .where(Idea.origin == "radar", Idea.published_at >= day_start)
    ):
        logged_today[(signal, topic.market_for_mic(mic) or "")] += 1

    for hit in sorted(hits, key=lambda h: -h.strength):
        listing = listings.get(hit.company_id)
        market = topic.market_for_mic(listing.mic) if listing else None
        if listing is None or market is None or not market_enabled(session, market):
            continue
        if (hit.company_id, hit.signal) in recent:
            report.cooldown += 1
            continue
        if logged_today[(hit.signal, market)] >= DAILY_CAP.get(market, 1):
            report.capped += 1
            continue
        session.add(Idea(
            origin="radar",
            signal=hit.signal,
            details=hit.details,
            company_id=hit.company_id,
            listing_id=listing.id,
            thesis=hit.thesis,
            benchmark=benchmark.get(market, ""),
            published_at=now,
        ))
        recent.add((hit.company_id, hit.signal))
        logged_today[(hit.signal, market)] += 1
        report.logged.append((hit.signal, names.get(hit.company_id, "?")))
    session.commit()
    return report
