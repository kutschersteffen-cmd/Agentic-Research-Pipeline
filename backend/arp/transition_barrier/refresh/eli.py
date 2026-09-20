from __future__ import annotations

import re
from dataclasses import dataclass

# EUR-Lex ELI URIs are the reason legal_regulatory_text is the first source
# category to automate: they are stable identifiers that survive amendment, so
# "has this regulation changed?" is answerable without scraping prose.
#
#   https://eur-lex.europa.eu/eli/reg/2023/956/oj/eng
#   https://eur-lex.europa.eu/eli/reg/2023/1804/2026-01-08/eng
#                              ^typ ^year ^num ^point-in-time
_ELI_RE = re.compile(
    r"/eli/(?P<typ>[a-z_]+)/(?P<year>\d{4})/(?P<number>\d+)"
    r"(?:/(?P<point_in_time>\d{4}-\d{2}-\d{2}|oj))?"
    r"(?:/(?P<language>[a-z]{3}))?"
)

# Not every EUR-Lex link in the registry is an ELI URI -- FuelEU Maritime is
# recorded as a legal-content CELEX link. A CELEX number encodes the same act:
#   3 2023 R 1805  ->  sector 3, year 2023, descriptor R (regulation), number
# so it maps onto the same EliRef rather than being written off as manual.
_CELEX_RE = re.compile(r"CELEX(?:%3A|:)3(?P<year>\d{4})(?P<descriptor>[A-Z])(?P<number>\d+)", re.I)

_CELEX_DESCRIPTOR_TO_TYP = {"R": "reg", "L": "dir", "D": "dec"}


@dataclass(frozen=True)
class EliRef:
    """A parsed ELI reference. `point_in_time` is either a consolidation date,
    the literal "oj" (the original Official Journal act), or None.
    """

    typ: str
    year: int
    number: int
    point_in_time: str | None
    language: str | None

    @property
    def celex_like(self) -> str:
        """A stable comparison key for 'same act, possibly different version'.
        Deliberately excludes point_in_time and language.
        """
        return f"{self.typ}/{self.year}/{self.number}"

    @property
    def is_consolidated(self) -> bool:
        return self.point_in_time is not None and self.point_in_time != "oj"


def parse_eli(url: str) -> EliRef | None:
    """Parse a EUR-Lex act reference from either an ELI URI or a CELEX link.

    Returns None for any URL that is neither -- the router uses that to decide
    a source cannot be automated yet, rather than guessing at a scrape.
    """
    url = url or ""
    if (match := _ELI_RE.search(url)) is not None:
        return EliRef(
            typ=match.group("typ"),
            year=int(match.group("year")),
            number=int(match.group("number")),
            point_in_time=match.group("point_in_time"),
            language=match.group("language"),
        )
    if (match := _CELEX_RE.search(url)) is not None:
        typ = _CELEX_DESCRIPTOR_TO_TYP.get(match.group("descriptor").upper())
        if typ is None:
            return None
        return EliRef(
            typ=typ,
            year=int(match.group("year")),
            number=int(match.group("number")),
            point_in_time=None,
            language=None,
        )
    return None
