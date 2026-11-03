import json
from pathlib import Path

from typer.testing import CliRunner

from arp.cli import app
from arp.config import Settings
from arp.research.authority_taxonomy.extract import _ActivitiesDraft
from arp.research.standards_mapping.gics import _GicsSelectionList
from tests.test_authority_taxonomy_extract import _act, _llm

CASE = "hydrogen_eu_taxonomy"
CASE_DIR = Path(__file__).parent / "golden" / "authority_taxonomy" / CASE
QUOTES = {
    "Manufacture of electrolysers": "Manufacture of electrolysers for the production of hydrogen.",
    "Manufacture of fuel cells": "Manufacture of fuel cells and of other equipment that converts hydrogen into electricity or heat.",
    "Manufacture of hydrogen storage and compression equipment": "Manufacture of equipment for the storage and compression of hydrogen",
}


def _invoke(monkeypatch, tmp_path, names):
    monkeypatch.setattr("arp.db.session.require_postgres", lambda s: None)
    monkeypatch.setattr("arp.db.session.require_cutover", lambda s: None)
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )
    monkeypatch.setattr("arp.config.get_settings", lambda: settings)
    monkeypatch.setattr("arp.cli.golden_set.get_settings", lambda: settings)
    llm = _llm(_ActivitiesDraft=_ActivitiesDraft(activities=[_act(n, QUOTES[n]) for n in names]))
    llm._script[_GicsSelectionList.__name__] = [_GicsSelectionList(matches=[]) for _ in range(10)]
    monkeypatch.setattr("arp.cli.golden_set.build_llm_client", lambda s: llm)
    return CliRunner().invoke(app, ["golden-set", "authority-taxonomy", "--case", CASE])


def test_golden_pass_exit0(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, list(QUOTES))
    assert result.exit_code == 0, result.output
    assert "grounded_rate=1.00 recall=1.00" in result.output
    assert not (tmp_path / "runs").exists()  # nothing saved


def test_golden_low_recall_exit1(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, list(QUOTES)[:1])
    assert result.exit_code == 1
    assert "grounded_rate=1.00 recall=0.33" in result.output


def test_case_json_is_valid():
    case = json.loads((CASE_DIR / "case.json").read_text())
    assert len(case["expected_activities"]) == 3 and case["min_recall"] == 0.67
    assert (CASE_DIR / "source.txt").is_file()
