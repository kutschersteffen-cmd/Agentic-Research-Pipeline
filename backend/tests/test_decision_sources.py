from __future__ import annotations

import json
from pathlib import Path

from arp.decision import sources, templates
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.profiling import profile_dataset
from arp.orchestration.job_manager import JobManager
from arp.presets.transition_plan import SCHEMA_ID, build_transition_plan_schema
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import ExtractedField, ExtractionRecord
from arp.storage.run_store import RunStore
from arp.transition_plan.indicators import load_indicators
from tests.postgres_helpers import replace_results


def _write(run_store: RunStore, run_id: str, rows: list[dict]) -> None:
    for r in rows:
        run_store.append_result(run_id, r)


def test_transition_plan_run_becomes_a_scoreable_table(tmp_path, pg):
    """The paper's completeness metric is a count, not a decision. This is
    what turns '42 of 64 disclosed' into a tier and an action."""
    run_store = RunStore(pg, tmp_path)
    _write(
        run_store,
        "tp1",
        [
            {
                "company_id": f"c{i}",
                "name": f"Company {i}",
                "company_sector": "Utilities",
                "company_location": "Europe",
                "disclosed_count": 8 + i * 3,
                "walk_disclosed_count": 2 + i,
                "walk_total_count": 30,
                "talk_disclosed_count": 6 + i,
                "overall_confidence": 0.5 + i * 0.05,
                "by_category": [
                    {"category": "target", "disclosed_count": i, "total_count": 16},
                    {"category": "governance", "disclosed_count": 2 * i, "total_count": 16},
                ],
                "needs_review": i == 0,
            }
            for i in range(8)
        ],
    )
    dataset = sources.from_transition_plan_run(run_store, "tp1")
    assert dataset.source == "transition_plan_run" and dataset.source_ref == "tp1"
    assert "Target_Disclosure_pct" in dataset.columns and "Governance_Disclosure_pct" in dataset.columns
    assert dataset.confidence["Indicators_Disclosed_Count"][3] == 0.65

    profiles = profile_dataset(dataset)
    assert profiles["Indicators_Disclosed_Count"].type in ("numeric", "ordinal")
    config, _ = derive_mechanism(dataset)
    directions = {c.column: c.direction for c in config.criteria}
    assert directions["Indicators_Disclosed_Count"] == "higher", "column names follow the conventions the dictionaries know"
    result = apply_mechanism(dataset, config)
    assert result.scored_count > 0


def test_extraction_run_carries_confidence_only_where_the_citation_grounded(tmp_path, pg):
    """An ungrounded value is present but not verified, and the two are
    different claims."""
    run_store = RunStore(pg, tmp_path)
    _write(
        run_store,
        "ex1",
        [
            {
                "company_id": "a",
                "name": "Alpha",
                "overall_confidence": 0.9,
                "fields": [
                    {"field_name": "Green_Capex_Share_pct", "value": 40, "confidence": 0.95, "grounded": True},
                    {"field_name": "Scope1_Intensity", "value": 120, "confidence": 0.9, "grounded": False},
                ],
            },
            {
                "company_id": "b",
                "name": "Bravo",
                "overall_confidence": 0.4,
                "fields": [{"field_name": "Green_Capex_Share_pct", "value": 10, "confidence": 0.8, "grounded": True}],
            },
        ],
    )
    dataset = sources.from_extraction_run(run_store, "ex1")
    assert dataset.confidence["Green_Capex_Share_pct"] == [0.95, 0.8]
    assert dataset.confidence["Scope1_Intensity"][0] == 0.0, "ungrounded means unverified, not confident"
    assert dataset.confidence["Scope1_Intensity"][1] is None, "absent is not the same as unverified"


