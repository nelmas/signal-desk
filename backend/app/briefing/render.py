"""Plain-text rendering of a briefing (terminal now, email in phase 7)."""

import datetime as dt
import textwrap

from app.models import Briefing

WIDTH = 88
ARROW = {"up": "more attention / better news", "down": "worse news", "mixed": "mixed"}


def _refs(cites: list[int]) -> str:
    return "".join(f"[{n}]" for n in cites)


def _para(text: str, cites: list[int], indent: str = "") -> str:
    return textwrap.fill(f"{text} {_refs(cites)}".strip(), WIDTH, initial_indent=indent,
                         subsequent_indent=indent)


def render_text(briefing: Briefing) -> str:
    c = briefing.content or {}
    out = [f"SIGNAL DESK - morning briefing, {briefing.date:%A %d %B %Y}", ""]
    if c.get("overview", {}).get("text"):
        out += [_para(c["overview"]["text"], c["overview"]["cites"]), ""]
    else:
        out += ["A quiet window: no news strong enough for a briefing.", ""]

    out.append("NEWS ABOUT YOUR HOLDINGS")
    for h in c.get("holdings", []):
        out.append(_para(f"{h['name']}: {h['text']}", h["cites"], "  "))
    if not c.get("holdings"):
        out.append("  No news about your holdings.")
    out.append("")

    if c.get("stories"):
        out.append("TOP STORIES")
        for i, st in enumerate(c["stories"], 1):
            out.append(f"{i}. {st['headline']}")
            for label, part in (("What happened", "what_happened"),
                                ("What it means", "what_it_means"),
                                ("What it could lead to", "what_next")):
                if st[part]["text"]:
                    out.append(_para(f"{label}: {st[part]['text']}", st[part]["cites"], "   "))
            out.append("")

    if c.get("sectors"):
        out.append("SECTORS TO KEEP AN EYE ON")
        for sec in c["sectors"]:
            out.append(_para(f"{sec['name']} ({ARROW[sec['direction']]}): {sec['reason']}",
                             sec["cites"], "  "))
        out.append("")

    if c.get("ideas"):
        out.append("STOCKS THAT COULD BENEFIT")
        for idea in c["ideas"]:
            out.append(f"  {idea['name']} - confidence {idea['confidence']}")
            out.append(_para(f"Why it could rise: {idea['why_rise']['text']}",
                             idea["why_rise"]["cites"], "    "))
            out.append(_para(f"What could go wrong: {idea['risks']['text']}",
                             idea["risks"]["cites"], "    "))
        out.append("")

    if c.get("sources"):
        out.append("SOURCES")
        for src in c["sources"]:
            when = dt.datetime.fromisoformat(src["published_at"])
            out.append(f"  [{src['n']}] {src['title']} - {src['source']}, {when:%d %b %H:%M} UTC")
            out.append(f"      {src['url']}")
        out.append("")
    out.append(c.get("disclaimer", ""))
    return "\n".join(out)
