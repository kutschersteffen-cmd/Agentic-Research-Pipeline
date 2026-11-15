"""Review sheet: fixture slides 0–8, `arp report sheet` and the golden PNGs (spec 2026-11-15-slide-components)."""

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from arp.reporting.browser import _page
from arp.reporting.design_checks import design_checks
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_deck
from arp.reporting.sheet import SHEET_NAMES, sheet_deck
from arp.schemas.reporting import ReportRequest
from tests.test_render_writers import _pptx_boxes

GOLDEN = Path(__file__).parent / "golden" / "slides"
NAMES = ["0-cover", "1-section", "2-kpi_row", "3-chart_insight", "4-step_flow", "5-comparison_table", "6-two_column",
         "7-next_steps", "8-line"]
RESERVED = ["ea4c14", "85601a", "d4a650", "13804f", "c8323f", "4fd69c", "ff6b7a", "2563c9"]
DESIGN_RULES = {"underfill", "small_text", "low_contrast", "emphasis_count"}


@pytest.fixture(scope="module")
def sheet_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("sheet")
    env = {k: v for k, v in os.environ.items() if k != "ARP_POSTGRES_DSN"}  # the sheet needs no database
    result = subprocess.run([sys.executable, "-m", "arp", "report", "sheet", "--out", str(out)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return out


def test_sheet_deck_shape():
    deck, datasets, notes = sheet_deck()
    assert [s.visual.type for s in deck.slides] == ["cover", "section", "kpi_row", "chart", "points", "comparison_table",
                                                    "two_column", "next_steps", "chart"]
    assert {d.dataset_id for d in datasets} == {"eps", "eps_q", "bridge", "segments", "names"}
    assert notes.startswith("Sector funding cost rose to 6.2% from 3.9%")
    assert deck.slides[3].source_refs == ["eps"]
    assert SHEET_NAMES == NAMES


def test_sheet_is_lint_clean():
    deck, datasets, notes = sheet_deck()
    assert lint_deck(deck, ReportRequest(title=deck.title, qualitative_notes=notes, datasets=datasets)) == []


def test_ac18_cli(sheet_dir):
    assert sorted(p.name for p in sheet_dir.iterdir()) == sorted([f"{n}.png" for n in NAMES] + ["sheet.png"])
    for n in NAMES:
        with Image.open(sheet_dir / f"{n}.png") as im:
            assert im.size == (1920, 1080), n
    with Image.open(sheet_dir / "sheet.png") as im:
        assert im.size == (1920, 540 * 5)  # two columns at half size


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ac12_sheet_clean(mode):
    deck, datasets, _ = sheet_deck()
    found = [f for f in design_checks(deck, datasets, mode=mode) if f.rule in DESIGN_RULES]
    assert found == []


def test_sheet_dark_has_no_contrast_findings():
    deck, datasets, _ = sheet_deck()
    assert [f for f in design_checks(deck, datasets, mode="dark") if f.rule == "low_contrast"] == []


_COLOURS_JS = """() => [...document.querySelectorAll('section.slide, section.slide *')].flatMap(el => {
  const s = getComputedStyle(el);
  return [s.color, s.backgroundColor, s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor, s.fill,
          s.stroke, s.outlineColor, s.webkitTextStrokeColor];
})"""


def _hex(css: str) -> str | None:
    m = re.match(r"rgba?\((\d+), (\d+), (\d+)", css)
    return "".join(f"{int(v):02x}" for v in m.groups()) if m else None


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_ac24_no_reserved_colours(tmp_path, mode):
    deck, datasets, _ = sheet_deck()
    with zipfile.ZipFile(build_house_pptx(deck, datasets, tmp_path / "d.pptx", mode=mode)) as z:
        parts = [n for n in z.namelist() if re.match(r"ppt/(slides|charts)/[^/]+\.xml$", n)]
        assert any("charts/" in n for n in parts)
        xml = "".join(z.read(n).decode() for n in parts).lower()
    async with _page(render_deck_html(deck, datasets, mode=mode)) as page:
        css = {h for c in await page.evaluate(_COLOURS_JS) if (h := _hex(c))}
    assert len(css) > 3
    for hexa in RESERVED:
        assert hexa not in xml, hexa
        assert hexa not in css, hexa


async def test_ac1_sheet_boxes_match(tmp_path):
    deck, datasets, _ = sheet_deck()
    out = build_house_pptx(deck, datasets, tmp_path / "d.pptx")
    async with _page(render_deck_html(deck, datasets)) as page:
        html = await page.evaluate("""() => [...document.querySelectorAll('section.slide')].map(sec => Object.fromEntries(
            [...sec.querySelectorAll('[data-name]')].map(el => { const r = el.getBoundingClientRect(), s = sec.getBoundingClientRect();
                return [el.dataset.name, [r.left - s.left, r.top - s.top, r.width, r.height]]; })))""")
    assert len(html) == len(deck.slides)
    for i, boxes in enumerate(html):
        pptx = _pptx_boxes(out, i)
        assert set(boxes) == set(pptx), i
        for name, box in boxes.items():
            assert box == pytest.approx(list(pptx[name]), abs=1), (i, name)


def _diff_share(a: Path, b: Path) -> float:
    with Image.open(a) as x, Image.open(b) as y:
        assert x.size == y.size, a.name
        diff = ImageChops.difference(x.convert("RGB"), y.convert("RGB"))
    # a pixel differs when any channel is off by more than 16/255
    mask = Image.merge("RGB", [ch.point(lambda v: 255 if v > 16 else 0) for ch in diff.split()]).convert("L").point(lambda v: 255 if v else 0)
    return mask.histogram()[255] / (mask.width * mask.height)


def test_sheet_matches_goldens(sheet_dir):
    goldens = sorted(GOLDEN.glob("*.png"))
    assert {g.stem for g in goldens} == {*NAMES, "sheet"}
    shares = {g.name: _diff_share(sheet_dir / g.name, g) for g in goldens}
    off = [f"{name}: {share:.2%}" for name, share in shares.items() if share > 0.005]  # every differing PNG, not the first
    assert not off, "pixels differ from the goldens: " + ", ".join(off)
