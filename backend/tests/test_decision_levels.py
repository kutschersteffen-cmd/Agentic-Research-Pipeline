from __future__ import annotations

import pytest
from pydantic import ValidationError

from arp.decision import templates
from arp.decision.dataset import build_dataset
from arp.decision.diffing import describe_changes
from arp.decision.mechanism import apply_mechanism
from arp.schemas.decision import Dimension, LevelCriterion, LevelRule, MechanismConfig, TierDefinition

HEADER = ["Company", "Company_Id", "Target_Coverage_pct", "Net_Zero_Target", "Board_Oversight"]
ROWS = [
    ["Alpha", "a", "80", "Yes", "Yes"],
    ["Beta", "b", "50", "Yes", "No"],
    ["Gamma", "c", "", "No", "No"],  # coverage not disclosed
]


def _dataset(rows=ROWS):
    return build_dataset("t", [HEADER, *rows], source="upload", source_ref="t")


def _config(**overrides) -> MechanismConfig:
    fields = dict(
        mode="levels",
        level_min=1,
        level_max=7,
        label_column="Company",
        source_columns=HEADER,
        min_coverage_pct=0,
        cut_mode="absolute",
        tiers=[TierDefinition(rank=1, name="Leader"), TierDefinition(rank=2, name="Laggard")],
        pinned_cuts=[4.0],
        dimensions=[Dimension(id="amb", name="Ambition", weight=2), Dimension(id="gov", name="Governance", weight=1)],
        level_criteria=[
            LevelCriterion(
                id="cov",
                name="Target coverage",
                dimension_id="amb",
                rules=[
                    LevelRule(level=7, when="target_coverage_pct >= 75"),
                    LevelRule(level=4, when="target_coverage_pct >= 40"),
                ],
                otherwise=1,
            ),
            LevelCriterion(id="nz", name="Net zero", dimension_id="amb", rules=[LevelRule(level=5, when="net_zero_target")], otherwise=2),
            LevelCriterion(id="board", name="Board oversight", dimension_id="gov", rules=[LevelRule(level=6, when="board_oversight")]),
        ],
    )
    fields.update(overrides)
    return MechanismConfig(**fields)


def _by_name(result):
    return {e.name: e for e in result.entities}


def test_levels_come_from_the_first_matching_rule_and_average_on_the_scale():
    result = _by_name(apply_mechanism(_dataset(), _config()))
    alpha = result["Alpha"]
    assert [c.normalised for c in alpha.contributions] == [7, 5, 6]
    # Ambition = (7 + 5) / 2 = 6; Governance = 6; total = (6*2 + 6*1) / 3 = 6.
    assert alpha.dimension_scores == {"amb": 6.0, "gov": 6.0}
    assert alpha.score == pytest.approx(6.0)
    assert alpha.tier_name == "Leader"

    beta = result["Beta"]
    # Beta: coverage 50 -> 4 (first rule fails, second holds), net zero 5, no board rule -> no level.
    assert [c.normalised for c in beta.contributions] == [4, 5, None]
    assert beta.dimension_scores == {"amb": 4.5, "gov": None}
    assert beta.score == pytest.approx(4.5), "a cluster without a level drops out of the average"


def test_a_blank_value_never_earns_a_level():
    gamma = _by_name(apply_mechanism(_dataset(), _config()))["Gamma"]
    coverage = gamma.contributions[0]
    assert coverage.normalised == 1 and coverage.imputed is True, "falls through both rules to the default"
    assert gamma.score == pytest.approx(1.5)  # Ambition (1 + 2) / 2; no Governance level
    assert gamma.tier_name == "Laggard"


def test_a_company_scores_the_same_whoever_else_is_in_the_table():
    """The point of levels mode: peers never move a score."""
    alone = _by_name(apply_mechanism(_dataset(ROWS[:1]), _config()))["Alpha"].score
    with_peers = _by_name(apply_mechanism(_dataset(ROWS + [["Delta", "d", "10", "No", "No"]]), _config()))["Alpha"].score
    assert alone == with_peers == pytest.approx(6.0)


def test_missing_levels_count_against_sufficiency_and_can_be_penalised():
    beta = _by_name(apply_mechanism(_dataset(), _config(min_coverage_pct=80)))["Beta"]
    assert beta.status == "insufficient", "board oversight carries a third of the weight and has no level"
    penalised = _by_name(apply_mechanism(_dataset(), _config(missing="penalise")))["Beta"]
    assert penalised.dimension_scores["gov"] == 1.0, "penalise counts a missing level as the bottom of the scale"


def test_tier_rules_can_read_each_criterion_level():
    node = lambda i, t, **c: {"id": i, "type": t, "name": i, "position": {"x": 0, "y": 0}, **({"content": {"passThrough": False, "inputField": None, "outputPath": None, "executionMode": "single", **c}} if c else {})}  # noqa: E731
    calc = node("calc", "expressionNode", expressions=[{"id": "t", "key": "tier", "value": "lvl_board_oversight == null ? 2 : band"}])
    tier_graph = {
        "nodes": [node("in", "inputNode"), calc, node("out", "outputNode")],
        "edges": [{"id": "e1", "sourceId": "in", "targetId": "calc", "type": "edge"}, {"id": "e2", "sourceId": "calc", "targetId": "out", "type": "edge"}],
    }
    result = _by_name(apply_mechanism(_dataset(), _config(tier_graph=tier_graph)))
    assert result["Alpha"].tier == 1
    assert result["Beta"].tier == 2, "Beta's band is Leader (4.5), but it has no board oversight level"


def test_the_grid_is_validated_on_save():
    with pytest.raises(ValidationError, match="outside 1-7"):
        _config(level_criteria=[LevelCriterion(name="x", dimension_id="amb", rules=[LevelRule(level=9, when="true")])])
    with pytest.raises(ValidationError, match="level 3"):
        _config(level_criteria=[LevelCriterion(name="x", dimension_id="amb", rules=[LevelRule(level=3, when="a >")])])


def test_template_fit_reads_the_columns_named_in_conditions():
    required = templates.required_columns(_config())
    assert {"Target_Coverage_pct", "Net_Zero_Target", "Board_Oversight"} <= set(required)
    assert templates.missing_columns(_config(), ["Company", "Target_Coverage_pct", "Net_Zero_Target"]) == ["Board_Oversight"]


def test_edits_to_the_grid_are_audited():
    before = _config()
    changed = before.level_criteria[0].model_copy(update={"rules": [LevelRule(level=7, when="target_coverage_pct >= 90")]})
    after = before.model_copy(update={"level_criteria": [changed, *before.level_criteria[1:]]})
    entries = describe_changes(before, after, by="ana")
    assert any(e.item == "Target coverage" and "90" in e.decision and e.by == "ana" for e in entries)
