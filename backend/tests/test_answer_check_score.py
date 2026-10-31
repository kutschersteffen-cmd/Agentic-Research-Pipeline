"""The answer-check scorer (spec 2026-10-31-table-aware-extraction, AC-28 to AC-28e)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from answer_check_score import main  # noqa: E402

_TRUTH = [("c1", "f1", "100 million"), ("c1", "f2", "100 million"), ("c1", "q1", "YES"), ("c1", "q2", "NO")]
_ROWS = [("f1", 100.9, "EUR million"), ("f2", 102.0, "EUR million"), ("q1", True, None), ("q2", None, None)]


def _files(tmp_path, extra_truth=(), extra_rows=()):
    truth = [{"company": c, "kind": "green-capex", "item": i, "period": "", "value": v} for c, i, v in [*_TRUTH, *extra_truth]]
    rows = [{"field_id": f, "value": v, "unit": u, "period_end": None} for f, v, u in [*_ROWS, *extra_rows]]
    (tmp_path / "t.json").write_text(json.dumps(truth))
    (tmp_path / "r.json").write_text(json.dumps([{"company_id": "c1", "fields": rows}]))
    return ["--truth", str(tmp_path / "t.json"), "--results-file", str(tmp_path / "r.json"), "--schema", "green-capex"]


def test_ac28_prints_score(tmp_path, capsys):
    main(_files(tmp_path))
    assert capsys.readouterr().out.strip() == "correct 2/4 · not_found_on_yes_no 1"


def test_ac28b_below_min_exits_1(tmp_path):
    assert main([*_files(tmp_path), "--min-correct", "3"]) == 1


def test_ac28c_within_limits_exits_0(tmp_path):
    assert main([*_files(tmp_path), "--min-correct", "2", "--max-not-found", "1"]) == 0


def test_ac28d_unanswered_card_is_wrong(tmp_path, capsys):
    main(_files(tmp_path, extra_truth=[("c1", "f5", "120 million")]))
    assert capsys.readouterr().out.strip() == "correct 2/5 · not_found_on_yes_no 1"


def test_ac28e_not_in_report_matches_not_found(tmp_path, capsys):
    main(_files(tmp_path, extra_truth=[("c1", "f5", "120 million"), ("c1", "f6", "not in report")],
                extra_rows=[("f6", None, None)]))
    assert capsys.readouterr().out.strip() == "correct 3/6 · not_found_on_yes_no 1"
