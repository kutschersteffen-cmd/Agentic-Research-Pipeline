import pytest
from pptx.enum.chart import XL_CHART_TYPE

from arp.reporting import chart_builder
from arp.schemas.reporting import ChartSpec, ChartType, ColumnKind, DatasetColumn, QuantitativeDataset


def _dataset() -> QuantitativeDataset:
    return QuantitativeDataset(
        name="Revenue by segment",
        columns=[
            DatasetColumn(name="segment", kind=ColumnKind.CATEGORY),
            DatasetColumn(name="revenue", kind=ColumnKind.NUMBER),
            DatasetColumn(name="ebitda", kind=ColumnKind.NUMBER),
        ],
        rows=[{"segment": "EV", "revenue": 120, "ebitda": 30}, {"segment": "Grid", "revenue": 80, "ebitda": 15}],
    )


def test_is_native_true_for_bar_false_for_heatmap():
    assert chart_builder.is_native(ChartSpec(dataset_id="x", chart_type=ChartType.BAR))
    assert not chart_builder.is_native(ChartSpec(dataset_id="x", chart_type=ChartType.HEATMAP))
    assert not chart_builder.is_native(ChartSpec(dataset_id="x", chart_type=ChartType.WATERFALL))


def test_build_native_chart_data_category_chart():
    ds = _dataset()
    spec = ChartSpec(dataset_id=ds.dataset_id, chart_type=ChartType.COLUMN, category_column="segment", value_columns=["revenue", "ebitda"])

    xl_type, chart_data = chart_builder.build_native_chart_data(spec, [ds])

    assert xl_type == XL_CHART_TYPE.COLUMN_CLUSTERED
    assert [c.label for c in chart_data.categories] == ["EV", "Grid"]
    assert len(list(chart_data)) == 2


def test_build_native_chart_data_scatter():
    ds = _dataset()
    spec = ChartSpec(dataset_id=ds.dataset_id, chart_type=ChartType.SCATTER, x_column="revenue", value_columns=["ebitda"])

    xl_type, xy_data = chart_builder.build_native_chart_data(spec, [ds])

    assert xl_type == XL_CHART_TYPE.XY_SCATTER
    series = list(xy_data)
    assert len(series) == 1


def test_build_native_chart_data_raises_on_unknown_dataset():
    with pytest.raises(chart_builder.ChartDataError):
        chart_builder.build_native_chart_data(ChartSpec(dataset_id="missing", chart_type=ChartType.BAR, category_column="a", value_columns=["b"]), [])


def test_build_native_chart_data_raises_on_missing_column():
    ds = _dataset()
    spec = ChartSpec(dataset_id=ds.dataset_id, chart_type=ChartType.BAR, category_column="nope", value_columns=["revenue"])
    with pytest.raises(chart_builder.ChartDataError):
        chart_builder.build_native_chart_data(spec, [ds])


def test_build_native_chart_data_raises_when_value_columns_missing():
    ds = _dataset()
    spec = ChartSpec(dataset_id=ds.dataset_id, chart_type=ChartType.BAR, category_column="segment")
    with pytest.raises(chart_builder.ChartDataError):
        chart_builder.build_native_chart_data(spec, [ds])


@pytest.mark.parametrize(
    "chart_type,extra",
    [
        (ChartType.BAR, {"category_column": "segment", "value_columns": ["revenue"]}),
        (ChartType.COLUMN, {"category_column": "segment", "value_columns": ["revenue", "ebitda"]}),
        (ChartType.STACKED_COLUMN, {"category_column": "segment", "value_columns": ["revenue", "ebitda"]}),
        (ChartType.LINE, {"category_column": "segment", "value_columns": ["revenue"]}),
        (ChartType.AREA, {"category_column": "segment", "value_columns": ["revenue"]}),
        (ChartType.PIE, {"category_column": "segment", "value_columns": ["revenue"]}),
        (ChartType.DOUGHNUT, {"category_column": "segment", "value_columns": ["revenue"]}),
        (ChartType.SCATTER, {"x_column": "revenue", "value_columns": ["ebitda"]}),
    ],
)
def test_render_chart_image_writes_a_png_for_every_native_type(tmp_path, chart_type, extra):
    ds = _dataset()
    spec = ChartSpec(dataset_id=ds.dataset_id, chart_type=chart_type, title="t", **extra)
    out = tmp_path / "chart.png"

    result = chart_builder.render_chart_image(spec, [ds], out)

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_render_chart_image_heatmap():
    ds = QuantitativeDataset(
        name="heat",
        columns=[DatasetColumn(name="region"), DatasetColumn(name="product"), DatasetColumn(name="score")],
        rows=[{"region": "EU", "product": "A", "score": 3}, {"region": "US", "product": "A", "score": 5}],
    )
    spec = ChartSpec(dataset_id=ds.dataset_id, chart_type=ChartType.HEATMAP, category_column="product", y_column="region", value_column="score")

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        out = chart_builder.render_chart_image(spec, [ds], Path(tmp) / "heat.png")
        assert out.exists()


def test_render_chart_image_waterfall():
    ds = _dataset()
    spec = ChartSpec(dataset_id=ds.dataset_id, chart_type=ChartType.WATERFALL, category_column="segment", value_columns=["revenue"])

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        out = chart_builder.render_chart_image(spec, [ds], Path(tmp) / "wf.png")
        assert out.exists()
