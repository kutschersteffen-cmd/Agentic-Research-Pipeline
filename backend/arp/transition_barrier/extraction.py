"""Phase 3: one rule-book fact from one stored source document through `extract_one_field`, then the code checks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from arp.checks.numeric import candidates
from arp.extraction.field_graph import extract_one_field
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDataType, FieldDefinition, ValueState
from arp.transition_barrier.dataset import data_dir
from arp.transition_barrier.facts import FactRefused, _parse_value
from arp.transition_barrier.render import _with_unit
from arp.transition_barrier.rule_book import FactDef
from arp.transition_barrier.units import convert

PROMPT_VERSION = "tb-extract-3"
AS_OF_RULE = "Give the as-of date of the value in period_text when the source states one."
_TYPES = {
    "number": FieldDataType.NUMBER, "boolean": FieldDataType.BOOLEAN,
    "enum": FieldDataType.ENUM, "date": FieldDataType.DATE,
}


@dataclass
class Answer:
    """The model's answer as grounded, stored as given: the code checks run on it each time it is read."""

    value: object  # as the source states it
    unit: str | None  # the source's unit text
    quote: str
    grounded: bool  # the quote was found in a passage the model was shown
    page: int | None
    locator: str | None
    as_of: date | None  # the value's own as-of date


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
        seed_keywords=seed_keywords(fact, cell.rsplit(", ", 1)[-1]),  # the cell ends with its criterion code
    )


@lru_cache
def _fact_keywords(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def seed_keywords(fact: FactDef, code: str) -> list[str]:
    """The curated retrieval keywords of `data/fact_keywords.json` (kept out of the signed rule book), as Argus
    fields carry them; the label's words (R7) for a fact without any."""
    curated = _fact_keywords(data_dir() / "fact_keywords.json").get(code, {}).get(fact.id)
    return curated or [w.lower() for w in re.findall(r"[A-Za-z]{4,}", fact.label)]


def fingerprint(fact: FactDef, code: str) -> str:
    """Changes when the fact, its retrieval keywords or the prompt change, so a stored extraction is redone (R3)."""
    text = fact.model_dump_json() + json.dumps(seed_keywords(fact, code)) + PROMPT_VERSION
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def answer(row: ExtractedField) -> Answer | None:
    """The stored part of the model's answer; None for its not-found answer."""
    if row.value_state in (ValueState.NOT_FOUND, ValueState.NOT_APPLICABLE):
        return None
    cite = next((c for c in row.citations if c.grounded), None) if row.grounded else None
    return Answer(
        value=row.value, unit=row.unit, quote=cite.quote if cite else (row.citations[0].quote if row.citations else ""),
        grounded=cite is not None, page=cite.page if cite else None, locator=cite.location if cite else None,
        as_of=date.fromisoformat(row.period_end) if row.period_end else None,
    )


def _typed(fact: FactDef, value):
    """The value as its fact type has it (a Yes/No/true/false text a bool, an ISO date a date), or None."""
    if fact.type == "number":
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        return value if numeric and math.isfinite(value) else None
    if isinstance(value, bool):
        return value if fact.type == "boolean" else None
    if fact.type == "boolean":
        value = {"true": "yes", "false": "no"}.get(str(value).strip().lower(), str(value))
    try:
        return _parse_value(fact, str(value))  # the analyst form's rules
    except FactRefused:
        return None


def check(fact: FactDef, a: Answer, tier: str, doc_as_of: date, conversions: list[dict]) -> Extraction:
    """The spec's checks in order (quote, type, number, unit, tier) with the current conversions and the source's
    current tier; the first that fails is the reason."""
    raw, unit = a.value, a.unit
    value, extracted, reason = _typed(fact, raw), None, None
    if not a.grounded:
        reason = "Quote not found in source"
    elif value is None:
        reason = f"Value not allowed: {raw}" if fact.type == "enum" else f"Value is not a {fact.type}"
    elif fact.type == "number" and raw not in candidates(a.quote):
        reason = "Number not in quote"
    elif fact.type == "number" and fact.unit:
        converted, reason = convert(raw, unit or "", fact.unit, (a.as_of or doc_as_of).year, conversions)
        if reason is None and unit != fact.unit:
            value, unit, extracted = converted, fact.unit, _with_unit(raw, a.unit)
    if reason is None and tier == "news":
        reason = "News cannot ground a fact"
    if reason:
        value, unit, extracted = raw, a.unit, None
    return Extraction(
        value=value, unit=unit, extracted=extracted, quote=a.quote, page=a.page, locator=a.locator, as_of=a.as_of,
        counted=reason is None, reason=reason,
    )


async def find(
    fact: FactDef, cell: str, doc: dict, conversions: list[dict], *, llm, verifier_llm, settings
) -> Answer | None:
    """One model call through `extract_one_field`, with its quote grounded in the passages shown."""
    sd = source_document(doc)
    rows, _, _ = await extract_one_field(
        cell, field_for(fact, cell, conversions), documents=[sd], documents_by_id={sd.doc_id: sd}, llm=llm,
        verifier_llm=verifier_llm, fuzzy_threshold=settings.grounding_fuzzy_threshold,
        # owner decision: keyword-only BM25, like Transition Plan Assessment (oracle coverage on G: 0.72 vs hybrid 0.60)
        settings=settings.model_copy(update={"hybrid_retrieval_enabled": False}),
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    return answer(rows[0])


async def extract(
    fact: FactDef, cell: str, doc: dict, conversions: list[dict], *, llm, verifier_llm, settings
) -> Extraction | None:
    """`find`, then `check` with the document's own tier: the value as a derivation would read it back."""
    got = await find(fact, cell, doc, conversions, llm=llm, verifier_llm=verifier_llm, settings=settings)
    return None if got is None else check(fact, got, doc["tier"], doc["as_of"], conversions)
