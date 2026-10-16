"""US insider trades (Form 4) and 5%+ ownership stakes (Schedule 13D/13G), read by rules.

Source: SEC's daily filing index, which lists every filing of a day, so nothing is missed
when a scheduled run is skipped. Insiders have two business days to file, so reading the
last two complete days keeps the briefing current. Only filings about companies the app
knows are opened; filings already stored are never opened again.

Kept, because they carry signal: open-market purchases of $10,000 or more, and open-market
sales of $1 million or more that weren't pre-planned (Rule 10b5-1). Grants, option
exercises and tax withholding are routine and skipped. New 13D (5%+, may seek influence),
13D amendments and new 13G (5%+, passive) become "ownership stake" news; 13G amendments
are routine and skipped.
"""

import datetime as dt
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx
from defusedxml import ElementTree

from app.collect.dedup import url_hash
from app.collect.fetchers import FetchContext
from app.collect.parsers import FetchedItem

DAILY_INDEX = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{ymd}.idx"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/"
NEW_YORK = ZoneInfo("America/New_York")
DAYS_BACK = 2
MAX_FORM4_PER_RUN = 120  # 2 requests each; SEC allows 10 requests a second
PAUSE = 0.15
MIN_PURCHASE_USD = 10_000
MIN_SALE_USD = 1_000_000
SENIOR = re.compile(r"\b(ceo|chief executive|cfo|chief financial|president|chair)", re.I)
_LINE = re.compile(
    r"^(?P<form>\S.*?)\s{2,}(?P<name>.+?)\s{2,}(?P<cik>\d+)\s+(?P<date>\d{8})\s+"
    r"(?P<path>edgar/data/\d+/(?P<acc>[\d-]+)\.txt)\s*$"
)


@dataclass
class IndexLine:
    form: str
    name: str
    cik: str  # 10 digits, as stored on companies
    filed: dt.date
    accession: str


def parse_daily_index(text: str) -> list[IndexLine]:
    out = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            out.append(IndexLine(
                form=m["form"].strip(), name=m["name"].strip(), cik=m["cik"].zfill(10),
                filed=dt.datetime.strptime(m["date"], "%Y%m%d").date(), accession=m["acc"],
            ))
    return out


def recent_business_days(now: dt.datetime, n: int = DAYS_BACK) -> list[dt.date]:
    """The last n complete US business days (weekends skipped), newest first."""
    day, out = now.astimezone(NEW_YORK).date(), []
    while len(out) < n:
        day -= dt.timedelta(days=1)
        if day.weekday() < 5:
            out.append(day)
    return out


def _money(x: float, language: str = "en") -> str:
    if language == "sv":
        text = f"{x / 1e6:.1f} miljoner USD" if x >= 1e6 else f"{x:,.0f} USD".replace(",", " ")
        return text.replace(".", ",")
    return f"${x / 1e6:.1f} million" if x >= 1e6 else f"${x:,.0f}"


def _shares(x: float) -> str:
    return f"{x:,.0f}"


