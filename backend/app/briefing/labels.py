"""Fixed text around the AI-written briefing, in English and Swedish.

The web app has its own copy of these words (frontend/lib/i18n.ts); this one is for
the email and the plain-text version.
"""

import datetime as dt

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "title": "SIGNAL DESK - morning briefing",
        "briefing": "Morning briefing",
        "quiet": "A quiet window: no news strong enough for a briefing.",
        "holdings": "News about your holdings",
        "no_holdings": "No news about your holdings.",
        "also": "Also in the news:",
        "stories": "Top stories",
        "happened": "What happened",
        "means": "What it means",
        "next": "What it could lead to",
        "sectors": "Sectors to keep an eye on",
        "up": "more attention / better news",
        "down": "worse news",
        "mixed": "mixed",
        "ideas": "Stocks that could benefit",
        "confidence": "confidence",
        "why": "Why it could rise",
        "risks": "What could go wrong",
        "sources": "Sources",
        "open_app": "Open the full briefing, watchlist and stock pages in",
        "open_app_text": "Open in the app:",
        "subject": "Signal Desk",
        "disclaimer": (
            "Ideas to research, not buy or sell advice. Every claim links to its sources. "
            "Companies come only from the app's verified list."
        ),
        "low": "low", "medium": "medium", "high": "high",
    },
    "sv": {
        "title": "SIGNAL DESK - morgonbrief",
        "briefing": "Morgonbrief",
        "quiet": "Ett lugnt dygn: inga nyheter starka nog för en brief.",
        "holdings": "Nyheter om dina innehav",
        "no_holdings": "Inga nyheter om dina innehav.",
        "also": "Också i nyheterna:",
        "stories": "Viktigaste nyheterna",
        "happened": "Vad hände",
        "means": "Vad det betyder",
        "next": "Vad det kan leda till",
        "sectors": "Sektorer att hålla ögonen på",
        "up": "mer uppmärksamhet / bättre nyheter",
        "down": "sämre nyheter",
        "mixed": "blandat",
        "ideas": "Aktier som kan gynnas",
        "confidence": "säkerhet",
        "why": "Varför den kan stiga",
        "risks": "Vad som kan gå fel",
        "sources": "Källor",
        "open_app": "Öppna hela briefen, signallistan och aktiesidorna i",
        "open_app_text": "Öppna i appen:",
        "subject": "Signal Desk",
        "disclaimer": (
            "Idéer att undersöka, inte köp- eller säljråd. Varje påstående länkar till sina "
            "källor. Bolag kommer bara från appens verifierade lista."
        ),
        "low": "låg", "medium": "medel", "high": "hög",
    },
}

_SV_DAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
_SV_MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti",
              "september", "oktober", "november", "december"]


def labels(language: str | None) -> dict[str, str]:
    return LABELS.get(language or "en", LABELS["en"])


def long_date(day: dt.date, language: str | None) -> str:
    """'Thursday 15 October 2026' / 'torsdag 15 oktober 2026', without the OS locale."""
    if language == "sv":
        return f"{_SV_DAYS[day.weekday()]} {day.day} {_SV_MONTHS[day.month - 1]} {day.year}"
    return f"{day:%A} {day.day} {day:%B %Y}"


def short_date(day: dt.date, language: str | None) -> str:
    if language == "sv":
        return f"{day.day} {_SV_MONTHS[day.month - 1][:3]}"
    return f"{day.day} {day:%b}"


def fund_share(percent: str, language: str | None) -> str:
    """'5.7' -> '5.7% of your fund' / '5,7 % av din fond'."""
    if language == "sv":
        return f"{percent.replace('.', ',')} % av din fond"
    return f"{percent}% of your fund"
