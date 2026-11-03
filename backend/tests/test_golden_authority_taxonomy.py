import json
from pathlib import Path

from typer.testing import CliRunner

from arp.cli import app
from arp.config import Settings
from arp.research.authority_taxonomy.extract import _ActivitiesDraft
from arp.research.authority_taxonomy.matching import _MatchReviewDraft, _PairVerdict
from arp.research.standards_mapping.gics import _GicsSelectionList
from tests.test_authority_taxonomy_extract import _act, _llm

CASE = "hydrogen_eu_taxonomy"
CASE_DIR = Path(__file__).parent / "golden" / "authority_taxonomy" / CASE
QUOTES = {
    "Manufacture of electrolysers": "Manufacture of electrolysers for the production of hydrogen.",
    "Manufacture of fuel cells": "Manufacture of fuel cells and of other equipment that converts hydrogen into electricity or heat.",
    "Manufacture of hydrogen storage and compression equipment": "Manufacture of equipment for the storage and compression of hydrogen",
}


def _invoke(monkeypatch, tmp_path, names, *, quotes=QUOTES, expected=None, review=None):
    monkeypatch.setattr("arp.db.session.require_postgres", lambda s: None)
    monkeypatch.setattr("arp.db.session.require_cutover", lambda s: None)
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )
    monkeypatch.setattr("arp.config.get_settings", lambda: settings)
    monkeypatch.setattr("arp.cli.golden_set.get_settings", lambda: settings)
    llm = _llm(_ActivitiesDraft=_ActivitiesDraft(activities=[_act(n, quotes[n]) for n in names]))
    llm._script[_GicsSelectionList.__name__] = [_GicsSelectionList(matches=[]) for _ in range(10)]
    if review is not None:
        llm._script[_MatchReviewDraft.__name__] = [review]
    monkeypatch.setattr("arp.cli.golden_set.build_llm_client", lambda s: llm)
    args = ["golden-set", "authority-taxonomy", "--case", CASE]
    if expected is not None:  # same source and scope, other expected activities
        case = json.loads((CASE_DIR / "case.json").read_text()) | {"expected_activities": expected}
        (tmp_path / CASE).mkdir()
        (tmp_path / CASE / "case.json").write_text(json.dumps(case))
        (tmp_path / CASE / "source.txt").write_text((CASE_DIR / "source.txt").read_text())
        args += ["--cases-dir", str(tmp_path)]
    return CliRunner().invoke(app, args)


def test_golden_pass_exit0(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, list(QUOTES))
    assert result.exit_code == 0, result.output
    assert "grounded_rate=1.00 recall=1.00" in result.output
    assert result.output.startswith("WARNING: excerpt written from memory")
    assert not (tmp_path / "runs").exists()  # nothing saved


def test_golden_two_of_three_passes(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, list(QUOTES)[:2])
    assert result.exit_code == 0, result.output
    assert "recall=0.67" in result.output


def test_golden_low_recall_exit1(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, list(QUOTES)[:1])
    assert result.exit_code == 1
    assert "grounded_rate=1.00 recall=0.33" in result.output


def test_case_json_is_valid():
    case = json.loads((CASE_DIR / "case.json").read_text())
    assert len(case["expected_activities"]) == 3 and case["min_recall"] == 0.67
    assert (CASE_DIR / "source.txt").is_file()


FUEL = "Manufacture of fuel cells and other hydrogen-to-power/heat equipment"


def test_ac22b_found_by_model(monkeypatch, tmp_path):
    review = _MatchReviewDraft(pairs=[_PairVerdict(left=0, right=0, same_activity=True, reason="same product")])
    result = _invoke(monkeypatch, tmp_path, [FUEL], quotes={FUEL: QUOTES["Manufacture of fuel cells"]},
                     expected=["Manufacture of fuel cells"], review=review)
    assert f"FOUND Manufacture of fuel cells = {FUEL} (model: same product)" in result.output.splitlines()


def test_ac22c_missed(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, ["Manufacture of electrolysers"], expected=["Manufacture of hydrogen compressors"])
    assert "MISSED Manufacture of hydrogen compressors" in result.output.splitlines()
    assert "recall=0.00" in result.output
    assert result.exit_code == 1


def test_ac22d_nothing_grounded(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, ["Manufacture of electrolysers"], quotes={"Manufacture of electrolysers": "not in the source at all, made up"})
    assert result.output.splitlines()[-1] == "grounded_rate=0.00 recall=0.00"
    assert result.exit_code == 1


def test_ac22e_ac22f_exact_found_after_names(monkeypatch, tmp_path):
    result = _invoke(monkeypatch, tmp_path, ["Manufacture of electrolysers"], expected=["Manufacture of electrolysers"])
    lines = result.output.splitlines()
    assert "FOUND Manufacture of electrolysers = Manufacture of electrolysers (exact: equal merge key)" in lines
    first = next(i for i, x in enumerate(lines) if x.startswith(("FOUND", "MISSED")))
    assert "Manufacture of electrolysers" in lines[1:first]
