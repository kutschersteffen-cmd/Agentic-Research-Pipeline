"""Authority-taxonomy run: a stored state that pauses at awaiting_sources and
awaiting_review and resumes on user calls. Nothing reaches the TaxonomyStore before accept."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from arp.discovery.site_finder import SearchReport
from arp.orchestration import jobs
from arp.orchestration.job_manager import JobManager
from arp.research.authority_taxonomy.consolidate import consolidate
from arp.research.authority_taxonomy.discovery import Candidate, discover_candidates
from arp.research.authority_taxonomy.extract import extract_source
from arp.research.taxonomy_sources.fetch import extract_pdf_pages, fetch_source_pages
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition

Stage = Literal["discovering", "awaiting_sources", "extracting", "awaiting_review", "accepted", "cancelled", "failed"]
_MAX_CHARS = 400_000
INTERRUPTED = "interrupted by a server restart"
SEARCH_DOWN = "The web search could not be reached, so no new sources were found. Add a URL or upload a document below."


class WrongStage(Exception):
    def __init__(self, stage: str) -> None:
        super().__init__(f"run is at stage {stage}")
        self.stage = stage


class SourceSelection(BaseModel):
    urls: list[str] = []
    files: list[str] = []


class RunState(BaseModel):
    run_id: str
    stage: Stage
    theme_name: str
    theme_key: str | None = None
    scope: str = ""
    guidance: str = ""
    value_chain: bool = False
    candidates: list[Candidate] = Field(default_factory=list)
    draft: ThemeDefinition | None = None
    notes: str = ""
    taxonomy_id: str | None = None
    error: str | None = None
    selection: SourceSelection | None = None
    step_started_at: str | None = None  # ISO UTC; when the running step began


def load_state(run_id: str, run_store) -> RunState:
    data = run_store.read_snapshot(run_id, "state")
    if data is None:
        raise KeyError(run_id)
    return RunState.model_validate(data)


def _save(state: RunState, run_store) -> RunState:
    run_store.save_snapshot(state.run_id, "state", state.model_dump(mode="json"))
    return state


def _require(run_id: str, run_store, *stages: str) -> RunState:
    state = load_state(run_id, run_store)
    if state.stage not in stages:
        raise WrongStage(state.stage)
    return state


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_run(theme_name: str, theme_key: str | None, scope: str, guidance: str, value_chain: bool, *, run_store) -> RunState:
    params = {"theme_name": theme_name, "theme_key": theme_key, "scope": scope, "guidance": guidance, "value_chain": value_chain}
    manifest = JobManager(run_store).create_run("authority_taxonomy", params, 0)
    return _save(RunState(run_id=manifest.run_id, stage="discovering", step_started_at=_now(), **params), run_store)


def _finish(run_id: str, run_store, **update) -> RunState:
    """Saves a background step's outcome, unless the user cancelled meanwhile."""
    current = load_state(run_id, run_store)
    if current.stage == "cancelled":
        return current
    return _save(current.model_copy(update={"step_started_at": None, **update}), run_store)


async def discover(
    run_id: str, *, run_store, search_client, llm, user_agent: str, use_library: bool = True, library_root: Path | None = None,
) -> RunState:
    state = load_state(run_id, run_store)
    report = SearchReport()
    try:
        candidates = await discover_candidates(
            state.theme_name, state.theme_key, state.guidance, search_client=search_client, llm=llm,
            user_agent=user_agent, use_library=use_library, library_root=library_root, report=report,
        )
    except Exception as e:  # noqa: BLE001 - shown to the user as the run's error
        return _finish(run_id, run_store, stage="failed", error=str(e))
    return _finish(run_id, run_store, stage="awaiting_sources", candidates=candidates,
                   error=SEARCH_DOWN if report.unreachable else None)


async def start_run(
    theme_name: str, theme_key: str | None, scope: str, guidance: str, value_chain: bool, *,
    run_store, search_client, llm, user_agent: str, use_library: bool = True, library_root: Path | None = None,
) -> RunState:
    state = create_run(theme_name, theme_key, scope, guidance, value_chain, run_store=run_store)
    state = await discover(
        state.run_id, run_store=run_store, search_client=search_client, llm=llm, user_agent=user_agent,
        use_library=use_library, library_root=library_root,
    )
    if state.error:
        raise ValueError(state.error)
    return state


