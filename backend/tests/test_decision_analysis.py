from __future__ import annotations

from pathlib import Path

import pytest

from arp.decision.compare import compare_results, hold_cuts
from arp.decision.dataset import build_dataset, dataset_from_file
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.sensitivity import tipping_points

SAMPLE = Path(__file__).resolve().parents[1] / "arp" / "decision" / "sample_data" / "example_transition_universe.csv"


@pytest.fixture(scope="module")
def sample():
    dataset = dataset_from_file(SAMPLE)
    config, audit = derive_mechanism(dataset)
    return dataset, config, audit


def test_tipping_points_report_how_far_a_weight_must_move(sample):
    dataset, config, _ = sample
    scored = [e for e in apply_mechanism(dataset, config).entities if e.status == "scored"]
    target = scored[0].entity_key
    rows = tipping_points(dataset, config, entity_keys=[target], steps=9)
    assert len(rows) == 1
    row = rows[0]
    assert row.tipping_points, "every dimension is tested"
    for point in row.tipping_points:
        assert point.current_weight_pct >= 0
        if not point.robust:
            assert point.delta_pct is not None and point.new_tier != row.tier


def test_a_tier_nothing_can_shift_is_reported_as_robust(sample):
    dataset, config, _ = sample
    result = apply_mechanism(dataset, config)
    top = min((e for e in result.entities if e.status == "scored"), key=lambda e: e.rank)
    rows = tipping_points(dataset, config, entity_keys=[top.entity_key], steps=9)
    assert rows[0].tier == 1
    assert all(p.robust for p in rows[0].tipping_points), "the top-ranked entity should not change tier on a weight tweak"
    assert rows[0].min_delta_pct is None


# --- period-on-period ----------------------------------------------------


def _snapshot(coverage_b: str, as_of: str):
    matrix = [
        ["Company", "Emissions_Data_Coverage_pct", "Transition_Plan_Disclosure_0_100", "Green_Capex_Share_pct"],
        ["Alpha", "95", "80", "40"],
        ["Bravo", coverage_b, "50", "20"],
        ["Charlie", "40", "30", "10"],
        ["Delta", "20", "20", "5"],
        ["Echo", "10", "10", "2"],
        ["Foxtrot", "5", "5", "1"],
    ]
    return build_dataset(f"snapshot {as_of}", matrix, as_of=as_of)


def test_the_same_framework_across_two_snapshots_reports_movement():
    """Did engagement work is the question the stewardship module exists to
    answer, and it only means anything with the framework held fixed."""
    before = _snapshot("45", "2026-01-01")
    after = _snapshot("98", "2026-07-01")
    config, _ = derive_mechanism(before)
    config.norm = "minmax"
    comparison = compare_results(
        apply_mechanism(before, config), apply_mechanism(after, config), label_before="2026-01-01", label_after="2026-07-01"
    )
    assert comparison.comparable is True
    bravo = next(m for m in comparison.movements if m.name == "Bravo")
    assert bravo.score_delta > 0
    assert bravo.drivers, "a movement with no named driver is a data problem, not progress"
    assert "Emissions Data Coverage" in bravo.drivers[0]


def test_percentile_scoring_cannot_show_absolute_improvement_and_says_so():
    """A rank-based score measures position in the field. Bravo nearly
    doubles its coverage and does not move, because nobody overtook anybody
    -- which is correct, and exactly the thing a reader would otherwise
    misread as 'no progress'."""
    before = _snapshot("45", "2026-01-01")
    after = _snapshot("92", "2026-07-01")
    config, _ = derive_mechanism(before)
    assert config.norm == "percentile"
    comparison = compare_results(apply_mechanism(before, config), apply_mechanism(after, config))
    bravo = next(m for m in comparison.movements if m.name == "Bravo")
    assert bravo.score_delta == 0
    assert comparison.caveat is not None
    assert "percentile" in comparison.caveat and "min-max" in comparison.caveat


def test_comparing_across_different_frameworks_is_flagged_not_silently_done():
    before = _snapshot("45", "2026-01-01")
    after = _snapshot("92", "2026-07-01")
    config_a, _ = derive_mechanism(before)
    config_b, _ = derive_mechanism(after)
    comparison = compare_results(apply_mechanism(before, config_a), apply_mechanism(after, config_b))
    assert comparison.comparable is False
    assert "different frameworks" in comparison.incomparable_reason


def test_entities_entering_and_leaving_are_counted_separately():
    before = _snapshot("45", "2026-01-01")
    after_matrix = [r for r in [
        ["Company", "Emissions_Data_Coverage_pct", "Transition_Plan_Disclosure_0_100", "Green_Capex_Share_pct"],
        ["Alpha", "95", "80", "40"],
        ["Bravo", "45", "50", "20"],
        ["Golf", "60", "60", "30"],
    ]]
    after = build_dataset("later", after_matrix, as_of="2026-07-01")
    config, _ = derive_mechanism(before)
    comparison = compare_results(apply_mechanism(before, config), apply_mechanism(after, config))
    assert comparison.entered == 1
    assert comparison.left == 4


def _kanto_improves(dataset):
    rows = [dict(r) for r in dataset.rows]
    for row in rows:
        if row["Company"].startswith("Kanto"):
            row["Scope3_Reported"] = "Yes"
            row["SBTi_Validated_Target"] = "Yes"
    return build_dataset("q3", [dataset.columns] + [[r[c] for c in dataset.columns] for r in rows])


def test_quantile_cuts_are_held_so_a_tier_change_needs_a_score_change(sample):
    """Kanto discloses Scope 3 and gets a target; nobody else changes. Drawn
    afresh, the quantile cuts move with Kanto and push Ardent Pharma down a
    tier on an identical score -- a movement with no driver. Held at the
    earlier snapshot's cuts, only Kanto moves."""
    dataset, config, _ = sample
    first = apply_mechanism(dataset, config)
    later = _kanto_improves(dataset)

    redrawn = compare_results(first, apply_mechanism(later, config))
    ardent = next(m for m in redrawn.movements if m.name.startswith("Ardent"))
    assert ardent.tier_delta == 1 and ardent.score_delta == 0 and not ardent.drivers
    assert redrawn.cuts_moved is not None

    held = compare_results(first, apply_mechanism(later, hold_cuts(config, first)))
    assert held.comparable is True
    assert held.cut_points == first.effective_cuts
    assert held.cuts_moved is None
    assert [m.name for m in held.movements if m.tier_delta] == ["Kanto Heavy Industries"]


def test_holding_cuts_leaves_fixed_cut_points_alone(sample):
    dataset, config, _ = sample
    fixed = config.model_copy(update={"cut_mode": "absolute", "pinned_cuts": [80.0, 60.0, 40.0]})
    assert hold_cuts(fixed, apply_mechanism(dataset, fixed)) is fixed
