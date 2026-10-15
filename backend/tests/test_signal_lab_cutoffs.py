from __future__ import annotations

import pytest
from pydantic import ValidationError

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


@pytest.mark.parametrize("cutoff", ["2024", "2024-6-30", "2024/06/30", "June 2024", "2024-W26-1"])
def test_cutoff_must_be_iso_date(cutoff):
    with pytest.raises(ValidationError):
        ModelCutoff(cutoff=cutoff, source="x")


def test_iso_cutoff_accepted():
    assert ModelCutoff(cutoff="2024-06-30", source="x").cutoff == "2024-06-30"


def test_load_invalid_entry_names_path_and_model(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"m": {"cutoff": "2024", "source": "doc"}}')
    with pytest.raises(ValueError, match="'m'") as exc:
        load_cutoff_table(p)
    assert str(p) in str(exc.value)


def test_load_malformed_json_names_path(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"m": ')
    with pytest.raises(ValueError) as exc:
        load_cutoff_table(p)
    assert str(p) in str(exc.value)
