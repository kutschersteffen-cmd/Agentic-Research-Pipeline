from __future__ import annotations

import json

import pytest

from arp.decision import sources
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.profiling import profile_dataset
from arp.decision.roles import propose_direction
from arp.schemas.common import JobStatus, RunManifest
from arp.schemas.emerging_themes import CandidateStatus, EmergingThemeCandidate, MentionCitation
from arp.schemas.strategy_replication import (
    BacktestResult,
    LegPerformance,
    ReplicationComparisonReport,
    ReplicationVerdict,
    ReportedPerformance,
)
from arp.storage.run_store import RunStore

# The engine scores rows; nothing in it assumes a row is a company. These
# three sources are where that stops being a claim and starts being tested:
# the entity is a sector-and-region cell, a theme, and a strategy.


# --- Transition Barrier: entity = sector x region ------------------------


def test_barrier_matrix_becomes_one_row_per_sector_and_region():
    dataset = sources.from_transition_barrier()
    assert dataset.source == "transition_barrier"
    assert dataset.row_count > 1
    keys = [(r["Sector"], r["Region"]) for r in dataset.rows]
    assert len(keys) == len(set(keys)), "one row per cell, not per criterion"
    assert all(r["Assessment"] == f"{r['Sector']} - {r['Region']}" for r in dataset.rows)


def test_barrier_columns_are_named_for_feasibility_not_barriers():
    """Rating.HIGH in that dataset means the transition is *more* feasible.
    A column called `..._Barrier_...` would be read as lower-is-better and
    would invert the whole ranking while every number still looked right."""
    dataset = sources.from_transition_barrier()
    feasibility = [c for c in dataset.columns if "Feasibility" in c]
    assert feasibility
    assert not any("Barrier" in c for c in dataset.columns)
    for column in feasibility:
        direction, _why, needs_check = propose_direction(column)
        assert direction == "higher"
        assert needs_check is False, "the dictionaries know this vocabulary, so it is not left as a guess"


def test_barrier_ratings_map_onto_a_common_scale():
    dataset = sources.from_transition_barrier(region="China")
    assert dataset.row_count >= 1
    for row in dataset.rows:
        assert row["Region"] == "China"
        for column, value in row.items():
            if column.endswith("_Feasibility_0_100") and value:
                assert 0.0 <= float(value) <= 100.0


def test_barrier_confidence_rides_along_per_cell():
    dataset = sources.from_transition_barrier()
    assert dataset.confidence, "each pillar's confidence tier is carried, so grounded coverage can key off it"
    for column, values in dataset.confidence.items():
        assert column.endswith("_Feasibility_0_100")
        assert len(values) == dataset.row_count
        assert all(v is None or 0.0 <= v <= 1.0 for v in values)


def test_a_uniform_column_is_dropped_rather_than_scored():
    """Every cell in the shipped matrix carries the same last_verified date,
    so staleness has no spread -- and a criterion that cannot separate
    anything must not be given weight."""
    dataset = sources.from_transition_barrier()
    profile = profile_dataset(dataset)["Evidence_Staleness_Days"]
    if profile.spread:
        pytest.skip("the shipped matrix now carries varied verification dates")
    config, audit = derive_mechanism(dataset)
    assert "Evidence_Staleness_Days" not in {c.column for c in config.criteria}
    entry = next(e for e in audit if e.item == "Evidence_Staleness_Days" and e.stage == "Roles")
    assert "no discriminating power" in entry.why


def test_barrier_matrix_scores_end_to_end_with_region_as_the_cohort():
    dataset = sources.from_transition_barrier()
    config, audit = derive_mechanism(dataset)
    assert config.label_column == "Assessment"
    assert config.normalise_within == "Region", "sectors compare against sectors in the same jurisdiction"
    result = apply_mechanism(dataset, config, derivation_audit=audit)
    assert result.scored_count == dataset.row_count
    assert all(e.cohort in ("China", "European Union", "United States") for e in result.entities)


def test_barrier_filter_that_matches_nothing_is_an_error():
    with pytest.raises(ValueError, match="No barrier scores"):
        sources.from_transition_barrier(sectors=["Nonexistent Sector"])


# --- Emerging Themes: entity = theme ------------------------------------