def _read_file(path: Path) -> tuple[str | None, list[int]]:
    # .pdf via fetch.py's pypdf extraction; anything else is read as UTF-8 text (.txt/.md)
    if path.suffix.lower() == ".pdf":
        text, breaks = extract_pdf_pages(path.read_bytes())
    else:
        text, breaks = path.read_text(errors="replace"), []
    return (text[:_MAX_CHARS] if text else None), breaks


def begin_extraction(run_id: str, urls: list[str], files: list[Path], *, run_store) -> RunState:
    state = _require(run_id, run_store, "awaiting_sources")
    selection = SourceSelection(urls=urls, files=[str(f) for f in files])
    return _save(state.model_copy(update={"stage": "extracting", "selection": selection, "step_started_at": _now()}), run_store)


async def _extract(state: RunState, *, llm, settings, user_agent: str, value_chain_model) -> tuple[ThemeDefinition, str]:
    selection = state.selection or SourceSelection()
    sources = [(u, *await fetch_source_pages(u, user_agent, max_chars=_MAX_CHARS)) for u in selection.urls]
    sources += [(f, *_read_file(Path(f))) for f in selection.files]
    extractions = [
        await extract_source(src, text, theme_name=state.theme_name, scope=state.scope, value_chain=state.value_chain,
                             llm=llm, page_breaks=breaks)
        for src, text, breaks in sources if text
    ]
    if not extractions:
        raise ValueError("no selected source could be read")
    draft, notes = await consolidate(
        extractions, theme_name=state.theme_name, scope=state.scope, value_chain=state.value_chain,
        settings=settings, llm=llm, value_chain_model=value_chain_model,
    )
    draft.scope = state.scope
    if unread := [src for src, text, _ in sources if not text]:
        notes = "\n".join(filter(None, [notes, f"Could not read: {', '.join(unread)}"]))
    return draft, notes


async def extract(
    run_id: str, *, run_store, llm, settings, user_agent: str, value_chain_model=None,
) -> RunState:
    state = load_state(run_id, run_store)
    try:
        draft, notes = await _extract(state, llm=llm, settings=settings, user_agent=user_agent, value_chain_model=value_chain_model)
    except Exception as e:  # noqa: BLE001 - shown to the user; the selection is kept for a retry
        return _finish(run_id, run_store, stage="awaiting_sources", error=str(e))
    return _finish(run_id, run_store, stage="awaiting_review", draft=draft, notes=notes, error=None)


async def select_sources(
    run_id: str, urls: list[str], files: list[Path], *,
    run_store, llm, settings, user_agent: str, value_chain_model=None,
) -> RunState:
    begin_extraction(run_id, urls, files, run_store=run_store)
    state = await extract(
        run_id, run_store=run_store, llm=llm, settings=settings, user_agent=user_agent, value_chain_model=value_chain_model,
    )
    if state.error:
        raise ValueError(state.error)
    return state


def refresh(state: RunState, run_store) -> RunState:
    """A step whose worker died (server restart) would poll forever; fail it the way an error would."""
    if state.stage not in ("discovering", "extracting") or not state.step_started_at:
        return state
    if datetime.now(UTC) - datetime.fromisoformat(state.step_started_at) < jobs._LEASE_GRACE or jobs.run_alive(run_store, state.run_id):
        return state
    back = "failed" if state.stage == "discovering" else "awaiting_sources"
    return _finish(state.run_id, run_store, stage=back, error=INTERRUPTED)


def put_draft(run_id: str, draft: ThemeDefinition, run_store) -> RunState:
    state = _require(run_id, run_store, "awaiting_review")
    for activity in draft.activities:
        if not activity.citations:
            raise ValueError(f"activity {activity.name} has no citation")
    return _save(state.model_copy(update={"draft": draft}), run_store)


def accept(run_id: str, run_store, taxonomy_store) -> RunState:
    state = _require(run_id, run_store, "awaiting_review")
    # shortcut: no lock, two concurrent accepts create two taxonomies; add a run lock when multi-user
    taxonomy = taxonomy_store.create(state.theme_name, state.draft, DerivationMethod.AUTHORITY_SOURCE, state.notes)
    return _save(state.model_copy(update={"stage": "accepted", "taxonomy_id": taxonomy.taxonomy_id}), run_store)


def cancel(run_id: str, run_store) -> RunState:
    state = _require(run_id, run_store, "discovering", "extracting", "awaiting_sources", "awaiting_review")
    return _save(state.model_copy(update={"stage": "cancelled", "step_started_at": None}), run_store)
