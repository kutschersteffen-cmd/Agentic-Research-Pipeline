from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: this module never opens a display, only writes PNG files
import matplotlib.pyplot as plt
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.enum.chart import XL_CHART_TYPE

from arp.schemas.reporting import ChartSpec, ChartType, QuantitativeDataset

# python-pptx chart types that render as native, still-editable-in-PowerPoint
# chart objects -- every ChartType NOT in this map falls back to a static
# matplotlib image (chart_builder.render_chart_image) instead. Kept as its
# own mapping (not reused from NATIVE_CHART_TYPES in schemas/reporting.py)
# so the pptx.enum.chart import stays local to this module.
_XL_CHART_TYPE = {
    ChartType.BAR: XL_CHART_TYPE.BAR_CLUSTERED,
    ChartType.COLUMN: XL_CHART_TYPE.COLUMN_CLUSTERED,
    ChartType.STACKED_COLUMN: XL_CHART_TYPE.COLUMN_STACKED,
    ChartType.LINE: XL_CHART_TYPE.LINE_MARKERS,
    ChartType.AREA: XL_CHART_TYPE.AREA,
    ChartType.PIE: XL_CHART_TYPE.PIE,
    ChartType.DOUGHNUT: XL_CHART_TYPE.DOUGHNUT,
    ChartType.RADAR: XL_CHART_TYPE.RADAR_MARKERS,
}


class ChartDataError(ValueError):
    """The ChartSpec references a column/dataset that doesn't actually
    exist, or references a chart shape the data doesn't support -- always a
    bug in the plan (LLM-authored or hand-edited), never a rendering
    failure to hide from the caller."""


def _dataset_by_id(datasets: list[QuantitativeDataset], dataset_id: str) -> QuantitativeDataset:
    for ds in datasets:
        if ds.dataset_id == dataset_id:
            return ds
    raise ChartDataError(f"Chart references unknown dataset_id {dataset_id!r}")


def _column(ds: QuantitativeDataset, name: str | None, *, label: str) -> str:
    if not name:
        raise ChartDataError(f"Chart on dataset {ds.dataset_id!r} is missing required column reference: {label}")
    if name not in ds.column_names():
        raise ChartDataError(f"Column {name!r} ({label}) not found in dataset {ds.dataset_id!r} (has: {ds.column_names()})")
    return name


def is_native(spec: ChartSpec) -> bool:
    return spec.chart_type in _XL_CHART_TYPE


def build_native_chart_data(spec: ChartSpec, datasets: list[QuantitativeDataset]) -> tuple[XL_CHART_TYPE, CategoryChartData | XyChartData]:
    """Builds python-pptx CategoryChartData/XyChartData for chart types
    PowerPoint can render natively -- the resulting chart stays a real,
    editable Office chart object bound to its own embedded worksheet, not a
    picture, so a user can restyle it or update its numbers directly in
    PowerPoint after generation. Scatter is XY-plotted; every other native
    type here is category-based.
    """
    ds = _dataset_by_id(datasets, spec.dataset_id)

    if spec.chart_type == ChartType.SCATTER:
        x_col = _column(ds, spec.x_column, label="x_column")
        if not spec.value_columns:
            raise ChartDataError("Scatter chart needs at least one value_columns entry for the y series.")
        xy_data = XyChartData()
        for y_col in spec.value_columns:
            y_col = _column(ds, y_col, label="value_columns")
            series = xy_data.add_series(y_col)
            for row in ds.rows:
                x_val, y_val = row.get(x_col), row.get(y_col)
                if x_val is None or y_val is None:
                    continue
                series.add_data_point(float(x_val), float(y_val))
        return XL_CHART_TYPE.XY_SCATTER, xy_data

    category_col = _column(ds, spec.category_column, label="category_column")
    if not spec.value_columns:
        raise ChartDataError("Chart needs at least one value_columns entry.")
    value_cols = [_column(ds, c, label="value_columns") for c in spec.value_columns]

    chart_data = CategoryChartData()
    chart_data.categories = [str(row.get(category_col, "")) for row in ds.rows]
    for col in value_cols:
        chart_data.add_series(col, [_as_float_or_zero(row.get(col)) for row in ds.rows])
    return _XL_CHART_TYPE[spec.chart_type], chart_data


