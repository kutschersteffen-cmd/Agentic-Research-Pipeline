"""Score lineage AC-3..AC-9, AC-12, AC-29..AC-31: required criteria give no_score; contributions carry value ids."""

from __future__ import annotations

import pytest

from arp.decision.dataset import Dataset
from arp.decision.mechanism import apply_mechanism
from arp.schemas.decision import Criterion, Dimension, MechanismConfig

# company -> (scope1, scope1 reason, capex, capex reason); value ids 11.. for scope1, 21.. for capex
ROWS = {
    "A": ("90", "", "10", ""),
    "B": ("50", "", "", "no_rule_value"),
    "C": ("", "not_in_dataset", "5", ""),
    "D": ("70", "", "20", ""),
}
IDS = {"A": (11, 21), "B": (12, 22), "C": (13, 23), "D": (14, 24)}


def da(without: tuple[str, ...] = ()) -> Dataset:
    rows = []
    for c, (s1, s1r, cx, cxr) in ROWS.items():
        if c in without:
            continue
        rows.append({
            "company_id": c, "Company": f"Company {c}",
            "auth_scope1": s1, "auth_scope1__reason": s1r, "auth_scope1__value_id": str(IDS[c][0]),
            "auth_capex": cx, "auth_capex__reason": cxr, "auth_capex__value_id": str(IDS[c][1]),
        })
    return Dataset(dataset_id="ds_da", name="DA", columns=list(rows[0]), rows=rows, source="authoritative")


def s_config(**update) -> MechanismConfig:
    config = MechanismConfig(
        framework_id="fw_s", label_column="Company", missing="renormalise", no_score_rows="include",
        min_coverage_pct=0,
        dimensions=[Dimension(id="d1", name="Climate")],
        criteria=[
            Criterion(column="auth_scope1", dimension_id="d1", direction="lower", required=True),
            Criterion(column="auth_capex", dimension_id="d1", direction="higher"),
        ],
    )
    return config.model_copy(update=update)


def entity(result, name):
    return next(e for e in result.entities if e.name == f"Company {name}")


def contribution(e, column):
    return next(c for c in e.contributions if c.column == column)


@pytest.fixture
def result():
    return apply_mechanism(da(), s_config(), with_stability=False)


def test_ac_3_missing_required_value_gives_no_score_with_reason(result):
    c = entity(result, "C")
    assert c.status == "no_score"
    assert c.reasons == ["required_missing: auth_scope1 (not_in_dataset)"]


def test_ac_4_no_score_row_has_no_score_rank_or_tier(result):
    c = entity(result, "C")
    assert (c.score, c.rank, c.rank_min, c.rank_max, c.tier, c.tier_name, c.leverage) == (None,) * 7


def test_ac_5_the_others_are_ranked_one_to_three(result):
    assert {entity(result, x).rank for x in "ABD"} == {1, 2, 3}


def test_ac_6_missing_optional_value_carries_its_reason_and_id(result):
    capex = contribution(entity(result, "B"), "auth_capex")
    assert (capex.missing_reason, capex.value_id, capex.imputed) == ("no_rule_value", 22, False)


def test_ac_7_contributions_carry_value_ids(result):
    a = entity(result, "A")
    assert [contribution(a, c).value_id for c in ("auth_scope1", "auth_capex")] == [11, 21]
    assert [contribution(a, c).missing_reason for c in ("auth_scope1", "auth_capex")] == [None, None]


def test_ac_8_include_leaves_the_others_unchanged(result):
    plain = apply_mechanism(da(), s_config(criteria=[c.model_copy(update={"required": False}) for c in s_config().criteria]),
                            with_stability=False)
    for x in "ABD":
        assert entity(result, x).score == pytest.approx(entity(plain, x).score, abs=1e-9)
        assert (entity(result, x).rank, entity(result, x).tier) == (entity(plain, x).rank, entity(plain, x).tier)


