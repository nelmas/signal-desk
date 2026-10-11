"""Article tagging: companies (checked against the ticker list), event type, tone, summary."""

from app.tagging.tagger import TagReport, tag_pending

__all__ = ["TagReport", "tag_pending"]
