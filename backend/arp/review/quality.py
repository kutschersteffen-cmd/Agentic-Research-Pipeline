"""Reviewer quality loop (E56): known-answer items seeded into the queue, per-reviewer agreement
and overturn rates, and gold cases grown from corrections a second reviewer confirmed.

Which items are known answers lives only in `settings.review_quality_dir/known.jsonl`; the seeded
run itself is an ordinary trial extraction run, so a reviewer cannot tell the items apart."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import takewhile
from pathlib import Path

from arp.checks.numeric import candidates, parse_number
from arp.checks.runner import CheckContext, check_record
from arp.config import Settings
from arp.extraction import extractor_agent, verifier_agent
from arp.extraction.aggregator import build_extracted_fields
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import (
    ExtractionRecordResult,
    create_extraction_run,
    input_settings,
    load_run_schema,
    review_items,
)
from arp.extraction.routing import route
from arp.extraction.verifier_agent import VerifierOutput
from arp.golden_set.runner import load_cases
from arp.golden_set.schema import GoldenSetCase
from arp.ingestion.local_files import parser_version
from arp.llm.base import LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.review_queue import FINAL_STATES, _kind, _value, agrees, item_states, same_value
from arp.planning.doc_routing import input_hash, route_documents
from arp.planning.periods import plan_periods, union_planned
from arp.retrieval.content_store_factory import content_store_for
from arp.review.items import REVIEWABLE_RUN_TYPES, cosign_rule
from arp.schemas.common import Citation, CompanyRef, DocType, ProvenanceInfo, SourceDocument, new_id
from arp.schemas.datapoints import DataPointSchema, ExtractionRecord, FieldDefinition
from arp.schemas.issuer import issuer_key
from arp.schemas.review import field_item_key, period_key
from arp.storage.atomic_io import atomic_write_text
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.locks import KeyedLock
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry

logger = logging.getLogger(__name__)
KNOWN = "known.jsonl"
GOLD = "extraction_cases.json"
_LOCKS = KeyedLock(lock_path=lambda d: Path(d) / ".lock")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class ReviewerStat:
    name: str
    decisions: int
    agreement_rate: float
    overturn_rate: float
    known_answer_items: int
    known_answer_accuracy: float


def _digits(v: float) -> str:
    return f"{abs(v):.10g}".replace(".", "").strip("0")


def _evidence(text: str, value) -> tuple[str | None, str | None, str | None]:
    """(quote, raw value text, period text) of the first sentence that states `value` at any scale."""
    for sentence in (s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text)):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            raw = next((m.group() for m in _NUMBER.finditer(sentence)
                        if (n := parse_number(m.group())) is not None and _digits(n) == _digits(value)), None)
        else:
            raw = str(value) if isinstance(value, str) and value.lower() in sentence.lower() else None
        if raw:
            period = re.search(r"(?:fiscal(?: year)? |FY ?)?20\d\d", sentence)
            return sentence, raw, period.group() if period else None
    return None, None, None


def _perturb(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return round(value * 10, 6) if value else 1  # a scale slip, the commonest wrong extraction; 0 * 10 is still 0
    return None  # a text value: claim "not disclosed"


def _cases(settings: Settings) -> list[GoldenSetCase]:
    grown = settings.review_quality_dir / GOLD
    return load_cases() + (load_cases(grown) if grown.exists() else [])


def _prompt_version(system: str) -> str:
    return hashlib.sha256(system.encode()).hexdigest()[:12]  # as the model client stamps it


async def _record(
    company: CompanyRef, case: GoldenSetCase, value, schema: DataPointSchema, spec: FieldDefinition,
    settings: Settings, rng: random.Random,
) -> ExtractionRecord:
    """One company's record, built by the real aggregate -> checks -> routing steps from a fixed draft."""
    text = case.document_text
    content_key = hashlib.sha256(text.encode()).hexdigest()
    content_store_for(settings).store(
        content_key, key_kind="file", parser_version=parser_version(), source_suffix=".txt",
        byte_size=len(text.encode()), text=text, page_breaks=[],
    )
    doc = SourceDocument(
        company_id=company.company_id, doc_type=case.doc_type, title=f"{company.name} {case.doc_type.value}",
        full_text=text, content_key=content_key, parser_version=parser_version(),
    )
    doc.period_plan = plan_periods(doc, fiscal_year_end=None, recorded=set())
    planned = union_planned([doc])
    quote, raw, period = _evidence(text, case.expected_value)
    values = [] if value is None else [PeriodValue(
        value=value, raw_value_text=raw, unit_text=spec.unit, period_text=period,
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)] if quote else [],
    )]
    draft = ExtractionDraft(values=values, confidence=round(rng.uniform(0.6, 0.88), 2))
    verifier = VerifierOutput(agrees=True, confidence=round(rng.uniform(0.6, 0.88), 2), notes="The cited text supports the value.")
    fields = build_extracted_fields(
        spec, draft, verifier, {doc.doc_id: doc}, settings.grounding_fuzzy_threshold,
        settings.confidence_review_threshold, planned_periods=planned,
    )
    provenance = ProvenanceInfo(
        provider="anthropic", extractor_model=settings.llm_model,
        extractor_prompt_version=_prompt_version(extractor_agent._SYSTEM_PROMPT),
        # a high-risk field is blind-verified: the verifier client runs the extractor's prompt (field_graph._verify)
        verifier_model=settings.llm_verifier_model,
        verifier_prompt_version=_prompt_version((extractor_agent if spec.high_risk else verifier_agent)._SYSTEM_PROMPT),
        schema_version=f"{schema.schema_id}:v{schema.version}", field_version=spec.version,
    )
    h = input_hash(spec, route_documents(spec, [doc]), planned, input_settings(settings))
    fields = [f.model_copy(update={"provenance": provenance, "input_hash": h}) for f in fields]
    key, scheme = issuer_key(company, IdentifierMapStore(settings.identifier_map_path))
    fields = await check_record(schema, fields, CheckContext(
        company=company, issuer_key=key, schema=schema, documents_by_id={doc.doc_id: doc}, record_fields=fields,
    ))
    quality = SchemaRegistry(settings.schema_registry_dir).quality(spec.field_id, spec.version)
    routed = []
    for f in fields:
        r = route(f, quality, spec, trial=True)
        routed.append(f.model_copy(update={"route": r.kind, "route_reasons": r.reasons}))
    found = [f.confidence for f in routed if f.value is not None]
    return ExtractionRecord(
        company_id=company.company_id, name=company.name, schema_id=schema.schema_id, run_id="",
        issuer_key=key, issuer_scheme=scheme, fields=routed,
        overall_confidence=sum(found) / len(found) if found else 0.0,
        needs_review=any(f.route == "review" for f in routed),
        documents=[{
            "doc_id": doc.doc_id, "doc_type": doc.doc_type.value, "title": doc.title, "company_id": doc.company_id,
            "content_key": doc.content_key, "parser_version": doc.parser_version, "source_filename": None,
        }],
    )


