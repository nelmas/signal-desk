"""Fingerprints for spotting the same article twice."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.names import normalize_name

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "cmpid", "ncid"}


def canonical_url(url: str) -> str:
    """Same page, same string: lowercase host, no fragment, no tracking parameters."""
    parts = urlsplit(url.strip())
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def content_hash(title: str, summary: str | None) -> str:
    """Catches one story syndicated under several URLs.

    The start of the summary is included because titles alone collide: every
    company on MFN publishes an "Interim report January-September".
    """
    text = normalize_name(title) + "|" + normalize_name((summary or "")[:300])
    return hashlib.sha256(text.encode()).hexdigest()
