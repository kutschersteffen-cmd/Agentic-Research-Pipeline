"""Headless-Chromium side of the HTML deck: fit measurement, PDF and PNG output.

One browser launch per call. Fit and design rules are computed from a single
in-page script that reads every slot's box, scroll size and content rects;
collisions, off-grid and the design rules are then judged in Python against the tokens.
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

# One evaluate: every slot's box (fit) plus its content rects -- each line of text (a Range over its text nodes), every
# table and image, and the drawn part of every chart or diagram svg -- clipped to the slot. Boxes, tints and rules are
# decoration and never count; and per
# slide the rendered anchor, the word count and the smallest and largest text outside data-chrome (svg text scaled).
_MEASURE_JS = """() => {
  const range = document.createRange();
  const texts = root => { const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), out = [];
    for (let n; (n = w.nextNode());) if (n.textContent.trim()) out.push(n); return out; };
  const slots = [...document.querySelectorAll('[data-slot]')].map(el => {
    const s = el.closest('section').getBoundingClientRect(), r = el.getBoundingClientRect();
    const clip = q => { const x0 = Math.max(q.left, r.left), y0 = Math.max(q.top, r.top), x1 = Math.min(q.right, r.right), y1 = Math.min(q.bottom, r.bottom);
      return x1 > x0 && y1 > y0 ? [x0 - s.left, y0 - s.top, x1 - x0, y1 - y0] : null; };
    const rects = texts(el).flatMap(n => { range.selectNodeContents(n); return [...range.getClientRects()].map(clip); });
    for (const e of el.querySelectorAll('table, img')) rects.push(clip(e.getBoundingClientRect()));
    for (const svg of el.querySelectorAll('svg:not(svg *)')) {  // what is drawn, not the canvas: skip defs and matplotlib's figure patch
      const marks = [...svg.querySelectorAll('path, rect, line, polyline, polygon, circle, ellipse, text, image, use')]
        .filter(e => !e.closest('defs, clipPath, #patch_1')).map(e => e.getBoundingClientRect()).filter(q => q.width || q.height);
      if (marks.length) rects.push(clip({left: Math.min(...marks.map(q => q.left)), top: Math.min(...marks.map(q => q.top)),
                                         right: Math.max(...marks.map(q => q.right)), bottom: Math.max(...marks.map(q => q.bottom))}));
    }
    return {slide: +el.dataset.slide, slot: el.dataset.slot, x: r.left - s.left, y: r.top - s.top, w: r.width, h: r.height,
            sh: el.scrollHeight, ch: el.clientHeight, sw: el.scrollWidth, cw: el.clientWidth, err: el.dataset.error || null, rects: rects.filter(Boolean)};
  });
  const slides = [...document.querySelectorAll('section.slide')].map(sec => {
    const sizes = [];
    for (const n of texts(sec)) {
      const e = n.parentElement, m = e instanceof SVGElement && e.getScreenCTM?.();
      if (!e.closest('[data-chrome], style, title, metadata, defs')) sizes.push([parseFloat(getComputedStyle(e).fontSize) * (m ? Math.hypot(m.a, m.b) : 1), e.closest('[data-slot]')?.dataset.slot ?? null]);
    }
    for (const e of sec.querySelectorAll('*:not([data-chrome], [data-chrome] *)')) {
      const b = getComputedStyle(e, '::before');
      if (!['none', 'normal', '""'].includes(b.content)) sizes.push([parseFloat(b.fontSize), e.closest('[data-slot]')?.dataset.slot ?? null]);
    }
    sizes.sort((a, b) => a[0] - b[0]);
    return {slide: +sec.dataset.slide, layout: sec.dataset.layout, anchor: sec.dataset.anchor, words: +sec.dataset.words,
            min: sizes[0] ?? null, max: sizes.at(-1) ?? null};
  });
  return {density: document.body.dataset.density, slots, slides};
}"""


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
        got = await page.evaluate(_MEASURE_JS)
    boxes = got["slots"]
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
    return out + _design(got, tokens)


SPARSE = {"present": 0.55, "committee": 0.70}  # least share of the body height the content must span
DENSE = {"present": 60, "committee": 180}  # most words a slide may hold


def _design(got: dict, tokens) -> list[Finding]:
    """Spec §3's rules on the measured content: thresholds verbatim, in px of the 1920x1080 canvas."""
    g = tokens.grid
    top = g.margin_top + g.headline_band
    body_h = tokens.canvas.height - g.margin_bottom - g.footer_band - top
    out: list[Finding] = []
    for sl in got["slides"]:
        i = sl["slide"]

        def add(rule, msg, slot=None):
            out.append(Finding(slide=i, slot=slot, stage="design", rule=rule, message=msg))  # noqa: B023 -- called in this iteration

        body = {b["slot"]: b["rects"] for b in got["slots"] if b["slide"] == i and b["slot"] not in ("headline", "eyebrow") and b["rects"]}
        rects = [r for rs in body.values() for r in rs]
        if i and sl["layout"] != "section":  # the title and section slides are display slides, exempt from both
            span = (max(y + h for _, y, _, h in rects) - min(y for _, y, _, _ in rects)) / body_h if rects else 0.0
            if span < SPARSE[got["density"]]:
                add("sparse", f"content spans {span:.2f} of the body height < {SPARSE[got['density']]:.2f}")
            if rects and sl["anchor"] == "middle":
                mass = sum(w * h for _, _, w, h in rects)
                off = abs(sum(w * h * (y + h / 2) for _, y, w, h in rects) / mass - (top + body_h / 2)) / body_h
                if off > 0.20:
                    add("unbalanced", f"content centre {off:.2f} of the body height off its middle anchor > 0.20")
        if sl["min"] and sl["min"][0] < 24 - 0.5:
            add("small_text", f"{sl['min'][0]:.0f}px text < 24px", sl["min"][1])
        if sl["max"] and sl["max"][0] / tokens.type["body"].size < 1.6:
            add("no_focal", f"largest text {sl['max'][0]:.0f}px is under 1.6x the {tokens.type['body'].size}px body")
        ext = {k: (min(x for x, _, _, _ in rs), min(y for _, y, _, _ in rs), max(x + w for x, _, w, _ in rs), max(y + h for _, y, _, h in rs))
               for k, rs in body.items()}
        for a, b in [(a, b) for n, a in enumerate(ext) for b in list(ext)[n + 1 :]]:
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = ext[a], ext[b]
            if min(ax1, bx1) - max(ax0, bx0) > _TOL:  # stacked: the vertical gap counts
                gap = max(by0 - ay1, ay0 - by1)
            elif min(ay1, by1) - max(ay0, by0) > _TOL:  # side by side: the horizontal gap counts
                gap = max(bx0 - ax1, ax0 - bx1)
            else:
                continue
            if gap < g.gutter - _TOL:
                add("crowded", f"{a} and {b} are {gap:.0f}px apart < the {g.gutter}px gutter", b)
        if sl["words"] > DENSE[got["density"]]:
            add("dense", f"{sl['words']} words > {DENSE[got['density']]}")
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
