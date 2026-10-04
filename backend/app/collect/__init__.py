"""News collection: fetch every enabled source, drop duplicates, store articles.

Runs hourly (GitHub Actions). Only headline, a short excerpt and the link are
kept; the full text stays with the source.
"""

from app.collect.run import SourceResult, collect, prune_untagged

__all__ = ["SourceResult", "collect", "prune_untagged"]