def fetch_sec_insiders(
    client: httpx.Client, headers: dict[str, str], ctx: FetchContext, now: dt.datetime
) -> list[FetchedItem]:
    lines: list[IndexLine] = []
    for day in recent_business_days(now):
        url = DAILY_INDEX.format(y=day.year, q=(day.month - 1) // 3 + 1, ymd=f"{day:%Y%m%d}")
        response = client.get(url, headers=headers)
        if response.status_code == 404:
            continue  # a holiday, or not published yet
        response.raise_for_status()
        lines += parse_daily_index(response.content.decode("latin-1"))

    # Each filing appears once per party (issuer and insider, or subject and investor).
    filings: dict[str, list[IndexLine]] = defaultdict(list)
    for line in lines:
        if line.form in ("4", "4/A") or line.form.startswith("SCHEDULE 13"):
            filings[line.accession].append(line)

    items, opened = [], 0
    for accession, parties in filings.items():
        issuer = next((p for p in parties if p.cik in ctx.company_by_cik), None)
        if issuer is None:
            continue  # not a company the app knows
        folder = accession.replace("-", "")
        index_url = ARCHIVE.format(cik=int(issuer.cik), folder=folder) + f"{accession}-index.htm"
        if url_hash(index_url) in ctx.known_urls:
            continue
        others = [p.name for p in parties if p is not issuer]
        published = dt.datetime.combine(issuer.filed, dt.time(18, 0), NEW_YORK).astimezone(dt.UTC)
        if issuer.form in ("4", "4/A"):
            if opened >= MAX_FORM4_PER_RUN:
                continue  # the rest are read next run
            opened += 1
            item = _form4(client, headers, issuer, folder, index_url, published, ctx)
        else:
            item = _stake(issuer, others, index_url, published, ctx)
        if item:
            items.append(item)
    return items


def _text(el, path: str) -> str | None:
    found = el.find(path)
    if found is None:
        return None
    value = found.find("value")
    text = (value if value is not None else found).text
    return text.strip() if text and text.strip() else None


def _number(el, path: str) -> float:
    try:
        return float(_text(el, path) or 0)
    except ValueError:
        return 0.0


def parse_form4(xml: bytes) -> dict:
    """Open-market buys (code P) and sells (code S) from a Form 4, summed."""
    root = ElementTree.fromstring(xml)
    relation = root.find("reportingOwner/reportingOwnerRelationship")
    role = None
    if relation is not None:
        title = _text(relation, "officerTitle")
        if title:
            role = title
        elif (_text(relation, "isDirector") or "").lower() in ("1", "true"):
            role = "Director"
        elif (_text(relation, "isTenPercentOwner") or "").lower() in ("1", "true"):
            role = "10% owner"
    totals = {"P": [0.0, 0.0], "S": [0.0, 0.0]}  # shares, value
    dates = set()
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        if code not in totals:
            continue
        shares = _number(tx, "transactionAmounts/transactionShares")
        price = _number(tx, "transactionAmounts/transactionPricePerShare")
        totals[code][0] += shares
        totals[code][1] += shares * price
        if d := _text(tx, "transactionDate"):
            dates.add(d[:10])
    planned = (_text(root, "aff10b5One") or "").lower() in ("1", "true")
    return {
        "owner": _text(root, "reportingOwner/reportingOwnerId/rptOwnerName") or "An insider",
        "role": role or "insider",
        "issuer": _text(root, "issuer/issuerName"),
        "bought": totals["P"], "sold": totals["S"], "planned": planned,
        "dates": sorted(dates),
    }


def form4_item(data: dict, issuer_name: str, company_id: int, url: str,
               published: dt.datetime, language: str) -> FetchedItem:
    """A news item for a meaningful trade, or a 'routine' marker so it isn't read again."""
    (b_shares, b_value), (s_shares, s_value) = data["bought"], data["sold"]
    senior = bool(SENIOR.search(data["role"]))
    who, role = data["owner"], data["role"]
    when = " and ".join(data["dates"]) or "recently"
    if b_value >= MIN_PURCHASE_USD:
        action, shares, value, positive = "bought", b_shares, b_value, True
    elif s_value >= MIN_SALE_USD and not data["planned"]:
        action, shares, value, positive = "sold", s_shares, s_value, False
    else:
        return FetchedItem(url=url, title=f"{issuer_name}: routine Form 4 ({who})",
                           published_at=published, language="en", status="irrelevant",
                           raw={"form": "4", "routine": True})
    price = value / shares if shares else 0
    if positive:
        importance = 0.45 + 0.15 * (value >= 250_000) + 0.15 * (value >= 1e6) + 0.1 * senior
        sentiment = 0.4 + 0.1 * senior + 0.1 * (value >= 1e6)
    else:
        importance = 0.25 + 0.1 * (value >= 1e7) + 0.1 * senior
        sentiment = -0.15 - 0.15 * (value >= 1e7)
    if language == "sv":
        verb = "köpte" if positive else "sålde"
        price_sv = f"{price:.2f}".replace(".", ",")
        summary = (f"{who} ({role}) {verb} {_shares(shares).replace(',', ' ')} aktier till i snitt "
                   f"{price_sv} USD, totalt {_money(value, 'sv')}, {when}.")
    else:
        summary = (f"{who} ({role}) {action} {_shares(shares)} shares at an average "
                   f"${price:.2f}, {_money(value)} in total, on {when}.")
    return FetchedItem(
        url=url,
        title=f"{issuer_name}: {role} {who} {action} {_shares(shares)} shares for {_money(value)}",
        published_at=published,
        summary=summary,
        language=language,
        raw={"form": "4", "owner": who, "role": role, "value_usd": round(value)},
        tag={"company_id": company_id, "event_type": "insider_trade", "basis": "announced",
             "sentiment": round(sentiment, 3), "importance": round(min(importance, 0.9), 3),
             "summary": summary, "matched": "sec-form4"},
    )


def _form4(client, headers, issuer: IndexLine, folder: str, index_url: str,
           published: dt.datetime, ctx: FetchContext) -> FetchedItem | None:
    base = ARCHIVE.format(cik=int(issuer.cik), folder=folder)
    time.sleep(PAUSE)
    listing = client.get(base + "index.json", headers=headers)
    if listing.status_code != 200:
        return None
    names = [i["name"] for i in listing.json().get("directory", {}).get("item", [])]
    xml_name = next((n for n in names if n.endswith(".xml")), None)
    if xml_name is None:
        return None
    time.sleep(PAUSE)
    doc = client.get(base + xml_name, headers=headers)
    if doc.status_code != 200:
        return None
    try:
        data = parse_form4(doc.content)
    except Exception:  # noqa: BLE001 - one malformed filing must not stop the rest
        return None  # tried again next run
    return form4_item(data, issuer.name, ctx.company_by_cik[issuer.cik], index_url, published,
                      ctx.language)


def _stake(issuer: IndexLine, filers: list[str], url: str, published: dt.datetime,
           ctx: FetchContext) -> FetchedItem | None:
    form = issuer.form
    if form.startswith("SCHEDULE 13G/A"):
        return None  # routine yearly updates of passive stakes; costs nothing to skip
    by = ", ".join(dict.fromkeys(filers)) or "An investor"
    if form.startswith("SCHEDULE 13D/A"):
        what = ("updated its Schedule 13D stake", "uppdaterade sitt ägande (13D)")
        importance, sentiment = 0.3, 0.0
    elif form.startswith("SCHEDULE 13D"):
        what = ("reported a 5%+ stake and may seek to influence the company (13D)",
                "rapporterade ett ägande på över 5 % och kan vilja påverka bolaget (13D)")
        importance, sentiment = 0.65, 0.2
    else:
        what = ("reported a passive 5%+ stake (13G)",
                "rapporterade ett passivt ägande på över 5 % (13G)")
        importance, sentiment = 0.4, 0.1
    summary = (f"{by} {what[1]} i {issuer.name}." if ctx.language == "sv"
               else f"{by} {what[0]} in {issuer.name}.")
    return FetchedItem(
        url=url,
        title=f"{issuer.name}: {by} {what[0]}",
        published_at=published,
        summary=summary,
        language=ctx.language,
        raw={"form": form, "filers": filers},
        tag={"company_id": ctx.company_by_cik[issuer.cik], "event_type": "ownership_stake",
             "basis": "announced", "sentiment": sentiment, "importance": importance,
             "summary": summary, "matched": "sec-13dg"},
    )
