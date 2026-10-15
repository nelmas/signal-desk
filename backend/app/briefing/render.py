"""Plain-text rendering of a briefing (terminal, and the email's text part)."""

import datetime as dt
import textwrap

from app.briefing.labels import labels, long_date
from app.models import Briefing

WIDTH = 88


def _refs(cites: list[int]) -> str:
    return "".join(f"[{n}]" for n in cites)


def _para(text: str, cites: list[int], indent: str = "") -> str:
    return textwrap.fill(f"{text} {_refs(cites)}".strip(), WIDTH, initial_indent=indent,
                         subsequent_indent=indent)


def render_text(briefing: Briefing) -> str:
    c = briefing.content or {}
    t = labels(briefing.language)
    out = [f"{t['title']}, {long_date(briefing.date, briefing.language)}", ""]
    if c.get("overview", {}).get("text"):
        out += [_para(c["overview"]["text"], c["overview"]["cites"]), ""]
    else:
        out += [t["quiet"], ""]

    out.append(t["holdings"].upper())
    for h in c.get("holdings", []):
        who = f"{h['name']} ({h['share']})" if h.get("share") else h["name"]
        out.append(_para(f"{who}: {h['text']}", h["cites"], "  "))
    if c.get("holdings_also"):
        out.append(_para(f"{t['also']} " + ", ".join(c["holdings_also"]) + ".", [], "  "))
    if not c.get("holdings"):
        out.append(f"  {t['no_holdings']}")
    out.append("")

    if c.get("stories"):
        out.append(t["stories"].upper())
        for i, st in enumerate(c["stories"], 1):
            out.append(f"{i}. {st['headline']}")
            for label, part in (("happened", "what_happened"), ("means", "what_it_means"),
                                ("next", "what_next")):
                if st[part]["text"]:
                    out.append(_para(f"{t[label]}: {st[part]['text']}", st[part]["cites"], "   "))
            out.append("")

    if c.get("sectors"):
        out.append(t["sectors"].upper())
        for sec in c["sectors"]:
            out.append(_para(f"{sec['name']} ({t[sec['direction']]}): {sec['reason']}",
                             sec["cites"], "  "))
        out.append("")

    if c.get("ideas"):
        out.append(t["ideas"].upper())
        for idea in c["ideas"]:
            level = t.get(idea["confidence"], idea["confidence"])
            out.append(f"  {idea['name']} - {t['confidence']} {level}")
            out.append(_para(f"{t['why']}: {idea['why_rise']['text']}",
                             idea["why_rise"]["cites"], "    "))
            out.append(_para(f"{t['risks']}: {idea['risks']['text']}",
                             idea["risks"]["cites"], "    "))
        out.append("")

    if c.get("sources"):
        out.append(t["sources"].upper())
        for src in c["sources"]:
            when = dt.datetime.fromisoformat(src["published_at"])
            out.append(f"  [{src['n']}] {src['title']} - {src['source']}, {when:%d %b %H:%M} UTC")
            out.append(f"      {src['url']}")
        out.append("")
    out.append(t["disclaimer"])
    return "\n".join(out)
