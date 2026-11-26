"""One Research Desk turn, run in the background: pick the scope's reports, search them, have the model write an
answer from the numbered passages, then check every sentence in code."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update

from arp.api.deps import get_document_content_store, get_run_store
from arp.api.saved_universe import load_saved_universe
from arp.config import get_settings
from arp.db import models as m
from arp.db.documents import derive_doc_id
from arp.db.session import transaction
from arp.grounding import _page_for_offset
from arp.ingestion.local_files import parse_file_to_text_with_pages, parser_version
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient
from arp.research_desk.check import MAX_CALCULATIONS, DeskAnswer, DeskSubQuestions, check_answer
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocType, SourceDocument
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

log = logging.getLogger(__name__)

STAGES = ("pick_sources", "split", "search", "rank", "write", "check")
SUFFIXES = {".pdf", ".docx", ".xlsx", ".xlsm", ".html", ".htm", ".txt", ".md"}
MAX_FILES = 100
QUICK_PASSAGES, THOROUGH_PASSAGES = 8, 12
MAX_SUB_QUESTIONS = 4
HISTORY_TURNS = 5
TIMEOUT_MIN = 10
NO_SOURCES = "I found no reports or saved data in this chat's scope."

_SYSTEM = """You answer an analyst's question about companies using only the numbered sources given. Write short
sentences. Each sentence cites the sources it relies on, with a quote copied word for word from that source. When a
sentence states a figure you worked out, give the calculation (an id, a label and an arithmetic expression using only
numbers from the quotes and + - * / ( )), name its id on the sentence and write its result in the sentence. If the
sources do not answer the question, say so."""
_SPLIT = "Split the analyst's question into at most 4 short search questions, one per thing it asks about."


def company_names() -> dict[str, str]:
    """Company key (upper-cased) -> name: a company's key is its active UNIVERSE identifier, else its id."""
    with transaction() as s:
        rows = s.execute(select(m.Company.id, m.Company.name, m.CompanyIdentifier.value).outerjoin(
            m.CompanyIdentifier, (m.CompanyIdentifier.company_id == m.Company.id)
            & (m.CompanyIdentifier.scheme == str(m.IdScheme.UNIVERSE)) & m.CompanyIdentifier.valid_to.is_(None)))
        return {(value or str(cid)).upper(): name for cid, name, value in rows}


def report_files(key: str) -> list[tuple[DocType, Path]]:
    """Every readable, non-dot file under `$ARP_DOCUMENTS_DIR/<key>/<doc_type>/`."""
    try:
        folder = get_settings().documents_dir / safe_id(key, label="company_id")
    except UnsafeIdentifierError:
        return []
    out = []
    for type_dir in folder.iterdir() if folder.is_dir() else ():
        if type_dir.is_dir() and type_dir.name in {d.value for d in DocType}:
            out += [(DocType(type_dir.name), f) for f in type_dir.iterdir()
                    if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in SUFFIXES]
    return out


def scope_companies(kind: str, ref: str) -> list[str]:
    """The company keys a scope item names."""
    settings = get_settings()
    if kind == "company":
        return [ref]
    if kind == "universe":
        # relative to runs_dir ("_universes/x.csv") or the absolute path the universe upload answers
        return [c.company_id for c in load_saved_universe(str(settings.runs_dir / ref), settings)]
    return [c.company_id for c in get_run_store().load_companies(ref) or []]


def reap_stale_desk_turns(now: datetime | None = None) -> int:
    """Fail `running` turns with no progress for the timeout; with `now=None` (API start) every `running` turn."""
    q = update(m.DeskTurn).where(m.DeskTurn.status == "running")
    if now is not None:
        q = q.where(m.DeskTurn.updated_at < now - timedelta(minutes=TIMEOUT_MIN))
    with transaction() as s:
        return s.execute(q.values(status="failed", error="interrupted", finished_at=func.now())).rowcount


def _save(turn_id: int, **values) -> None:
    """Writes onto a `running` turn only, bumping `updated_at`."""
    with transaction() as s:
        s.execute(update(m.DeskTurn).where(m.DeskTurn.id == turn_id, m.DeskTurn.status == "running")
                  .values(**values, updated_at=func.now()))


def _pick_sources(keys: list[str]) -> tuple[list, dict[str, SourceDocument]]:
    store = get_document_content_store()
    files = sorted(((k, t, f) for k in keys for t, f in report_files(k)), key=lambda x: x[2].stat().st_mtime,
                   reverse=True)[:MAX_FILES]
    chunks, docs = [], {}
    for key, doc_type, path in files:
        parsed = store.get_or_parse(path, parser_version=parser_version(), parse=parse_file_to_text_with_pages)
        doc = SourceDocument(
            doc_id=derive_doc_id(key, doc_type.value, parsed.content_key), company_id=key, doc_type=doc_type,
            title=path.name, local_path=str(path), full_text=parsed.full_text, page_breaks=parsed.page_breaks,
            table_spans=parsed.table_spans, content_key=parsed.content_key)
        docs[doc.doc_id] = doc
        chunks += chunk_document(doc)
    return chunks, docs


def _search(chunks: list, questions: list[str], thorough: bool) -> tuple[list[list], dict, bool]:
    settings = get_settings()
    rerank = {"rerank_candidates": settings.rerank_candidates, "rerank_model": settings.rerank_model} \
        if thorough and settings.rerank_enabled else {}
    lists, scores, reranked = [], {}, False
    for q in questions:
        explain: dict = {}
        lists.append(select_relevant_chunks(
            chunks, q.split(), max_chunks=THOROUGH_PASSAGES if thorough else QUICK_PASSAGES, require_hit=True,
            fallback_to_all=True, hybrid_retrieval_enabled=settings.hybrid_retrieval_enabled,
            content_store=get_document_content_store(), explain=explain, **rerank))
        for cid, s in explain.get("scores", {}).items():
            scores.setdefault(cid, s)
        reranked = reranked or bool(explain.get("reranked"))
    return lists, scores, reranked


