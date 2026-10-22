"""The RFP tables: library import, the detect-and-fill run, auto-fill, and the project as the API returns it."""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select, update

from arp.db import models as m
from arp.db.session import transaction
from arp.llm.base import LLMClient
from arp.rfp.detect import detect_questions
from arp.rfp.draft import APPROVED, NO_SOURCE, Draft, Entry, draft_answer
from arp.rfp.library import extract_pairs
from arp.rfp.locations import Layout
from arp.rfp.text import has_figures
from arp.schemas.rfp import RfpLibraryEntryOut, RfpProjectOut, RfpProjectSummary, RfpQuestionOut, RfpSourceOut


def today() -> date:
    return date.today()


def source_label(e: m.RfpLibraryEntry) -> str:
    if e.source_file:
        return f"{e.source_file} {e.source_location or ''}".strip()
    if e.source_project_id is not None:
        return f"project {e.source_project_id}"
    return f"written by {e.written_by}"


def entry_out(e: m.RfpLibraryEntry) -> RfpLibraryEntryOut:
    return RfpLibraryEntryOut(
        id=e.id, question=e.question, answer=e.answer, tags=e.tags, source=source_label(e), source_file=e.source_file,
        source_location=e.source_location, source_project_id=e.source_project_id, written_by=e.written_by,
        approved_on=e.approved_on, review_by=e.review_by, owner=e.owner, has_figures=e.has_figures, status=e.status,
    )


async def import_library(files: list[tuple[str, bytes]], llm: LLMClient) -> tuple[int, list[str]]:
    """(entries imported, questions of the dropped pairs) for (file name, bytes) of .docx/.xlsx files."""
    imported, dropped = 0, []
    for name, data in files:
        pairs, lost = await extract_pairs(data, "." + name.rsplit(".", 1)[-1], llm, today=today())
        dropped += lost
        with transaction() as s:
            s.add_all(
                m.RfpLibraryEntry(question=p.question, answer=p.answer, tags=[], source_file=name, source_location=p.location,
                                  approved_on=p.approved_on, review_by=p.review_by, has_figures=has_figures(p.answer),
                                  status="active")
                for p in pairs
            )
        imported += len(pairs)
    return imported, dropped


def _active_entries(s) -> list[Entry]:
    rows = s.scalars(select(m.RfpLibraryEntry).where(m.RfpLibraryEntry.status == "active").order_by(m.RfpLibraryEntry.id))
    return [Entry(e.id, e.question, e.answer, e.review_by) for e in rows]


def set_run_status(project_id: int, run_status: str, **values) -> None:
    with transaction() as s:
        s.execute(update(m.RfpProject).where(m.RfpProject.id == project_id).values(run_status=run_status, **values))


async def autofill(project_id: int, llm: LLMClient, settings=None) -> None:
    """Drafts every `no source` question again from the active library; never touches edited, approved, left blank."""
    with transaction() as s:
        entries = _active_entries(s)
        todo = [(q.id, q.question) for q in s.scalars(
            select(m.RfpQuestion).where(m.RfpQuestion.project_id == project_id, m.RfpQuestion.status == NO_SOURCE)
            .order_by(m.RfpQuestion.position)
        )]
    day = today()
    limit = asyncio.Semaphore(settings.max_concurrent_llm_calls if settings is not None else 4)

    async def one(question: str) -> Draft:
        async with limit:
            return await draft_answer(question, entries, llm, today=day, settings=settings)

    drafts: list[Draft] = await asyncio.gather(*(one(question) for _, question in todo))
    with transaction() as s:
        for (qid, _), d in zip(todo, drafts, strict=True):
            # WHERE status: a colleague may have edited the question while its draft was being written
            s.execute(update(m.RfpQuestion).where(m.RfpQuestion.id == qid, m.RfpQuestion.status == NO_SOURCE)
                      .values(status=d.status, answer=d.answer, sources=d.sources, flags=d.flags))


async def detect_and_fill(project_id: int, data: bytes, suffix: str, llm: LLMClient, settings=None) -> None:
    try:
        found, not_located = await detect_questions(Layout(data, suffix), llm)
        with transaction() as s:
            s.add_all(
                m.RfpQuestion(project_id=project_id, position=i, location=d.location, answer_location=d.answer_location,
                              question=d.question, answer="", status=NO_SOURCE, flags=[], sources=[])
                for i, d in enumerate(found)
            )
        set_run_status(project_id, "drafting", not_located=not_located)
        await autofill(project_id, llm, settings)
        set_run_status(project_id, "done")
    except Exception:
        set_run_status(project_id, "failed")
        raise


def _summary(p: m.RfpProject, questions: list[m.RfpQuestion]) -> dict:
    return dict(id=p.id, investor=p.investor, due_date=p.due_date, filename=p.filename, run_status=p.run_status,
                not_located=p.not_located, question_count=len(questions),
                approved_count=sum(q.status == APPROVED for q in questions))


def questions_of(s, project_id: int) -> list[m.RfpQuestion]:
    return list(s.scalars(select(m.RfpQuestion).where(m.RfpQuestion.project_id == project_id).order_by(m.RfpQuestion.position)))


def project_summaries(s) -> list[RfpProjectSummary]:
    return [RfpProjectSummary(**_summary(p, questions_of(s, p.id)))
            for p in s.scalars(select(m.RfpProject).order_by(m.RfpProject.id.desc()))]


def project_out(s, p: m.RfpProject) -> RfpProjectOut:
    questions = questions_of(s, p.id)
    ids = {src["entry_id"] for q in questions for src in q.sources}
    entries = {e.id: e for e in s.scalars(select(m.RfpLibraryEntry).where(m.RfpLibraryEntry.id.in_(ids)))} if ids else {}

    def source(src: dict) -> RfpSourceOut:
        e = entries[src["entry_id"]]
        return RfpSourceOut(entry_id=e.id, entry_question=e.question, quote=src["quote"], source=source_label(e),
                         file=e.source_file, location=e.source_location, written_by=e.written_by)

    return RfpProjectOut(
        **_summary(p, questions),
        questions=[
            RfpQuestionOut(id=q.id, location=q.location, answer_location=q.answer_location, question=q.question,
                        answer=q.answer, status=q.status, flags=q.flags, assignee=q.assignee, last_editor=q.last_editor,
                        sources=[source(src) for src in q.sources])
            for q in questions
        ],
    )
