import typer

from app.config import get_settings
from app.topic import get_topic, load_companies, topic_dir

app = typer.Typer(no_args_is_help=True, help="Signal Desk command line.")


@app.command()
def check_topic() -> None:
    """Validate the topic config and companies file (no database needed)."""
    topic = get_topic()
    companies = load_companies(topic, topic_dir())
    enabled = sum(s.enabled for s in topic.sources)
    typer.echo(
        f"Topic {topic.key!r} OK: {len(topic.markets)} markets, "
        f"{len(topic.sources)} sources ({enabled} enabled), "
        f"{len(topic.event_types)} event types, {len(companies)} companies"
    )


@app.command()
def sync_topic() -> None:
    """Write sources, companies and default settings from the topic config to the database."""
    from app.db import get_sessionmaker
    from app.sync import sync_topic as run_sync

    topic = get_topic()
    companies = load_companies(topic, topic_dir())
    with get_sessionmaker()() as session:
        report = run_sync(session, topic, companies)
    typer.echo(f"Synced topic {topic.key!r}: {report}")


@app.command()
def serve(reload: bool = True) -> None:
    """Run the API server on http://localhost:8000."""
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=reload)


@app.command()
def show_config() -> None:
    """Print effective settings (secrets masked)."""
    s = get_settings()
    db = s.database_url.split("@")[-1]
    typer.echo(f"database: ...@{db}")
    typer.echo(f"topic: {s.topic} ({s.topics_dir})")
    typer.echo(f"llm: {s.llm_provider} / {s.llm_model}")
    typer.echo(f"gemini key: {'set' if s.gemini_api_key else 'missing'}")


if __name__ == "__main__":
    app()
