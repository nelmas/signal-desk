import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Canonical form for matching company names: "H&M" == "h & m" == "H and M".

    Accents are stripped so "Industrivärden" matches "Industrivarden".
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold().replace("&", " and ")
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()
