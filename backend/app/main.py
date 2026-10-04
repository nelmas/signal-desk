from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Company, Source
from app.topic import get_topic

app = FastAPI(title="Signal Desk")

SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/api/health")
def health(session: SessionDep) -> dict:
    session.execute(text("select 1"))
    return {"status": "ok"}


@app.get("/api/topic")
def topic_summary(session: SessionDep) -> dict:
    topic = get_topic()
    return {
        "key": topic.key,
        "name": topic.name,
        "markets": [m.key for m in topic.markets],
        "companies": session.scalar(
            select(func.count()).select_from(Company).where(Company.topic == topic.key)
        ),
        "sources_enabled": session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.topic == topic.key, Source.enabled)
        ),
    }
