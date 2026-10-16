"""Turn feed responses into `FetchedItem`s. Pure functions, no network."""

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

SUMMARY_MAX_CHARS = 1000

_ATOM = "{http://www.w3.org/2005/Atom}"
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_END = re.compile(r"</(p|li|div|h\d)>|<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


@dataclass
class FetchedItem:
    url: str
    title: str
    published_at: dt.datetime
    summary: str | None = None
    language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # small source metadata only
    # Structured sources (insider trades) arrive already tagged by rules, not the AI:
    # {"company_id", "event_type", "basis", "sentiment", "importance", "summary", "matched"}.
    tag: dict[str, Any] | None = None
    # "irrelevant": stored only so it isn't fetched again (e.g. a routine Form 4).
    status: str | None = None


def html_to_text(markup: str | None) -> str:
    if not markup:
        return ""
    text = _SCRIPT_STYLE.sub(" ", markup)
    text = _BLOCK_END.sub(". ", text)
    text = html.unescape(_TAG.sub(" ", text))
    text = _SPACES.sub(" ", text).replace(" .", ".")
    return re.sub(r"(\.\s*){2,}", ". ", text).strip(" .")


def excerpt(markup: str | None) -> str | None:
    text = html_to_text(markup)
    if len(text) <= SUMMARY_MAX_CHARS:
        return text or None
    cut = text[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0]
    return cut + " …"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: Element) -> dict[str, list[str]]:
    """Child texts by local tag name, so namespaced extras (MFN's x:language) are found."""
    out: dict[str, list[str]] = {}
    for child in el:
        out.setdefault(_local(child.tag), []).append((child.text or "").strip())
    return out


def _utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def parse_rss(content: bytes, *, now: dt.datetime) -> list[FetchedItem]:
    items = []
    for el in ElementTree.fromstring(content).iter("item"):
        f = _children(el)
        title = html_to_text(f.get("title", [""])[0])
        link = f.get("link", [""])[0]
        if not (title and link):
            continue
        try:
            published = _utc(parsedate_to_datetime(f["pubDate"][0]))
        except (KeyError, TypeError, ValueError):
            published = now
        # MFN leaves <description> empty and puts the release in x:content.
        body = f.get("description", [""])[0] or f.get("content", [""])[0]
        raw: dict[str, Any] = {"guid": f.get("guid", [None])[0]}
        if f.get("tag"):
            raw["tags"] = f["tag"]
        items.append(
            FetchedItem(
                url=link,
                title=title,
                published_at=published,
                summary=excerpt(body),
                language=f.get("language", [None])[0] or None,
                raw=raw,
            )
        )
    return items


def parse_atom(content: bytes, *, now: dt.datetime) -> list[FetchedItem]:
    items = []
    for entry in ElementTree.fromstring(content).iter(f"{_ATOM}entry"):
        title = html_to_text(entry.findtext(f"{_ATOM}title"))
        link = next(
            (
                el.get("href")
                for el in entry.iter(f"{_ATOM}link")
                if el.get("rel", "alternate") == "alternate" and el.get("href")
            ),
            None,
        )
        if not (title and link):
            continue
        stamp = entry.findtext(f"{_ATOM}published") or entry.findtext(f"{_ATOM}updated")
        try:
            published = _utc(dt.datetime.fromisoformat(stamp)) if stamp else now
        except ValueError:
            published = now
        items.append(
            FetchedItem(
                url=link,
                title=title,
                published_at=published,
                summary=excerpt(entry.findtext(f"{_ATOM}summary")),
                raw={
                    "id": entry.findtext(f"{_ATOM}id"),
                    "categories": [c.get("term") for c in entry.iter(f"{_ATOM}category")],
                },
            )
        )
    return items


def parse_finnhub_news(data: list[dict[str, Any]], *, symbol: str) -> list[FetchedItem]:
    items = []
    for row in data:
        if not (row.get("headline") and row.get("url") and row.get("datetime")):
            continue
        items.append(
            FetchedItem(
                url=row["url"],
                title=html_to_text(row["headline"]),
                published_at=dt.datetime.fromtimestamp(row["datetime"], dt.UTC),
                summary=excerpt(row.get("summary")),
                language="en",
                raw={
                    "id": row.get("id"),
                    "outlet": row.get("source"),
                    "related": row.get("related"),
                    "queried_symbol": symbol,
                },
            )
        )
    return items
