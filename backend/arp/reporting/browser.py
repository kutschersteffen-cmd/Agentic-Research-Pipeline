"""Headless-Chromium side of the HTML deck: fit measurement, PDF and PNG output.

One browser launch per call. Fit rules are computed from a single in-page
script that reads every slot's box and scroll size; collisions and off-grid
are then judged in Python against the tokens.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from arp.config import Settings
from arp.reporting.house_style import load_tokens
from arp.schemas.reporting import Finding

_TOL = 1.5  # px slack for sub-pixel layout rounding

_SLOTS_JS = """() => [...document.querySelectorAll('[data-slot]')].map(el => {
  const s = el.closest('section').getBoundingClientRect(), r = el.getBoundingClientRect();
  return {slide: +el.dataset.slide, slot: el.dataset.slot, x: r.left - s.left, y: r.top - s.top, w: r.width, h: r.height,
          sh: el.scrollHeight, ch: el.clientHeight, sw: el.scrollWidth, cw: el.clientWidth, err: el.dataset.error || null};
})"""


class BrowserUnavailable(RuntimeError):
    pass


@asynccontextmanager
async def _page(html: str, scale: float = 1.0):
    t = load_tokens().canvas
    async with async_playwright() as p:
        try:
            # Settings() read per call so ARP_CHROMIUM_PATH changes take effect without a restart.
            browser = await p.chromium.launch(executable_path=Settings().chromium_path)
        except PlaywrightError as e:
            raise BrowserUnavailable(
                "Chromium is not available for the HTML deck renderer. Run `python -m playwright install chromium`, "
                f"or point ARP_CHROMIUM_PATH at an existing Chromium binary. ({str(e).splitlines()[0]})"
            ) from e
        try:
            page = await browser.new_page(viewport={"width": t.width, "height": t.height}, device_scale_factor=scale)
            await page.set_content(html)
            await page.evaluate("document.fonts.ready")
            yield page
        finally:
            await browser.close()


async def measure(html: str) -> list[Finding]:
    tokens = load_tokens()
    g, w, h = tokens.grid, tokens.canvas.width, tokens.canvas.height
    safe = (g.margin_x, g.margin_top + g.headline_band, w - g.margin_x, h - g.margin_bottom - g.footer_band)
    async with _page(html) as page:
        boxes = await page.evaluate(_SLOTS_JS)
    out: list[Finding] = []

    def add(b, rule, msg):
        out.append(Finding(slide=b["slide"], slot=b["slot"], stage="fit", rule=rule, message=msg))

    for b in boxes:
        if b["err"]:  # a structured slot that did not parse and was drawn as a plain list
            out.append(Finding(slide=b["slide"], slot=b["slot"], stage="data", rule="bad_structure", message=b["err"]))
        if b["sh"] > b["ch"] + _TOL:
            add(b, "overflow", f"ratio={b['sh'] / b['ch']:.2f}")
        if b["sw"] > b["cw"] + _TOL:
            add(b, "overflow_x", f"content {b['sw']}px wide in a {b['cw']}px slot")
        if b["slot"] not in ("headline", "eyebrow") and (b["x"] < safe[0] - _TOL or b["y"] < safe[1] - _TOL or b["x"] + b["w"] > safe[2] + _TOL or b["y"] + b["h"] > safe[3] + _TOL):
            add(b, "off_grid", "slot box leaves the grid's safe area")
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            if a["slide"] == b["slide"] and a["x"] < b["x"] + b["w"] - _TOL and b["x"] < a["x"] + a["w"] - _TOL \
                    and a["y"] < b["y"] + b["h"] - _TOL and b["y"] < a["y"] + a["h"] - _TOL:
                add(b, "collision", f"overlaps {a['slot']}")
    return out


async def write_pdf(html: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    async with _page(html) as page:
        await page.pdf(path=str(out), width="1920px", height="1080px", print_background=True)
    return out


async def write_pngs(html: str, out_dir: Path, scale: float = 0.5) -> list[Path]:
    """One page-NNN.png per slide. Call after write_pdf so the PNGs' mtime is newer than the PDF's
    (preview.ensure_preview_images treats them as fresh); zero padding keeps sorted() right past 9 slides."""
    out_dir.mkdir(parents=True, exist_ok=True)
    async with _page(html, scale) as page:
        paths = []
        for n, el in enumerate(await page.query_selector_all("section.slide"), 1):
            paths.append(out_dir / f"page-{n:03d}.png")
            await el.screenshot(path=str(paths[-1]))
    return paths