def test_ac_9_exclude_normalises_the_others_among_themselves():
    excluded = apply_mechanism(da(), s_config(no_score_rows="exclude"), with_stability=False)
    without_c = apply_mechanism(da(without=("C",)), s_config(), with_stability=False)
    assert [e.name for e in excluded.entities] == [f"Company {x}" for x in "ABCD"]  # row order kept for publishing
    assert entity(excluded, "C").status == "no_score"
    for x in "ABD":
        assert entity(excluded, x).score == pytest.approx(entity(without_c, x).score, abs=1e-9)


def _upload(cell: str) -> Dataset:
    rows = [{"Company": "R", "x": cell, "y": "1"}, {"Company": "S", "x": "4", "y": "2"}, {"Company": "T", "x": "6", "y": "3"}]
    return Dataset(dataset_id="ds_u", name="u", columns=["Company", "x", "y"], rows=rows)


def _upload_config(**criterion) -> MechanismConfig:
    return MechanismConfig(
        label_column="Company", min_coverage_pct=0, dimensions=[Dimension(id="d1", name="D")],
        criteria=[Criterion(column="x", dimension_id="d1", required=True, **criterion),
                  Criterion(column="y", dimension_id="d1")],
    )


@pytest.mark.parametrize("cell", ["", "n/a"])  # AC-12 blank, AC-29 unparseable
def test_ac_12_29_blank_or_unparseable_required_cell(cell):
    r = next(e for e in apply_mechanism(_upload(cell), _upload_config(), with_stability=False).entities if e.name == "R")
    assert (r.status, r.reasons) == ("no_score", ["required_missing: x (blank)"])


def test_ac_30_disabled_required_criterion_is_not_required():
    config = s_config(criteria=[s_config().criteria[0].model_copy(update={"enabled": False}), s_config().criteria[1]])
    c = entity(apply_mechanism(da(), config, with_stability=False), "C")
    assert (c.status, c.reasons) == ("scored", [])
    assert c.rank is not None


def test_ac_31_imputing_policy_marks_imputed_with_reason():
    b = entity(apply_mechanism(da(), s_config(missing="mean"), with_stability=False), "B")
    capex = contribution(b, "auth_capex")
    assert (capex.imputed, capex.missing_reason) == (True, "no_rule_value")


def test_exclude_with_every_row_no_score_does_not_crash():
    rows = {k: ("", "not_in_dataset", v[2], v[3]) for k, v in ROWS.items()}
    ds = da()
    for r in ds.rows:
        r["auth_scope1"], r["auth_scope1__reason"] = "", rows[r["company_id"]][1]
    result = apply_mechanism(ds, s_config(no_score_rows="exclude"), with_stability=False)
    assert {e.status for e in result.entities} == {"no_score"}


def test_review_c1_exclude_keeps_each_rows_own_confidence():
    rows = [{"Company": c, "x": x, "y": "1"} for c, x in (("A", ""), ("B", "2"), ("C", "3"), ("D", "4"), ("E", "5"))]
    ds = Dataset(dataset_id="ds_c", name="c", columns=["Company", "x", "y"], rows=rows,
                 confidence={"y": [0.1, 0.9, 0.9, 0.9, 0.1]})
    config = MechanismConfig(
        label_column="Company", min_coverage_pct=60, require_grounded_coverage=True, grounded_confidence_min=0.8,
        dimensions=[Dimension(id="d1", name="D")],
        criteria=[Criterion(column="x", dimension_id="d1", required=True, weight=0.0001), Criterion(column="y", dimension_id="d1")],
    )
    include = {e.name: e.status for e in apply_mechanism(ds, config, with_stability=False).entities}
    exclude = {e.name: e.status for e in apply_mechanism(ds, config.model_copy(update={"no_score_rows": "exclude"}), with_stability=False).entities}
    assert (exclude["B"], exclude["E"]) == (include["B"], include["E"])
