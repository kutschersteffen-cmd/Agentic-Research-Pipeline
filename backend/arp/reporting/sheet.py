"""The slide-component review sheet: one fixture slide per visual, numbered like the mockups in
docs/superpowers/specs/assets/slide-components/, and `write_sheet` for `arp report sheet`.

Every number on a slide is in the datasets or NOTES, so lint finds nothing on the sheet.
Spec: docs/superpowers/specs/2026-11-15-slide-components-design.md, "Review sheet" and "Acceptance".
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

from PIL import Image

from arp.reporting.browser import write_pngs
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.render_model import render_slide
from arp.schemas.chart_specs import ChartSpec, TableSpec
from arp.schemas.reporting import DatasetColumn, Deck, QuantitativeDataset, SlideContent
from arp.schemas.visuals import (
    Callout,
    Chart,
    Column,
    ComparisonTable,
    Cover,
    Figure,
    Insight,
    KpiRow,
    NextAction,
    NextSteps,
    Points,
    Section,
    Tile,
    TwoColumn,
)

# Slide i is written as f"{SHEET_NAMES[i]}.png". Slide 4 keeps the mockup's name while it is a points slide (PR 1).
SHEET_NAMES = ["0-cover", "1-section", "2-kpi_row", "3-chart_insight", "4-step_flow", "5-comparison_table", "6-two_column",
               "7-next_steps", "8-line"]

NOTES = ("Sector funding cost rose to 6.2% from 3.9%, up 2.3 pts in a year. 30% of sector debt is due by 2027. Utilities trail "
         "the market by −7 pts, 7 pts behind; the market grew 11%, 2 pts more than in 2024, and utilities 4%. Two central-bank "
         "cuts lower yields 60 bp. Brightline trades below 14x earnings.")


def _ds(ds_id: str, name: str, cols: list[str], rows: list[tuple]) -> QuantitativeDataset:
    return QuantitativeDataset(dataset_id=ds_id, name=name, columns=[DatasetColumn(name=c) for c in cols],
                               rows=[dict(zip(cols, r, strict=True)) for r in rows])


def datasets() -> list[QuantitativeDataset]:
    quarters = ["Q1 24", "Q2 24", "Q3 24", "Q4 24", "Q1 25", "Q2 25", "Q3 25", "Q4 25"]
    return [
        _ds("eps", "EPS growth 2025", ["sector", "growth_pct"],
            [("Tech", 18), ("Financials", 12), ("Market", 11), ("Industrials", 9), ("Energy", 6), ("Utilities", 4)]),
        _ds("eps_q", "Sector earnings, quarterly", ["quarter", "utilities", "market"],
            list(zip(quarters, [9.1, 8.4, 7.0, 5.9, 5.2, 4.6, 4.1, 4.0], [11.5, 11.2, 11.0, 10.8, 10.9, 11.1, 11.0, 11.0], strict=True))),
        _ds("bridge", "EPS bridge 2024–2025", ["step", "value"],
            [("2024 EPS", 100), ("Funding cost", -14), ("Tariff lag", -6), ("Volume", 4), ("Opex", -2), ("2025 EPS", 82)]),
        _ds("segments", "Holdings segments", ["segment", "share"], [("Regulated networks", 58), ("Generation", 27), ("Retail", 15)]),
        _ds("names", "Utility holdings", ["Company", "Weight %", "EPS growth %", "Net debt / EBITDA", "Action"],
            [("Northgrid", 2.1, 7, 4.2, "Hold"), ("Solvane Power", 1.6, 5, 5.1, "Hold"), ("Eastwater", 1.2, 2, 6.0, "Engage"),
             ("Kestrel Gas", 0.9, -1, 5.8, "Engage"), ("Brightline", 0.7, 9, 3.4, "Add")]),
    ]


def _slide(headline: str, visual, kicker: str = "", subheading: str = "", refs: list[str] | None = None) -> SlideContent:
    return SlideContent(headline=headline, kicker=kicker, subheading=subheading, visual=visual, source_refs=refs or [])


def sheet_deck() -> tuple[Deck, list[QuantitativeDataset], str]:
    """Slides 0–8 of the sheet, the five fixture datasets and the fixture notes."""
    slides = [
        _slide("Utilities outlook 2026", Cover(
            title="Utilities outlook 2026", context="Stewardship committee · 15 Nov 2026",
            answer="Utilities trail the market by 7 points; rate resets in Q3 narrow the gap, so we add after them.",
            figures=[Figure(value="−7 pts", label="Earnings gap, 2025"), Figure(value="Q3", label="Turning point")]),
            subheading="Why we hold the underweight until rate reviews land"),
        _slide("Where the gap comes from", Section(
            number=2, title="Where the gap comes from", summary="Funding costs, slow tariff resets and three weak balance sheets",
            agenda=["The gap", "Causes", "Holdings", "Decision"])),
        _slide("Utilities grew earnings 7 points slower than the market in 2025", KpiRow(tiles=[
            Tile(value="4%", label="Utilities EPS growth", delta="▼ 7 pts vs market"),
            Tile(value="11%", label="Market EPS growth", delta="▲ 2 pts vs 2024"),
            Tile(value="6.2%", label="Sector funding cost", delta="▲ 2.3 pts in a year"),
            Tile(value="30%", label="Debt due by 2027", delta="Refinances at lower rates"),
        ], emphasis=0), kicker="The gap", subheading="Funding costs rose faster for utilities than for any other sector",
            refs=["eps", "Committee notes"]),
        _slide("Utilities posted the slowest earnings growth of six sectors", Chart(
            data=ChartSpec(dataset_id="eps", category_column="sector", value_columns=["growth_pct"]), kind="bar", unit="%",
            highlight="Utilities", insight=Insight(
                stat="−7 pts", headline="Slowest of six sectors, for the second year running",
                points=["Funding costs took most of the gap", "Tariffs reset every 3–5 years, so revenue trails rates"])),
            kicker="The gap", refs=["eps"]),
        _slide("Rate reviews land in the second half, so earnings turn late", Points(
            points=["Rates fall", "Refinancing", "Tariff resets", "Earnings turn"]),
            kicker="What changes", subheading="Four steps between today's rates and the first reset quarter",
            refs=["Central bank calendars", "regulator review schedules (2026)"]),
        _slide("Eastwater and Kestrel Gas carry the most debt and the least growth", ComparisonTable(
            table=TableSpec(dataset_id="names"), highlight_column="Net debt / EBITDA",
            total_row={"Weight %": "sum", "EPS growth %": "mean", "Net debt / EBITDA": "mean"}),
            kicker="Holdings", subheading="Two of five holdings sit at 5.8x and 6.0x net debt to EBITDA", refs=["names"]),
        _slide("Hold the underweight through Q2, then add after the Q3 rate reviews", TwoColumn(
            kpis=[Tile(value="−7 pts", label="EPS gap vs market"), Tile(value="2 pts", label="Current underweight"),
                  Tile(value="Q3", label="Review point")],
            left=Column(title="Why we stay underweight", points=[
                "Earnings trail the market by 7 points.", "Funding costs keep rising until Q2.",
                "Two holdings carry debt of 5.8x or more."]),
            right=Column(title="What makes us add", points=[
                "Q3 tariff resets lift allowed returns.", "Refinancing cuts interest on 30% of debt.",
                "Brightline trades below 14x earnings."])),
            kicker="Decision", refs=["Earlier slides 3–6"]),
        _slide("Four actions, one decision point in September", NextSteps(actions=[
            NextAction(text="Keep utilities 2 points underweight through Q2", owner="Portfolio team", when="Now"),
            NextAction(text="Engage Eastwater and Kestrel Gas on debt reduction", owner="Stewardship", when="Before Q3"),
            NextAction(text="Review the position after the Q3 rate decisions", owner="Committee", when="Sep 2026"),
            NextAction(text="Add Brightline on weakness below 14x earnings", owner="Portfolio team", when="Trigger"),
        ]), kicker="Next steps", subheading="Owner and timing for each", refs=["Committee proposal"]),
        _slide("Utility earnings growth has fallen for eight quarters while the market held at 11%", Chart(
            data=ChartSpec(dataset_id="eps_q", title="EPS growth", category_column="quarter", value_columns=["utilities", "market"]),
            kind="line", unit="%", highlight="utilities", callout=Callout(category="Q3 24", text="Funding costs start rising")),
            kicker="The gap", subheading="EPS growth, rolling 4 quarters, %", refs=["eps_q"]),
    ]
    return Deck(title="Utilities outlook 2026", slides=slides), datasets(), NOTES


def _plain(v):
    """Primitive fields as JSON values; floats rounded so the snapshot ignores sub-pixel float noise."""
    if isinstance(v, float):
        return round(v, 1)
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def sheet_snapshot(mode: str = "light") -> list[list[dict]]:
    """Every primitive of every sheet slide (type, name, box, colours, sizes, text), the review sheet's golden."""
    deck, ds, _ = sheet_deck()
    by_id = {d.dataset_id: d for d in ds}
    return [[{"type": type(p).__name__, **_plain(dataclasses.asdict(p))} for p in render_slide(s, i, deck, load_tokens(), by_id, mode)]
            for i, s in enumerate(deck.slides)]


def write_sheet(out: Path) -> list[Path]:
    """One 1920×1080 PNG per sheet slide, named like the mockups, plus `sheet.png`: two columns at half size."""
    deck, data, _ = sheet_deck()
    pages = asyncio.run(write_pngs(render_deck_html(deck, data), out, scale=1))
    paths = [page.replace(out / f"{name}.png") for page, name in zip(pages, SHEET_NAMES, strict=True)]
    w, h = 960, 540
    sheet = Image.new("RGB", (2 * w, h * ((len(paths) + 1) // 2)), "white")
    for i, p in enumerate(paths):
        with Image.open(p) as im:
            sheet.paste(im.convert("RGB").resize((w, h), Image.LANCZOS), ((i % 2) * w, (i // 2) * h))
    sheet.save(out / "sheet.png")
    return [*paths, out / "sheet.png"]
