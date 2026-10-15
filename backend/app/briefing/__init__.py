"""The morning briefing: stories from tagged articles, written by the AI, checked by code."""

from app.briefing.generate import generate_briefing, is_due
from app.briefing.render import render_text

__all__ = ["generate_briefing", "is_due", "render_text"]
