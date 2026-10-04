from typing import Annotated

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
def collect(
    source: Annotated[list[str] | None, typer.Option(help="Only these source keys.")] = None,
) -> None:
    """Fetch all enabled news sources and store new articles (run hourly)."""
    from app.collect import collect as run_collect
    from app.collect.fetchers import make_client
    from app.db import get_sessionmaker

    with get_sessionmaker()() as session, make_client() as client:
        results = run_collect(session, client, get_topic(), get_settings(), source_keys=source)
    for r in results:
        if r.skipped:
            status = f"skipped: {r.skipped}"
        elif r.error:
            status = f"ERROR {r.error}"
        else:
            status = (
                f"{r.new} new, {r.duplicates} duplicates, {r.too_old} too old, "
                f"{r.other_language} other language"
            )
        typer.echo(f"{r.key:<16} fetched {r.fetched:>4}  {status}")
    # Fail the scheduled job only if nothing worked, so one flaky feed doesn't page you.
    attempted = [r for r in results if not r.skipped]
    if attempted and all(r.error for r in attempted):
        raise typer.Exit(1)


@app.command()
def prune(days: int | None = None) -> None:
    """Delete old articles that no tracked company was tagged in."""
    from app.collect import prune_untagged
    from app.db import get_sessionmaker

    days = days if days is not None else get_settings().untagged_retention_days
    with get_sessionmaker()() as session:
        removed = prune_untagged(session, older_than_days=days)
    typer.echo(f"Deleted {removed} untagged articles older than {days} days")


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
    typer.echo(f"finnhub key: {'set' if s.finnhub_api_key else 'missing'}")
    typer.echo(f"sec user agent: {s.sec_user_agent or 'missing'}")


if __name__ == "__main__":
    app()
