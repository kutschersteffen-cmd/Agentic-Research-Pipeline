"""Phase 3: one rule-book fact from one stored source document through `extract_one_field`, then the code checks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from arp.checks.numeric import candidates
from arp.extraction.field_graph import extract_one_field
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDataType, FieldDefinition, ValueState
from arp.transition_barrier.render import _with_unit
from arp.transition_barrier.rule_book import FactDef
from arp.transition_barrier.units import convert

PROMPT_VERSION = "tb-extract-2"
# Passages one fact sees. Barrier sources are long law texts (50-130 pages, up to ~110 chunks) where the operative
# article often ranks 20th-45th; the default 12 left half of golden set G unreachable even for a perfect model.
EVIDENCE_CHUNKS = 45
AS_OF_RULE = "Give the as-of date of the value in period_text when the source states one."
# function words of 4+ letters that the fact definitions use; they carry no search signal
_STOPWORDS = {
    "also", "been", "does", "each", "from", "have", "into", "less", "more", "most", "only", "other", "over", "same",
    "such", "than", "that", "their", "them", "then", "there", "these", "they", "this", "those", "under", "were",
    "what", "when", "where", "which", "while", "will", "with", "within", "without",
}
_TYPES = {
    "number": FieldDataType.NUMBER, "boolean": FieldDataType.BOOLEAN,
    "enum": FieldDataType.ENUM, "date": FieldDataType.DATE,
}


@dataclass
class Extraction:
    value: object  # in the rule book's unit when counted, else as the source states it
    unit: str | None
    extracted: str | None  # the source-unit figure shown, when converted
    quote: str
    page: int | None
    locator: str | None
    as_of: date | None  # the value's own as-of date
    counted: bool
    reason: str | None


def field_for(fact: FactDef, cell: str, conversions: list[dict]) -> FieldDefinition:
    instructions = [fact.definition]
    num, slash, per = (fact.unit or "").partition("/")
    # R6: each side of the fact unit that a conversion row targets may come in that row's `from` unit
    froms = [r["from"] for r in conversions if r["to"] == num] + [r["from"] for r in conversions if slash and r["to"] == per]
    examples = [r["from"] + slash + per for r in conversions if r["to"] == num]
    examples += [num + slash + r["from"] for r in conversions if slash and r["to"] == per]
    if froms:
        instructions.append(
            f"Give unit_text in the source's own unit, written like {fact.unit}; code converts "
            f"{', '.join(dict.fromkeys(froms))} (for example {', '.join(list(dict.fromkeys(examples))[:3])})."
        )
    elif fact.unit:
        instructions.append(f"Give unit_text as {fact.unit} when the source uses that unit.")
    instructions.append(AS_OF_RULE)
    return FieldDefinition(
        field_id=fact.id,
        name=fact.id,
        description=f"{fact.label} ({cell})",
        data_type=_TYPES[fact.type],
        extraction_instructions=" ".join(i for i in instructions if i),
        allowed_values=fact.allowed_values,
        seed_keywords=seed_keywords(fact),
    )


def seed_keywords(fact: FactDef) -> list[str]:
    """R7: the label's words, then the definition's content words, lower-case and each once. Law texts word a fact
    the way its definition does ("minimum shares", "surrender allowances"), rarely the way its label does."""
    words = re.findall(r"[A-Za-z]{4,}", f"{fact.label} {fact.definition}")
    return list(dict.fromkeys(w.lower() for w in words if w.lower() not in _STOPWORDS))


def fingerprint(fact: FactDef) -> str:
    return hashlib.sha256((fact.model_dump_json() + PROMPT_VERSION).encode("utf-8")).hexdigest()


def source_document(doc: dict) -> SourceDocument:
    pages = doc["page_texts"]
    starts, offset = [], 0
    for p in pages:
        starts.append(offset)
        offset += len(p) + 1  # the "\n" join
    return SourceDocument(
        doc_id=f"tbsrc_{doc['id']}", company_id="transition_barrier", doc_type=DocType.OTHER, title=doc["title"],
        source_url=doc.get("url"), full_text="\n".join(pages), content_key=doc.get("content_key"),
        page_breaks=[] if doc["html"] else starts,
    )


def check(fact: FactDef, row: ExtractedField, doc: dict, conversions: list[dict]) -> Extraction | None:
    """The spec's checks in order (quote, number, unit, tier); the first that fails is the reason."""
    if row.value_state in (ValueState.NOT_FOUND, ValueState.NOT_APPLICABLE):
        return None
    cite = next((c for c in row.citations if c.grounded), None) if row.grounded else None
    quote = cite.quote if cite else (row.citations[0].quote if row.citations else "")
    as_of = date.fromisoformat(row.period_end) if row.period_end else None
    raw, unit = row.value, row.unit
    value, extracted, reason = raw, None, None
    numeric = isinstance(raw, (int, float)) and not isinstance(raw, bool)
    if cite is None:
        reason = "Quote not found in source"
    elif fact.type == "number" and not (numeric and raw in candidates(quote)):
        reason = "Number not in quote"
    elif fact.type == "number" and fact.unit:
        converted, reason = convert(raw, unit or "", fact.unit, (as_of or doc["as_of"]).year, conversions)
        if reason is None and unit != fact.unit:
            value, unit, extracted = converted, fact.unit, _with_unit(raw, row.unit)
    if reason is None and doc["tier"] == "news":
        reason = "News cannot ground a fact"
    if reason:
        value, unit, extracted = raw, row.unit, None
    return Extraction(
        value=value, unit=unit, extracted=extracted, quote=quote, page=cite.page if cite else None,
        locator=cite.location if cite else None, as_of=as_of, counted=reason is None, reason=reason,
    )


async def extract(
    fact: FactDef, cell: str, doc: dict, conversions: list[dict], *, llm, verifier_llm, settings
) -> Extraction | None:
    sd = source_document(doc)
    rows, _, _ = await extract_one_field(
        cell, field_for(fact, cell, conversions), documents=[sd], documents_by_id={sd.doc_id: sd}, llm=llm,
        verifier_llm=verifier_llm, fuzzy_threshold=settings.grounding_fuzzy_threshold,
        settings=settings.model_copy(update={"evidence_max_chunks": max(settings.evidence_max_chunks, EVIDENCE_CHUNKS)}),
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    return check(fact, rows[0], doc, conversions)
