"""The approved answer-set export (spec 2026-11-01-extraction-cost-quality-roadmap, AC-A1, AC-A1c)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from answer_check_export import main  # noqa: E402

_CARDS = {"items": [
    {"id": "rwe--capex_total--2025-12-31", "company": "rwe", "kind": "green capex", "item": "capex_total", "period": "2025-12-31"},
    {"id": "rwe--tp_a_headline_1", "company": "rwe", "kind": "transition plan", "item": "A_headline_1", "period": ""},
    {"id": "rwe--tp_a_headline_2", "company": "rwe", "kind": "transition plan", "item": "A_headline_2", "period": ""},
    {"id": "rwe--tp_a_ambition_3", "company": "rwe", "kind": "transition plan", "item": "A_ambition_3", "period": ""},
]}
_TRUTH = {
    "rwe--capex_total--2025-12-31": {"status": "checked", "value": "11887 EUR million", "page": "99", "checked_by": "u_1", "checked_at": "2026-11-01T10:00:00Z"},
    "rwe--tp_a_headline_1": {"status": "checked", "value": "YES", "page": "110", "checked_by": "u_1", "checked_at": "2026-11-01T10:01:00Z"},
    "rwe--tp_a_headline_2": {"status": "proposed", "value": "YES"},
    "rwe--tp_a_ambition_3": {"status": "checked", "value": " ", "checked_by": "u_1", "checked_at": "2026-11-01T10:02:00Z"},
}


def _run(tmp_path) -> list[dict]:
    (tmp_path / "cards").mkdir()
    (tmp_path / "truth").mkdir()
    (tmp_path / "cards" / "rwe.json").write_text(json.dumps(_CARDS))
    for k, v in _TRUTH.items():
        (tmp_path / "truth" / f"{k}.json").write_text(json.dumps(v))
    out = tmp_path / "approved.json"
    main(["--cards", str(tmp_path / "cards"), "--truth", str(tmp_path / "truth"), "--out", str(out)])
    return json.loads(out.read_text())


def test_ac_a1_exports_exactly_the_checked_cards(tmp_path):
    rows = _run(tmp_path)
    assert [(r["kind"], r["item"]) for r in rows] == [("green-capex", "capex_total"), ("transition-plan", "tp_a_headline_1")]


def test_ac_a1c_every_card_has_approver_and_time(tmp_path):
    assert all(r["approved_by"] and r["approved_at"] for r in _run(tmp_path))


def test_checked_card_with_empty_answer_is_skipped(tmp_path):  # plan Review Focus 1
    assert "tp_a_ambition_3" not in {r["item"] for r in _run(tmp_path)}
