"""Page-image check for a value whose citation failed the text grounding check.

PDF tables often come out of text extraction with shifted columns or merged numbers, so a right
value can fail grounding. This renders the cited page and asks the model to read the figure off
the image. A match clears NOT_GROUNDED (not on high-risk fields); anything else stays in review."""

from __future__ import annotations

import asyncio
import bisect
import math

from pydantic import BaseModel, Field

from arp.checks.numeric import candidates
from arp.ingestion.pdf_page import render_page
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDefinition
from arp.schemas.review import ReasonCode

_SYSTEM = """\
You read one page of a company report as an image. Find the figure the question asks for and copy it \
exactly as printed (digits, separators, sign). Report only what the page shows; if the figure is not \
on this page, say so."""


class PageReading(BaseModel):
    found: bool = Field(description="True only if the page visibly prints the requested figure.")
    figure_text: str | None = Field(default=None, description="The figure exactly as printed on the page.")
    notes: str = ""


def cited_page(
    ef: ExtractedField, passages: dict[str, DocumentChunk], documents_by_id: dict[str, SourceDocument]
) -> tuple[SourceDocument, int] | None:
    """The PDF page of the first citation whose evidence passage is known: 1-indexed."""
    for c in ef.citations:
        chunk = passages.get(c.passage_id or "")
        doc = documents_by_id.get(c.doc_id)
        if chunk and doc and doc.page_breaks and (doc.local_path or "").lower().endswith(".pdf"):
            return doc, bisect.bisect_right(doc.page_breaks, chunk.char_start)
    return None


def same_figure(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    xs, ys = candidates(a), candidates(b)
    return any(math.isclose(abs(x), abs(y), rel_tol=1e-9) for x in xs for y in ys)


async def check_on_page(
    company_name: str,
    field: FieldDefinition,
    ef: ExtractedField,
    passages: dict[str, DocumentChunk],
    documents_by_id: dict[str, SourceDocument],
    llm: LLMClient,
) -> tuple[ExtractedField, LLMUsage | None]:
    """Returns `ef` unchanged (and no usage) when there is no PDF page to look at."""
    located = cited_page(ef, passages, documents_by_id)
    if located is None:
        return ef, None
    doc, page = located
    image = await asyncio.to_thread(render_page, doc.local_path, page)
    if image is None:
        return ef, None
    prompt = (
        f"Company: {company_name}\nFigure: {field.name} -- {field.description}\n"
        f"Period: {ef.period_text or 'the latest reported period'}\n"
        f"Read this figure off page {page} of '{doc.title}'."
    )
    reading, usage = await llm.complete_structured(system=_SYSTEM, prompt=prompt, output_model=PageReading, images=[image])
    if reading.found and same_figure(reading.figure_text, ef.raw_value_text):
        note = f"Page {page} image shows {reading.figure_text!r}, matching the value (vision check)."
        reasons = ef.review_reasons if field.high_risk else [r for r in ef.review_reasons if r != ReasonCode.NOT_GROUNDED]
    else:
        seen = repr(reading.figure_text) if reading.found else "no such figure"
        note = f"Page {page} image shows {seen}, not confirming the value (vision check)."
        reasons = ef.review_reasons
    notes = " ".join(filter(None, [ef.verifier_notes, note]))
    return ef.model_copy(update={"review_reasons": reasons, "verifier_notes": notes}), usage
