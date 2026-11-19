"""House deck build after storyline approval: fill -> lint+rewrite -> fit (legacy slides) -> fit ladder (component slides) -> visual QA -> PDF + PNGs + PPTX."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from arp.config import Settings
from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.adapters import with_run_datasets
from arp.reporting.browser import write_pdf, write_pngs
from arp.reporting.fit import fit_deck, fit_ladder
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import Mode, Tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_and_rewrite, lint_deck
from arp.reporting.render_model import ImagePrim, render_slide
from arp.reporting.slide_fill import duplicate_data, fill_slide
from arp.reporting.storyline import content_cap
from arp.reporting.template_frame import house_tokens
from arp.reporting.visual_qa import visual_qa
from arp.schemas.reporting import Deck, Finding, ReportRequest, SlideContent, Storyline, StorylineSlide
from arp.schemas.visuals import Cover, NextSteps, Section
from arp.storage.report_images import LoadedImage
from arp.storage.reporting_store import ReportingStore

LOW_RESOLUTION = 0.75  # a crop narrower than this share of its slot width (canvas px) is a `low_resolution` finding


def low_resolution(deck: Deck, request: ReportRequest, tokens: Tokens, mode: Mode, images: dict[str, LoadedImage]) -> list[Finding]:
    """One finding per image shown wider than 1 / 0.75 of its source pixels."""
    by_id, out = {d.dataset_id: d for d in request.datasets}, []
    for i, s in enumerate(deck.slides):
        if s.visual is None:
            continue
        for p in render_slide(s, i, deck, tokens, by_id, mode, images=images):
            if isinstance(p, ImagePrim):
                left, _, right, _ = p.crop
                shown = images[p.image].entry.width * (1 - left - right)
                if shown < LOW_RESOLUTION * p.w:
                    out.append(Finding(slide=i, slot=p.name, stage="fit", rule="low_resolution",
                                       message=f"image '{p.image}' is shown at {p.w / shown:.1f}× its pixels; use a larger image"))
    return out


async def render_house_outputs(report_id: str, deck: Deck, request: ReportRequest, store: ReportingStore) -> list[Finding]:
    """Writes output.pdf, output.pptx and the preview PNGs from `deck`; no LLM, no measuring (fit_deck owns the fit findings).
    Replaces the report's `low_resolution` findings with the current ones, keeps all others, and returns the new ones."""
    tokens = house_tokens(request, store)
    images = store.load_report_images(report_id, request)
    html = render_deck_html(deck, request.datasets, tokens, mode=request.layout.theme, images=images)
    await write_pdf(html, store.output_path(report_id, "output.pdf"))
    build_house_pptx(deck, request.datasets, store.output_path(report_id, "output.pptx"), tokens, mode=request.layout.theme, images=images)
    preview = store.preview_dir(report_id)
    for old in preview.glob("page-*.png"):  # a shorter deck must not keep the old tail
        old.unlink()
    await write_pngs(html, preview)
    low = low_resolution(deck, request, tokens, request.layout.theme, images)
    store.save_findings(report_id, [f for f in store.load_findings(report_id) if f.rule != "low_resolution"] + low)
    return low


def _outline(storyline: Storyline, request: ReportRequest) -> tuple[list[SlideContent | StorylineSlide], list[Finding]]:
    """A visual storyline's slide order, built by code: cover -> per section its divider, then its slides -> next steps.
    Storyline slides are left for fill_slide; those beyond the profile's cap are dropped with one `profile_cap` finding."""
    cap = content_cap(request)
    kept = storyline.slides[:cap]
    findings = []
    if len(storyline.slides) > cap:
        findings.append(Finding(slide=0, stage="data", rule="profile_cap", message=(
            f"{len(storyline.slides) - cap} content slides dropped: the {request.deck.profile} profile keeps at most {cap}")))
    plan: list[SlideContent | StorylineSlide] = [
        SlideContent(headline=storyline.title, subheading=storyline.subtitle, visual=Cover(title=storyline.title, answer=storyline.answer, figures=storyline.figures))]
    agenda = [sec.title for sec in storyline.sections]
    for i, sec in enumerate(storyline.sections):
        plan.append(SlideContent(headline=sec.title, visual=Section(number=i + 1, title=sec.title, summary=sec.summary, agenda=agenda)))
        plan += [s for s in kept if s.section == i]
    plan += [s for s in kept if s.section is None or not 0 <= s.section < len(agenda)]
    if len(storyline.closing) >= 2:  # NextSteps needs 2-5 actions; a storyline without them gets no closing slide
        plan.append(SlideContent(headline="Next steps", kicker="Next steps", visual=NextSteps(actions=storyline.closing)))
    return plan, findings


