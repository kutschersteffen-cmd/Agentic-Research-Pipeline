from __future__ import annotations

import pytest

from arp.signal_lab.adapters.revisions import CsvRevisionSource

HEADER = "issuer_key,event_time,direction\n"
GRID = ["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"]


def _panel(tmp_path, rows: str, issuers=("iss_a",), grid=GRID, **kw):
    path = tmp_path / "rev.csv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return CsvRevisionSource(path).get_panel(list(issuers), grid, **kw)


def test_net_ratio_over_window(tmp_path):
    rows = "".join(f"iss_a,2024-01-1{n}T10:00:00Z,up\n" for n in (1, 2, 3)) + "iss_a,2024-01-20T10:00:00Z,down\n"
    p = _panel(tmp_path, rows)
    assert p.source == "analyst_revisions"
    assert p.period_ends == GRID
    assert p.values["iss_a"][0] == 0.5


def test_no_revisions_is_none_not_zero(tmp_path):
    assert _panel(tmp_path, "iss_a,2024-01-10T10:00:00Z,up\n", window_months=1).values["iss_a"][1] is None


def test_revision_after_month_end_counts_next_month(tmp_path):
    p = _panel(tmp_path, "iss_a,2024-02-01T00:00:00Z,up\n", window_months=1)
    assert p.values["iss_a"][:2] == [None, 1.0]


def test_revision_older_than_window_excluded(tmp_path):
    p = _panel(tmp_path, "iss_a,2024-01-31T23:59:59Z,up\n")  # window 3: Jan..Mar
    assert p.values["iss_a"] == [1.0, 1.0, 1.0, None]


def test_window_one_changes_result(tmp_path):
    rows = "iss_a,2024-01-10T10:00:00Z,up\niss_a,2024-02-10T10:00:00Z,down\n"
    assert _panel(tmp_path, rows, window_months=1).values["iss_a"][:2] == [1.0, -1.0]
    assert _panel(tmp_path, rows).values["iss_a"][:2] == [1.0, 0.0]


def test_window_start_before_first_period(tmp_path):
    # Grid starts in March; window 3 reaches back to January.
    p = _panel(tmp_path, "iss_a,2024-01-05T10:00:00Z,up\n", grid=["2024-03-31"])
    assert p.values["iss_a"] == [1.0]


def test_window_crosses_year_boundary(tmp_path):
    p = _panel(tmp_path, "iss_a,2023-12-05T10:00:00Z,down\n", grid=["2024-01-31"])
    assert p.values["iss_a"] == [-1.0]


def test_offset_time_compared_as_moment(tmp_path):
    # 2024-02-01T01:00+02:00 is 2024-01-31T23:00Z: counts in January.
    p = _panel(tmp_path, "iss_a,2024-02-01T01:00:00+02:00,up\n", window_months=1)
    assert p.values["iss_a"][:2] == [1.0, None]


def test_absent_issuer_all_none(tmp_path):
    assert _panel(tmp_path, "iss_a,2024-01-10T10:00:00Z,up\n", issuers=("iss_z",)).values["iss_z"] == [None] * 4


def test_unknown_direction_names_row(tmp_path):
    with pytest.raises(ValueError, match=r"rev\.csv.*row 2"):
        _panel(tmp_path, "iss_a,2024-01-10T10:00:00Z,up\niss_a,2024-01-11T10:00:00Z,sideways\n")


def test_naive_event_time_names_row(tmp_path):
    with pytest.raises(ValueError, match=r"rev\.csv.*row 1"):
        _panel(tmp_path, "iss_a,2024-01-10T10:00:00,up\n")


def test_short_row_names_row(tmp_path):
    with pytest.raises(ValueError, match=r"rev\.csv.*row 1"):
        _panel(tmp_path, "iss_a,2024-01-10T10:00:00Z\n")


def test_missing_column_names_file(tmp_path):
    path = tmp_path / "rev.csv"
    path.write_text("issuer_key,event_time\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"rev\.csv.*direction"):
        CsvRevisionSource(path).get_panel(["iss_a"], GRID)