def test_grounded_coverage_gate_routes_an_unverified_score_to_review(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    _write(
        run_store,
        "ex2",
        [
            {
                "company_id": f"c{i}",
                "name": f"Company {i}",
                "overall_confidence": 0.9,
                "fields": [
                    {"field_name": "Green_Capex_Share_pct", "value": 10 * i, "confidence": 0.95, "grounded": i > 2},
                    {"field_name": "Disclosure_Score", "value": 5 * i, "confidence": 0.95, "grounded": i > 2},
                ],
            }
            for i in range(8)
        ],
    )
    dataset = sources.from_extraction_run(run_store, "ex2")
    config, _ = derive_mechanism(dataset)
    config.require_grounded_coverage = True
    config.min_coverage_pct = 60
    result = apply_mechanism(dataset, config)
    ungrounded = [e for e in result.entities if e.name in ("Company 0", "Company 1", "Company 2")]
    assert all(e.status == "insufficient" for e in ungrounded)
    assert all("grounded weight covered" in "".join(e.notes) for e in ungrounded)


def test_asking_for_grounded_coverage_without_confidence_says_so(tmp_path):
    from arp.decision.dataset import build_dataset

    dataset = build_dataset(
        "plain.csv",
        [["Name", "A_Score", "B_Score"]] + [[f"E{i}", str(i * 10), str(i * 5)] for i in range(8)],
    )
    config, _ = derive_mechanism(dataset)
    config.require_grounded_coverage = True
    result = apply_mechanism(dataset, config)
    entry = next(e for e in result.audit if e.stage == "Sufficiency")
    assert entry.needs_check is True
    assert "no per-cell confidence" in entry.why


def test_theme_run_aggregates_per_activity_matches_to_one_row_per_company(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    _write(
        run_store,
        "th1",
        [
            {"company_id": "a", "name": "Alpha", "verdict": "include", "exposure_estimate": "high", "confidence": 0.9, "flagged_for_review": False},
            {"company_id": "a", "name": "Alpha", "verdict": "include", "exposure_estimate": "medium", "confidence": 0.7, "flagged_for_review": False},
            {"company_id": "b", "name": "Bravo", "verdict": "exclude", "exposure_estimate": "none", "confidence": 0.8, "flagged_for_review": True},
        ],
    )
    dataset = sources.from_theme_run(run_store, "th1")
    assert dataset.row_count == 2
    alpha = next(r for r in dataset.rows if r["Company"] == "Alpha")
    assert alpha["Activities_Included_Count"] == "2"
    assert alpha["Best_Exposure_Score_0_100"] == "75.0"
    assert alpha["Mean_Exposure_Score_0_100"] == "62.5"
    bravo = next(r for r in dataset.rows if r["Company"] == "Bravo")
    assert bravo["Flagged_For_Review_Flag"] == "Yes"


def test_an_empty_run_is_an_error_not_an_empty_table(tmp_path, pg):
    import pytest

    run_store = RunStore(pg, tmp_path)
    _write(run_store, "empty", [])
    with pytest.raises(ValueError, match="no results"):
        sources.from_transition_plan_run(run_store, "empty")


def test_decision_source_takes_latest_period(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    _write(
        run_store,
        "ex2",
        [{
            "company_id": "a", "name": "Alpha", "overall_confidence": 0.9,
            "fields": [  # latest period first
                {"field_name": "Capex", "value": 10, "confidence": 0.9, "grounded": True, "period_end": "2024-12-31"},
                {"field_name": "Capex", "value": 7, "confidence": 0.9, "grounded": True, "period_end": "2023-12-31"},
            ],
        }],
    )
    dataset = sources.from_extraction_run(run_store, "ex2")
    assert str(dataset.rows[0]["Capex"]) in ("10", "10.0")


# --- transition-plan preset runs (spec 2026-10-21-retire-transition-plan-pipeline §3) ---

OLD_RUN_MAIN = Path(__file__).parent / "fixtures" / "transition_plan_old_run_main.json"


def preset_record(company_id: str, found: dict[str, tuple] | None = None, *, needs_review: bool = False, extra: list[dict] | None = None) -> dict:
    """One company's result row, shaped like ExtractionRecord: every preset field, `found` ones as
    field_id -> (value, grounded, confidence), the rest not found. `extra` rows go first."""
    found = found or {}
    fields = [
        ExtractedField(field_id=f.field_id, field_name=f.name, value=found[f.field_id][0], grounded=found[f.field_id][1], confidence=found[f.field_id][2])
        if f.field_id in found
        else ExtractedField(field_id=f.field_id, field_name=f.name, value=None, confidence=0.0)
        for f in build_transition_plan_schema().fields
    ]
    record = ExtractionRecord(company_id=company_id, name=company_id.upper(), schema_id=SCHEMA_ID, run_id="r", fields=fields, needs_review=needs_review)
    dumped = record.model_dump(mode="json")
    dumped["fields"] = [*(extra or []), *dumped["fields"]]
    return dumped


def store_preset_run(run_store: RunStore, companies: list[CompanyRef] | None, records: list[dict]) -> str:
    """A stored preset run: an extraction run on the transition-plan preset, its companies (None: none
    stored) and one result row per company."""
    run_id = JobManager(run_store).create_run("extraction", {"schema_id": SCHEMA_ID}, len(records)).run_id
    if companies is not None:
        run_store.save_companies(run_id, companies)
    (run_store.run_dir(run_id) / "schema.json").write_text(build_transition_plan_schema().model_dump_json())
    replace_results(run_store, run_id, records)
    return run_id


def preset_run_r(run_store: RunStore) -> str:
    """Run `R` of the spec's Acceptance preamble."""
    x = {f"tp_{i.identifier.lower()}": (i.category.value == "target", True, 0.8) for i in load_indicators()}
    y = {
        "tp_a_headline_1": (True, True, 0.6),
        "tp_a_management_32": (True, False, 0.9),
        "tp_h_scope1_emissions": (1200.0, True, 1.0),
    }
    return store_preset_run(
        run_store,
        [CompanyRef(company_id="x", name="X", sector="Utilities", country="DE"), CompanyRef(company_id="y", name="Y")],
        [preset_record("x", x), preset_record("y", y, needs_review=True)],
    )


def extraction_run_e(run_store: RunStore) -> str:
    """Run `E`: an extraction run of another schema, one company."""
    run_id = JobManager(run_store).create_run("extraction", {"schema_id": "sch_other"}, 1).run_id
    (run_store.run_dir(run_id) / "schema.json").write_text(json.dumps({"fields": [{"name": "Green capex"}]}))
    replace_results(
        run_store,
        run_id,
        [{"company_id": "x", "name": "X", "overall_confidence": 0.9, "needs_review": False, "fields": [{"field_name": "Green capex", "value": 40.0, "confidence": 0.9, "grounded": True}]}],
    )
    return run_id


def old_run_o(run_store: RunStore) -> str:
    """An old `transition_plan` run, from the records main's output was captured on."""
    run_id = JobManager(run_store).create_run("transition_plan", {}, 2).run_id
    replace_results(run_store, run_id, json.loads(OLD_RUN_MAIN.read_text())["records"])
    return run_id


def _row(dataset, company_id: str) -> dict[str, str]:
    return next(r for r in dataset.rows if r["Company_Id"] == company_id)


def _cell_confidence(dataset, column: str, company_id: str):
    index = next(i for i, r in enumerate(dataset.rows) if r["Company_Id"] == company_id)
    return dataset.confidence.get(column, [None] * len(dataset.rows))[index]


def test_preset_run_gives_the_transition_plan_columns_then_the_generic_ones(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    run_id = preset_run_r(run_store)
    dataset = sources.from_source("transition_plan_run", run_store, run_id=run_id, include_indicators=True)
    group_1 = sources.expected_transition_plan_columns()
    generic = sources.from_extraction_run(run_store, run_id).columns
    assert dataset.columns == group_1 + [c for c in generic if c not in group_1]
    assert dataset.columns[: len(group_1)] == json.loads(OLD_RUN_MAIN.read_text())["columns"], "what an old run gives on main"
    assert dataset.columns[len(group_1)] == "Extraction_Confidence_pct"
    assert {"A_headline_1", "Scope 1 emissions"} <= set(dataset.columns[len(group_1) :])
    assert dataset.source == "transition_plan_run" and dataset.source_ref == run_id


def test_preset_run_x_row(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    x = _row(sources.from_transition_plan_run(run_store, preset_run_r(run_store), include_indicators=True), "x")
    assert {c: x[c] for c in ("Sector", "Region", "Indicators_Disclosed_Count", "Walk_Disclosed_Count", "Talk_Disclosed_Count")} == {
        "Sector": "Utilities", "Region": "DE", "Indicators_Disclosed_Count": "12", "Walk_Disclosed_Count": "0", "Talk_Disclosed_Count": "12",
    }
    assert (x["Walk_Share_pct"], x["Assessment_Confidence_pct"], x["Needs_Review_Flag"]) == ("0.0", "80.0", "No")
    assert x["Target_Disclosure_pct"] == "100.0"
    assert (x["Governance_Disclosure_pct"], x["Strategy_Disclosure_pct"], x["Tracking_Disclosure_pct"]) == ("0.0", "0.0", "0.0")
    assert (x["Ind_A_headline_1_Disclosed"], x["Ind_A_emissions_59_Disclosed"]) == ("Yes", "No")


def test_preset_run_y_row(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    y = _row(sources.from_transition_plan_run(run_store, preset_run_r(run_store), include_indicators=True), "y")
    assert {c: y[c] for c in ("Sector", "Region", "Indicators_Disclosed_Count", "Walk_Disclosed_Count", "Talk_Disclosed_Count")} == {
        "Sector": "", "Region": "", "Indicators_Disclosed_Count": "2", "Walk_Disclosed_Count": "1", "Talk_Disclosed_Count": "1",
    }
    assert (y["Walk_Share_pct"], y["Assessment_Confidence_pct"], y["Needs_Review_Flag"]) == ("2.9", "30.0", "Yes")
    assert (y["Target_Disclosure_pct"], y["Strategy_Disclosure_pct"], y["Governance_Disclosure_pct"], y["Tracking_Disclosure_pct"]) == ("8.3", "4.2", "0.0", "0.0")
    assert (y["Ind_A_headline_1_Disclosed"], y["Ind_A_management_32_Disclosed"], y["Ind_A_headline_2_Disclosed"]) == ("Yes", "Yes", "")


def test_preset_run_y_confidences(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    dataset = sources.from_transition_plan_run(run_store, preset_run_r(run_store), include_indicators=True)
    assert _cell_confidence(dataset, "Ind_A_headline_1_Disclosed", "y") == 0.6
    assert _cell_confidence(dataset, "Ind_A_management_32_Disclosed", "y") == 0, "found but ungrounded"
    assert _cell_confidence(dataset, "Ind_A_headline_2_Disclosed", "y") is None, "a not-found row is not a found one"
    assert _cell_confidence(dataset, "Indicators_Disclosed_Count", "y") == 0.3
    assert _cell_confidence(dataset, "Walk_Share_pct", "y") == 0.3
    assert _cell_confidence(dataset, "Target_Disclosure_pct", "y") is None
    assert _cell_confidence(dataset, "Indicators_Disclosed_Count", "x") == 0.8


def test_preset_run_group_2_carries_the_generic_values_and_confidences(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    run_id = preset_run_r(run_store)
    dataset = sources.from_transition_plan_run(run_store, run_id, include_indicators=True)
    generic = sources.from_extraction_run(run_store, run_id)
    group_2 = dataset.columns[len(sources.expected_transition_plan_columns()) :]
    assert [{c: r[c] for c in group_2} for r in dataset.rows] == [{c: r[c] for c in group_2} for r in generic.rows]
    assert {c: dataset.confidence.get(c) for c in group_2} == {c: generic.confidence.get(c) for c in group_2}


def test_extraction_run_source_stays_generic_on_a_preset_run(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    run_id = preset_run_r(run_store)
    dataset = sources.from_source("extraction_run", run_store, run_id=run_id)
    assert dataset.source == "extraction_run" and "Indicators_Disclosed_Count" not in dataset.columns


def test_false_value_is_found(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    run_id = store_preset_run(run_store, [], [preset_record("a", {"tp_a_headline_1": (False, True, 0.5)})])
    dataset = sources.from_transition_plan_run(run_store, run_id, include_indicators=True)
    row = dataset.rows[0]
    assert (row["Ind_A_headline_1_Disclosed"], row["Indicators_Disclosed_Count"], row["Assessment_Confidence_pct"]) == ("No", "0", "50.0")
    assert dataset.confidence["Ind_A_headline_1_Disclosed"] == [0.5]


def test_first_period_row_per_field_wins(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    rows = [
        {"field_id": "tp_a_headline_1", "field_name": "A_headline_1", "value": True, "grounded": True, "confidence": 0.7},
        {"field_id": "tp_a_headline_1", "field_name": "A_headline_1", "value": False, "grounded": True, "confidence": 0.2},
    ]
    run_id = store_preset_run(run_store, [], [preset_record("a", extra=rows)])
    dataset = sources.from_transition_plan_run(run_store, run_id, include_indicators=True)
    row = dataset.rows[0]
    assert (row["Indicators_Disclosed_Count"], row["Ind_A_headline_1_Disclosed"]) == ("1", "Yes")
    assert dataset.confidence["Ind_A_headline_1_Disclosed"] == [0.7]


def test_company_without_fields(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    empty = {"company_id": "", "name": "Nameless", "schema_id": SCHEMA_ID, "run_id": "r", "fields": [], "overall_confidence": 0.0, "needs_review": False}
    run_id = store_preset_run(run_store, [CompanyRef(company_id="a", name="A", sector="Energy", country="FR")], [preset_record("a", {"tp_a_headline_1": (True, True, 1.0)}), empty])
    dataset = sources.from_transition_plan_run(run_store, run_id, include_indicators=True)
    row = dataset.rows[1]
    assert (row["Company"], row["Company_Id"], row["Sector"], row["Region"]) == ("Nameless", "", "", "")
    assert (row["Indicators_Disclosed_Count"], row["Walk_Share_pct"], row["Assessment_Confidence_pct"], row["Target_Disclosure_pct"]) == ("0", "0.0", "0.0", "0.0")
    assert all(row[sources.indicator_column(i.identifier)] == "" for i in load_indicators())
    assert dataset.confidence["Indicators_Disclosed_Count"][1] == 0.0
    assert (dataset.rows[0]["Sector"], dataset.rows[0]["Region"]) == ("Energy", "FR")


def test_run_without_stored_companies(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    run_id = store_preset_run(run_store, None, [preset_record("a", {"tp_a_headline_1": (True, True, 1.0)})])
    row = sources.from_transition_plan_run(run_store, run_id, include_indicators=True).rows[0]
    assert (row["Sector"], row["Region"], row["Indicators_Disclosed_Count"]) == ("", "", "1")


def test_extraction_run_without_schema_id_keeps_generic_adapter(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    run_id = JobManager(run_store).create_run("extraction", {}, 1).run_id
    replace_results(run_store, run_id, [{"company_id": "a", "name": "A", "fields": [{"field_name": "Capex", "value": 1, "confidence": 0.9, "grounded": True}]}])
    manifest = run_store.load_manifest(run_id)
    assert sources.is_transition_plan_preset_run(manifest) is False
    assert templates.decision_kind(manifest) == "extraction"
    assert templates.run_dataset(run_store, manifest).source == "extraction_run"


def test_preset_run_is_recognised_by_its_schema(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    manifest = run_store.load_manifest(preset_run_r(run_store))
    assert sources.is_transition_plan_preset_run(manifest) is True
    assert templates.decision_kind(manifest) == "transition_plan"
    assert templates.run_dataset(run_store, manifest).source == "transition_plan_run"


def test_joined_preset_run_takes_the_prefix_an_old_run_gets(tmp_path, pg):
    run_store = RunStore(pg, tmp_path)
    r, e, o = preset_run_r(run_store), extraction_run_e(run_store), old_run_o(run_store)
    old = sources.from_joined_runs(run_store, [o, e], include_indicators=True)
    preset = sources.from_joined_runs(run_store, [r, e], include_indicators=True)
    e_columns = set(sources.from_extraction_run(run_store, e).columns)
    o_part = [f"TP_{c}" if c in e_columns else c for c in sources.from_transition_plan_run(run_store, o, include_indicators=True).columns if c not in ("Company", "Company_Id")]
    assert "TP_Needs_Review_Flag" in o_part and set(o_part) <= set(old.columns)
    assert set(o_part) <= set(preset.columns)


def test_old_transition_plan_run_is_unchanged_from_main(tmp_path, pg):
    """Must not change: an old run's columns, rows and confidences equal what main gave."""
    run_store = RunStore(pg, tmp_path)
    main = json.loads(OLD_RUN_MAIN.read_text())
    run_id = old_run_o(run_store)
    manifest = run_store.load_manifest(run_id)
    for dataset in (sources.from_transition_plan_run(run_store, run_id, include_indicators=True), templates.run_dataset(run_store, manifest)):
        assert (dataset.columns, dataset.rows, dataset.confidence, dataset.source) == (main["columns"], main["rows"], main["confidence"], main["source"])
    assert templates.decision_kind(manifest) == "transition_plan"
