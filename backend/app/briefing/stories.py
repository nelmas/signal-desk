"""Group tagged articles into stories and rank them. Plain code, no AI.

A story is one company + one kind of event in the briefing window: nine outlets
reporting Apple's order cuts become one story with nine sources. Stories rank by
how important and trustworthy the best article is, how many outlets covered it,
the company's signal score, and whether you own or watch the company.
"""

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Article,
    ArticleAnalysis,
    ArticleCompany,
    Company,
    SignalScore,
    Source,
    TrackedStock,
)
from app.scoring.score import BASIS_WEIGHT

MAX_ARTICLES_PER_STORY = 6  # sent to the AI; the rest still count as coverage


@dataclass
class StoryArticle:
    id: int
    title: str
    url: str
    source: str
    published_at: dt.datetime
    basis: str
    importance: float
    sentiment: float
    summary: str

    @property
    def trust(self) -> float:
        return BASIS_WEIGHT.get(self.basis, 0.6)


@dataclass
class StoryCandidate:
    key: str  # "<company key>:<event type>", stable within a briefing
    company_id: int
    company_key: str
    company_name: str
    sector: str | None
    event_type: str
    articles: list[StoryArticle] = field(default_factory=list)
    other_companies: set[int] = field(default_factory=set)
    signal_score: float = 0.0
    is_holding: bool = False
    holding_note: str | None = None
    is_watched: bool = False

    @property
    def lead(self) -> StoryArticle:
        """The most trusted, most important article: its headline names the story."""
        return max(self.articles, key=lambda a: (a.trust, a.importance, a.published_at))

    @property
    def tone(self) -> float:
        total = sum(a.trust for a in self.articles)
        return sum(a.sentiment * a.trust for a in self.articles) / total if total else 0.0

    @property
    def rank_score(self) -> float:
        best = max(a.importance * a.trust for a in self.articles)
        outlets = len({a.source for a in self.articles})
        return (
            100 * best
            + 10 * math.log2(1 + outlets)
            + 0.3 * self.signal_score
            + (15 if self.is_holding else 5 if self.is_watched else 0)
        )

    def for_prompt(self) -> list[StoryArticle]:
        ranked = sorted(self.articles, key=lambda a: (a.trust, a.importance), reverse=True)
        return ranked[:MAX_ARTICLES_PER_STORY]


def build_stories(
    session: Session, topic_key: str, since: dt.datetime, until: dt.datetime, score_date: dt.date
) -> list[StoryCandidate]:
    """Stories from articles tagged in [since, until), best first."""
    scores = dict(
        session.execute(
            select(SignalScore.company_id, SignalScore.score).where(SignalScore.date == score_date)
        ).all()
    )
    watched = {t.company_id: t for t in session.scalars(select(TrackedStock))}
    sources = dict(session.execute(select(Source.id, Source.name)).all())

    rows = session.execute(
        select(
            Article,
            ArticleAnalysis,
            ArticleCompany.company_id,
            ArticleCompany.role,
            Company.key,
            Company.name,
            Company.sector,
        )
        .join(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
        .join(ArticleCompany, ArticleCompany.article_id == Article.id)
        .join(Company, Company.id == ArticleCompany.company_id)
        .where(
            Article.topic == topic_key,
            Article.tag_status == "tagged",
            Article.published_at >= since,
            Article.published_at < until,
        )
    ).all()

    # One main company per article: a subject, the highest-scoring if several.
    per_article: dict[int, list] = defaultdict(list)
    for row in rows:
        per_article[row.Article.id].append(row)

    stories: dict[str, StoryCandidate] = {}
    for tags in per_article.values():
        subjects = [t for t in tags if t.role == "subject"] or tags
        main = max(subjects, key=lambda t: float(scores.get(t.company_id, 0)))
        article, analysis = main.Article, main.ArticleAnalysis
        key = f"{main.key}:{analysis.event_type}"
        story = stories.get(key)
        if story is None:
            tracked = watched.get(main.company_id)
            story = stories[key] = StoryCandidate(
                key=key,
                company_id=main.company_id,
                company_key=main.key,
                company_name=main.name,
                sector=main.sector,
                event_type=analysis.event_type,
                signal_score=float(scores.get(main.company_id, 0)),
                is_holding=bool(tracked and tracked.is_holding),
                holding_note=tracked.note if tracked else None,
                is_watched=tracked is not None,
            )
        story.articles.append(
            StoryArticle(
                id=article.id,
                title=article.title,
                url=article.url,
                # Finnhub articles come from many outlets; show the real one.
                source=(article.raw or {}).get("outlet") or sources.get(article.source_id, "?"),
                published_at=article.published_at,
                basis=analysis.basis,
                importance=float(analysis.importance),
                sentiment=float(analysis.sentiment),
                summary=analysis.summary,
            )
        )
        story.other_companies.update(t.company_id for t in tags if t.company_id != main.company_id)

    return sorted(stories.values(), key=lambda s: s.rank_score, reverse=True)
