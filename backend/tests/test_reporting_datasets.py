from arp.reporting.datasets import parse_csv_dataset, parse_tabular_upload
from arp.schemas.reporting import ColumnKind


def test_parse_csv_dataset_infers_numeric_and_category_columns():
    csv_bytes = b"segment,revenue\nEV,120\nGrid,80\n"
    ds = parse_csv_dataset("Revenue", csv_bytes)

    assert ds.name == "Revenue"
    assert [c.kind for c in ds.columns] == [ColumnKind.CATEGORY, ColumnKind.NUMBER]
    assert ds.rows == [{"segment": "EV", "revenue": 120.0}, {"segment": "Grid", "revenue": 80.0}]


def test_parse_csv_dataset_infers_percent_column_from_header_name():
    csv_bytes = b"quarter,growth_pct\nQ1,5\nQ2,7\n"
    ds = parse_csv_dataset("Growth", csv_bytes)

    kinds = {c.name: c.kind for c in ds.columns}
    assert kinds["growth_pct"] == ColumnKind.PERCENT
    assert ds.rows[0]["growth_pct"] == 5.0


def test_parse_csv_dataset_handles_empty_cells_as_none():
    csv_bytes = b"segment,revenue\nEV,120\nGrid,\n"
    ds = parse_csv_dataset("Revenue", csv_bytes)

    assert ds.rows[1] == {"segment": "Grid", "revenue": None}


def test_parse_tabular_upload_dispatches_by_extension():
    ds = parse_tabular_upload("my_data.csv", b"a,b\n1,2\n")
    assert ds.name == "my_data"
    assert ds.column_names() == ["a", "b"]


def test_dataset_summary_truncates_and_reports_remaining_rows():
    csv_bytes = ("segment,revenue\n" + "".join(f"S{i},{i}\n" for i in range(20))).encode()
    ds = parse_csv_dataset("Revenue", csv_bytes)

    summary = ds.summary(max_rows=3)

    assert "20 rows" in summary
    assert "17 more rows" in summary
    assert summary.count(" - ") == 3
