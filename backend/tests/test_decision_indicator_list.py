"""A framework built from a list of indicators, before any company data
exists (docs/superpowers/specs/2026-10-01-credibility-from-indicator-list.md)."""

from __future__ import annotations

import pytest

from arp.decision.indicator_list import parse_indicator_list


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
