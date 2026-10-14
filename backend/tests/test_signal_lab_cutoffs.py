from __future__ import annotations

from arp.signal_lab.cutoffs import CutoffTable, ModelCutoff, load_cutoff_table, period_window


def _table() -> CutoffTable:
    return CutoffTable(entries={"m": ModelCutoff(cutoff="2024-06-30", source="x")})


def test_post_cutoff_is_strictly_after():
    t = _table()
    assert period_window("m", "2024-07-01", t) == "post_cutoff"
    assert period_window("m", "2024-06-30", t) == "in_window"


def test_unknown_model_is_contaminated():
    assert period_window("other", "2030-01-01", CutoffTable(entries={})) == "in_window"


def test_no_model_is_post_cutoff():
    assert period_window(None, "1999-01-01", CutoffTable(entries={})) == "post_cutoff"


def test_load_missing_file_is_empty(tmp_path):
    assert load_cutoff_table(tmp_path / "nope.json").entries == {}


def test_load_reads_entries(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"m": {"cutoff": "2024-06-30", "source": "doc"}}')
    assert load_cutoff_table(p).cutoff_for("m") == "2024-06-30"
