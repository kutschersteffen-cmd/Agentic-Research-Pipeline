import pytest
from pydantic import ValidationError

from arp.reporting.house_style import load_tokens
from arp.schemas.reporting import Deck, ReportRequest
from arp.schemas.visuals import KpiRow, Tile


def _tiles(n, label="Label"):
    return [Tile(value="4%", label=label) for _ in range(n)]


def test_limits_enforced():
    with pytest.raises(ValidationError):
        KpiRow(tiles=_tiles(5))
    with pytest.raises(ValidationError):
        KpiRow(tiles=_tiles(2, "one two three four five six"))


def test_emphasis_out_of_range_is_valid():
    assert KpiRow(tiles=_tiles(4), emphasis=7).emphasis == 7


def test_old_deck_json_loads():
    d = Deck.model_validate({"title": "T", "slides": [{"headline": "H", "layout": "text", "variant": "plain", "slots": {"body": "x"}}]})
    assert d.slides[0].visual is None and d.slides[0].needs_review is False


def test_visual_union_discriminates():
    d = Deck.model_validate({"title": "T", "slides": [{"headline": "H", "visual": {"type": "kpi_row", "tiles": [t.model_dump() for t in _tiles(2)]}}]})
    assert isinstance(d.slides[0].visual, KpiRow)


def test_deck_settings_defaults():
    s = ReportRequest(title="T", qualitative_notes="n").deck
    assert (s.profile, s.purpose, s.detail, s.max_slides) == ("committee", "recommendation", "balanced", 12)
    with pytest.raises(ValidationError):
        ReportRequest(title="T", qualitative_notes="n", deck={"max_slides": 2})


def test_graphite_tokens():
    t = load_tokens()
    assert t.graphite["ink"] == "#121722"
    assert t.graphite_dark["panel"] == "#141921"
    assert t.color.accent == "#ea4c14"


def test_chart_and_table_limits():
    from arp.schemas.chart_specs import ChartSpec, TableSpec
    from arp.schemas.visuals import Chart, ComparisonTable

    with pytest.raises(ValidationError):
        Chart(data=ChartSpec(dataset_id="d", category_column="c", value_columns=[]), kind="bar")
    with pytest.raises(ValidationError):
        ComparisonTable(table=TableSpec(dataset_id="d", columns=["a"], max_rows=8))
    assert ComparisonTable(table=TableSpec(dataset_id="d", columns=["a", "b"], max_rows=8)).total_row == {}
