from __future__ import annotations

import pytest

from arp.signal_lab.adapters.fundamentals import CsvFundamentalSource

HEADER = "issuer_key,metric,fiscal_period_end,available_time,value\n"
GRID = ["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31", "2024-06-30"]


def _panel(tmp_path, rows: str, issuers=("iss_a",), metric="eps", header=HEADER):
    path = tmp_path / "fund.csv"
    path.write_text(header + rows, encoding="utf-8")
    return CsvFundamentalSource(path).get_panel(metric, list(issuers), GRID)


def test_value_visible_from_availability_month(tmp_path):
    p = _panel(tmp_path, "iss_a,eps,2023-12-31,2024-03-15,1.5\n")
    assert p.source == "fundamentals:eps"
    assert p.period_ends == GRID
    assert p.values["iss_a"] == [None, None, 1.5, 1.5, 1.5, 1.5]


def test_restatement_counts_only_from_publication(tmp_path):
    rows = "iss_a,eps,2023-12-31,2024-03-15,1.0\niss_a,eps,2023-12-31,2024-06-10,2.0\n"
    assert _panel(tmp_path, rows).values["iss_a"] == [None, None, 1.0, 1.0, 1.0, 2.0]


def test_newer_period_beats_older_restated_later(tmp_path):
    rows = (
        "iss_a,eps,2023-12-31,2024-02-10,1.0\n"
        "iss_a,eps,2024-03-31,2024-04-10,3.0\n"
        "iss_a,eps,2023-12-31,2024-05-10,1.2\n"
    )
    assert _panel(tmp_path, rows).values["iss_a"] == [None, 1.0, 1.0, 3.0, 3.0, 3.0]


def test_date_only_available_time_is_end_of_day(tmp_path):
    rows = "iss_a,eps,2023-12-31,2024-02-29,1.0\n"
    assert _panel(tmp_path, rows).values["iss_a"][1] == 1.0
    rows = "iss_a,eps,2023-12-31,2024-03-01T00:00:00Z,1.0\n"
    assert _panel(tmp_path, rows).values["iss_a"][1] is None


def test_fiscal_period_compared_as_moment(tmp_path):
    rows = (
        "iss_a,eps,2023-12-31T23:59:59Z,2024-01-10,1.0\n"
        "iss_a,eps,2023-12-31,2024-02-10,2.0\n"
    )  # same period spelled two ways: the later publication wins
    assert _panel(tmp_path, rows).values["iss_a"][:2] == [1.0, 2.0]


def test_tie_picks_last_row_in_file(tmp_path):
    rows = "iss_a,eps,2023-12-31,2024-01-10,1.0\niss_a,eps,2023-12-31,2024-01-10,9.0\n"
    assert _panel(tmp_path, rows).values["iss_a"][0] == 9.0


def test_other_metric_and_unrequested_issuer_ignored(tmp_path):
    rows = "iss_a,sales,2023-12-31,2024-01-10,5.0\niss_b,eps,2023-12-31,2024-01-10,7.0\n"
    p = _panel(tmp_path, rows, issuers=("iss_a", "iss_c"))
    assert p.values == {"iss_a": [None] * 6, "iss_c": [None] * 6}


@pytest.mark.parametrize("bad", ["abc", "nan", "inf", "-inf", ""])
def test_bad_value_raises_with_row(tmp_path, bad):
    rows = f"iss_a,eps,2023-12-31,2024-01-10,1.0\niss_a,eps,2023-12-31,2024-01-11,{bad}\n"
    with pytest.raises(ValueError, match=r"fund\.csv row 2"):
        _panel(tmp_path, rows)


@pytest.mark.parametrize(
    "row",
    [
        "iss_a,eps,2023-12-31,2024-01-10T00:00:00,1.0",  # naive available_time
        "iss_a,eps,2023-12-31T00:00:00,2024-01-10,1.0",  # naive period end
        "iss_a,eps,2023-12-31,not-a-time,1.0",
        "iss_a,eps,2023-12-31,2024-01-10",  # short row
        "iss_a,eps,,2024-01-10,1.0",
        ",eps,2023-12-31,2024-01-10,1.0",
    ],
)
def test_bad_row_raises_naming_file_and_row(tmp_path, row):
    with pytest.raises(ValueError, match=r"fund\.csv row 1"):
        _panel(tmp_path, row + "\n")


def test_missing_column_raises(tmp_path):
    with pytest.raises(ValueError, match=r"fund\.csv.*value"):
        _panel(tmp_path, "iss_a,eps,2023-12-31,2024-01-10\n", header="issuer_key,metric,fiscal_period_end,available_time\n")
