"""Send the morning briefing by email, once, right after it is written.

Two free ways to send:
- resend (default): Resend's free plan. Without your own domain it sends from
  onboarding@resend.dev and only to the address of your Resend account, which is
  exactly one person emailing themselves.
- smtp: any mailbox that allows app passwords, e.g. Gmail (smtp.gmail.com:465).
"""

import datetime as dt
import html
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.briefing.generate import briefing_options
from app.briefing.labels import labels, long_date, short_date
from app.briefing.render import render_text
from app.config import Settings
from app.models import Briefing
from app.topic import TopicConfig
from app.user_settings import email_settings

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Signal Desk <onboarding@resend.dev>"


class EmailError(Exception):
    pass


@dataclass
class Message:
    to: str
    subject: str
    text: str
    html: str


# --- rendering ---------------------------------------------------------------------------

_INK, _MUTED, _ACCENT, _LINE = "#15212b", "#4a5a67", "#b8541a", "#d8dee3"


def _cites(ns: list[int]) -> str:
    return "".join(
        f'<a href="#s{n}" style="color:{_ACCENT};text-decoration:none;font-size:12px">'
        f"<sup>[{n}]</sup></a>"
        for n in ns
    )


def _p(text: str, cites: list[int] | None = None, style: str = "") -> str:
    return (f'<p style="margin:0 0 10px;line-height:1.55;{style}">'
            f"{html.escape(text)} {_cites(cites or [])}</p>")


def _h(text: str) -> str:
    return (f'<h2 style="font-size:17px;margin:26px 0 10px;padding-top:14px;'
            f'border-top:1px solid {_LINE}">{html.escape(text)}</h2>')


def render_html(briefing: Briefing, app_url: str | None = None) -> str:
    """Simple, inline-styled HTML that survives email clients."""
    c = briefing.content or {}
    t = labels(briefing.language)
    parts = [
        f'<div lang="{html.escape(briefing.language or "en")}" '
        f'style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:{_INK};'
        f'max-width:640px;margin:0 auto;padding:16px">',
        f'<p style="margin:0;color:{_MUTED};font-size:12px;letter-spacing:.08em;'
        f'text-transform:uppercase">Signal Desk · '
        f'{html.escape(long_date(briefing.date, briefing.language))}</p>',
    ]
    if c.get("stories"):
        parts.append(f'<h1 style="font-size:22px;margin:6px 0 12px">'
                     f'{html.escape(c["stories"][0]["headline"])}</h1>')
    if c.get("overview", {}).get("text"):
        parts.append(_p(c["overview"]["text"], c["overview"]["cites"], "font-size:16px"))

    parts.append(_h(t["holdings"]))
    for h in c.get("holdings", []):
        who = f"{h['name']} ({h['share']})" if h.get("share") else h["name"]
        parts.append(_p(f"{who}: {h['text']}", h["cites"]))
    if c.get("holdings_also"):
        parts.append(_p(f"{t['also']} " + ", ".join(c["holdings_also"]) + ".",
                        style=f"color:{_MUTED}"))
    if not c.get("holdings"):
        parts.append(_p(t["no_holdings"], style=f"color:{_MUTED}"))

    if c.get("stories"):
        parts.append(_h(t["stories"]))
        for i, st in enumerate(c["stories"], 1):
            parts.append(f'<h3 style="font-size:15px;margin:16px 0 6px">{i}. '
                         f'{html.escape(st["headline"])}</h3>')
            for label, key in (("happened", "what_happened"), ("means", "what_it_means"),
                               ("next", "what_next")):
                if st[key]["text"]:
                    parts.append(_p(f"{t[label]}: {st[key]['text']}", st[key]["cites"]))

    if c.get("sectors"):
        parts.append(_h(t["sectors"]))
        arrow = {"up": "↑", "down": "↓", "mixed": "→"}
        for s in c["sectors"]:
            parts.append(_p(f"{arrow.get(s['direction'], '→')} {s['name']}: {s['reason']}",
                            s["cites"]))

    if c.get("ideas"):
        parts.append(_h(t["ideas"]))
        for idea in c["ideas"]:
            parts.append(f'<h3 style="font-size:15px;margin:16px 0 6px">'
                         f'{html.escape(idea["name"])} · {t["confidence"]} '
                         f'{html.escape(t.get(idea["confidence"], idea["confidence"]))}</h3>')
            parts.append(_p(f"{t['why']}: {idea['why_rise']['text']}", idea["why_rise"]["cites"]))
            parts.append(_p(f"{t['risks']}: {idea['risks']['text']}", idea["risks"]["cites"]))

    if c.get("sources"):
        parts.append(_h(t["sources"]))
        parts.append(f'<ol style="padding-left:22px;color:{_MUTED};font-size:13px">')
        for s in c["sources"]:
            parts.append(
                f'<li id="s{s["n"]}" value="{s["n"]}" style="margin-bottom:4px">'
                f'<a href="{html.escape(s["url"], quote=True)}" style="color:{_INK}">'
                f'{html.escape(s["title"])}</a> · {html.escape(s["source"])}</li>'
            )
        parts.append("</ol>")
    if app_url:
        link = html.escape(app_url, quote=True)
        parts.append(f'<p style="margin:18px 0 0">{html.escape(t["open_app"])} '
                     f'<a href="{link}" style="color:{_ACCENT}">Signal Desk</a>.</p>')
    parts.append(f'<p style="margin-top:22px;color:{_MUTED};font-size:12px">'
                 f'{html.escape(t["disclaimer"])}</p></div>')
    return "\n".join(parts)