def _as_float_or_zero(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def render_chart_image(spec: ChartSpec, datasets: list[QuantitativeDataset], out_path: Path, *, width_in: float = 9.0, height_in: float = 5.0) -> Path:
    """Renders a chart type python-pptx has no native equivalent for
    (waterfall, heatmap) -- or is used by the docx/pdf report builders,
    which have no native-chart-object concept at all -- to a PNG via
    matplotlib. This is the deliberate fallback path, not the default: see
    build_native_chart_data for the still-editable path used for pptx
    output whenever the chart type supports it.
    """
    ds = _dataset_by_id(datasets, spec.dataset_id)
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=150)

    if spec.chart_type == ChartType.HEATMAP:
        _render_heatmap(ax, spec, ds)
    elif spec.chart_type == ChartType.WATERFALL:
        _render_waterfall(ax, spec, ds)
    elif spec.chart_type == ChartType.SCATTER:
        x_col = _column(ds, spec.x_column, label="x_column")
        for y_col in spec.value_columns or []:
            y_col = _column(ds, y_col, label="value_columns")
            xs = [row.get(x_col) for row in ds.rows]
            ys = [row.get(y_col) for row in ds.rows]
            ax.scatter(xs, ys, label=y_col)
        ax.set_xlabel(x_col)
        if len(spec.value_columns or []) > 1:
            ax.legend()
    else:
        category_col = _column(ds, spec.category_column, label="category_column")
        categories = [str(row.get(category_col, "")) for row in ds.rows]
        value_cols = [_column(ds, c, label="value_columns") for c in spec.value_columns]
        if spec.chart_type == ChartType.PIE or spec.chart_type == ChartType.DOUGHNUT:
            values = [_as_float_or_zero(row.get(value_cols[0])) for row in ds.rows]
            wedge_kwargs = {"wedgeprops": {"width": 0.4}} if spec.chart_type == ChartType.DOUGHNUT else {}
            ax.pie(values, labels=categories, autopct="%1.0f%%", **wedge_kwargs)
            ax.axis("equal")
        elif spec.chart_type == ChartType.LINE or spec.chart_type == ChartType.AREA:
            for col in value_cols:
                ys = [_as_float_or_zero(row.get(col)) for row in ds.rows]
                if spec.chart_type == ChartType.AREA:
                    ax.fill_between(categories, ys, alpha=0.4, label=col)
                ax.plot(categories, ys, marker="o", label=col)
            if len(value_cols) > 1:
                ax.legend()
            plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        else:
            import numpy as np

            x = np.arange(len(categories))
            n = max(len(value_cols), 1)
            bar_width = 0.8 / n
            stacked = spec.chart_type == ChartType.STACKED_COLUMN
            bottoms = [0.0] * len(categories)
            for i, col in enumerate(value_cols):
                ys = [_as_float_or_zero(row.get(col)) for row in ds.rows]
                if stacked:
                    ax.bar(x, ys, bottom=bottoms, label=col)
                    bottoms = [b + y for b, y in zip(bottoms, ys, strict=True)]
                elif spec.chart_type == ChartType.BAR:
                    ax.barh(x + i * bar_width, ys, height=bar_width, label=col)
                else:
                    ax.bar(x + i * bar_width, ys, width=bar_width, label=col)
            if spec.chart_type == ChartType.BAR:
                ax.set_yticks(x + bar_width * (n - 1) / 2)
                ax.set_yticklabels(categories)
            else:
                ax.set_xticks(x + bar_width * (n - 1) / 2)
                ax.set_xticklabels(categories, rotation=30, ha="right")
            if n > 1:
                ax.legend()

    if spec.title:
        ax.set_title(spec.title)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def _render_heatmap(ax, spec: ChartSpec, ds: QuantitativeDataset) -> None:
    row_col = _column(ds, spec.y_column, label="y_column (heatmap row axis)")
    col_col = _column(ds, spec.category_column, label="category_column (heatmap column axis)")
    val_col = _column(ds, spec.value_column, label="value_column (heatmap cell values)")

    row_labels = list(dict.fromkeys(str(r.get(row_col)) for r in ds.rows))
    col_labels = list(dict.fromkeys(str(r.get(col_col)) for r in ds.rows))
    grid = [[float("nan")] * len(col_labels) for _ in row_labels]
    row_idx = {v: i for i, v in enumerate(row_labels)}
    col_idx = {v: i for i, v in enumerate(col_labels)}
    for r in ds.rows:
        i, j = row_idx[str(r.get(row_col))], col_idx[str(r.get(col_col))]
        grid[i][j] = _as_float_or_zero(r.get(val_col))

    im = ax.imshow(grid, aspect="auto", cmap="viridis")
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=30, ha="right")
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels)
    ax.figure.colorbar(im, ax=ax)


def _render_waterfall(ax, spec: ChartSpec, ds: QuantitativeDataset) -> None:
    category_col = _column(ds, spec.category_column, label="category_column")
    value_col = _column(ds, spec.value_columns[0] if spec.value_columns else None, label="value_columns[0]")
    categories = [str(row.get(category_col, "")) for row in ds.rows]
    values = [_as_float_or_zero(row.get(value_col)) for row in ds.rows]

    running = 0.0
    bottoms, heights, colors = [], [], []
    for v in values:
        bottoms.append(min(running, running + v))
        heights.append(abs(v))
        colors.append("#2ca02c" if v >= 0 else "#d62728")
        running += v
    ax.bar(categories, heights, bottom=bottoms, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")


def render_table_image(columns: list[str], rows: list[dict], out_path: Path, *, width_in: float = 9.0) -> Path:
    """Not used by DeckBuilder (which renders tables as native pptx table
    shapes, see deck_builder.py), only kept here for symmetry/tests. The
    docx/pdf report builders render tables with their own native table
    primitives too -- this function exists purely as a fallback for a
    caller that wants a table as a flat image."""
    height_in = 0.35 * (len(rows) + 1) + 0.3
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=150)
    ax.axis("off")
    cell_text = [[str(row.get(c, "")) for c in columns] for row in rows]
    table = ax.table(cellText=cell_text, colLabels=columns, loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


__all__ = [
    "ChartDataError",
    "is_native",
    "build_native_chart_data",
    "render_chart_image",
    "render_table_image",
]
