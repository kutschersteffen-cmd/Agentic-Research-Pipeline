"""One slide per layout x variant, every text slot at its max_words (or 1 word), for fit tuning.

"short" puts each slot that steps up a type role at exactly short_words words (its largest text), the rest at max."""

from typing import Literal

from arp.reporting.house_style import load_layouts
from arp.schemas.reporting import ChartSpec, ColumnKind, DatasetColumn, Deck, QuantitativeDataset, SlideContent, TableSpec

_WORD = "dolore"  # 6 chars: average English word length incl. the space


def stress_deck(mode: Literal["max", "min", "short"]) -> tuple[Deck, list[QuantitativeDataset]]:
    ds = QuantitativeDataset(
        dataset_id="stress", name="Stress",
        columns=[DatasetColumn(name="cat", kind=ColumnKind.CATEGORY), DatasetColumn(name="a"), DatasetColumn(name="b")],
        rows=[{"cat": f"Category {i}", "a": 10 + i * 3, "b": 40 - i * 2} for i in range(8)],
    )
    slides = []
    for layout in load_layouts().values():
        for variant in layout.variants:
            slots: dict[str, str | list[str]] = {}
            slide = SlideContent(headline=" ".join([_WORD] * (1 if mode == "min" else 14)), layout=layout.id, variant=variant.id)
            for s in variant.slots:
                n = 1 if mode == "min" else (s.short_words if mode == "short" and s.short_words else s.max_words) or 1
                words = " ".join([_WORD] * n)
                if s.kind == "list":
                    slots[s.name] = [words] * (1 if mode == "min" else s.max_items or 1)
                elif s.kind == "number":
                    slots[s.name] = "1,234%"
                elif s.kind == "text":
                    slots[s.name] = words
                elif s.kind == "chart":
                    slide.chart = ChartSpec(dataset_id="stress", chart_type="column", category_column="cat", value_columns=["a", "b"])
                elif s.kind == "table":
                    slide.table = TableSpec(dataset_id="stress", max_rows=8)
            slide.slots = slots
            slides.append(slide)
    return Deck(title="Stress", slides=slides), [ds]
