from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from arp.api.deps import get_llm_client, get_run_store, get_taxonomy_store, get_web_search_client, settings_dep
from arp.config import Settings
from arp.research.authority_taxonomy import run
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.schemas.thematic import ThemeDefinition

router = APIRouter(prefix="/api/authority-taxonomy", tags=["authority-taxonomy"])


class AuthorityRunRequest(BaseModel):
    theme_name: str
    theme_key: str | None = None
    scope: str = ""
    guidance: str = ""
    value_chain: bool = False


class AuthorityRunStarted(BaseModel):
    id: str
    stage: str


class SourcesRequest(BaseModel):
    urls: list[str] = []
    files: list[str] = []


class AcceptResponse(BaseModel):
    taxonomy_id: str


def _state(run_id: str, run_store) -> run.RunState:
    try:
        return run.load_state(run_id, run_store)
    except KeyError:
        raise HTTPException(404, "run not found") from None


def _http(e: Exception) -> HTTPException:
    if isinstance(e, run.WrongStage):
        return HTTPException(409, f"run is at stage {e.stage}")
    return HTTPException(422, str(e))


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (run.WrongStage, ValueError) as e:
        raise _http(e) from None


@router.post("/runs", status_code=201, response_model=AuthorityRunStarted)
async def start(
    req: AuthorityRunRequest, settings: Settings = Depends(settings_dep), run_store=Depends(get_run_store),
    llm=Depends(get_llm_client), search_client=Depends(get_web_search_client),
) -> AuthorityRunStarted:
    state = await run.start_run(
        req.theme_name, req.theme_key, req.scope, req.guidance, req.value_chain,
        run_store=run_store, search_client=search_client, llm=llm, user_agent=settings.discovery_user_agent,
    )
    return AuthorityRunStarted(id=state.run_id, stage=state.stage)


@router.get("/runs/{run_id}", response_model=run.RunState)
def get_run(run_id: str, run_store=Depends(get_run_store)) -> run.RunState:
    return _state(run_id, run_store)


@router.post("/runs/{run_id}/sources", response_model=run.RunState)
async def select_sources(
    run_id: str, req: SourcesRequest, settings: Settings = Depends(settings_dep),
    run_store=Depends(get_run_store), llm=Depends(get_llm_client),
) -> run.RunState:
    if not req.urls and not req.files:
        raise HTTPException(422, "select at least one source")
    root = settings.documents_dir.resolve()
    paths = []
    for f in req.files:
        try:
            path = Path(f).resolve()
            ok = path.is_relative_to(root) and path.is_file()
        except (OSError, ValueError):  # ValueError: NUL byte in the path
            ok = False
        if not ok:
            raise HTTPException(422, f"file not allowed: {Path(f).name}")
        paths.append(path)
    state = _state(run_id, run_store)
    model = resolve_indirect_exposure_model(settings) if state.value_chain else None
    try:
        return await run.select_sources(
            run_id, req.urls, paths, run_store=run_store, llm=llm, settings=settings,
            user_agent=settings.discovery_user_agent, value_chain_model=model,
        )
    except (run.WrongStage, ValueError, OSError) as e:
        raise _http(e) from None


@router.get("/runs/{run_id}/draft", response_model=ThemeDefinition)
def get_draft(run_id: str, run_store=Depends(get_run_store)) -> ThemeDefinition:
    draft = _state(run_id, run_store).draft
    if draft is None:
        raise HTTPException(422, "run has no draft yet")
    return draft


@router.put("/runs/{run_id}/draft", response_model=run.RunState)
def put_draft(run_id: str, draft: ThemeDefinition, run_store=Depends(get_run_store)) -> run.RunState:
    _state(run_id, run_store)
    return _guard(run.put_draft, run_id, draft, run_store)


@router.post("/runs/{run_id}/accept", status_code=201, response_model=AcceptResponse)
def accept(run_id: str, run_store=Depends(get_run_store), taxonomy_store=Depends(get_taxonomy_store)) -> AcceptResponse:
    _state(run_id, run_store)
    state = _guard(run.accept, run_id, run_store, taxonomy_store)
    return AcceptResponse(taxonomy_id=state.taxonomy_id)


@router.delete("/runs/{run_id}", status_code=204)
def cancel(run_id: str, run_store=Depends(get_run_store)) -> Response:
    _state(run_id, run_store)
    _guard(run.cancel, run_id, run_store)
    return Response(status_code=204)
