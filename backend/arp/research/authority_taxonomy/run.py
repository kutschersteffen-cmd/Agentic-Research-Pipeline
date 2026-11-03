"""Authority-taxonomy run: a stored state that pauses at awaiting_sources and
awaiting_review and resumes on user calls. Nothing reaches the TaxonomyStore before accept."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from arp.orchestration.job_manager import JobManager
from arp.research.authority_taxonomy.consolidate import consolidate
from arp.research.authority_taxonomy.discovery import Candidate, discover_candidates
from arp.research.authority_taxonomy.extract import extract_source
from arp.research.taxonomy_sources.fetch import extract_pdf_text, fetch_source_text
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition

Stage = Literal["awaiting_sources", "awaiting_review", "accepted", "cancelled"]
_MAX_CHARS = 400_000


class WrongStage(Exception):
    def __init__(self, stage: str) -> None:
        super().__init__(f"run is at stage {stage}")
        self.stage = stage


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


async def start_run(
    theme_name: str, theme_key: str | None, scope: str, guidance: str, value_chain: bool, *,
    run_store, search_client, llm, user_agent: str, use_library: bool = True, library_root: Path | None = None,
) -> RunState:
    params = {"theme_name": theme_name, "theme_key": theme_key, "scope": scope, "guidance": guidance, "value_chain": value_chain}
    manifest = JobManager(run_store).create_run("authority_taxonomy", params, 0)
    candidates = await discover_candidates(
        theme_name, theme_key, guidance, search_client=search_client, llm=llm, user_agent=user_agent,
        use_library=use_library, library_root=library_root,
    )
    state = RunState(run_id=manifest.run_id, stage="awaiting_sources", candidates=candidates, **params)
    return _save(state, run_store)


def _read_file(path: Path) -> str | None:
    # .pdf via fetch.py's pypdf extraction; anything else is read as UTF-8 text (.txt/.md)
    text = extract_pdf_text(path.read_bytes()) if path.suffix.lower() == ".pdf" else path.read_text(errors="replace")
    return text[:_MAX_CHARS] if text else None


async def select_sources(
    run_id: str, urls: list[str], files: list[Path], *,
    run_store, llm, settings, user_agent: str, value_chain_model=None,
) -> RunState:
    state = _require(run_id, run_store, "awaiting_sources")
    sources = [(u, await fetch_source_text(u, user_agent, max_chars=_MAX_CHARS)) for u in urls]
    sources += [(str(f), _read_file(f)) for f in files]
    extractions = [
        await extract_source(src, text, theme_name=state.theme_name, scope=state.scope, value_chain=state.value_chain, llm=llm)
        for src, text in sources if text
    ]
    if not extractions:
        raise ValueError("no selected source could be read")
    draft, notes = await consolidate(
        extractions, theme_name=state.theme_name, scope=state.scope, value_chain=state.value_chain,
        settings=settings, llm=llm, value_chain_model=value_chain_model,
    )
    draft.scope = state.scope
    if unread := [src for src, text in sources if not text]:
        notes = "\n".join(filter(None, [notes, f"Could not read: {', '.join(unread)}"]))
    return _save(state.model_copy(update={"stage": "awaiting_review", "draft": draft, "notes": notes}), run_store)


def put_draft(run_id: str, draft: ThemeDefinition, run_store) -> RunState:
    state = _require(run_id, run_store, "awaiting_review")
    for activity in draft.activities:
        if not activity.citations:
            raise ValueError(f"activity {activity.name} has no citation")
    return _save(state.model_copy(update={"draft": draft}), run_store)


def accept(run_id: str, run_store, taxonomy_store) -> RunState:
    state = _require(run_id, run_store, "awaiting_review")
    taxonomy = taxonomy_store.create(state.theme_name, state.draft, DerivationMethod.AUTHORITY_SOURCE, state.notes)
    return _save(state.model_copy(update={"stage": "accepted", "taxonomy_id": taxonomy.taxonomy_id}), run_store)


def cancel(run_id: str, run_store) -> RunState:
    state = _require(run_id, run_store, "awaiting_sources", "awaiting_review")
    return _save(state.model_copy(update={"stage": "cancelled"}), run_store)
