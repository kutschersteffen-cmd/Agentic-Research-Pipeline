from __future__ import annotations

import re

from arp.schemas.common import CompanyRef, MatchStatus, SourceDocument
from arp.schemas.issuer import lei_is_valid, normalise_lei
from arp.storage.identifier_map import IdentifierMapStore

LEGAL_SUFFIXES = (
    "plc", "inc", "ltd", "limited", "llc", "gmbh", "ag", "se", "sa", "nv", "bv",
    "corp", "corporation", "spa", "ab", "asa", "oyj",
)
NOISE_WORDS = ("group", "holdings", "holding", "the", "company", "co")

TITLE_STOP_WORDS = (
    "report", "annual", "esg", "sustainability", "integrated", "independent", "assurance", "climate",
    "impact", "responsibility", "corporate", "financial", "statements", "statement", "review", "form",
    "and", "of", "the", "for",
)

_LEI_RE = re.compile(r"\b[A-Za-z0-9]{20}\b")


def _words(s: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", s.lower()).split()


def normalise_entity_name(name: str) -> str:
    words = _words(name)
    while words and words[-1] in LEGAL_SUFFIXES + NOISE_WORDS:
        words.pop()
    return " ".join(words)


def find_leis(text: str) -> list[str]:
    found: list[str] = []
    for m in _LEI_RE.findall(text[:5000]):
        lei = normalise_lei(m)
        if lei_is_valid(lei) and lei not in found:
            found.append(lei)
    return found


def legal_name(text: str) -> str | None:
    """First run of up to 6 capitalised words ending in a legal suffix."""
    words = text.split()
    for i, w in enumerate(words):
        if w.strip(".,;:()").lower() not in LEGAL_SUFFIXES:
            continue
        start = i
        while start > 0 and i - start < 5:
            prev = words[start - 1]
            if not prev[:1].isupper() or prev.lower() in TITLE_STOP_WORDS or any(c.isdigit() for c in prev):
                break
            start -= 1
        if start < i:
            return " ".join(words[start : i + 1]).strip(".,;:()")
    return None


def _same_name(found: str, want: str) -> bool:
    got = normalise_entity_name(found)
    return got == want or want.endswith(" " + got)


def _issuer_lei(company: CompanyRef, idmap: IdentifierMapStore | None) -> str | None:
    lei = normalise_lei(company.lei or "")
    if lei_is_valid(lei):
        return lei
    if idmap is None:
        return None
    for scheme, value in (("CIK", company.cik), ("ISIN", company.isin)):
        keys = idmap.resolve(scheme, value) if value else []
        if len(keys) == 1 and lei_is_valid(keys[0]):
            return keys[0]
    return None


def confirm_entity(
    doc: SourceDocument, company: CompanyRef, idmap: IdentifierMapStore | None = None
) -> SourceDocument:
    def done(status: MatchStatus, covered: str | None) -> SourceDocument:
        return doc.model_copy(update={"covered_entity": covered, "match_status": status})

    want = normalise_entity_name(company.name)

    if company.cik and company.cik.strip().isdigit() and f"/data/{int(company.cik)}/" in (doc.source_url or ""):
        return done(MatchStatus.CONFIRMED, company.name)

    lei = _issuer_lei(company, idmap)
    if lei:
        leis = find_leis(f"{doc.title}\n{doc.full_text}")
        if lei in leis:
            return done(MatchStatus.CONFIRMED, company.name)
        if leis:
            return done(MatchStatus.MISMATCH, leis[0])

    name = legal_name(doc.title)
    if name:
        same = _same_name(name, want)
        return done(MatchStatus.CONFIRMED if same else MatchStatus.MISMATCH, name)

    name = legal_name(doc.full_text[:2000])
    if name:
        same = _same_name(name, want)
        return done(MatchStatus.CONFIRMED if same else MatchStatus.AMBIGUOUS, name)
    return done(MatchStatus.AMBIGUOUS, None)