def seed_known_answers(run_store: RunStore, settings: Settings, *, count: int, seed: int | None = None) -> str:
    """One trial extraction run of `count` review items: half carry the gold value, half a wrong copy."""
    rng = random.Random(seed)
    cases = _cases(settings)
    shuffled = rng.sample(cases, len(cases))

    def take(xs: list, k: int) -> list:
        # ponytail: cycles past the pool's size, so a large count repeats companies; grow the gold set instead
        return [xs[i % len(xs)] for i in range(k)] if xs else []

    bent = take([c for c in shuffled if c.expected_value is not None], count // 2)
    plain = take([c for c in shuffled if c not in bent] or shuffled, count - len(bent))
    plan = [(c, True) for c in bent] + [(c, False) for c in plain]
    rng.shuffle(plan)
    by_name: dict[str, FieldDefinition] = {}
    for case, _ in plan:
        by_name.setdefault(case.field.name, case.field)
    companies = [CompanyRef(company_id=new_id("co"), name=case.company_name) for case, _ in plan]
    run_id = create_extraction_run(
        DataPointSchema(name=f"{plan[0][0].field.name} extraction", fields=list(by_name.values())), companies, settings,
        run_store, trial=True,
    )
    schema = load_run_schema(run_store, run_id)
    specs = {f.name: f for f in schema.fields}
    planned = {c.company_id: (case, p) for c, (case, p) in zip(companies, plan, strict=True)}
    known: list[dict] = []

    async def _worker(company: CompanyRef) -> ExtractionRecordResult:
        case, perturbed = planned[company.company_id]
        value = _perturb(case.expected_value) if perturbed else case.expected_value
        record = await _record(company, case, value, schema, specs[case.field.name], settings, rng)
        record.run_id = run_id
        known.extend({"item_key": field_item_key(record.issuer_key, f.field_id, period_key(f)), "run_id": run_id,
                      "case_id": case.case_id, "expected_value": case.expected_value, "perturbed": perturbed}
                     for f in record.fields)
        return ExtractionRecordResult(record, LLMUsage(), 0.0)

    asyncio.run(run_company_batch(
        run_id, companies, run_store=run_store, worker=_worker, result_to_json=lambda r: r.record.model_dump(mode="json"),
        review_items=review_items, cost_usd=lambda r: r.cost_usd, concurrency=1,
    ))
    d = settings.review_quality_dir
    d.mkdir(parents=True, exist_ok=True)
    with _LOCKS.acquire(str(d)), (d / KNOWN).open("a") as f:
        f.writelines(json.dumps(k) + "\n" for k in known)
    return run_id


def _known(settings: Settings) -> dict[tuple[str, str], dict]:
    path = settings.review_quality_dir / KNOWN
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    return {(k["run_id"], k["item_key"]): k for k in rows}


def _rate(n: int, d: int) -> float:
    return n / d if d else 0.0


def reviewer_stats(run_store: RunStore, settings: Settings) -> list[ReviewerStat]:
    """Per reviewer, grouped by user_id and reported by name only (approvers see this, never reviewers)."""
    known = _known(settings)
    n: dict[str, dict] = defaultdict(lambda: {"name": "", "decisions": 0, "firsts": 0, "decided": 0, "agree": 0, "overturn": 0})
    last_on_known: dict[tuple[str, str, str], dict] = {}  # (user, run, item) -> that user's latest row
    for m in run_store.list_runs():
        if m.run_type not in REVIEWABLE_RUN_TYPES:
            continue
        for key, s in item_states(run_store, m.run_id, cosign_required=cosign_rule(m.run_type)).items():
            final = s.effective if s.state in FINAL_STATES else None
            for i, row in enumerate(s.rows):
                uid = row.get("user_id")
                if not uid or uid == "system":  # a legacy row names no person; a system row is no reviewer
                    continue
                c = n[uid]
                c["name"] = row.get("reviewer") or c["name"]
                c["decisions"] += 1
                if (m.run_id, key) in known:
                    last_on_known[(uid, m.run_id, key)] = row
                if row.get("step") not in (None, "first"):
                    continue
                c["firsts"] += 1
                if final is not None:
                    c["decided"] += 1
                    c["agree"] += agrees(row, final)
                later = takewhile(lambda r: r.get("step") in ("second", "resolution"), s.rows[i + 1:])
                c["overturn"] += any(not agrees(row, r) for r in later)
    ka: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # items, right
    for (uid, run_id, key), row in last_on_known.items():
        k = known[(run_id, key)]
        right = _kind(row) == "approve" if not k["perturbed"] else (
            _kind(row) == "correct" and same_value(_value(row), k["expected_value"]))
        ka[uid][0] += 1
        ka[uid][1] += right
    return sorted((
        ReviewerStat(
            name=c["name"], decisions=c["decisions"], agreement_rate=_rate(c["agree"], c["decided"]),
            overturn_rate=_rate(c["overturn"], c["firsts"]), known_answer_items=ka[uid][0],
            known_answer_accuracy=_rate(ka[uid][1], ka[uid][0]),
        ) for uid, c in n.items()
    ), key=lambda s: s.name)


def record_confirmed_correction(
    bundle: dict, corrected_value: dict, settings: Settings, *, citation: dict | None = None,
) -> None:
    """Appends the confirmed correction as a gold case to the deployment's own set (never the bundled one).
    `citation`: the first decision's grounded correction citation, from the server-side row (a blind
    bundle hides it). Skipped for a known-answer item, and when the text does not state the number."""
    spec = bundle.get("field_definition")
    item = bundle["item"]
    if spec is None or (item["run_id"], item["item_key"]) in _known(settings):  # not a field item, or a copy of a gold case
        return
    pages = list(dict.fromkeys(e["page_text"] for e in bundle.get("evidence", []) if e.get("page_text")))
    cited = (citation or {}).get("span_text")
    if cited and not any(cited in p for p in pages):
        pages.insert(0, cited)
    value = corrected_value.get("value")
    want = parse_number(str(value)) if value is not None and not isinstance(value, bool) else None
    text = "\n\n".join(pages)
    if not text or (want is not None and not any(math.isclose(abs(want), abs(n), rel_tol=1e-9) for n in candidates(text))):
        logger.warning("No gold case for %s/%s: the text does not state the corrected value", item["run_id"], item["item_key"])
        return
    evidence = bundle.get("evidence") or [{"doc_type": (citation or {}).get("doc_type")}]
    doc_type = evidence[0].get("doc_type")
    case = GoldenSetCase(
        case_id=f"review:{item['run_id']}:{item['item_key']}",
        description="A correction confirmed by a second reviewer.",
        company_name=item["payload"].get("name") or "",
        field=FieldDefinition.model_validate(spec),
        document_text=text,
        doc_type=doc_type if doc_type in {t.value for t in DocType} else DocType.OTHER,
        expected_value=value,
        expect_not_disclosed=value is None,
    )
    d = settings.review_quality_dir
    d.mkdir(parents=True, exist_ok=True)
    path = d / GOLD
    with _LOCKS.acquire(str(d)):
        cases = json.loads(path.read_text()) if path.exists() else []
        cases = [c for c in cases if c.get("case_id") != case.case_id] + [case.model_dump(mode="json")]
        atomic_write_text(path, json.dumps(cases, indent=2))
