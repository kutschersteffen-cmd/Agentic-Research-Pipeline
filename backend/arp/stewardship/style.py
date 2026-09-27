"""E8 style check: a deterministic phrase matcher run on client-facing and
outreach text before the checkpoint. It flags, it never rewrites or removes.

The blocklist is a versioned house policy (`phrase_blocklist`), so changing it
follows the same save / four-eyes activate path as the rule graphs.
"""

from __future__ import annotations

import json
import re

from arp.stewardship.policy_review import DATA

CATEGORIES = {"overclaiming", "unsupported_claim", "regulated_term", "legal_risk", "other"}


def load_blocklist() -> dict:
    return json.loads((DATA / "style_blocklist.json").read_text())


def validate_blocklist(blocklist: dict, _sample: dict | None = None) -> None:
    phrases = blocklist.get("phrases") if isinstance(blocklist, dict) else None
    if not isinstance(phrases, list) or not phrases:
        raise ValueError("A blocklist needs a non-empty list of phrases")
    seen = set()
    for p in phrases:
        phrase = (p.get("phrase") or "").strip() if isinstance(p, dict) else ""
        if not phrase:
            raise ValueError("Every blocklist entry needs a phrase")
        if phrase.lower() in seen:
            raise ValueError(f"Duplicate phrase: {phrase}")
        seen.add(phrase.lower())
        if p.get("category") not in CATEGORIES:
            raise ValueError(f"Unknown category for '{phrase}': {p.get('category')} (one of {sorted(CATEGORIES)})")


def _pattern(phrase: str) -> re.Pattern:
    # whole words, any run of spaces or hyphens between them, case-insensitive
    words = [re.escape(w) for w in re.split(r"[\s-]+", phrase.strip())]
    return re.compile(r"(?<!\w)" + r"[\s-]+".join(words) + r"(?!\w)", re.IGNORECASE)


def check(text: str, blocklist: dict) -> list[dict]:
    """Every blocklisted phrase in `text`, with where it is (line, offsets) and
    the surrounding words, in reading order."""
    flags = []
    for entry in blocklist["phrases"]:
        for m in _pattern(entry["phrase"]).finditer(text):
            flags.append(
                {
                    "phrase": entry["phrase"],
                    "match": m.group(0),
                    "category": entry["category"],
                    "suggestion": entry.get("suggestion", ""),
                    "start": m.start(),
                    "end": m.end(),
                    "line": text.count("\n", 0, m.start()) + 1,
                    "context": text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " "),
                }
            )
    return sorted(flags, key=lambda f: f["start"])