def _prompt(question: str, history: list[tuple[str, dict]], sources: list[dict]) -> str:
    parts = [f"Question: {question}"]
    if history:
        parts.append("Earlier in this chat:\n" + "\n".join(
            f"Q: {q}\nA: {' '.join(s['text'] for s in a.get('sentences', []))}" for q, a in history))
    parts.append("Sources:\n" + "\n".join(f"[{s['n']}] {s['text']}" for s in sources))
    return "\n\n".join(parts)


async def run_turn(turn_id: int, llm: LLMClient) -> None:
    with transaction() as s:
        t = s.get(m.DeskTurn, turn_id)
        chat_id, question, thorough, stages = t.chat_id, t.question, t.mode == "thorough", {x["name"]: x for x in t.stages}
        scope = s.execute(select(m.DeskScope.kind, m.DeskScope.ref).where(m.DeskScope.chat_id == chat_id)
                          .order_by(m.DeskScope.id)).all()
        history = s.execute(select(m.DeskTurn.question, m.DeskTurn.answer).where(
            m.DeskTurn.chat_id == chat_id, m.DeskTurn.status == "done", m.DeskTurn.id != turn_id)
            .order_by(m.DeskTurn.id.desc()).limit(HISTORY_TURNS)).all()[::-1]
    sources: list[dict] = []
    current = {"name": None, "t0": 0.0}

    def save(**values) -> None:
        _save(turn_id, stages=list(stages.values()), sources=sources, **values)

    def start(name: str) -> None:
        current.update(name=name, t0=time.monotonic())
        stages[name]["status"] = "running"
        save()

    def done(detail: dict) -> None:
        stages[current["name"]].update(status="done", ms=int((time.monotonic() - current["t0"]) * 1000), detail=detail)
        current["name"] = None
        save()

    async def model(output_model, system: str, prompt: str):
        try:
            return (await llm.complete_structured(system=system, prompt=prompt, output_model=output_model))[0]
        except Exception as exc:  # noqa: BLE001 -- any model failure fails the turn with its reason
            raise RuntimeError(f"The model call failed: {exc}") from exc

    try:
        start("pick_sources")
        keys = list(dict.fromkeys(k for kind, ref in scope for k in scope_companies(kind, ref)))
        chunks, docs = await asyncio.to_thread(_pick_sources, keys)
        done({"companies": len(keys), "documents": len(docs)})
        if not chunks:
            for n in ("split", "search", "rank", "write"):
                stages[n]["status"] = "skipped"
            stages["check"].update(status="done", ms=0, detail={"found": 0, "calculated": 0, "to_check": 1})
            answer = {"sentences": [{"n": 1, "text": NO_SOURCES, "status": "to_check", "citations": [], "calculation": None}],
                      "calculations": [], "check": {"found": 0, "calculated": 0, "to_check": 1}}
            save(answer=answer, status="done", finished_at=func.now())
            return

        questions = [question]
        if thorough:
            start("split")
            out = await model(DeskSubQuestions, _SPLIT, question)
            questions = [q for q in out.questions if q.strip()][:MAX_SUB_QUESTIONS] or [question]
            done({"questions": questions})
        else:
            stages["split"]["status"] = "skipped"

        start("search")
        lists, scores, reranked = await asyncio.to_thread(_search, chunks, questions, thorough)
        kept = list({c.chunk_id: c for picked in lists for c in picked}.values())
        done({"matched": len(chunks), "kept": len(kept)})

        passages = lists[0]
        if thorough:
            start("rank")
            merged = {}
            for i in range(max(len(p) for p in lists)):  # round-robin across the sub-questions' lists
                for picked in lists:
                    if i < len(picked):
                        merged.setdefault(picked[i].chunk_id, picked[i])
            passages = list(merged.values())[:THOROUGH_PASSAGES]
            done({"passages": len(passages), "reranked": reranked})
        else:
            stages["rank"]["status"] = "skipped"

        names = company_names()
        for n, c in enumerate(passages, 1):
            doc = docs[c.doc_id]
            sources.append({"n": n, "kind": "report", "company_id": doc.company_id,
                            "company_name": names.get(doc.company_id.upper(), doc.company_id), "filename": doc.title,
                            "doc_type": doc.doc_type.value, "chunk_id": c.chunk_id, "text": c.text,
                            "page": _page_for_offset(doc.page_breaks, c.char_start), "scores": scores.get(c.chunk_id, {}),
                            "used": False})

        start("write")
        out = await model(DeskAnswer, _SYSTEM, _prompt(question, [(q, a or {}) for q, a in history], sources))
        done({"calculations": len(out.calculations[:MAX_CALCULATIONS])})

        start("check")
        answer = check_answer(out, {s["n"]: (s["text"], docs[passages[s["n"] - 1].doc_id].page_breaks,
                                             passages[s["n"] - 1].char_start) for s in sources})
        cited = {c["source"] for s in answer["sentences"] for c in s["citations"]}
        for s in sources:
            s["used"] = s["n"] in cited
        done(answer["check"])
        save(answer=answer, status="done", finished_at=func.now())
    except Exception as exc:  # noqa: BLE001 -- nobody awaits the task: the turn records why it failed
        log.exception("Research Desk turn %s failed", turn_id)
        if current["name"]:
            stages[current["name"]]["status"] = "failed"
        save(status="failed", error=str(exc), finished_at=func.now())
