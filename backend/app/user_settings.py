"""Choices made on the Settings page, read by the jobs.

Stored as JSON in the `settings` table. The web app writes them; nothing here ever
overwrites them (sync-topic only seeds missing keys). Missing keys mean "the defaults":
every source and market on, email off.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Setting


@dataclass
class EmailSettings:
    enabled: bool = False
    to: str | None = None


def _value(session: Session, key: str) -> dict:
    row = session.get(Setting, key)
    return row.value if row and isinstance(row.value, dict) else {}


def source_enabled(session: Session, source_key: str) -> bool:
    return _value(session, "sources").get(source_key, True) is not False


def market_enabled(session: Session, market_key: str | None) -> bool:
    return market_key is None or _value(session, "markets").get(market_key, True) is not False


def disabled_markets(session: Session) -> set[str]:
    return {k for k, on in _value(session, "markets").items() if on is False}


def email_settings(session: Session) -> EmailSettings:
    v = _value(session, "email")
    to = v.get("to")
    return EmailSettings(enabled=v.get("enabled") is True, to=to if isinstance(to, str) else None)
