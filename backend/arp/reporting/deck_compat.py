"""ReportPlan -> Deck, so existing plans can render through the HTML house deck (art-directed, no LLM)."""

from __future__ import annotations

import logging

from arp.reporting.art_direct import direct
from arp.schemas.reporting import Deck, ReportPlan, SectionLayoutHint, SlideContent

logger = logging.getLogger(__name__)


def deck_from_plan(plan: ReportPlan) -> Deck:
    slides = [SlideContent(headline=plan.title, layout="title", variant="plain", slots={"title": plan.title, "subtitle": plan.subtitle})]
    for sec in plan.sections:
        texts = [c.text for c in sec.narrative]
        base = {"headline": sec.heading, "speaker_notes": sec.speaker_notes}
        if sec.layout_hint == SectionLayoutHint.SECTION_HEADER:
            slides.append(SlideContent(**base, layout="section", variant="default", slots={"title": sec.heading, "subtitle": texts[0] if texts else ""}))
        elif sec.layout_hint == SectionLayoutHint.TEXT_ONLY:
            slides.append(SlideContent(**base, layout="bullets", variant="five", slots={"items": texts}))
        elif sec.layout_hint == SectionLayoutHint.CHART_FOCUS or sec.chart:
            variant = "full" if sec.layout_hint == SectionLayoutHint.CHART_FOCUS else "chart_left"
            takeaway = (sec.chart.notes if sec.chart else "") or (texts[0] if texts else "")
            slides.append(SlideContent(**base, layout="chart_takeaway", variant=variant, slots={"takeaway": takeaway}, chart=sec.chart))
        elif sec.table:
            slides.append(SlideContent(**base, layout="table", variant="compact", table=sec.table))
        else:
            slides.append(SlideContent(**base, layout="bullets", variant="five", slots={"items": texts}))
    deck, findings = direct(Deck(title=plan.title, subtitle=plan.subtitle, slides=slides))
    for f in findings:  # this path has no findings channel: the log is where a relayout shows
        logger.info("art direction, slide %d: %s", f.slide, f.message)
    return deck