async def build_house_deck(
    report_id: str, request: ReportRequest, storyline: Storyline, llm: LLMClient, store: ReportingStore, usage: LLMUsage | None = None,
    settings: Settings | None = None,
) -> tuple[Deck, list[Finding]]:
    """`usage`, when given, is incremented in place with every LLM call's tokens (later stages add theirs too)."""
    tokens = house_tokens(request, store)  # checked before any LLM call is spent
    loaded = with_run_datasets(request, settings, only_missing=True)  # a rerun has loaded them already
    if loaded is not request:  # persisted, so a later re-render sees the same data the deck was built from
        request = loaded
        store.save_request(report_id, request)
    if any(s.visual for s in storyline.slides):
        plan, findings = _outline(storyline, request)
    else:  # legacy: a title slide, then the storyline slides
        title = SlideContent(headline=storyline.title, layout="title", variant="plain", slots={"title": storyline.title, "subtitle": storyline.subtitle})
        plan, findings = [title, *storyline.slides], []

    async def build(slide: SlideContent | StorylineSlide, i: int) -> tuple[SlideContent, list[Finding], LLMUsage]:
        # Each storyline slide is filled (and reported) at its position in the deck.
        return (slide, [], LLMUsage()) if isinstance(slide, SlideContent) else await fill_slide(slide, i, request, llm)

    filled = await asyncio.gather(*(build(s, i) for i, s in enumerate(plan)))
    deck = Deck(title=storyline.title, subtitle=storyline.subtitle, slides=[content for content, _, _ in filled])
    findings += [f for _, fs, _ in filled for f in fs] + duplicate_data(deck)
    if usage is not None:
        for _, _, u in filled:
            usage.input_tokens += u.input_tokens
            usage.output_tokens += u.output_tokens
    deck, _ = await lint_and_rewrite(deck, request, llm, usage=usage)  # its findings are recomputed on the final deck below
    deck, fit_findings = await fit_deck(deck, request, llm, usage=usage, shift=findings, tokens=tokens)
    findings += fit_findings
    n = len(request.datasets)
    request = request.model_copy(update={"datasets": [*request.datasets]})  # fit_ladder may add a switched table's rows
    deck, ladder_findings = await fit_ladder(deck, request, llm, tokens, usage, shift=findings)
    findings += ladder_findings
    if len(request.datasets) > n:  # saved, so a re-render finds the table's rows
        store.save_request(report_id, request)
    with tempfile.TemporaryDirectory() as tmp:
        images = store.load_report_images(report_id, request)
        pngs = await write_pngs(render_deck_html(deck, request.datasets, tokens, mode=request.layout.theme, images=images), Path(tmp))
        deck, qa_findings = await visual_qa(deck, pngs, request, llm, usage=usage, shift=findings, tokens=tokens)
    if any(f.rule == "applied" for f in qa_findings):  # QA re-measured the deck: the first fit's measurements are stale
        # Component slides are not QA-edited, so their ladder findings stay.
        findings = [f for f in findings if f.stage != "fit" or f.rule == "slot_dropped" or deck.slides[f.slide].visual is not None]
    # Fit splits moved slides; lint once more on the final deck so every lint finding points at the right slide.
    findings = [f for f in [*findings, *qa_findings] if f.stage != "lint"] + lint_deck(deck, request)
    store.save_deck(report_id, deck)
    store.save_findings(report_id, findings)
    findings += await render_house_outputs(report_id, deck, request, store)  # it adds the low_resolution findings
    return deck, findings
