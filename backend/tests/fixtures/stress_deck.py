"""One slide per layout x variant, every text slot at its max_words (or 1 word), for fit tuning.

"short" puts each slot that steps up a type role at exactly short_words words (its largest text), the rest at max.
At committee density, slots with committee_words are filled to that instead. Structured committee slots get valid
`a :: b` items at their limits (see _structured)."""

from typing import Literal

from arp.reporting.house_style import load_layouts
from arp.schemas.reporting import ChartSpec, ColumnKind, DatasetColumn, Deck, QuantitativeDataset, SlideContent, TableSpec

_WORD = "dolore"  # 6 chars: average English word length incl. the space


def _w(n: int) -> str:
    return " ".join([_WORD] * n)


def _structured(layout: str, slot: str, small: bool) -> list[str] | None:
    """Valid items at the slot's word/item limits (or the smallest valid set); None for a plain list slot."""
    tree = (["q :: dolore? :: a :: b", "a :: =dolore :: high", "b :: =dolore :: low"] if small else
            [f"q{i} :: {_w(6)} :: {f'q{i + 1}' if i < 3 else 'end'} :: o{i}" for i in range(4)]
            + ["end :: =" + _w(6) + " :: high"] + [f"o{i} :: ={_w(6)} :: {s}" for i, s in enumerate(["low", "mid", "neutral", "low"])])
    return {
        ("flow", "items"): ["dolore :: dolore"] * 2 if small else [f"{_w(2)} :: {_w(4)} :: *{_w(4)} :: {_w(4)}"] * 5,
        ("profile", "meters"): ["dolore :: 5%"] if small else [f"{_w(4)} :: 100%"] * 6,
        ("scatter_zone", "items"): ["+1 :: dolore"] if small else [f"+1,234 :: {_w(14)}"] * 3,
        ("matrix2x2", "quadrants"): [f"dolore :: dolore :: dolore :: {s}" for s in ("low", "high", "mid", "neutral")] if small
        else [f"{_w(3)} :: {_w(3)} :: {_w(10)} :: {s}" for s in ("low", "high", "mid", "neutral")],
        ("tree", "items"): tree,
        ("decisions", "items"): ["dolore :: dolore"] if small else [f"{_w(5)} :: {_w(14)}"] * 5,
    }.get((layout, slot))


def stress_deck(mode: Literal["max", "min", "short"], density: Literal["present", "committee"] = "present") -> tuple[Deck, list[QuantitativeDataset]]:
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
                limit = (s.committee_words if density == "committee" else None) or s.max_words
                n = 1 if mode == "min" else (s.short_words if mode == "short" and s.short_words and density == "present" else limit) or 1
                words = _w(n)
                if (items := _structured(layout.id, s.name, mode == "min")) is not None:
                    slots[s.name] = items
                elif s.kind == "list":
                    slots[s.name] = [words] * (1 if mode == "min" else s.max_items or 1)
                elif s.kind == "number":
                    slots[s.name] = "1,234%"
                elif s.kind == "text":
                    slots[s.name] = words
                elif s.kind == "chart" and layout.id == "scatter_zone":
                    slide.chart = ChartSpec(dataset_id="stress", chart_type="scatter", x_column="a", value_columns=["b"], category_column="cat",
                                            zone=[20, 35, 25, 40], diagonal=True)
                elif s.kind == "chart":
                    slide.chart = ChartSpec(dataset_id="stress", chart_type="column", category_column="cat", value_columns=["a", "b"])
                elif s.kind == "table":
                    slide.table = TableSpec(dataset_id="stress", max_rows=8, heat={"a": [15, 25]} if variant.id == "heat" else {})
            slide.slots = slots
            slides.append(slide)
    return Deck(title="Stress", slides=slides), [ds]