def build_message(briefing: Briefing, to: str, app_url: str | None) -> Message:
    c = briefing.content or {}
    t = labels(briefing.language)
    lead = c["stories"][0]["headline"] if c.get("stories") else t["briefing"]
    day = short_date(briefing.date, briefing.language)
    return Message(
        to=to,
        subject=f"{t['subject']} {day}: {lead}"[:150],
        text=render_text(briefing) + (f"\n\n{t['open_app_text']} {app_url}\n" if app_url else ""),
        html=render_html(briefing, app_url),
    )


# --- sending -----------------------------------------------------------------------------


def send(message: Message, settings: Settings, client: httpx.Client) -> None:
    if settings.email_provider == "smtp":
        _send_smtp(message, settings)
    else:
        _send_resend(message, settings, client)


def _send_resend(message: Message, settings: Settings, client: httpx.Client) -> None:
    if not settings.resend_api_key:
        raise EmailError("set RESEND_API_KEY (free at resend.com)")
    response = client.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={
            "from": settings.email_from or DEFAULT_FROM,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        },
    )
    if response.status_code >= 400:
        raise EmailError(f"Resend HTTP {response.status_code}: {response.text[:300]}")


def _send_smtp(message: Message, settings: Settings) -> None:
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_password):
        raise EmailError("set SMTP_HOST, SMTP_USER and SMTP_PASSWORD")
    mail = EmailMessage()
    mail["From"] = settings.email_from or settings.smtp_user
    mail["To"] = message.to
    mail["Subject"] = message.subject
    mail.set_content(message.text)
    mail.add_alternative(message.html, subtype="html")
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(mail)
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"SMTP: {type(e).__name__}: {e}") from e


def send_due_briefing(
    session: Session,
    client: httpx.Client,
    topic: TopicConfig,
    settings: Settings,
    *,
    now: dt.datetime | None = None,
    test: bool = False,
) -> str:
    """Email today's briefing if email is on and it hasn't been sent. Returns what happened.

    test=True sends the latest briefing now, whatever the settings and time, and does not
    mark it as sent, so the scheduled email still goes out.
    """
    now = now or dt.datetime.now(dt.UTC)
    prefs = email_settings(session)
    to = prefs.to or settings.email_to
    if not test and not prefs.enabled:
        return "email is off in Settings"
    if not to:
        return "no email address set (Settings, or EMAIL_TO)"
    opts = briefing_options(session, topic)
    local = now.astimezone(ZoneInfo(opts.timezone))
    if not test and local.time() < opts.send_time:
        return "before send time"
    query = select(Briefing).where(Briefing.topic == topic.key)
    if not test:  # a test sends the latest briefing, whatever its language
        query = query.where(Briefing.language == opts.language)
    briefing = session.scalars(query.order_by(Briefing.date.desc(), Briefing.id.desc())).first()
    if briefing is None or (briefing.date != local.date() and not test):
        return "no briefing for today yet"
    if briefing.sent_at is not None and not test:
        return "already sent"
    send(build_message(briefing, to, settings.app_url), settings, client)
    if test:
        return f"test email sent to {to}"
    briefing.status = "sent"
    briefing.sent_at = now
    session.commit()
    return f"sent to {to}"
