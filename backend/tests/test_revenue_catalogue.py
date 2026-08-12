from pathlib import Path

from arp.research.revenue_exposure.catalogue import by_company, distinct_labels, load_catalogue, total_value

_SAMPLE_PATH = Path(__file__).parent.parent / "arp/research/revenue_exposure/sample_data/catalogue_sample.csv"


def test_load_catalogue_parses_value_and_pct_rows():
    points = load_catalogue(_SAMPLE_PATH)
    acme_ev = next(p for p in points if p.company_id == "ACME" and p.label == "EV Battery Systems")
    assert acme_ev.value == 2500000000.0
    assert acme_ev.as_pct_of_total is None

    grid = next(p for p in points if p.company_id == "GLOBALGRID" and p.label == "Grid Modernization Services")
    assert grid.value is None
    assert grid.as_pct_of_total == 0.34


def test_distinct_labels_excludes_total_rows():
    points = load_catalogue(_SAMPLE_PATH)
    labels = distinct_labels(points, "revenue")
    assert "Total Revenue" not in labels
    assert "EV Battery Systems" in labels
    assert "Solar Module Manufacturing" in labels


def test_distinct_labels_dedupes():
    from arp.research.revenue_exposure.catalogue import CatalogueDataPoint

    points = [
        CatalogueDataPoint(data_point_id="a", company_id="c1", metric="revenue", label="Widgets", value=10),
        CatalogueDataPoint(data_point_id="b", company_id="c2", metric="revenue", label="Widgets", value=20),
    ]
    assert distinct_labels(points, "revenue") == ["Widgets"]


def test_by_company_groups_rows():
    points = load_catalogue(_SAMPLE_PATH)
    grouped = by_company(points)
    assert set(grouped) == {"ACME", "GLOBALGRID", "SUNCELL"}
    assert len(grouped["ACME"]) == 5


def test_total_value_returns_none_when_no_total_row():
    points = load_catalogue(_SAMPLE_PATH)
    grouped = by_company(points)
    assert total_value(grouped["ACME"], "revenue") == 10000000000.0
    assert total_value(grouped["GLOBALGRID"], "revenue") is None
