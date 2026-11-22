"""Refine chat, deck operations: the model's ops applied to a Deck in one pure step.
Slide numbers in `ops` are positions at the start of the turn; results use positions after it."""

from __future__ import annotations

import re

from arp.reporting.chart_builder import build_native_chart_data, is_native, render_chart_svg
from arp.reporting.house_style import get_variant, load_layouts, load_tokens
from arp.reporting.html_render import theme_from_tokens
from arp.reporting.vega import layout_spec, to_svg
from arp.schemas.reporting import ChartType, Deck, QuantitativeDataset, SlideContent

NO_DECK = "This report has no deck yet. Approve its storyline in Report Builder first."
NO_SUCH_SLIDE, NO_SUCH_SLOT, NO_SUCH_VARIANT = "no such slide", "no such slot", "no such variant"
NO_SUCH_POSITION, NO_TEXT, NO_CHART = "no such position", "no text", "no chart"
DOES_NOT_FIT = "chart type does not fit the data"
UNKNOWN_OP = "unknown op"
_TEXT_KINDS = {"text", "list", "number"}
_CONTENT = ("set_text", "set_headline", "set_variant", "set_chart_type")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(t.replace(",", "")) for t in _NUMBER.findall(text)}


def _slide_text(s: SlideContent) -> str:
    return " ".join([s.headline, *(v if isinstance(v, str) else " ".join(v) for v in s.slots.values())])


def _fits(slide: SlideContent, chart_type: str, datasets: list[QuantitativeDataset]) -> bool:
    """Builds the chart the way the preview (`html_render._slot_view`) and the pptx export do."""
    spec = slide.chart.model_copy(update={"chart_type": ChartType(chart_type)})
    tokens = load_tokens()
    theme = theme_from_tokens(tokens)
    try:
        if is_native(spec):
            build_native_chart_data(spec, datasets)
        if spec.chart_type in (ChartType.RADAR, ChartType.TABLE):
            render_chart_svg(spec, datasets, width_px=800, height_px=450, theme=theme)
        else:
            to_svg(layout_spec(spec, datasets, 800, 450, theme, tokens, "light"), tokens)
    except Exception:  # noqa: BLE001 -- any failure to build or draw means the type does not fit
        return False
    return True


def apply_deck_ops(deck: Deck, ops: list[dict], datasets: list[QuantitativeDataset], findings_text: str) -> tuple[Deck, dict]:
    deck = deck.model_copy(deep=True)
    slides = list(deck.slides)
    start = list(slides)
    before = {id(s): _slide_text(s) for s in start}
    known = _numbers(findings_text) | {n for ds in datasets for row in ds.rows for v in row.values() for n in _numbers(str(v))}
    changed: list[SlideContent] = []
    skipped: list[tuple[int, SlideContent | None, object, str]] = []
    unbacked: list[SlideContent] = []

    def slide_of(op: dict) -> SlideContent | None:
        n = op.get("slide")
        if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(start):
            return start[n - 1]
        return None

    def written(s: SlideContent, text: str | list[str]) -> None:
        new = text if isinstance(text, str) else " ".join(text)
        if not _numbers(new) <= known | _numbers(before[id(s)]):
            unbacked.append(s)

    def content(op: dict, s: SlideContent) -> str | None:
        """None when applied, else the skip reason."""
        kind = op.get("op")
        if kind in ("set_text", "set_headline"):
            text = op.get("text")
            if kind == "set_text":
                spec = next((x for x in _variant_slots(s) if x.name == op.get("slot")), None)
                if spec is None or spec.kind not in _TEXT_KINDS:
                    return NO_SUCH_SLOT
                is_list = isinstance(text, list) and all(isinstance(t, str) for t in text)
                if not (is_list if spec.kind == "list" else isinstance(text, str)):
                    return NO_TEXT
                s.slots[spec.name] = text
            else:
                if not isinstance(text, str):
                    return NO_TEXT
                s.headline = text
            written(s, text)
        elif kind == "set_variant":
            layout = load_layouts().get(s.layout)
            if layout is None or not isinstance(op.get("variant"), str) or op["variant"] not in {v.id for v in layout.variants}:
                return NO_SUCH_VARIANT
            s.variant = op["variant"]
        else:  # set_chart_type
            if s.chart is None:
                return NO_CHART
            if not isinstance(op.get("chart_type"), str) or op["chart_type"] not in {t.value for t in ChartType} or not _fits(s, op["chart_type"], datasets):
                return DOES_NOT_FIT
            s.chart.chart_type = ChartType(op["chart_type"])
        return None

    def _variant_slots(s: SlideContent) -> list:
        try:
            return get_variant(s.layout, s.variant).slots
        except KeyError:
            return []

    for i, op in enumerate(ops):
        if op.get("op") not in _CONTENT:
            continue
        s = slide_of(op)
        reason = NO_SUCH_SLIDE if s is None else content(op, s)
        if reason:
            skipped.append((i, s, op.get("slide"), reason))
        else:
            changed.append(s)
    for i, op in enumerate(ops):
        if op.get("op") not in ("move_slide", "delete_slide"):
            continue
        s = slide_of(op)
        to = op.get("to")
        if s is None or not any(x is s for x in slides):
            skipped.append((i, None, op.get("slide"), NO_SUCH_SLIDE))
        elif op["op"] == "delete_slide":
            slides = [x for x in slides if x is not s]
        elif not isinstance(to, int) or isinstance(to, bool) or not 1 <= to <= len(slides):
            skipped.append((i, s, op.get("slide"), NO_SUCH_POSITION))
        else:
            slides = [x for x in slides if x is not s]
            slides.insert(to - 1, s)
            changed.append(s)
    for i, op in enumerate(ops):
        if op.get("op") not in (*_CONTENT, "move_slide", "delete_slide"):
            skipped.append((i, None, op.get("slide"), UNKNOWN_OP))

    deck.slides = slides
    pos = {id(s): i + 1 for i, s in enumerate(slides)}
    not_changed = []
    for _, s, raw, reason in sorted(skipped, key=lambda x: x[0]):
        if s is None:
            not_changed.append({"id": raw, "reason": reason})
        elif id(s) in pos:  # a slide deleted later in the turn is reported nowhere
            not_changed.append({"id": pos[id(s)], "reason": reason})
    return deck, {
        "changed": sorted({pos[id(s)] for s in changed if id(s) in pos}),
        "not_changed": not_changed,
        "check_figures": sorted({pos[id(s)] for s in unbacked if id(s) in pos}),
    }
