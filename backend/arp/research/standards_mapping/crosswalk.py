from __future__ import annotations

import csv
from pathlib import Path

from arp.schemas.standards import StandardCodeMatch


class CrosswalkTable:
    """A deterministic ISIC Rev.4 -> target-standard code lookup, loaded
    from a correspondence CSV (isic_code,target_code,target_label).

    Lookups aren't required to match digit-for-digit: a taxonomy's
    core_isic_codes may be coarser or finer than the table's granularity
    (a 2-digit division vs. a 4-digit class), so a code matches any table
    entry where one is a prefix of the other, in addition to an exact
    match. No fuzzy/semantic matching -- only digit-prefix containment,
    since that's the one relationship ISIC's hierarchical code structure
    actually guarantees.
    """

    def __init__(self, entries: dict[str, list[StandardCodeMatch]]) -> None:
        self._entries = entries

    def __len__(self) -> int:
        return len(self._entries)

    @classmethod
    def empty(cls) -> "CrosswalkTable":
        return cls({})

    def lookup(self, isic_code: str) -> list[StandardCodeMatch]:
        exact = self._entries.get(isic_code)
        if exact:
            return list(exact)
        matches: list[StandardCodeMatch] = []
        seen: set[str] = set()
        for table_code, rows in self._entries.items():
            if table_code.startswith(isic_code) or isic_code.startswith(table_code):
                for row in rows:
                    if row.code not in seen:
                        seen.add(row.code)
                        matches.append(row)
        return matches

    def lookup_many(self, isic_codes: list[str]) -> tuple[list[StandardCodeMatch], list[str]]:
        """Returns (deduped matches across all codes, isic_codes with zero matches)."""
        all_matches: list[StandardCodeMatch] = []
        seen: set[str] = set()
        unmapped: list[str] = []
        for isic_code in isic_codes:
            rows = self.lookup(isic_code)
            if not rows:
                unmapped.append(isic_code)
            for row in rows:
                if row.code not in seen:
                    seen.add(row.code)
                    all_matches.append(row)
        return all_matches, unmapped


def load_crosswalk(path: Path) -> CrosswalkTable:
    entries: dict[str, list[StandardCodeMatch]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            isic_code = row["isic_code"].strip()
            match = StandardCodeMatch(code=row["target_code"].strip(), label=row.get("target_label", "").strip())
            entries.setdefault(isic_code, []).append(match)
    return CrosswalkTable(entries)
