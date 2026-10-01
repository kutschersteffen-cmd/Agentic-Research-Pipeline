"""House deck build after storyline approval: fill -> lint+rewrite -> fit -> visual QA -> PDF + PNGs + PPTX."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.browser import write_pdf, write_pngs
from arp.reporting.fit import fit_deck
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_and_rewrite
from arp.reporting.slide_fill import fill_slide
from arp.reporting.visual_qa import visual_qa
from arp.schemas.reporting import Deck, Finding, ReportRequest, SlideContent, Storyline
from arp.storage.reporting_store import ReportingStore


async def render_house_outputs(report_id: str, deck: Deck, request: ReportRequest, store: ReportingStore) -> None:
    """Writes output.pdf, output.pptx and the preview PNGs from `deck`; no LLM, no measuring (fit_deck owns the fit findings)."""
    html = render_deck_html(deck, request.datasets, mode=request.layout.theme)
    await write_pdf(html, store.output_path(report_id, "output.pdf"))
    build_house_pptx(deck, request.datasets, store.output_path(report_id, "output.pptx"), mode=request.layout.theme)
    preview = store.preview_dir(report_id)
    for old in preview.glob("page-*.png"):  # a shorter deck must not keep the old tail
        old.unlink()
    await write_pngs(html, preview)


async def build_house_deck(
    report_id: str, request: ReportRequest, storyline: Storyline, llm: LLMClient, store: ReportingStore, usage: LLMUsage | None = None,
) -> tuple[Deck, list[Finding]]:
    """`usage`, when given, is incremented in place with every LLM call's tokens (later stages add theirs too)."""
    # Slide 0 is the title slide, so storyline slide i renders (and is reported) as slide i + 1.
    filled = await asyncio.gather(*(fill_slide(s, i, request, llm) for i, s in enumerate(storyline.slides, 1)))
    title = SlideContent(headline=storyline.title, layout="title", variant="plain", slots={"title": storyline.title, "subtitle": storyline.subtitle})
    deck = Deck(title=storyline.title, subtitle=storyline.subtitle, slides=[title, *(content for content, _, _ in filled)])
    findings = [f for _, fs, _ in filled for f in fs]
    if usage is not None:
        for _, _, u in filled:
            usage.input_tokens += u.input_tokens
            usage.output_tokens += u.output_tokens
    deck, lint_findings = await lint_and_rewrite(deck, request, llm, usage=usage)
    findings += lint_findings
    deck, fit_findings = await fit_deck(deck, request, llm, usage=usage)
    findings += fit_findings
    with tempfile.TemporaryDirectory() as tmp:
        pngs = await write_pngs(render_deck_html(deck, request.datasets, mode=request.layout.theme), Path(tmp))
        deck, qa_findings = await visual_qa(deck, pngs, request, llm, usage=usage)
    if any(f.rule == "applied" for f in qa_findings):  # QA re-measured the deck: the first fit's measurements are stale
        findings = [f for f in findings if f.stage != "fit" or f.rule == "slot_dropped"]
    edited = {(f.slide, f.slot) for f in qa_findings if f.rule == "applied" and f.slot}
    findings = [f for f in findings if f.stage != "lint" or (f.slide, f.slot) not in edited]  # QA's re-lint replaces them
    findings += qa_findings
    store.save_deck(report_id, deck)
    await render_house_outputs(report_id, deck, request, store)
    store.save_findings(report_id, findings)
    return deck, findings
