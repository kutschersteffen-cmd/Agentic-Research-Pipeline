"""Refine chat, one turn: build the prompt, make the one model call, apply its ops and log the result on the turn."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Literal

from pydantic import BaseModel

from arp.db.session import transaction
from arp.llm.base import LLMClient
from arp.refine.deck_ops import apply_deck_ops
from arp.refine.rfp_ops import apply_rfp_ops
from arp.refine.turns import (
    REFINE_ANSWER_PREVIEW_CHARS,
    REFINE_HISTORY_TURNS,
    REFINE_MAX_QUESTIONS,
    finish_turn,
    save_progress,
)
from arp.reporting.house_style import load_layouts
from arp.rfp.store import questions_of
from arp.schemas.reporting import ChartType
from arp.storage.reporting_store import ReportingStore

log = logging.getLogger(__name__)

TOO_MANY_QUESTIONS = f"This RFP has more than {REFINE_MAX_QUESTIONS} questions. Name a section or question numbers."
NO_DECK = "This report has no deck yet. Approve its storyline in Report Builder first."

_SYSTEM = {
    "rfp": """You help a person edit the answers of an investor's RFP. Reply in one or two short sentences saying what you
will do, and list the operations that do it:
- rewrite(question_ids, instruction): re-draft those answers from the library, following the instruction.
- leave_blank(question_ids): mark those questions to be left blank.
Use only question ids listed in the document. If the request is unclear, ask in the reply and return no ops.""",
    "deck": """You help a person edit a slide deck. Reply in one or two short sentences saying what you will do, and list
the operations that do it. Slide numbers are the positions listed in the document.
- set_text(slide, slot, text): replace one text slot (a string) or list slot (a list of strings).
- set_headline(slide, text): replace the headline.
- set_variant(slide, variant): switch to another variant the slide's layout allows.
- set_chart_type(slide, chart_type): change the chart's type; its data stays.
- move_slide(slide, to) / delete_slide(slide): reorder or remove a slide.
Use only slot and variant names the slide's layout allows. Never invent figures. If the request is unclear, ask in
the reply and return no ops.""",
}


class RefineOp(BaseModel):
    op: Literal["rewrite", "leave_blank", "set_text", "set_headline", "set_variant", "set_chart_type", "move_slide",
                "delete_slide"]
    question_ids: list[int] | None = None
    instruction: str | None = None
    slide: int | None = None
    slot: str | None = None
    text: str | list[str] | None = None
    variant: str | None = None
    chart_type: ChartType | None = None
    to: int | None = None


class RefineOps(BaseModel):
    reply: str
    ops: list[RefineOp]


def _deck_lines(slides: list[dict]) -> list[str]:
    layouts = load_layouts()
    lines = []
    for i, s in enumerate(slides, 1):
        layout = layouts.get(s["layout"])
        allowed = {v.id: [x.name for x in v.slots] for v in layout.variants} if layout else {}
        chart = (s.get("chart") or {}).get("chart_type")
        lines.append(json.dumps({"slide": i, "layout": s["layout"], "variant": s["variant"], "headline": s["headline"],
                                 "slots": s["slots"], "chart_type": chart, "allowed_variants_and_slots": allowed}))
    return lines


def build_prompt(kind: str, document: dict, message: str, history: list[dict]) -> str:
    """`document` is `{"questions": [{id, status, question, answer}]}` for an RFP, the deck's JSON for a deck."""
    parts = ["Earlier in this chat:"]
    for h in history[-REFINE_HISTORY_TURNS:]:
        parts += [f"Person: {h.get('message', '')}", f"You: {h.get('reply', '')}"]
    if kind == "rfp":
        parts.append("\nThe RFP's questions (id, status, question, start of the answer):")
        parts += [json.dumps({"id": q["id"], "status": q["status"], "question": q["question"],
                              "answer": (q["answer"] or "")[:REFINE_ANSWER_PREVIEW_CHARS]}) for q in document["questions"]]
    else:
        parts.append("\nThe deck's slides:")
        parts += _deck_lines(document["slides"])
    parts.append(f"\nThe person now asks: {message}")
    return "\n".join(parts)


def _result(reply: str, changed=(), not_changed=(), check_figures=()) -> dict:
    return {"reply": reply, "changed": list(changed), "not_changed": list(not_changed), "check_figures": list(check_figures)}


async def run_turn(turn_id: int, kind: str, doc_id: str, message: str, history: list[dict], llm: LLMClient,
                   store: ReportingStore, *, today: date) -> None:
    try:
        if kind == "rfp":
            with transaction() as s:
                document = {"questions": [{"id": q.id, "status": q.status, "question": q.question, "answer": q.answer}
                                          for q in questions_of(s, int(doc_id))]}
            if len(document["questions"]) > REFINE_MAX_QUESTIONS:
                save_progress(turn_id, result=_result(TOO_MANY_QUESTIONS))
                finish_turn(turn_id, "done")
                return
        else:
            deck = store.load_deck(doc_id)
            if deck is None:
                raise ValueError(NO_DECK)
            document = deck.model_dump(mode="json")
        out, _ = await llm.complete_structured(system=_SYSTEM[kind], prompt=build_prompt(kind, document, message, history),
                                               output_model=RefineOps)
        ops = [op.model_dump(exclude_none=True) for op in out.ops]
        if kind == "rfp":
            save_progress(turn_id, ops=ops, result=_result(out.reply))  # the reply shows while answers arrive
            r = await apply_rfp_ops(turn_id, int(doc_id), ops, llm, today=today)
            save_progress(turn_id, result=_result(out.reply, r["changed"], r["not_changed"]))
        else:
            request = store.load_request(doc_id)
            findings = "\n".join(f.message for f in store.load_findings(doc_id))
            new, r = apply_deck_ops(deck, ops, request.datasets if request else [], findings)
            edited = new != deck
            save_progress(turn_id, ops=ops, result=_result(out.reply, r["changed"], r["not_changed"], r["check_figures"]),
                          before=document if edited else None, after=new.model_dump(mode="json") if edited else None)
            if edited:  # logged first, so a written deck always has its undo
                store.save_deck(doc_id, new)
                manifest = store.load_manifest(doc_id)
                if manifest is not None:
                    manifest.deck_edited_since_render = True
                    store.save_manifest(manifest)
        finish_turn(turn_id, "done")
    except Exception as exc:  # noqa: BLE001 -- a background turn must always end; the page shows the error
        log.exception("refine: turn %s failed", turn_id)
        finish_turn(turn_id, "failed", error=str(exc))