def _candidate(name: str, **kwargs) -> EmergingThemeCandidate:
    base = dict(
        theme_name=name,
        first_detected_date="2026-01-05",
        signal_velocity=1.5,
        breadth=0.4,
        persistence=2,
        novelty=0.8,
        action_score=0.5,
        materiality=0.3,
        contradiction=0.1,
        confidence_score=0.8,
        candidate_sectors_companies=["a", "b"],
        corroborating_sources=[
            MentionCitation(mention_id="m1", source_type="edgar_fts", url="http://x", quote="q", grounded=True),
            MentionCitation(mention_id="m2", source_type="gdelt", url="http://y", quote="q", grounded=False),
        ],
        cluster_id="c1",
        run_id="et1",
    )
    base.update(kwargs)
    return EmergingThemeCandidate(**base)


def _write_themes(run_store: RunStore, run_id: str, candidates: list[EmergingThemeCandidate]) -> None:
    path = run_store.results_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(c.model_dump_json() for c in candidates) + "\n")


def test_theme_run_becomes_one_row_per_candidate(tmp_path):
    run_store = RunStore(tmp_path)
    _write_themes(run_store, "et1", [_candidate("solid-state batteries"), _candidate("grid-scale storage", action_score=0.9)])
    dataset = sources.from_emerging_themes_run(run_store, "et1")
    assert dataset.source == "emerging_themes_run"
    assert [r["Theme"] for r in dataset.rows] == ["solid-state batteries", "grid-scale storage"]
    assert dataset.rows[1]["Action_Score_pct"] == "90.0"
    assert dataset.rows[0]["Grounded_Sources_pct"] == "50.0", "one of two citations grounded"


def test_contradiction_is_scored_as_counter_evidence_not_as_a_virtue():
    """A theme with more counter-evidence should rank lower, and the column
    name is what tells the engine so."""
    direction, _why, needs_check = propose_direction("Contradiction_pct")
    assert direction == "lower"
    assert needs_check is False


def test_a_disconfirmed_theme_is_gated_out_not_merely_marked_down(tmp_path):
    run_store = RunStore(tmp_path)
    good = [_candidate(f"theme {i}", action_score=0.2 + i * 0.1, novelty=0.3 + i * 0.1) for i in range(6)]
    dead = _candidate("invalidated thesis", status=CandidateStatus.DISCONFIRMED, action_score=0.99, novelty=0.99)
    _write_themes(run_store, "et2", [*good, dead])

    dataset = sources.from_emerging_themes_run(run_store, "et2")
    config, audit = derive_mechanism(dataset)
    assert "Disconfirmed_Flag" in {g.column for g in config.gates}
    assert next(g for g in config.gates if g.column == "Disconfirmed_Flag").outcome == "exclude"

    result = apply_mechanism(dataset, config, derivation_audit=audit)
    invalidated = next(e for e in result.entities if e.name == "invalidated thesis")
    assert invalidated.status == "excluded", "its transmission mechanism was invalidated -- a knockout, not a deduction"
    assert invalidated.tier is None and invalidated.rank is None


def test_theme_run_reflects_the_append_only_review_decisions(tmp_path):
    """Read through load_candidates_with_status, not off results.jsonl, so a
    rejected theme does not arrive looking like a live candidate."""
    run_store = RunStore(tmp_path)
    _write_themes(run_store, "et3", [_candidate("kept"), _candidate("thrown out")])
    rows = run_store.read_jsonl(run_store.results_path("et3"))
    theme_id = rows[1]["theme_id"]
    decisions = run_store.review_decisions_path("et3")
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text(json.dumps({"theme_id": theme_id, "action": "reject", "reason": "not real"}) + "\n")

    dataset = sources.from_emerging_themes_run(run_store, "et3")
    statuses = {r["Theme"]: r["Status"] for r in dataset.rows}
    assert statuses["thrown out"] == "rejected"
    assert statuses["kept"] == "candidate"


def test_an_empty_themes_run_is_an_error(tmp_path):
    run_store = RunStore(tmp_path)
    _write_themes(run_store, "empty", [])
    with pytest.raises(ValueError, match="no candidates"):
        sources.from_emerging_themes_run(run_store, "empty")


# --- Strategy replication: entity = strategy ----------------------------


