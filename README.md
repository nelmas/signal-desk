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
uv run signal-desk collect         # fetch news once
uv run signal-desk serve           # http://127.0.0.1:8000/api/health
```

If `uv` isn't on your PATH, `python -m uv` works the same way.

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

## News collection

`signal-desk collect` reads every enabled source in `topic.yaml`. The `fetcher` field picks
the reader: `rss`, `atom` or `finnhub_company_news`. Per run it:

- skips items older than 7 days and items not in the topic's `article_languages`;
- drops duplicates by canonical URL (tracking parameters removed), then by a hash of the
  title and the start of the excerpt within 3 days, which catches syndicated copies;
- stores the headline, a plain-text excerpt (max 1,000 characters), the link and a few
  metadata fields. Never the full text;
- records `last_fetched_at` or `last_error` per source. One failing feed doesn't stop the
  rest, and a source missing its free key is skipped, not failed.

`signal-desk prune` deletes articles older than `UNTAGGED_RETENTION_DAYS` that no tracked
company was tagged in, which keeps the database inside Neon's free storage.

### Running it hourly

`.github/workflows/collect.yml` runs migrations, `sync-topic`, `collect` and `prune` at
:17 past every hour. In the GitHub repo, go to Settings → Secrets and variables → Actions
and add the secrets `DATABASE_URL`, `SEC_USER_AGENT`, `FINNHUB_API_KEY` and `GEMINI_API_KEY`. Then, on the
Variables tab, add `COLLECT_ENABLED` = `true`; until then the job skips. Open the Actions tab,
choose "Collect news" and press "Run workflow" to test it.

## Article tagging

`signal-desk tag` runs after each collection, in two steps:

1. **Name match (free).** Each new article's headline and excerpt are checked against
   every alias in `companies.csv`, as whole words ("visade" never matches "Visa").
   Finnhub articles also match the stock they were fetched for. Articles that name no
   tracked company are marked `no_match` and never reach the AI.
2. **AI (Gemini free tier).** Matching articles go to `LLM_TAG_MODEL` in batches of 15.
   For each one the model returns:
   - the candidate companies it concerns, each with a role (`subject`, or `affected`
     for a company the news materially changes things for) and its own tone (-1 to 1);
   - the event type, importance (0 to 1) and a one-line summary;
   - the basis: `announced` (company, filing, regulator), `reported` (media, sources,
     analysts) or `commentary` (opinion, roundups, rehashed news). Scoring trusts them
     in that order.

   The prompt version is stored with every tag (`tag-v2`); migration 0004 sent all
   `tag-v1` tags back to be redone.

The answer is checked before it is saved: companies the name match didn't find are
dropped, unknown event types become `other`, and numbers are clamped. So the agent can
never tag a company that isn't on the list. Articles that are only passing mentions are
marked `irrelevant`; articles without a usable answer after 3 tries are marked `failed`.

Free-tier limits: requests are spaced to stay under `LLM_TAG_REQUESTS_PER_MINUTE`, and
each run and each day (counted from midnight Pacific, when Gemini resets) has a cap. Every
call is logged in `ai_calls` with tokens and latency. A 429 (quota reached) ends the run;
the remaining articles wait for the next run.

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
(`LLM_PROVIDER`, `LLM_TAG_MODEL`, `LLM_BRIEFING_MODEL`) so it can move to another free provider if Gemini's
free tier changes.

## Phases

1. Project setup and database ✅
2. News collection (RSS, MFN/Cision, news API, dedup, hourly) ✅
3. AI tagging (companies checked against ticker list, event type, sentiment, summary) ✅
4. Prices and the 0–100 signal score
5. Story clustering and briefing generation with citations
6. Web app: briefing, watchlist, news feed, stock detail
7. Settings and daily email
8. Track record
