from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Process-level settings from environment / .env.

    User-facing preferences (score weights, briefing time, ...) live in the
    `settings` table instead, so they can be changed from the app.
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/signal_desk"
    topic: str = "stocks"
    topics_dir: Path = BACKEND_DIR / "topics"

    # The AI must stay on free tiers: Gemini's free tier needs no billing account,
    # so going over its limits fails a request instead of charging for it.
    llm_provider: str = "gemini"
    gemini_api_key: str | None = None
    # Tagging makes dozens of calls a day, so it uses the model with the biggest free
    # daily quota. The briefing is one call a day and uses the better writer.
    llm_tag_model: str = "gemini-3.5-flash-lite"
    llm_briefing_model: str = "gemini-3.8-flash"
    # Used when the briefing model is overloaded or out of quota (also free, 20/day).
    llm_briefing_fallback_model: str | None = "gemini-3.5-flash"
    # Stay under the tag model's free limits (Flash-Lite: 15/min, 500/day), with headroom.
    llm_tag_requests_per_minute: int = 12
    llm_tag_requests_per_day: int = 400
    llm_tag_requests_per_run: int = 25

    # News sources. SEC rejects requests without a "Name email" User-Agent.
    sec_user_agent: str | None = None
    finnhub_api_key: str | None = None  # free key, no card: https://finnhub.io
    # Prices: Twelve Data free plan (US only, 8/min, 800/day). Watchlist + top scorers.
    twelve_data_api_key: str | None = None
    price_requests_per_minute: int = 7
    price_requests_per_run: int = 40
    price_top_scorers: int = 15

    # Articles no company was tagged in are deleted after this many days, so the
    # database stays inside Neon's free storage.
    untagged_retention_days: int = 14

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # Neon and most hosts hand out postgres:// or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