def _report(spec_id: str, sharpe: float, verdict: ReplicationVerdict, oos_gap: float | None = 1.0) -> ReplicationComparisonReport:
    leg = LegPerformance(annualized_return_pct=sharpe * 8, sharpe_ratio=sharpe, t_stat=sharpe * 2, max_drawdown_pct=-12.0)
    return ReplicationComparisonReport(
        spec_id=spec_id,
        in_sample=BacktestResult(
            spec_id=spec_id, period_label="in_sample", period_start="2015-01-31", period_end="2020-12-31",
            data_source="csv", universe_size=500, long_short=leg, monthly_turnover_pct=8.0, warnings=["thin early coverage"],
        ),
        out_of_sample=BacktestResult(
            spec_id=spec_id, period_label="out_of_sample", period_start="2021-01-31", period_end="2025-12-31",
            data_source="csv", universe_size=500,
            long_short=LegPerformance(annualized_return_pct=sharpe * 5, sharpe_ratio=sharpe * 0.6),
        ),
        reported_performance=ReportedPerformance(),
        out_of_sample_return_gap_pp=oos_gap,
        verdict=verdict,
    )


def _write_replication(run_store: RunStore, run_id: str, name: str, report: ReplicationComparisonReport) -> None:
    path = run_store.results_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "spec", "spec_id": report.spec_id, "strategy_name": name}) + "\n"
        + json.dumps({"type": "comparison", **json.loads(report.model_dump_json())}) + "\n"
    )
    run_store.save_manifest(RunManifest(run_id=run_id, run_type="strategy_replication", status=JobStatus.COMPLETED))


def test_replication_table_spans_runs_because_one_run_is_one_strategy(tmp_path):
    run_store = RunStore(tmp_path)
    _write_replication(run_store, "r1", "Momentum 12-1", _report("s1", 1.2, ReplicationVerdict.REPLICATED))
    _write_replication(run_store, "r2", "Low Vol", _report("s2", 0.4, ReplicationVerdict.PARTIALLY_REPLICATED))

    dataset = sources.from_replication_runs(run_store)
    assert dataset.source == "replication_runs"
    assert sorted(r["Strategy"] for r in dataset.rows) == ["Low Vol", "Momentum 12-1"]
    momentum = next(r for r in dataset.rows if r["Strategy"] == "Momentum 12-1")
    assert momentum["In_Sample_Sharpe"] == "1.2"
    assert momentum["Data_Warnings_Count"] == "1"


def test_out_of_sample_column_is_not_called_a_gap(tmp_path):
    """`gap` is in the lower-is-better dictionary. Persistence carries the
    sign the engine needs: higher means the effect held up."""
    run_store = RunStore(tmp_path)
    _write_replication(run_store, "r1", "Momentum", _report("s1", 1.0, ReplicationVerdict.REPLICATED))
    dataset = sources.from_replication_runs(run_store)
    assert "Out_Of_Sample_Persistence_pp" in dataset.columns
    assert not any("Gap" in c for c in dataset.columns)
    direction, _why, needs_check = propose_direction("Out_Of_Sample_Persistence_pp")
    assert direction == "higher" and needs_check is False


def test_sharpe_and_drawdown_directions_are_inferred_not_guessed():
    assert propose_direction("In_Sample_Sharpe")[0] == "higher"
    assert propose_direction("In_Sample_Sharpe")[2] is False
    assert propose_direction("Max_Drawdown_pct")[0] == "lower"
    assert propose_direction("Max_Drawdown_pct")[2] is False


def test_a_strategy_that_did_not_replicate_is_gated_out(tmp_path):
    run_store = RunStore(tmp_path)
    for i in range(5):
        _write_replication(run_store, f"ok{i}", f"Strategy {i}", _report(f"s{i}", 0.3 + i * 0.2, ReplicationVerdict.REPLICATED))
    _write_replication(run_store, "bad", "Wrong Sign", _report("sbad", 2.5, ReplicationVerdict.NOT_REPLICATED))

    dataset = sources.from_replication_runs(run_store)
    config, audit = derive_mechanism(dataset)
    assert "Not_Replicated_Flag" in {g.column for g in config.gates}
    result = apply_mechanism(dataset, config, derivation_audit=audit)
    failed = next(e for e in result.entities if e.name == "Wrong Sign")
    assert failed.status == "excluded", "a high Sharpe on an unreplicated result is not something to average in"


def test_runs_without_a_completed_comparison_are_skipped(tmp_path):
    run_store = RunStore(tmp_path)
    path = run_store.results_path("half")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "spec", "spec_id": "s1", "strategy_name": "Unfinished"}) + "\n")
    with pytest.raises(ValueError, match="completed replication comparison"):
        sources.from_replication_runs(run_store, run_ids=["half"])


def test_no_replication_runs_at_all_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="No strategy_replication runs"):
        sources.from_replication_runs(RunStore(tmp_path))
