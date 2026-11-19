"""Typed visual calls for house-deck slides. Limits are what the AI may return; overflow within them is the fit ladder's job."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator

from arp.schemas.chart_specs import ChartSpec, TableSpec


def _words(n: int):
    def check(v: str) -> str:
        if len(v.split()) > n:
            raise ValueError(f"at most {n} words")
        return v
    return AfterValidator(check)


def _chars(n: int):
    def check(v: str) -> str:
        if len(v) > n:
            raise ValueError(f"at most {n} characters")
        return v
    return AfterValidator(check)


def Words(n: int):  # noqa: N802 - reads like a type
    return Annotated[str, _words(n)]


def Chars(n: int):  # noqa: N802
    return Annotated[str, _chars(n)]


class Figure(BaseModel):
    value: Chars(8)
    label: Words(4)


class Tile(BaseModel):
    value: Chars(8)
    label: Words(5)
    delta: Words(6) = ""


class Callout(BaseModel):
    category: str
    text: Words(8)


class Insight(BaseModel):
    stat: Chars(8)
    headline: Words(12)
    points: list[str] = Field(default_factory=list, max_length=2)


class SectionPlan(BaseModel):
    title: Words(6)
    summary: Words(14) = ""


class NextAction(BaseModel):
    text: Words(12)
    owner: Words(3) = ""
    when: Chars(10) = ""


class Column(BaseModel):
    title: Words(5)
    points: list[Words(14)] = Field(min_length=2, max_length=4)


class Cover(BaseModel):
    type: Literal["cover"] = "cover"
    title: Words(10)
    context: Words(8) = ""
    answer: Words(30) = ""
    figures: list[Figure] = Field(default_factory=list, max_length=2)


class Section(BaseModel):
    type: Literal["section"] = "section"
    number: int
    title: Words(6)
    summary: Words(14) = ""
    agenda: list[str] = Field(default_factory=list, description="Filled by code.")


class KpiRow(BaseModel):
    type: Literal["kpi_row"] = "kpi_row"
    tiles: list[Tile] = Field(min_length=2, max_length=4)
    emphasis: int | None = None  # out of range is dropped later with a finding, not rejected here


class Chart(BaseModel):
    type: Literal["chart"] = "chart"
    data: ChartSpec
    kind: Literal["bar", "column", "stacked_column", "line", "waterfall"]
    unit: Chars(6) = ""
    data_labels: bool = True
    highlight: str | None = None
    callout: Callout | None = None
    insight: Insight | None = None

    @model_validator(mode="after")
    def _series(self):
        if not 1 <= len(self.data.value_columns) <= 3:
            raise ValueError("a chart plots 1 to 3 value columns")
        if self.kind == "waterfall" and len(self.data.value_columns) != 1:
            raise ValueError("a waterfall plots 1 value column")
        return self


class ComparisonTable(BaseModel):
    type: Literal["comparison_table"] = "comparison_table"
    table: TableSpec
    highlight_column: str | None = None
    total_row: dict[str, Literal["sum", "mean", "none"]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _size(self):
        if self.table.columns and not 2 <= len(self.table.columns) <= 6:
            raise ValueError("a table has 2 to 6 columns")
        if "max_rows" not in self.table.model_fields_set:  # TableSpec's default (20) means "all rows, up to 8" here
            self.table = self.table.model_copy(update={"max_rows": 8})
        if self.table.max_rows > 8:
            raise ValueError("a table shows at most 8 rows")
        return self


class TwoColumn(BaseModel):
    type: Literal["two_column"] = "two_column"
    kpis: list[Tile] = Field(default_factory=list, max_length=3)
    left: Column
    right: Column


class Points(BaseModel):
    type: Literal["points"] = "points"
    points: list[Words(20)] = Field(min_length=3, max_length=6)
    emphasis: int | None = None


class NextSteps(BaseModel):
    type: Literal["next_steps"] = "next_steps"
    actions: list[NextAction] = Field(min_length=2, max_length=5)
    emphasis: int | None = 0


class FlowStep(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")]
    label: Annotated[Words(5), Field(pattern=r"\S")]
    tag: Chars(24) = ""
    kind: Literal["step", "decision", "data"] = "step"
    actor: str | None = None
    stored: bool = False


class FlowArrow(BaseModel):
    source: str
    target: str
    label: Words(3) = ""


class FlowBox(BaseModel):
    """A rectangle in canvas px."""

    x: float
    y: float
    w: float
    h: float


class FlowStepLayout(BaseModel):
    id: str
    box: FlowBox
    label_lines: list[str]


class FlowArrowLayout(BaseModel):
    points: list[tuple[float, float]]  # the route, source border to target border
    label_box: FlowBox | None = None


class FlowLayout(BaseModel):
    """Filled by code (`layout_flows`), never by the model. All positions are absolute canvas px."""

    type_step: Literal[0, 1] = 0
    wrapped: bool = False
    too_big: bool = False
    width: float = 0
    height: float = 0
    steps: list[FlowStepLayout] = Field(default_factory=list)  # in `steps` order
    arrows: list[FlowArrowLayout] = Field(default_factory=list)  # in `arrows` order


class Flow(BaseModel):
    type: Literal["flow"] = "flow"
    mermaid: str = ""
    direction: Literal["LR", "TB"] = "LR"
    steps: list[FlowStep] = Field(min_length=2, max_length=12)
    actors: list[str] = Field(default_factory=list, max_length=4)
    arrows: list[FlowArrow] = Field(default_factory=list, max_length=20)
    emphasis: str | None = None
    layout: FlowLayout | None = None

    @model_validator(mode="before")
    @classmethod
    def _parse_mermaid(cls, data):
        if isinstance(data, dict) and isinstance(data.get("mermaid"), str) and data["mermaid"].strip():
            from arp.reporting.mermaid_flow import MermaidError, parse_mermaid

            try:
                parsed = parse_mermaid(data["mermaid"])
            except MermaidError as e:
                raise ValueError(str(e)) from None
            data = {**data, **parsed.model_dump(include={"direction", "steps", "actors", "arrows", "emphasis"})}
        return data

    @model_validator(mode="after")
    def _consistent(self):
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        pairs = [(a.source, a.target) for a in self.arrows]
        for a in self.arrows:
            if a.source not in ids or a.target not in ids:
                raise ValueError(f"arrow {a.source}→{a.target} names an unknown step")
            if a.source == a.target:
                raise ValueError(f"arrow {a.source}→{a.target}: a step cannot point to itself")
        if len(set(pairs)) != len(pairs):
            raise ValueError("an arrow appears twice")
        for s in self.steps:
            if s.actor is not None and s.actor not in self.actors:
                raise ValueError(f"step {s.id}: actor {s.actor} is not in actors")
            if self.actors and s.actor is None:
                raise ValueError(f"step {s.id} has no actor; give every step an actor or none")
        if self.emphasis is not None and self.emphasis not in ids:
            raise ValueError(f"emphasis {self.emphasis} is not a step id")
        return self


Visual = Annotated[Cover | Section | KpiRow | Chart | ComparisonTable | TwoColumn | Points | NextSteps | Flow, Field(discriminator="type")]

FRIENDLY_NAMES: dict[str, str] = {
    "cover": "Cover",
    "section": "Section divider",
    "kpi_row": "KPI row",
    "chart": "Chart",
    "comparison_table": "Comparison table",
    "two_column": "Two columns",
    "points": "Key points",
    "next_steps": "Next steps",
    "flow": "Flowchart",
}
