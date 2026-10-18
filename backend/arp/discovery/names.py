"""Company-name matching shared by the site check and the document check."""

from __future__ import annotations

import re
import unicodedata

from cleanco import basename
from rapidfuzz import fuzz

NAME_MATCH_THRESHOLD = 90
_SHORT_NAME_LEN = 3  # fuzzy ratios are meaningless this short ("AB Foods" vs "ABB"), so require equality


def clean_name(name: str) -> str:
    """Legal suffix dropped, accents folded, lowercased, punctuation collapsed to single spaces."""
    folded = unicodedata.normalize("NFKD", basename(name))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"\W+", " ", folded.lower()).strip()


def names_match(a: str, b: str) -> bool:
    ca, cb = clean_name(a), clean_name(b)
    if not ca or not cb:  # a blank name must never match
        return False
    if len(ca) <= _SHORT_NAME_LEN or len(cb) <= _SHORT_NAME_LEN:
        return ca == cb
    return fuzz.token_set_ratio(ca, cb) >= NAME_MATCH_THRESHOLD
