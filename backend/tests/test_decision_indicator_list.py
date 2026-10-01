"""A framework built from a list of indicators, before any company data
exists (docs/superpowers/specs/2026-10-01-credibility-from-indicator-list.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arp.decision.dataset import build_dataset, dataset_from_file
from arp.decision.indicator_list import build_framework, parse_indicator_list
from arp.decision.mechanism import apply_mechanism
from arp.decision.parsing import load_table

DECK = Path(__file__).resolve().parents[2] / "docs/decision-studio/example-framework/credibility"


@pytest.fixture
def sample_companies():
    return dataset_from_file(DECK / "companies.csv")


def test_a_list_parses_with_defaults():
    specs = parse_indicator_list(
        [["ID", "Name", "Group", "Critical", "Question", "View_Disclosure"], ["A3", "Medium-term GHG target", "Ambition", "yes", "Q2", "2"]]
    )
    s = specs[0]
    assert (s.id, s.group, s.weight, s.scale_min, s.scale_max, s.direction) == ("A3", "Ambition", 1.0, 0, 3, "higher")
    assert s.critical and s.question == "Q2" and s.views == {"Disclosure": 2.0} and s.kind == "indicator"


def test_event_rows_need_an_outlook():
    with pytest.raises(ValueError, match="row 1"):
        parse_indicator_list([["id", "name", "group", "kind"], ["targets_weakened", "Targets weakened", "Events", "event"]])


@pytest.mark.parametrize("row, message", [(["A1", "x", ""], "group"), (["A1", "x", "G", "abc"], "weight")])
def test_bad_rows_name_the_row(row, message):
    with pytest.raises(ValueError, match=f"row 1.*{message}"):
        parse_indicator_list([["id", "name", "group", "weight"][: len(row)], row])


def test_duplicate_ids_and_mixed_scales_are_refused():
    with pytest.raises(ValueError, match="A1.*twice"):
        parse_indicator_list([["id", "name", "group"], ["A1", "x", "G"], ["A1", "y", "G"]])
    with pytest.raises(ValueError, match="one scale"):
        parse_indicator_list([["id", "name", "group", "scale"], ["A1", "x", "G", "0-3"], ["A2", "y", "G", "1-5"]])


def test_a_plain_list_becomes_a_levels_framework():
    config, audit = build_framework(
        parse_indicator_list(
            [["id", "name", "group", "weight"], ["A1", "Net zero", "Ambition", "2"], ["A3", "Medium-term", "Ambition", "1"], ["G1", "GHG disclosure", "Metrics", "1"]]
        ),
        name="T",
    )
    assert (config.mode, config.level_min, config.level_max) == ("levels", 0, 3)
    assert [d.name for d in config.dimensions] == ["Ambition", "Metrics"]
    assert [(c.name, c.weight) for c in config.level_criteria] == [("Net zero", 2.0), ("Medium-term", 1.0), ("GHG disclosure", 1.0)]
    assert config.source_columns == ["A1", "A3", "G1"] and not config.ratified
    assert all(a.stage == "Indicator list" and a.origin == "derived" for a in audit)


def test_scores_become_levels_and_cluster_averages(sample_companies):
    # Shell's Ambition A1..A7 = 2,2,0,2,2,1,2 -> 11/7 = 1.57 (deck slide 10: 1.6)
    specs = [s.model_copy(update={"question": None}) for s in parse_indicator_list(load_table(DECK / "indicators.csv"))]
    config, _ = build_framework(specs, name="Credibility")  # no questions: plain framework
    shell = next(e for e in apply_mechanism(sample_companies, config).entities if e.name == "Shell")
    ambition = next(d.id for d in config.dimensions if d.name == "Ambition & targets")
    assert round(shell.dimension_scores[ambition], 2) == 1.57


def test_lower_is_better_flips_the_level():
    config, _ = build_framework(parse_indicator_list([["id", "name", "group", "direction"], ["X", "x", "G", "lower"]]), name="T")
    data = build_dataset("t", [["Company", "X"], ["a", "0"], ["b", "3"]])
    assert [c.normalised for e in apply_mechanism(data, config).entities for c in e.contributions] == [3, 0]


def test_a_list_without_five_questions_skips_the_preset_and_says_why():
    _, audit = build_framework(parse_indicator_list([["id", "name", "group", "question"], ["A1", "x", "G", "Q1"]]), name="T")
    assert any(a.item == "Credibility preset" and a.decision == "skipped" and "five questions" in a.why for a in audit)
