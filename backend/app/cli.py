import datetime as dt
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
def sync_universe() -> None:
    """Refresh the list of every listed company (SEC for the US, Finnhub for Sweden)."""
    from app.collect.fetchers import make_client
    from app.db import get_sessionmaker
    from app.universe import refresh_universe

    with get_sessionmaker()() as session, make_client() as client:
        r = refresh_universe(session, client, get_topic(), get_settings())
    typer.echo(
        f"Fetched {r.fetched}. Created {r.created}, updated {r.updated}, "
        f"{r.listings_added} new listings, {r.aliases_added} aliases "
        f"({r.aliases_skipped} skipped as ambiguous), {r.deactivated} delisted."
    )
    for market, error in r.errors.items():
        typer.echo(f"ERROR {market}: {error}")
    if r.errors and not r.fetched:
        raise typer.Exit(1)


@app.command()
def watch(
    stocks: Annotated[
        list[str] | None, typer.Argument(help="Symbols, e.g. \"VOLV B\" AAPL")
    ] = None,
    holding: Annotated[bool, typer.Option(help="Mark as stocks you own.")] = False,
    remove: Annotated[bool, typer.Option(help="Remove from the watchlist.")] = False,
) -> None:
    """Show or change your watchlist. Without arguments, lists it."""
    from sqlalchemy import func, select

    from app.db import get_sessionmaker
    from app.models import Company, Listing, TrackedStock

    with get_sessionmaker()() as session:
        for text in stocks or []:
            company = session.scalars(
                select(Company)
                .join(Listing)
                .where(func.upper(Listing.symbol) == text.upper(), Company.active)
                .order_by(Listing.is_primary.desc())
            ).first() or session.scalars(select(Company).where(Company.key == text.lower())).first()
            if company is None:
                typer.echo(f"Not found: {text!r}. Use the symbol, e.g. \"VOLV B\" or AAPL.")
                continue
            row = session.get(TrackedStock, company.id)
            if remove:
                if row:
                    session.delete(row)
                typer.echo(f"Removed {company.name}")
            else:
                row = row or TrackedStock(company_id=company.id)
                row.is_holding = holding or row.is_holding
                session.add(row)
                typer.echo(f"Watching {company.name}{' (holding)' if row.is_holding else ''}")
        session.commit()
        rows = session.execute(
            select(Company.name, TrackedStock.is_holding, TrackedStock.note)
            .join(TrackedStock, TrackedStock.company_id == Company.id)
            .order_by(Company.name)
        ).all()
    typer.echo(f"\nWatchlist ({len(rows)}):")
    for name, is_holding, note in rows:
        typer.echo(f"  {name:<30}{'holding' if is_holding else '':<9}{note or ''}")


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
def tag() -> None:
    """Tag new articles: tracked companies, event type, tone and a one-line summary."""
    from app.ai import LLMClient
    from app.collect.fetchers import make_client
    from app.db import get_sessionmaker
    from app.models import Setting
    from app.tagging import tag_pending

    settings = get_settings()
    topic = get_topic()
    with get_sessionmaker()() as session, make_client() as client:
        briefing = session.get(Setting, "briefing")
        language = (briefing.value if briefing else {}).get("language", topic.briefing.language)
        key = settings.gemini_api_key
        llm = LLMClient(client, session, key) if key else None
        r = tag_pending(session, llm, topic, settings, language=language)
    typer.echo(
        f"checked {r.checked}: {r.no_match} name no tracked company, {r.tagged} tagged, "
        f"{r.irrelevant} only passing mentions, {r.failed} failed; {r.requests} AI requests"
    )
    if r.stopped:
        typer.echo(f"stopped early: {r.stopped}")


@app.command()
def score(top: int = 10) -> None:
    """Compute today's 0-100 signal score for every tracked company."""
    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.models import Company
    from app.scoring import compute_scores

    with get_sessionmaker()() as session:
        scores = compute_scores(session, get_topic())
        names = dict(session.execute(select(Company.id, Company.name)).all())
    typer.echo(f"Scored {len(scores)} companies. Top {top}:")
    for s in sorted(scores, key=lambda s: s.score, reverse=True)[:top]:
        factors = s.components["factors"]
        detail = ", ".join(f"{k} {v['score']:.0f}" for k, v in factors.items())
        market = s.components["market"]["label"].replace("_", " ")
        typer.echo(f"{float(s.score):6.1f}  {names[s.company_id]:<28} {detail}  [{market}]")


