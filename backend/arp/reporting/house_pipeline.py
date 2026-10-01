"""House deck build after storyline approval: fill -> render+measure -> PDF + PNGs.

Later stages (write-check, fit loop, visual QA, PPTX) slot in between fill and output.
"""

from __future__ import annotations

import asyncio

from arp.llm.base import LLMClient
from arp.reporting.browser import measure, write_pdf, write_pngs
from arp.reporting.html_render import render_deck_html
from arp.reporting.slide_fill import fill_slide
from arp.schemas.reporting import Deck, Finding, ReportRequest, SlideContent, Storyline
from arp.storage.reporting_store import ReportingStore


async def render_house_outputs(report_id: str, deck: Deck, request: ReportRequest, store: ReportingStore) -> list[Finding]:
    """Writes output.pdf and the preview PNGs from `deck`; returns the fit findings. No LLM."""
    html = render_deck_html(deck, request.datasets, mode=request.layout.theme)
    findings = await measure(html)
    await write_pdf(html, store.output_path(report_id, "output.pdf"))
    preview = store.preview_dir(report_id)
    for old in preview.glob("page-*.png"):  # a shorter deck must not keep the old tail
        old.unlink()
    await write_pngs(html, preview)
    return findings


async def build_house_deck(report_id: str, request: ReportRequest, storyline: Storyline, llm: LLMClient, store: ReportingStore) -> tuple[Deck, list[Finding]]:
    # Slide 0 is the title slide, so storyline slide i renders (and is reported) as slide i + 1.
    filled = await asyncio.gather(*(fill_slide(s, i, request, llm) for i, s in enumerate(storyline.slides, 1)))
    title = SlideContent(headline=storyline.title, layout="title", variant="plain", slots={"title": storyline.title, "subtitle": storyline.subtitle})
    deck = Deck(title=storyline.title, subtitle=storyline.subtitle, slides=[title, *(content for content, _, _ in filled)])
    findings = [f for _, fs, _ in filled for f in fs]
    store.save_deck(report_id, deck)
    findings += await render_house_outputs(report_id, deck, request, store)
    store.save_findings(report_id, findings)
    return deck, findings
