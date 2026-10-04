from arp.checks.prior_period import check_comparative_jump, check_last_decided, open_restatement_candidates
from arp.checks.runner import CheckContext
from arp.extraction.history import RunHistory
from arp.schemas.common import CompanyRef, RunManifest
from arp.schemas.datapoints import (
    CheckConfig,
    DataPointSchema,
    ExtractedField,
    ExtractionRecord,
    FieldDefinition,
)
from arp.storage.run_store import RunStore

IK = "lei:K1"
FY23, FY24 = "2023-12-31", "2024-12-31"


def _spec(**cfg):
    return FieldDefinition(
        field_id="rev", name="rev", description="d", data_type="number", extraction_instructions="i",
        check_config=CheckConfig(**cfg),
    )


def _field(v, period):
    return ExtractedField(
        field_id="rev", field_name="rev", value=v, confidence=0.9, value_state="found",
        canonical_value=v, period_end=period,
    )


def _prior_run(store, run_id, v, period=FY23, *, decision="approve", trial=False, route=None, queued=True, created="2024-01-01"):
    store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", created_at=created, params={"trial": trial}))
    row = {"company_id": "c1", "issuer_key": IK, "fields": [_field(v, period).model_dump(mode="json")]}
    if route:
        row["fields"][0]["route"] = route
    store.append_jsonl(store.results_path(run_id), row)
    key = f"{IK}:rev:{period}"
    if queued:
        store.append_jsonl(store.review_queue_path(run_id), {"item_key": key})
    if decision:
        store.append_jsonl(
            store.review_decisions_path(run_id), {"item_key": key, "decision": decision, "decided_at": "t"}
        )


def _ctx(store, fields, **cfg):
    spec = _spec(**cfg)
    return spec, CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key=IK,
        schema=DataPointSchema(name="s", fields=[spec]), documents_by_id={}, record_fields=fields,
        history=RunHistory.load(store, exclude_run_id="new"),
    )


def _checked(spec, ctx):
    ctx.record_fields = [f.model_copy(update={"checks": check_last_decided(spec, f, ctx)}) for f in ctx.record_fields]
    return ctx.record_fields


def _record(*fields):
    return ExtractionRecord(company_id="c1", name="A", schema_id="s", run_id="new", issuer_key=IK, fields=list(fields))


def test_differing_comparative_opens_one_candidate(tmp_path):
    store = RunStore(tmp_path)
    _prior_run(store, "old", 1000)
    rec = _record(_field(1100, FY24), _field(1050, FY23))
    spec, ctx = _ctx(store, rec.fields)
    rec.fields = _checked(spec, ctx)
    assert open_restatement_candidates(store, "new", rec, ctx.history) == 1
    (row,) = store.read_jsonl(store.restatements_path("new"))
    assert (row["period_end"], row["previous_value"], row["new_value"]) == (FY23, 1000, 1050)


def test_equal_comparative_opens_none(tmp_path):
    store = RunStore(tmp_path)
    _prior_run(store, "old", 1000)
    rec = _record(_field(1100, FY24), _field(1000, FY23))
    spec, ctx = _ctx(store, rec.fields)
    rec.fields = _checked(spec, ctx)
    assert open_restatement_candidates(store, "new", rec, ctx.history) == 0
    assert store.read_jsonl(store.restatements_path("new")) == []


def test_current_period_difference_warns_but_no_candidate(tmp_path):
    store = RunStore(tmp_path)
    _prior_run(store, "old", 1000, FY24)
    f = _field(1100, FY24)
    spec, ctx = _ctx(store, [f])
    (r,) = check_last_decided(spec, f, ctx)
    assert (r.check_id, r.outcome, r.severity) == ("prior.last_decided", "fail", "warn")
    assert open_restatement_candidates(store, "new", _record(*_checked(spec, ctx)), ctx.history) == 0


def test_jump_past_tolerance_warns(tmp_path):
    store = RunStore(tmp_path)
    new, old = _field(2000, FY24), _field(1000, FY23)
    spec, ctx = _ctx(store, [new, old], prior_change_max=0.5)
    (r,) = check_comparative_jump(spec, new, ctx)
    assert (r.check_id, r.outcome, r.severity) == ("prior.comparative_jump", "fail", "warn")
    (r,) = check_comparative_jump(spec, old, ctx)
    assert r.outcome == "not_applicable"


def test_rejected_and_trial_values_not_prior(tmp_path):
    store = RunStore(tmp_path)
    _prior_run(store, "rej", 1000, decision="reject")
    _prior_run(store, "trial", 1000, trial=True, created="2024-02-01")
    assert RunHistory.load(store).last_decided(f"{IK}:rev:{FY23}") is None


def test_auto_accepted_row_is_system_decided(tmp_path):
    store = RunStore(tmp_path)
    _prior_run(store, "old", 1000, decision=None, route="auto_accept")
    _prior_run(store, "legacy", 900, FY24, decision=None, queued=False, created="2024-02-01")
    h = RunHistory.load(store)
    assert h.last_decided(f"{IK}:rev:{FY23}").decided_by == "system"
    assert h.last_decided(f"{IK}:rev:{FY24}").decided_by == "system"
    assert h.recorded_periods(IK) == {FY23, FY24}
    assert [r["value"] for r in h.last_rows("c1", "rev")] == [900]
