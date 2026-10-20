"""Task 2 of phase 2: plan actions and assumptions as list rows (rulings P3-P6), over the spec's P1 quotes."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api.main import app
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.pipeline import _extract_company, create_extraction_run, execute_extraction_run
from arp.extraction.routing import route
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.presets.transition_plan_actions import OPERATES_FIELDS, build_transition_plan_actions_schema
from arp.review.context import build_context, similar_decisions
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import FieldQuality, FieldStatus
from arp.schemas.review import field_item_key, period_key
from arp.storage.run_store import RunStore
from arp.transition_alignment.plan_extraction import ActionDraft, AssumptionDraft, Cited, PlanDraft, extract_plan, plan_evidence
from tests.conftest import PRINCIPAL
from tests.transition_alignment_helpers import ta_dirs  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("pg", "ta_dirs")

P1_QUOTES = {
    12: "We will commission a 2 Mt hydrogen-based DRI plant in Sweden by 2028.",
    13: "The DRI project needs EUR 1,500 million, of which EUR 600 million is approved.",
    14: "The DRI plant will cut emissions by 3.5 MtCO2e a year.",
    15: "Our electric arc furnace in Ohio has run on scrap since 2022.",
    16: "We are studying carbon capture at our Tianjin plant.",
    20: "Our plan assumes a carbon price of EUR 90/tCO2 in the EU by 2030.",
    21: "We assume renewable hydrogen at USD 3/kg.",
}
C = CompanyRef(company_id="c", name="Fixture Steel AG", isic_code="2410", fiscal_year_end="12-31")
Q = CompanyRef(company_id="q", name="Fixture Foods SA", isic_code="1050")


def _doc(doc_id: str, doc_type: DocType, title: str, pages: dict[int, str], company: str = "c") -> SourceDocument:
    texts = [pages.get(n, f"Page {n} of the {title}.") for n in range(1, max(pages) + 1)]
    starts = [sum(len(t) + 1 for t in texts[:i]) for i in range(len(texts))]
    return SourceDocument(doc_id=doc_id, company_id=company, doc_type=doc_type, title=title, full_text="\n".join(texts),
                          page_breaks=starts)


P1 = _doc("P1", DocType.TRANSITION_PLAN, "Fixture Steel Transition Plan 2025", P1_QUOTES)
P2 = _doc("P2", DocType.OTHER, "Fixture Steel Annual Report 2025",
          {3: "We operate steelworks in Germany, Sweden, the United States and China."})


def _c(value, page, quote=None, unit=None):
    return Cited(value=value, unit=unit, page=page, quote=quote or P1_QUOTES[page])


def _a1(action_id="steel.h2_dri", text_quote=None):
    return ActionDraft(
        text=_c("2 Mt hydrogen-based DRI plant in Sweden", 12, text_quote), action_id=_c(action_id, 12),
        status=_c("planned", 12), year=_c(2028, 12), region=_c("European Union", 12),
        ghg_saving=_c(3.5, 14, unit="MtCO2e/yr"), capex_needed=_c(1500, 13, unit="EUR million"),
        capex_allocated=_c(600, 13, unit="EUR million"),
    )


A2 = ActionDraft(text=_c("Electric arc furnace in Ohio running on scrap", 15), action_id=_c("steel.scrap_eaf", 15),
                 status=_c("implemented", 15), year=_c(2022, 15), region=_c("United States", 15))
ASSUMPTIONS = [
    AssumptionDraft(kind="carbon_price", value=90, unit="EUR/tCO2", region="European Union", year=2030,
                    quote=P1_QUOTES[20], page=20),
    AssumptionDraft(kind="h2_cost", value=3, unit="USD/kg H2", quote=P1_QUOTES[21], page=21),
]


def _plan(*actions) -> PlanDraft:
    return PlanDraft(actions=list(actions) or [_a1(), A2], assumptions=ASSUMPTIONS, confidence=0.9)


def _script(*plans: PlanDraft) -> dict:
    """The plan calls plus not-found answers for the three ta_operates_* fields (normal per-field path)."""
    n = len(OPERATES_FIELDS)
    return {"PlanDraft": list(plans), "ExtractionDraft": [ExtractionDraft(values=[], confidence=0.9)] * 2 * n,  # extract + blind verify
            "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")] * n}


def _settings(tmp_path) -> Settings:
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", schema_registry_dir=tmp_path / "schemas",
                    documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
                    hybrid_retrieval_enabled=False)


def _released():
    schema = build_transition_plan_actions_schema()
    fields = [f.model_copy(update={"status": FieldStatus.RELEASED}) for f in schema.fields]
    qualities = {(f.field_id, f.version): FieldQuality(field_id=f.field_id, version=f.version, first_audit_passed=True)
                 for f in fields}
    return schema.model_copy(update={"fields": fields, "release_flag": True}), qualities


class _Docs(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


async def _extract(tmp_path, fake_llm, script, docs=(P1,), company=C):
    schema, qualities = _released()
    llm = fake_llm(script)
    result = await _extract_company(company, schema, registry=DocumentSourceRegistry([_Docs(list(docs))]), llm=llm,
                                    settings=_settings(tmp_path), qualities=qualities)
    return result.record.fields, llm


async def _record(tmp_path, fake_llm, script, docs=(P1,), company=C):
    """A full extraction run, results recorded to Postgres as a run does: (run_store, run_id, company entity id, llm)."""
    settings = _settings(tmp_path)
    run_store = RunStore(settings.postgres_dsn, settings.runs_dir)
    schema = build_transition_plan_actions_schema()
    reg = SchemaRegistry()
    saved = reg.save(schema)
    reg.release(saved.schema_id, saved.version)
    for f in saved.fields:
        reg.record_first_audit(f.field_id, f.version, "auditor")
    run_id = create_extraction_run(schema, [company], settings, run_store)
    llm = fake_llm(script)
    await execute_extraction_run(run_id, schema, [company], llm=llm, registry=DocumentSourceRegistry([_Docs(list(docs))]),
                                 settings=settings, run_store=run_store)
    return run_store, run_id, run_store.load_companies(run_id)[0].entity_id, llm


def _by(rows, field_id):
    return [r for r in rows if r.field_id == field_id]


async def test_actions_become_rows_with_basis(tmp_path, fake_llm):
    rows, llm = await _extract(tmp_path, fake_llm, _script(_plan()))
    a1 = [r for r in rows if r.basis == "action:P1:12:1"]
    assert [r.field_id for r in a1] == [
        "ta_action_text", "ta_action_id", "ta_action_status", "ta_action_year", "ta_action_region",
        "ta_action_ghg_saving", "ta_action_capex_needed", "ta_action_capex_allocated"]
    assert [r.value for r in a1[1:]] == ["steel.h2_dri", "planned", 2028, "European Union", 3.5, 1500, 600]
    assert all(r.grounded and r.period_end is None for r in a1)
    assert {r.citations[0].page for r in a1} == {12, 13, 14}
    a2 = [r for r in rows if r.basis == "action:P1:15:1"]
    assert [r.field_id for r in a2] == [
        "ta_action_text", "ta_action_id", "ta_action_status", "ta_action_year", "ta_action_region"]
    (carbon,) = _by(rows, "ta_assumed_carbon_price")
    assert (carbon.basis, carbon.period_end, carbon.value, carbon.unit) == (
        "region:European Union", "2030-12-31", 90, "EUR/tCO2")
    (h2,) = _by(rows, "ta_assumed_h2_cost")
    assert (h2.basis, h2.period_end, h2.value, h2.unit) == ("region:any", None, 3, "USD/kg H2")
    assert llm.calls.count("PlanDraft") == 1
    # schema order: every action field's rows, then the operates fields, then the assumptions
    order = [r.field_id for r in rows]
    assert order.index("ta_action_capex_allocated") < order.index("ta_operates_eu") < order.index("ta_assumed_carbon_price")


async def test_ac30_unknown_action_id(tmp_path, fake_llm):
    run_store, run_id, entity, _ = await _record(tmp_path, fake_llm, _script(_plan(_a1("steel.foo"), A2)))
    (q,) = [q for q in run_store.read_review_queue(run_id)
            if q["field_id"] == "ta_action_id" and q["field"]["value"] == "steel.foo"]
    assert q["field"]["route"] == "review" and "check:action_id" in q["route_reasons"]
    ctx = build_context(run_store, run_id, q["item_key"], PRINCIPAL, settings=_settings(tmp_path), content_store=None)
    assert "Unknown action id 'steel.foo'" in [c["plain"] for c in ctx["failed_checks"]]
    facts = TestClient(app).get(f"/api/companies/{entity}/facts", params={"field_id": "ta_action_id"}).json()
    assert not [f for f in facts if f["value"] == "steel.foo" and f["status"] in ("approved", "auto_accepted", "edited")]


async def test_other_sector_id_refused(tmp_path, fake_llm):  # Review Focus 2
    rows, _ = await _extract(tmp_path, fake_llm, _script(_plan(_a1("pwr.renewables"))))
    (row,) = _by(rows, "ta_action_id")
    assert row.route == "review" and "check:action_id" in row.route_reasons
    assert [c.detail for c in row.checks if c.check_id == "action_id"] == ["Unknown action id 'pwr.renewables'"]


async def test_two_actions_two_review_items(tmp_path, fake_llm):
    rows, _ = await _extract(tmp_path, fake_llm, _script(_plan()))
    keys = {field_item_key("ISS", r.field_id, period_key(r)) for r in _by(rows, "ta_action_status")}
    assert keys == {"ISS:ta_action_status:unspecified|action|P1|12|1", "ISS:ta_action_status:unspecified|action|P1|15|1"}
    (carbon,) = _by(rows, "ta_assumed_carbon_price")
    assert period_key(carbon) == "2030-12-31|region|European Union"
    canonical = next(csv.DictReader(_basis_table().open(encoding="utf8")))["canonical"]
    assert period_key({"period_end": "2025-12-31", "basis": canonical}) == "2025-12-31"
    assert field_item_key("ISS", "f", period_key({"period_end": None, "basis": canonical})) == "ISS:f:unspecified"


def _basis_table() -> Path:
    return Path(__file__).parents[1] / "arp" / "normalise" / "tables" / "basis_v1.csv"


def test_basis_table_has_no_list_prefix():
    with _basis_table().open(encoding="utf8") as f:
        assert not [r["canonical"] for r in csv.DictReader(f) if r["canonical"].startswith(("action:", "region:"))]


async def test_ungrounded_quote_goes_to_review(tmp_path, fake_llm):
    rows, _ = await _extract(tmp_path, fake_llm, _script(_plan(_a1(text_quote="We will build a plant on the moon."))))
    (text,) = _by(rows, "ta_action_text")
    assert text.grounded is False and "not_grounded" in text.review_reasons
    assert text.route == "review" and "not_grounded" in text.route_reasons
    assert text.basis == "action:P1:12:1"  # the model's page when its quote does not ground


async def test_ac48_q_gets_no_rows(tmp_path, fake_llm):
    doc = _doc("P5", DocType.OTHER, "Fixture Foods Report 2025", {8: "Capital expenditure was EUR 200 million."}, "q")
    plan = _doc("PQ", DocType.TRANSITION_PLAN, "Fixture Foods Plan", {1: P1_QUOTES[20]}, "q")
    run_store, run_id, entity, llm = await _record(tmp_path, fake_llm, {}, docs=(doc, plan), company=Q)
    assert llm.calls == []
    assert TestClient(app).get(f"/api/companies/{entity}/facts").json() == []
    assert run_store.read_review_queue(run_id) == []


async def test_only_transition_plans_read(tmp_path, fake_llm):
    rows, llm = await _extract(tmp_path, fake_llm, _script(), docs=(P2,))
    assert "PlanDraft" not in llm.calls
    assert {r.field_id for r in rows} == set(OPERATES_FIELDS)


async def test_list_item_key_resolves_similar_decisions(tmp_path, fake_llm):
    run_store, run_id, _, _ = await _record(tmp_path, fake_llm, _script(_plan()))
    (q,) = [q for q in run_store.read_review_queue(run_id)
            if q["field_id"] == "ta_action_status" and q["field"]["basis"] == "action:P1:12:1"]
    assert q["item_key"].endswith(":ta_action_status:unspecified|action|P1|12|1")
    assert similar_decisions(run_store, run_id=run_id, item_key=q["item_key"]) == []  # found, no other runs: not None


async def test_plan_rows_never_auto_accept(tmp_path, fake_llm):
    schema, qualities = _released()
    defs = [f for f in schema.fields if f.field_id == "ta_action_status"]
    llm = fake_llm({"PlanDraft": [PlanDraft(actions=[A2], confidence=0.99)]})
    (row,) = (await extract_plan(C, "Steel", P1, plan_evidence(defs, P1, _settings(tmp_path)), llm, fields=defs,
                                 fuzzy_threshold=0.92))[0]
    assert row.grounded and row.confidence == 0.99 and row.checks == []
    r = route(row, qualities[(defs[0].field_id, defs[0].version)], defs[0])
    assert (r.kind, r.reasons) == ("review", ["unverified_list_item"])


async def test_a3_planned_without_year(tmp_path, fake_llm):
    a3 = ActionDraft(text=_c("Carbon capture study at the Tianjin plant", 16), action_id=_c("steel.ccus", 16),
                     status=_c("planned", 16), region=_c("China", 16))
    rows, _ = await _extract(tmp_path, fake_llm, _script(_plan(a3)))
    got = [(r.field_id, r.value) for r in rows if r.basis == "action:P1:16:1"]
    assert got == [("ta_action_text", "Carbon capture study at the Tianjin plant"), ("ta_action_id", "steel.ccus"),
                   ("ta_action_status", "planned"), ("ta_action_region", "China")]
    assert not _by(rows, "ta_action_year")


async def test_repeated_assumption_newest_plan_wins(tmp_path, fake_llm):
    quote = "Our plan assumes a carbon price of EUR 95/tCO2 in the EU by 2030."
    p1 = P1.model_copy(update={"published_at": "2026-03-31"})
    p6 = _doc("P6", DocType.TRANSITION_PLAN, "Fixture Steel Transition Plan 2025 (revised)", {4: quote})
    p6 = p6.model_copy(update={"published_at": "2026-03-31", "fetched_at": "2099-01-01T00:00:00+00:00"})  # uploaded after P1
    revised = PlanDraft(assumptions=[AssumptionDraft(kind="carbon_price", value=95, unit="EUR/tCO2",
                                                     region="European Union", year=2030, quote=quote, page=4)],
                        confidence=0.9)
    rows, llm = await _extract(tmp_path, fake_llm, _script(revised, _plan()), docs=(p1, p6))  # P6 is read first
    assert llm.calls.count("PlanDraft") == 2
    (carbon,) = _by(rows, "ta_assumed_carbon_price")
    assert (carbon.value, carbon.citations[0].doc_id, carbon.period_end) == (95, "P6", "2030-12-31")
    assert len(_by(rows, "ta_assumed_h2_cost")) == 1  # P1's other assumption is kept
