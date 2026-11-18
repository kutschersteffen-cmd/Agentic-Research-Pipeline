"""Layout-slide charts drawn by Vega-Lite (spec 2026-11-18-house-deck-vega-lite-charts, slice 2)."""

import io
import re
import subprocess
import sys

import pytest
from PIL import Image
from pptx import Presentation

from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_deck
from arp.schemas.chart_specs import ChartSpec
from arp.schemas.reporting import ColumnKind, DatasetColumn, Deck, QuantitativeDataset, ReportRequest, SlideContent

T = load_tokens()
DS = QuantitativeDataset(
    dataset_id="d", name="D",
    columns=[DatasetColumn(name="region", kind=ColumnKind.CATEGORY), DatasetColumn(name="sales"), DatasetColumn(name="cost")],
    rows=[{"region": "North", "sales": 12, "cost": 5}, {"region": "South", "sales": 8, "cost": 3}, {"region": "West", "sales": 15, "cost": 9}],
)
HEAT = {"y_column": "region", "category_column": "cost", "value_column": "sales"}
SALES = ["North | sales | 12", "South | sales | 8", "West | sales | 15"]


def L(chart_type, **kw):  # noqa: N802 -- the spec's name for the deck
    spec = ChartSpec(dataset_id="d", chart_type=chart_type, category_column="region", value_columns=["sales"]).model_copy(update=kw)
    return Deck(title="t", slides=[SlideContent(headline="h", layout="chart_takeaway", variant="full", chart=spec, slots={"takeaway": "x"})])


def chart_svg(deck, mode="light"):
    html = render_deck_html(deck, [DS], T, mode)
    start = html.index("<svg", html.index('data-slot="chart"'))
    return html[start : html.index("</svg>", start)]


def marks(svg):
    return re.findall(r'aria-label="([^"]*\| [^"]*)"', svg)


@pytest.mark.parametrize("kind", ["bar", "column", "stacked_column", "line", "area", "pie", "doughnut"])
def test_ac20_layout_marks(kind):
    svg = chart_svg(L(kind))
    assert 'class="marks"' in svg[: svg.index(">")] and marks(svg) == SALES


def test_ac20b_ac20c_ac20d_scatter_waterfall_heatmap():
    assert marks(chart_svg(L("scatter", x_column="cost"))) == ["5 | sales | 12", "3 | sales | 8", "9 | sales | 15"]
    assert marks(chart_svg(L("waterfall"))) == ["North | sales | +12", "South | sales | +8", "West | sales | +15"]
    assert marks(chart_svg(L("heatmap", **HEAT))) == ["North | 5 | 12", "South | 3 | 8", "West | 9 | 15"]


def test_ac21_ac21b_dark_text_size_and_label_colour():
    """Replaces test_chart_svg_uses_dark_ink_and_projector_sized_text (matplotlib SVG format)."""
    svg = chart_svg(L("bar"), "dark")
    tags = re.findall(r"<text[^>]*>([^<]*)</text>", svg)
    assert tags and len(re.findall(r'<text[^>]* font-size="24px"', svg)) == len(tags)
    fills = {t: f for f, t in re.findall(r'<text[^>]* fill="([^"]*)"[^>]*>([^<]*)</text>', svg)}
    assert {fills[c].lower() for c in ("North", "South", "West")} == {"#a3acbb"}


def test_ac22_radar_keeps_matplotlib():
    html = render_deck_html(L("radar"), [DS], T)
    slot = html[html.index('data-slot="chart"') :]
    assert slot[: slot.index("</div>")].count("<svg") == 1


@pytest.mark.parametrize("kind,kw", [("waterfall", {}), ("heatmap", HEAT)])
def test_ac23_pptx_picture_at_scale_2(tmp_path, kind, kw):
    prs = Presentation(build_house_pptx(L(kind, **kw), [DS], tmp_path / "d.pptx", T))
    shapes = [s for s in prs.slides[0].shapes if s.name.startswith("slot:chart")]
    assert [s.name for s in shapes] == ["slot:chart"] and not shapes[0].has_chart and shapes[0].shape_type == 13
    w, h = Image.open(io.BytesIO(shapes[0].image.blob)).size
    assert abs(w - 2 * shapes[0].width / T.emu_per_px) <= 1 and abs(h - 2 * shapes[0].height / T.emu_per_px) <= 1


def test_ac26_html_without_matplotlib():
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] == "matplotlib":
            raise ImportError(name)
sys.meta_path.insert(0, Block())
from tests.test_reporting_vega_layout import L, chart_svg, marks
for kind, kw in [("bar", {}), ("pie", {}), ("scatter", {"x_column": "cost"}), ("waterfall", {})]:
    assert len(marks(chart_svg(L(kind, **kw)))) == 3
assert "matplotlib" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_ac27_ac27b_chart_picture_finding():
    req = ReportRequest(title="t", qualitative_notes="", datasets=[DS])
    found = [f for f in lint_deck(L("waterfall"), req) if f.rule == "chart_picture"]
    assert [(f.slide, f.slot, f.stage, f.message) for f in found] == [
        (0, "chart", "lint", "waterfall chart is a picture in the PowerPoint: change its data in ARP and build again")]
    assert [f.message.split()[0] for f in lint_deck(L("heatmap", **HEAT), req) if f.rule == "chart_picture"] == ["heatmap"]
    assert not [f for f in lint_deck(L("pie"), req) if f.rule == "chart_picture"]
