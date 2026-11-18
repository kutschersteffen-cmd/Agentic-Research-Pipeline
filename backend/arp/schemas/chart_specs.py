"""Chart and table references into datasets, shared by reporting and visuals (kept apart to avoid an import cycle)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ChartType(StrEnum):
    BAR = "bar"
    COLUMN = "column"
    STACKED_COLUMN = "stacked_column"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    DOUGHNUT = "doughnut"
    SCATTER = "scatter"
    RADAR = "radar"
    WATERFALL = "waterfall"
    HEATMAP = "heatmap"
    TABLE = "table"
    """Not a chart at all -- an explicit signal the data reads better as a table than any chart."""


NATIVE_CHART_TYPES = {
    ChartType.BAR, ChartType.COLUMN, ChartType.STACKED_COLUMN, ChartType.LINE,
    ChartType.AREA, ChartType.PIE, ChartType.DOUGHNUT, ChartType.SCATTER, ChartType.RADAR,
}
"""Chart types python-pptx can build as a native, still-editable-in-PowerPoint chart object.
Everything else (waterfall, heatmap) is rendered to a static image instead -- see chart_builder.py."""


class ChartSpec(BaseModel):
    dataset_id: str
    chart_type: ChartType = ChartType.BAR
    title: str = ""
    category_column: str | None = Field(default=None, description="Column used for category/x-axis labels. Required for every type except scatter/heatmap.")
    value_columns: list[str] = Field(default_factory=list, description="One or more numeric columns to plot as series.")
    x_column: str | None = Field(default=None, description="scatter only: numeric column for the x-axis (category_column is unused).")
    y_column: str | None = Field(default=None, description="heatmap only: the row-axis category column (category_column is the column axis).")
    value_column: str | None = Field(default=None, description="heatmap only: the numeric cell value column.")
    notes: str = Field(default="", description="Caption/takeaway text rendered under the chart.")


class TableSpec(BaseModel):
    dataset_id: str
    columns: list[str] = Field(default_factory=list, description="Subset/order of dataset columns to include. Empty = all columns.")
    row_offset: int = Field(default=0, ge=0, description="First dataset row shown; a split table slide continues from here.")
    max_rows: int = Field(default=20, description="Renderer truncates to this many rows; a truncation note is added if the dataset has more.")
