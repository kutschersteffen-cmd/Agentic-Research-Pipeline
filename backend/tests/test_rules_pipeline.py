"""Schema rules in the extraction pipeline: reuse and review context (schema-rules spec, AC-21, AC-38, AC-65, AC-66)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldStatus
from arp.storage.run_store import RunStore
from tests.postgres_helpers import pg_dsn, replace_results
from tests.rules_fixtures import R1, schema_f, with_rules
from tests.test_doc_routing import _Src

pytestmark = pytest.mark.usefixtures("pg")

# 31 page breaks before the text, so every quote is on page 31.
TEXT = "Acme Corp report. Halving target: yes. Target reduction: 42%. Target year: 2030."
PAGE_BREAKS = list(range(1, 32))
ANSWERS = {  # field name -> (value, quote, unit_text)
    "Halving target": (True, "Halving target: yes", None),
    "Target reduction": (42.0, "Target reduction: 42%", "%"),
    "Target year": (2030.0, "Target year: 2030", None),
}
AC3 = (
    "When Halving target is YES: needs Target reduction >= 50 and Target year <= 2030. Failed. "
    "Found Target reduction = 42 (p. 31), Target year = 2030 (p. 31)."
)


def _doc():
    return SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=TEXT, content_key="rules-k1",
        doc_id="rd1", page_breaks=PAGE_BREAKS,
    )


class _FieldLLM:
    """Answers each field's extraction by the field name in the prompt; the verifier always agrees."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def complete_structured(self, *, system, prompt, output_model, **kw):
        from arp.llm.base import LLMUsage

        self.calls.append(output_model.__name__)
        if output_model is VerifierOutput:
            out = VerifierOutput(agrees=True, confidence=0.9, notes="ok")
        else:
            name = next(n for n in self.answers if f"Field: {n}\n" in prompt)
            value, quote, unit = self.answers[name]
            out = ExtractionDraft(values=[PeriodValue(
                value=value, raw_value_text=quote.split(": ")[1], unit_text=unit,
                citations=[Citation(doc_id="rd1", doc_type=DocType.SUSTAINABILITY_REPORT, quote=quote)],
            )], confidence=0.9)
        return out, LLMUsage(input_tokens=10, output_tokens=10, provider="fake")


def _schema(*, pct_version=1, r1=None):
    s = schema_f()
    fields = [f for f in s.fields if f.field_id in ("ambition", "pct", "year")]
    fields = [f.model_copy(update={"seed_keywords": [f.name], "status": FieldStatus.RELEASED}) for f in fields]
    fields = [f.model_copy(update={"version": pct_version, "extraction_instructions": f"v{pct_version}"})
              if f.field_id == "pct" else f for f in fields]
    return with_rules(DataPointSchema(schema_id="sch1", name="F", fields=fields), {"ambition": [r1 or R1()]})


async def _run(tmp_path, schema, answers, *, calls=None):
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "r", schema_registry_dir=tmp_path / "s",
        documents_dir=tmp_path / "d", cache_dir=tmp_path / "c", discovery_state_dir=tmp_path / "x",
    )
    reg = SchemaRegistry()
    saved = reg.release(*[(s := reg.save(schema)).schema_id, s.version])
    store, llm = RunStore(pg_dsn(), settings.runs_dir), _FieldLLM(answers)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
    run_id = create_extraction_run(saved, [company], settings, store)
    await execute_extraction_run(
        run_id, saved, [company], llm=llm, registry=DocumentSourceRegistry([_Src([_doc()])]),
        settings=settings, run_store=store,
    )
    (row,) = store.read_results(run_id)
    return run_id, {f["field_id"]: f for f in row["fields"]}, llm, store


def _rule_result(field, rule_id="R1"):
    (res,) = [c for c in field["checks"] if c["check_id"] == f"rule.{rule_id}"]
    return res


async def test_rule_only_failure_is_reused(tmp_path):  # AC-21
    run1, rows1, _, _ = await _run(tmp_path, _schema(), ANSWERS)
    assert _rule_result(rows1["ambition"])["outcome"] == "fail"
    assert [c["check_id"] for c in rows1["ambition"]["checks"] if c["outcome"] == "fail"] == ["rule.R1"]
    _, rows2, llm2, _ = await _run(tmp_path, _schema(), ANSWERS)
    assert llm2.calls == [] and rows2["ambition"]["reused_from_run"] == run1


async def test_non_rule_failure_not_reused(tmp_path):  # AC-65
    run1, _, _, store = await _run(tmp_path, _schema(), ANSWERS)
    rows = store.read_results(run1)
    rows[0]["fields"][0]["checks"].append({"check_id": "c", "layer": 2, "outcome": "fail", "severity": "warn"})
    replace_results(store, run1, rows)
    _, rows2, llm2, _ = await _run(tmp_path, _schema(), ANSWERS)
    assert llm2.calls and rows2["ambition"]["reused_from_run"] is None


async def test_reused_row_reruns_rules(tmp_path):  # AC-66
    run1, _, _, _ = await _run(tmp_path, _schema(), ANSWERS)
    answers = {**ANSWERS, "Target reduction": (55.0, "Target reduction: 42%", "%")}
    _, rows2, llm2, _ = await _run(tmp_path, _schema(pct_version=2), answers)
    assert rows2["ambition"]["reused_from_run"] == run1 and rows2["pct"]["reused_from_run"] is None
    assert rows2["pct"]["value"] == 55.0 and llm2.calls
    assert _rule_result(rows2["ambition"])["outcome"] == "pass"


async def test_review_context_keeps_run_time_sentence(tmp_path):  # AC-38
    run1, rows, _, store = await _run(tmp_path, _schema(), ANSWERS)
    assert _rule_result(rows["ambition"])["detail"] == AC3
    edited = R1().model_copy(update={"conditions": [R1().conditions[0].model_copy(update={"value": 40}), R1().conditions[1]]})
    schema = _schema(r1=edited)
    schema = schema.model_copy(update={"fields": [f.model_copy(update={"version": 2}) if f.field_id == "ambition" else f
                                                  for f in schema.fields]})
    assert SchemaRegistry().save(schema).version == 2  # the edited rule is now the latest schema
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: Settings(schema_registry_dir=tmp_path / "s")
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_carol", name="Carol", role="approver")
    try:
        (item,) = [i for i in store.read_review_queue(run1) if i["field_id"] == "ambition"]
        r = TestClient(app).get(f"/api/review/runs/{run1}/items/{item['item_key']}/context")
        assert r.status_code == 200, r.text
        checks = [c for c in r.json()["failed_checks"] if c["check_id"] == "rule.R1"]
    finally:
        for dep in (get_run_store, settings_dep, current_user):
            app.dependency_overrides.pop(dep, None)
    assert [c["plain"] for c in checks] == [AC3]
