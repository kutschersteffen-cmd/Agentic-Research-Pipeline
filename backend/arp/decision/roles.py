from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from arp.schemas.decision import ColumnProfile, Direction, RoleProposal

_KEYWORDS_PATH = Path(__file__).parent / "data" / "role_keywords.json"

_STOP_TOKENS = {
    "the", "of", "and", "per", "pct", "percent", "score", "flag", "eur", "meur", "usd",
    "total", "share", "rate", "index", "level", "co2e", "tco2e", "0", "1", "2", "3", "5", "100",
}
_UNIT_TOKENS = {
    "pct", "percent", "eur", "meur", "usd", "gbp", "tco2e", "co2e", "per", "bps",
    "mn", "bn", "kt", "mt", "ratio", "idx",
}


@lru_cache(maxsize=1)
def load_keywords() -> dict:
    return json.loads(_KEYWORDS_PATH.read_text())


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def tokens(name: str) -> list[str]:
    return [t for t in slug(name).split("_") if t]


def pretty(name: str) -> str:
    """A column name as a human would write it: unit tokens and bare
    numbers dropped, the rest title-cased."""
    keep = [t for t in tokens(name) if t not in _UNIT_TOKENS and not t.isdigit()]
    return " ".join(t.capitalize() for t in keep) or name


def _keyword_score(name: str, weighted: list[list]) -> tuple[int, list[str]]:
    lowered = name.lower()
    total, hits = 0, []
    for keyword, weight in weighted:
        if keyword in lowered:
            total += int(weight)
            hits.append(keyword)
    return total, hits


def has_keyword(name: str, keywords: list[str]) -> bool:
    """Short keys ("id", "na") must match a whole token or "Validated"
    reads as an identifier; long keys match anywhere in the name."""
    lowered = name.lower()
    toks = tokens(name)
    return any(k in lowered if len(k) >= 4 else k in toks for k in keywords)


def propose_direction(column: str) -> tuple[Direction, str, bool]:
    """Returns (direction, reason, needs_check).

    Direction is the single most valuable guess this layer makes and the
    most dangerous one to get wrong -- it silently inverts a ranking and
    the result looks entirely normal. So an ambiguous match (the name hits
    both dictionaries) or no match at all is flagged for a human rather
    than applied quietly.
    """
    kw = load_keywords()
    high, high_hits = _keyword_score(column, kw["higher"])
    low, low_hits = _keyword_score(column, kw["lower"])
    direction: Direction = "lower" if low > high else "higher"
    if not high and not low:
        return direction, "no directional keyword matched -- defaulted to higher is better, please confirm", True
    mixed = high > 0 and low > 0
    hits = ", ".join(low_hits if direction == "lower" else high_hits)
    reason = f"name matches {hits}"
    if mixed:
        reason += " -- but the name also matches the opposite dictionary, so this is worth checking"
    return direction, reason, mixed


def propose_roles(profiles: dict[str, ColumnProfile], columns: list[str]) -> list[RoleProposal]:
    """Assigns every column a job. Order matters: the first high-cardinality
    text column becomes the label, so an entity has a name before anything
    else competes for it."""
    kw = load_keywords()
    proposals: list[RoleProposal] = []
    label_taken = False

    for column in columns:
        p = profiles[column]
        if not label_taken and p.type in ("identifier", "text") and not has_keyword(column, kw["identifier"]):
            role, reason = "label", "first high-cardinality text column -- used to name each row"
            label_taken = True
        elif has_keyword(column, kw["identifier"]) or p.type == "identifier":
            role, reason = "reference", "looks like an identifier -- carried through, never scored"
        elif has_keyword(column, kw["size"]) and p.type == "numeric":
            role, reason = "size", "name signals position size, not quality -- used for leverage, not for the score"
        elif p.type == "boolean" and has_keyword(column, kw["gate"]):
            role, reason = "gate", "binary flag with exclusion-type wording"
        elif p.type in ("numeric", "ordinal", "boolean"):
            if not p.spread:
                role, reason = "excluded", "a single value across all rows -- no discriminating power"
            elif p.coverage < 0.25:
                role, reason = "excluded", f"coverage {p.coverage:.0%}, below the 25% floor"
            else:
                role, reason = "criterion", f"{p.type} indicator with spread"
        elif p.type == "categorical":
            role, reason = "segment", f"{p.unique} levels -- usable as a grouping or a peer cohort"
        else:
            role, reason = "excluded", "free text -- nothing orderable in it"

        direction, direction_reason, needs_check = propose_direction(column)
        proposals.append(
            RoleProposal(
                column=column,
                role=role,
                role_reason=reason,
                direction=direction,
                direction_reason=direction_reason,
                needs_check=needs_check and role == "criterion",
            )
        )
    return proposals


def propose_cohort_column(profiles: dict[str, ColumnProfile], proposals: list[RoleProposal], row_count: int, min_cohort: int) -> tuple[str | None, str]:
    """Picks the column whose levels make the most plausible peer cohorts.

    Scoring an emissions intensity across utilities and software companies
    in one percentile ranking is close to meaningless, so a sector-like
    column is preferred over any other categorical -- but only when its
    levels are big enough for a within-cohort rank to mean something.
    """
    kw = load_keywords()
    segments = [p.column for p in proposals if p.role == "segment"]
    if not segments:
        return None, "no categorical column with usable levels -- normalising across the whole table"

    def viable(column: str) -> bool:
        p = profiles[column]
        return p.unique >= 2 and (row_count / max(1, p.unique)) >= min_cohort

    named = [c for c in segments if has_keyword(c, kw["cohort"])]
    for candidate in named + segments:
        if viable(candidate):
            why = "name signals a peer grouping" if candidate in named else "the only categorical with large enough levels"
            return candidate, f"{why}; {profiles[candidate].unique} cohorts over {row_count} rows"
    return None, (
        f"every categorical column splits {row_count} rows into cohorts below the {min_cohort}-row floor -- "
        "a percentile rank over three peers is noise dressed as a score, so normalisation stays whole-table"
    )
