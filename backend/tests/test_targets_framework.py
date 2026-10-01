"""The 'Logic of targets' sheet (Q2.1.1-Q2.1.5) as an importable framework:
docs/decision-studio/example-framework/targets/."""

from __future__ import annotations

import json
from pathlib import Path

from arp.decision.dataset import dataset_from_file
from arp.decision.mechanism import apply_mechanism
from arp.decision.templates import import_template

TARGETS = Path(__file__).resolve().parents[2] / "docs/decision-studio/example-framework/targets"


def _result():
    config, _ = import_template(json.loads((TARGETS / "framework.json").read_text()))
    return config, apply_mechanism(dataset_from_file(TARGETS / "companies.csv"), config)


def test_each_company_lands_in_the_tier_its_answers_give():
    _, result = _result()
    assert not result.missing_columns
    assert {e.name: e.tier_name for e in result.entities} == {
        "Alder Power": "Aligned targets",  # SBTi near-term target set for 2030: Yes to all
        "Birch Mining": "Targets, alignment not shown",  # Q2.1.1-4 Yes, TPI says National Pledges
        "Cedar Chemicals": "Partial targets",
        "Dune Logistics": "Partial targets",
        "Elm Retail": "No targets",
        "Fir Textiles": "No information",
        "Gale Steel": "Aligned targets",  # all four Yes from MSCI, TPI 2035 Below 2 Degrees
    }


def test_the_note_names_each_answer_and_its_source():
    _, result = _result()
    notes = {e.name: e.notes[-1] for e in result.entities}
    # SBTi target year 2040 is outside 2029-2035, so Step 1 has no info and MSCI answers;
    # MSCI 'No' on Q2.1.2 stops the waterfall; WBA answers Q2.1.3; CDP answers Q2.1.4.
    assert notes["Cedar Chemicals"] == (
        "2/5 Yes · Q2.1.1 Yes (MSCI) · Q2.1.2 No (MSCI) · Q2.1.3 Yes (WBA) · Q2.1.4 No (CDP) · Q2.1.5 No (Q2.1.1-4)"
    )
    assert notes["Dune Logistics"].startswith("1/5 Yes · Q2.1.1 Yes (CDP) · Q2.1.2 No info")
    assert notes["Birch Mining"].endswith("Q2.1.4 Yes (CA100+/WBA) · Q2.1.5 No (TPI)")


def test_the_framework_names_every_source_column():
    config, _ = _result()
    header = (TARGETS / "companies.csv").read_text().splitlines()[0].split(",")
    assert sorted(config.source_columns) == sorted(header)
