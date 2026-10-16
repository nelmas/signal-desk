"""Swedish insider trades from Finansinspektionen's public insider register, read by rules.

The register is public by law (SFS 2016:1306) and FI offers this CSV export on its public
search page. One small export per run, covering the last few days of publications.

Kept: purchases (Förvärv) of shares worth 100,000 SEK or more, and disposals (Avyttring)
of 10 MSEK or more, by insiders of companies the app knows. Allocations, share-programme
transactions, other instruments and outdated (non-current) reports are skipped. Several
lines from one notification (one person, one company, one direction) become one item.
The register names people; only name and role are kept, inside this private app.
"""

import csv
import datetime as dt
import hashlib
import io
import re
from collections import defaultdict
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from app.collect.fetchers import FetchContext
from app.collect.parsers import FetchedItem
from app.names import normalize_name
from app.universe import clean_name

STOCKHOLM = ZoneInfo("Europe/Stockholm")
DAYS_BACK = 3
MIN_PURCHASE_SEK = 100_000
MIN_DISPOSAL_SEK = 10_000_000
# No word boundary at the start: Swedish compounds like "Styrelseordförande" must match.
SENIOR = re.compile(
    r"(\bvd\b|verkställande direktör|ordförande|finanschef|ekonomichef|\bcfo\b|\bceo\b)", re.I
)
# FI's catch-all category is too long for a headline.
_SHORT_ROLES = {
    "Annan medlem i bolagets administrations-, lednings- eller kontrollorgan":
        "ledande befattningshavare",
}


def _number(text: str) -> float:
    try:
        return float((text or "0").replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


def _sek(x: float, language: str) -> str:
    if language == "sv":
        return (f"{x / 1e6:.1f} miljoner kr" if x >= 1e6 else f"{x:,.0f} kr".replace(",", " ")
                ).replace(".", ",")
    return f"SEK {x / 1e6:.1f} million" if x >= 1e6 else f"SEK {x:,.0f}"


def parse_export(content: bytes) -> list[dict[str, str]]:
    """FI's export is UTF-16 text with ';' between fields."""
    for encoding in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("unreadable export")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def _company(issuer: str, ctx: FetchContext) -> int | None:
    for name in (normalize_name(issuer), clean_name(issuer)):
        if name in ctx.company_by_name:
            return ctx.company_by_name[name]
    return None


def fetch_fi_insider(
    client: httpx.Client, url: str, ctx: FetchContext, now: dt.datetime
) -> list[FetchedItem]:
    today = now.astimezone(STOCKHOLM).date()
    params = {
        "SearchFunctionType": "Insyn",
        "Publiceringsdatum.From": (today - dt.timedelta(days=DAYS_BACK)).isoformat(),
        "Publiceringsdatum.To": today.isoformat(),
        "button": "export",
    }
    response = client.get(url, params=params)
    response.raise_for_status()
    return insider_items(parse_export(response.content), url, ctx)


def insider_items(rows: list[dict[str, str]], url: str, ctx: FetchContext) -> list[FetchedItem]:
    groups: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        kind = row.get("Karaktär", "")
        if kind not in ("Förvärv", "Avyttring"):
            continue
        if row.get("Instrumenttyp") != "Aktie" or row.get("Är kopplad till aktieprogram") == "Ja":
            continue
        if row.get("Status") != "Aktuell":
            continue
        company_id = _company(row.get("Emittent", ""), ctx)
        if company_id is None:
            continue  # not a company the app knows
        key = (company_id, row.get("Emittent"), row.get("Person i ledande ställning"),
               row.get("Befattning"), kind, row.get("Publiceringsdatum"), row.get("Valuta"))
        groups[key].append(row)

    items = []
    for (company_id, issuer, person, role, kind, published, currency), lines in groups.items():
        shares = sum(_number(r.get("Volym", "")) for r in lines)
        value = sum(_number(r.get("Volym", "")) * _number(r.get("Pris", "")) for r in lines)
        if currency != "SEK":
            continue  # thresholds are in SEK; rare other currencies are left out
        bought = kind == "Förvärv"
        if value < (MIN_PURCHASE_SEK if bought else MIN_DISPOSAL_SEK):
            continue
        senior = bool(SENIOR.search(role or ""))
        related = any(r.get("Närstående") == "Ja" for r in lines)
        dates = sorted({(r.get("Transaktionsdatum") or "")[:10] for r in lines} - {""})
        when = " och ".join(dates) if ctx.language == "sv" else " and ".join(dates)
        if bought:
            importance = 0.45 + 0.15 * (value >= 2.5e6) + 0.15 * (value >= 1e7) + 0.1 * senior
            sentiment = 0.4 + 0.1 * senior + 0.1 * (value >= 1e7)
        else:
            importance = 0.25 + 0.1 * (value >= 1e8) + 0.1 * senior
            sentiment = -0.15 - 0.15 * (value >= 1e8)
        verb_sv, verb_en = ("köpte", "bought") if bought else ("sålde", "sold")
        rel_sv = " (genom närstående)" if related else ""
        rel_en = " (through a closely associated person)" if related else ""
        if ctx.language == "sv":
            shares_sv = f"{shares:,.0f}".replace(",", " ")
            summary = (f"{person} ({role}){rel_sv} {verb_sv} {shares_sv} aktier i {issuer} "
                       f"för totalt {_sek(value, 'sv')}, {when}.")
        else:
            summary = (f"{person} ({role}){rel_en} {verb_en} {shares:,.0f} shares in {issuer} "
                       f"for {_sek(value, 'en')} in total, on {when}.")
        publication = dt.datetime.strptime(published, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=STOCKHOLM).astimezone(dt.UTC)
        # The register has no page per notification; link to the issuer's day in the
        # search, with a key so each notification is stored once.
        key = hashlib.sha256(f"{issuer}|{person}|{kind}|{published}".encode()).hexdigest()[:16]
        day = published[:10]
        link = url + "?" + urlencode({
            "SearchFunctionType": "Insyn", "Utgivare": issuer,
            "Publiceringsdatum.From": day, "Publiceringsdatum.To": day, "notis": key,
        })
        items.append(FetchedItem(
            url=link,
            title=f"{issuer}: {_SHORT_ROLES.get(role, role)} {person} {verb_sv} aktier "
                  f"för {_sek(value, 'sv')}",
            published_at=publication,
            summary=summary,
            language="sv",
            raw={"register": "fi-insyn", "person": person, "role": role, "value_sek": round(value)},
            tag={"company_id": company_id, "event_type": "insider_trade", "basis": "announced",
                 "sentiment": round(sentiment, 3), "importance": round(min(importance, 0.9), 3),
                 "summary": summary, "matched": "fi-insyn"},
        ))
    return items
