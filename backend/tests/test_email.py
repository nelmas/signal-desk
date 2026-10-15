import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.email import build_message, render_html, send_due_briefing
from app.models import Briefing, Setting
from app.sync import sync_topic
from app.topic import load_companies, load_topic_from

STOCKS_DIR = Path(__file__).resolve().parent.parent / "topics" / "stocks"
TOPIC = load_topic_from(STOCKS_DIR)
SETTINGS = Settings(resend_api_key="re_test", app_url="https://desk.example")
MORNING = dt.datetime(2026, 10, 15, 6, 0, tzinfo=dt.UTC)  # 08:00 Stockholm, after 07:00

CONTENT = {
    "disclaimer": "Ideas to research, not buy or sell advice.",
    "overview": {"text": "Volvo won a record order <b>today</b>.", "cites": [1]},
    "holdings": [{"company": "nvidia", "name": "NVIDIA", "share": "5.7% of your fund",
                  "text": "Nvidia raised its buyback.", "cites": [2]}],
    "holdings_also": ["Apple"],
    "stories": [{"headline": "Volvo's record order", "company": "volvo", "name": "AB Volvo",
                 "event_type": "contract",
                 "what_happened": {"text": "Volvo won.", "cites": [1]},
                 "what_it_means": {"text": "", "cites": []},
                 "what_next": {"text": "Watch the Q3 report.", "cites": [1]}}],
    "sectors": [], "ideas": [],
    "sources": [{"n": 1, "article_id": 10, "title": "Volvo order", "url": "https://mfn.se/a?x=1&y=2",
                 "source": "MFN", "published_at": "2026-10-15T05:00:00+00:00"},
                {"n": 2, "article_id": 11, "title": "Nvidia buyback", "url": "https://x/2",
                 "source": "Yahoo", "published_at": "2026-10-14T12:00:00+00:00"}],
}


@pytest.fixture
def db(session: Session) -> Session:
    sync_topic(session, TOPIC, load_companies(TOPIC, STOCKS_DIR))
    return session


def briefing(db: Session, day: dt.date = dt.date(2026, 10, 15)) -> Briefing:
    b = Briefing(topic="stocks", date=day, language="en", status="ready", content=CONTENT)
    db.add(b)
    db.commit()
    return b


def email_on(db: Session, to: str = "me@example.com", enabled: bool = True) -> None:
    db.add(Setting(key="email", value={"enabled": enabled, "to": to}))
    db.commit()


class FakeResend:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.sent: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append({"auth": request.headers["Authorization"], **json.loads(request.content)})
        return httpx.Response(self.status, json={"id": "abc"})


def run(db: Session, fake: FakeResend, now=MORNING, **kw) -> str:
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        return send_due_briefing(db, client, TOPIC, SETTINGS, now=now, **kw)


def test_html_escapes_text_and_links_every_source(db: Session) -> None:
    html = render_html(briefing(db), "https://desk.example")
    assert "&lt;b&gt;today&lt;/b&gt;" in html  # article-derived text can't inject markup
    assert 'href="https://mfn.se/a?x=1&amp;y=2"' in html
    assert 'href="#s1"' in html and 'id="s1"' in html and 'id="s2"' in html
    assert "NVIDIA (5.7% of your fund)" in html and "Also in the news: Apple." in html
    assert "What it means" not in html  # empty parts are left out
    assert 'href="https://desk.example"' in html


def test_subject_names_the_lead_story(db: Session) -> None:
    msg = build_message(briefing(db), "me@example.com", None)
    assert msg.subject == "Signal Desk 15 Oct: Volvo's record order"
    assert "SOURCES" in msg.text


def test_sends_once_after_send_time_and_marks_sent(db: Session) -> None:
    b = briefing(db)
    email_on(db)
    fake = FakeResend()
    early = dt.datetime(2026, 10, 15, 4, 0, tzinfo=dt.UTC)  # 06:00 Stockholm
    assert run(db, fake, now=early) == "before send time"
    assert run(db, fake) == "sent to me@example.com"
    assert run(db, fake) == "already sent"
    assert len(fake.sent) == 1
    sent = fake.sent[0]
    assert sent["to"] == ["me@example.com"] and sent["auth"] == "Bearer re_test"
    assert sent["from"] == "Signal Desk <onboarding@resend.dev>"
    db.refresh(b)
    assert b.status == "sent" and b.sent_at == MORNING


def test_nothing_is_sent_when_email_is_off_or_briefing_missing(db: Session) -> None:
    fake = FakeResend()
    assert run(db, fake) == "email is off in Settings"
    email_on(db)
    assert run(db, fake) == "no briefing for today yet"
    briefing(db, day=dt.date(2026, 10, 14))  # yesterday's doesn't count
    assert run(db, fake) == "no briefing for today yet"
    assert fake.sent == []


def test_failed_send_is_retried_next_run(db: Session) -> None:
    b = briefing(db)
    email_on(db)
    from app.email import EmailError

    with pytest.raises(EmailError, match="Resend HTTP 403"):
        run(db, FakeResend(status=403))
    db.refresh(b)
    assert b.sent_at is None
    assert run(db, FakeResend()) == "sent to me@example.com"


def test_test_email_ignores_settings_and_does_not_count_as_sent(db: Session) -> None:
    b = briefing(db)
    email_on(db, enabled=False)
    fake = FakeResend()
    early = dt.datetime(2026, 10, 15, 4, 0, tzinfo=dt.UTC)
    assert run(db, fake, now=early, test=True) == "test email sent to me@example.com"
    db.refresh(b)
    assert b.sent_at is None and len(fake.sent) == 1