@app.command()
def radar() -> None:
    """Log today's Radar hits (early signals) as ideas for Facit."""
    from app.db import get_sessionmaker
    from app.radar import run_radar

    with get_sessionmaker()() as session:
        r = run_radar(session, get_topic())
    typer.echo(
        f"{r.candidates} candidates: {len(r.logged)} logged, {r.cooldown} logged recently, "
        f"{r.capped} over today's cap"
    )
    for signal, name in r.logged:
        typer.echo(f"  {signal.replace('_', ' ')}: {name}")


@app.command()
def prices() -> None:
    """Fetch daily prices: US from Twelve Data, Swedish from EODHD."""
    from app.collect.fetchers import make_client
    from app.db import get_sessionmaker
    from app.prices import update_prices
    from app.prices_se import update_swedish_prices

    with get_sessionmaker()() as session, make_client() as client:
        for market, update in (("US", update_prices), ("SE", update_swedish_prices)):
            r = update(session, client, get_topic(), get_settings())
            typer.echo(
                f"{market}: {r.listings} listings: {r.up_to_date} up to date, {r.fetched} fetched "
                f"({r.rows} price rows), {r.requests} requests"
            )
            for symbol, error in r.failed.items():
                typer.echo(f"  failed {symbol}: {error}")
            if r.stopped:
                typer.echo(f"  stopped: {r.stopped}")


@app.command()
def briefing(
    if_due: Annotated[bool, typer.Option(help="Only if past send time and none today.")] = False,
    force: Annotated[bool, typer.Option(help="Replace today's briefing.")] = False,
) -> None:
    """Write today's morning briefing (one AI call) and print it."""
    from app.ai import LLMClient, LLMError
    from app.briefing import generate_briefing, is_due, render_text
    from app.collect.fetchers import make_client
    from app.db import get_sessionmaker

    settings, topic = get_settings(), get_topic()
    with get_sessionmaker()() as session, make_client() as client:
        if if_due and not force and not is_due(session, topic, dt.datetime.now(dt.UTC)):
            typer.echo("Briefing not due yet (before send time, or already written today).")
            return
        if not settings.gemini_api_key:
            typer.echo("No GEMINI_API_KEY; cannot write the briefing.")
            raise typer.Exit(1)
        try:
            result = generate_briefing(
                session, LLMClient(client, session, settings.gemini_api_key), topic, settings,
                force=force,
            )
        except LLMError as e:
            # Nothing is saved, so the next hourly run tries again.
            typer.echo(f"Briefing not written: {e}")
            return
        typer.echo(render_text(result))


@app.command()
def send_briefing(
    test: Annotated[bool, typer.Option(help="Send the latest briefing now, as a test.")] = False,
) -> None:
    """Email today's briefing if email is on, it's past send time and it isn't sent yet."""
    from app.collect.fetchers import make_client
    from app.db import get_sessionmaker
    from app.email import EmailError, send_due_briefing

    with get_sessionmaker()() as session, make_client() as client:
        try:
            typer.echo(send_due_briefing(session, client, get_topic(), get_settings(), test=test))
        except EmailError as e:
            # Not marked as sent, so the next hourly run tries again.
            typer.echo(f"Email not sent: {e}")
            if test:
                raise typer.Exit(1) from e


@app.command()
def evaluate_ideas() -> None:
    """Score published ideas after 1, 5 and 20 trading days against their index."""
    from app.db import get_sessionmaker
    from app.track import evaluate_ideas as run

    with get_sessionmaker()() as session:
        r = run(session, get_topic())
    typer.echo(
        f"{r.ideas} ideas: {r.entered} newly entered, {r.scored} results added, "
        f"{r.no_prices} without prices yet"
    )


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
    typer.echo(f"llm: {s.llm_provider}")
    typer.echo(f"  tag model: {s.llm_tag_model}, briefing model: {s.llm_briefing_model}")
    typer.echo(f"gemini key: {'set' if s.gemini_api_key else 'missing'}")
    typer.echo(f"finnhub key: {'set' if s.finnhub_api_key else 'missing'}")
    typer.echo(f"sec user agent: {s.sec_user_agent or 'missing'}")
    typer.echo(f"twelve data key: {'set' if s.twelve_data_api_key else 'missing'}")
    typer.echo(f"eodhd key: {'set' if s.eodhd_api_key else 'missing'}")


if __name__ == "__main__":
    app()
