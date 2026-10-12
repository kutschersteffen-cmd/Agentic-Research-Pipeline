from __future__ import annotations

import json
from pathlib import Path

from arp.config import Settings
from arp.extraction.pipeline import _extract_company
from arp.extraction.pre_steps import prepare_company
from arp.golden_set.runner import _values_match
from arp.golden_set.schema import ExpectedValue, PrecisionReport, RecordGoldenCase
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient
from arp.retrieval.content_store_factory import content_store_for
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldQuality, FieldStatus, RouteKind
from arp.storage.identifier_map import IdentifierMapStore

_NUMBER_TOLERANCE = 0.005  # relative


def load_record_cases(path: Path) -> list[RecordGoldenCase]:
    return [RecordGoldenCase.model_validate(c) for c in json.loads(path.read_text())]


def _compared(row: ExtractedField) -> str | float | bool | None:
    return row.canonical_value if row.canonical_value is not None else row.value


def _correct(expected: ExpectedValue, row: ExtractedField) -> bool:
    if expected.value_state != row.value_state:
        return False
    if expected.value is None:
        return True
    actual = _compared(row)
    is_number = isinstance(expected.value, (int, float)) and not isinstance(expected.value, bool)
    return _values_match(expected.value, actual, _NUMBER_TOLERANCE * abs(expected.value) if is_number else 0.0)


def _find_row(expected: ExpectedValue, rows: list[ExtractedField]) -> ExtractedField | None:
    # Rows come latest period first, so a missing period_end takes the first match.
    return next(
        (r for r in rows if r.field_id == expected.field_id and expected.period_end in (None, r.period_end)), None
    )


async def run_precision(
    cases: list[RecordGoldenCase],
    *,
    schema: DataPointSchema,
    documents_dir: Path,
    llm: LLMClient,
    verifier_llm: LLMClient | None,
    settings: Settings,
) -> PrecisionReport:
    """Runs whole records and scores the auto-accepted rows against hand-checked answers. It routes as if every
    field were released and audited, so the numbers show what auto-accept would let through in production.
    An expected value with no matching row counts as not auto-accepted."""
    released = schema.model_copy(update={"fields": [f.model_copy(update={"status": FieldStatus.RELEASED}) for f in schema.fields]})
    qualities = {(f.field_id, f.version): FieldQuality(field_id=f.field_id, version=f.version, first_audit_passed=True) for f in released.fields}
    source = LocalFileDocumentSource(
        documents_dir,
        content_store=content_store_for(settings),
        max_concurrent_parses=settings.max_concurrent_parses,
        indexing_config=IndexingConfig.from_settings(settings),
    )
    registry = DocumentSourceRegistry([source])
    identifier_map = IdentifierMapStore(settings.identifier_map_path)
    xbrl_source = None
    if settings.xbrl_facts_enabled:
        from arp.orchestration.jobs import _xbrl_source  # the same construction the CLI and API use

        xbrl_source = _xbrl_source(settings)
    total = auto = correct = 0
    wrong: list[dict] = []
    for case in cases:
        # As execute_extraction_run does per company. No `history`: a fresh extraction, nothing reused from earlier runs.
        company = await prepare_company(
            case.company, settings=settings, llm=llm, registry=registry, parent_run=(schema.schema_id, "golden-precision")
        )
        result = await _extract_company(
            company, released, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings,
            documents=await source.fetch(company), identifier_map=identifier_map, qualities=qualities, trial=False,
            xbrl_source=xbrl_source,
        )
        for expected in case.expected:
            total += 1
            row = _find_row(expected, result.record.fields)
            if row is None or row.route != RouteKind.AUTO_ACCEPT:
                continue
            auto += 1
            if _correct(expected, row):
                correct += 1
            else:
                wrong.append({
                    "case_id": case.case_id, "field_id": expected.field_id,
                    "expected": expected.value if expected.value is not None else expected.value_state.value,
                    "actual": _compared(row) if _compared(row) is not None else row.value_state.value,
                    "actual_raw": row.value,
                    "citations": [c.model_dump(mode="json") for c in row.citations],
                })
    return PrecisionReport(
        schema_id=schema.schema_id, total=total, auto_accepted=auto, auto_accepted_correct=correct,
        precision=correct / auto if auto else None,
        review_rate=(total - auto) / total if total else 0.0,
        coverage=auto / total if total else 0.0,
        wrong_auto_accepted=wrong,
    )
