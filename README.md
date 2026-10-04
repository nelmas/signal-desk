# Signal Desk

A personal AI agent that reads stock news (Nasdaq Stockholm and US) every day and
writes a short morning briefing with sources. Ideas to research, not buy or sell advice.

## Layout

```
backend/
  app/            FastAPI app, models, topic config loader, CLI
  alembic/        database migrations
  topics/stocks/  topic config: markets, sources, event types, companies.csv
  tests/          pytest (runs on an embedded Postgres, no setup needed)
frontend/         Next.js app (phase 6)
```

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
cd backend
uv sync
copy ..\.env.example ..\.env      # then paste your Neon DATABASE_URL and Gemini key
uv run alembic upgrade head        # create tables
uv run signal-desk sync-topic      # load sources, companies, default settings
uv run signal-desk serve           # http://127.0.0.1:8000/api/health
```

Run tests and lint:

```powershell
uv run pytest
uv run ruff check .
```

## Topic config

Everything topic-specific lives in `backend/topics/<topic>/`:

- `topic.yaml`: markets, news sources, event types and their importance, default
  score weights, briefing schedule.
- `companies.csv`: the ticker list. Listings are `SYMBOL@MIC` separated by `|`, and
  the first one is the primary listing used for prices. The company name is always an
  alias. An alias may belong to only one company, which `signal-desk check-topic` enforces.

After editing either file, run `uv run signal-desk sync-topic`. It is idempotent.
Settings you changed in the app are never overwritten.

A source can only be enabled once it has a `url` and a `terms_basis`, which records
why we're allowed to use it.

## Schema changes

Edit `app/models.py`, then:

```powershell
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

`tests/test_db.py::test_models_match_migrations` fails if you forget the migration.

## Free by design

Signal Desk must cost nothing to run, and it runs in the cloud, not on a home PC.
Every dependency is a free tier that fails or pauses at its limit instead of billing:

| Part | Service | Limit to keep in mind |
|---|---|---|
| AI tagging and briefing | Google Gemini API free tier (Flash) | Requests per minute and per day. Articles are tagged in batches; leftovers retry next run. Never enable billing on the Google project. |
| Scheduled jobs | GitHub Actions cron (public repo) | Unlimited minutes on a public repo. GitHub turns off scheduled workflows after 60 days without repo activity; re-enable them in the Actions tab if that happens. |
| Database | Neon free tier | Storage cap; we store headlines and summaries, not full articles. |
| Web app | Vercel Hobby | Personal, non-commercial use only. |
| Email | Gmail SMTP with an app password | Daily sending cap, far above one briefing. |
| News and prices | MFN, Cision, SEC EDGAR, Finnhub free tier, Stooq | Per-source rate limits. |

The repo is public. Secrets (database URL, API keys, email password) go only in
`.env` locally and in GitHub Secrets for Actions, never in the code.

Do not add a dependency that needs a card on file. The AI provider is a setting
(`LLM_PROVIDER`, `LLM_MODEL`) so it can move to another free provider if Gemini's
free tier changes.

## Phases

1. Project setup and database ✅
2. News collection (RSS, MFN/Cision, news API, dedup, hourly)
3. AI tagging (companies checked against ticker list, event type, sentiment, summary)
4. Prices and the 0–100 signal score
5. Story clustering and briefing generation with citations
6. Web app: briefing, watchlist, news feed, stock detail
7. Settings and daily email
8. Track record
