import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import golden_universe  # noqa: E402
import score_stock_inference as sc  # noqa: E402

from arp.research.stock_inference.schemas import InferRun, Mapping, Selection, StockProfile, Theme  # noqa: E402

CASES = [
    {"case_id": "a", "company": "A", "isin": "I1", "label": "core", "split": "tune"},
    {"case_id": "b", "company": "B", "label": "peripheral", "split": "tune"},
    {"case_id": "c", "company": "C", "label": "not", "split": "tune"},
    {"case_id": "d", "company": "D", "label": "not", "split": "tune"},
    {"case_id": "h", "company": "H", "label": "core", "split": "holdout"},
]


def _run(supporting, mapping):
    m = lambda cid, act: Mapping(company_id=cid, activity_id=act, reason="r", quote="q", tier="core")  # noqa: E731
    return InferRun(
        run_id="r1", stage="drafted", name="n", extractor_model="x", verifier_model="y",
        selection=Selection(method="sample", cutoff_reason="all"),
        profiles=[StockProfile(company_id=i, name=i, description="d") for i in "abcd"]
        + [StockProfile(company_id="e", name="e")],  # undescribed
        themes=[Theme(rank=1, name="Electrolyser makers", description="", supporting=supporting, count_share=1)],
        mapping=[m(i, act) for i, act in mapping.items()],
    )


def _go(tmp_path, monkeypatch, run, *args):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": CASES}))
    monkeypatch.setattr(sc, "_load", lambda run_id: run)
    return sc.main(["--run", "r1", "--cases", str(cases), "--split", "tune", *args])


def test_theme_pass_and_fail_by_one_stock(tmp_path, monkeypatch, capsys):
    args = ["--check", "theme", "--theme-pattern", "ELECTROLY", "--min-recall", "1"]
    assert _go(tmp_path, monkeypatch, _run(["a", "b"], {}), *args) == 0
    assert capsys.readouterr().out.strip() == "theme 'Electrolyser makers' recall 1.00 (2 described core+peripheral)"
    assert _go(tmp_path, monkeypatch, _run(["a"], {}), *args) == 1
    assert "recall 0.50" in capsys.readouterr().out
    assert _go(tmp_path, monkeypatch, _run(["a", "b"], {}), "--check", "theme", "--theme-pattern", "solar") == 1


def test_mapping_pass_and_fail_by_one_stock(tmp_path, monkeypatch, capsys):
    args = ["--check", "mapping", "--min-precision", "1"]
    ok = {"a": "act1", "c": None, "d": "act2"}
    assert _go(tmp_path, monkeypatch, _run([], ok), *args) == 0
    assert capsys.readouterr().out.strip() == "mapping precision 1.00 (2 of 2 described not)"
    assert _go(tmp_path, monkeypatch, _run([], {**ok, "d": "act1"}), *args) == 1
    assert "precision 0.50" in capsys.readouterr().out


def test_golden_universe(tmp_path):
    cases, out = tmp_path / "c.json", tmp_path / "u.json"
    cases.write_text(json.dumps({"cases": CASES}))
    golden_universe.main(["--cases", str(cases), "--split", "holdout", "--out", str(out)])
    assert json.loads(out.read_text()) == [{"company_id": "h", "name": "H", "isin": None}]
