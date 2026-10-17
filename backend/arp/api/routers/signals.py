from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

import arp.signal_lab.methods  # noqa: F401  (importing registers every method)
from arp.api.auth import Principal, require_role
from arp.api.deps import get_run_store
from arp.config import get_settings
from arp.db.session import require_dsn
from arp.signal_lab.compare import Comparison, compare_experiments
from arp.signal_lab.cutoffs import CutoffTable, load_cutoff_table
from arp.signal_lab.inputs import load_inputs
from arp.signal_lab.methods.base import TEXTLESS_METHODS, get_method, method_names, run_recipe, spec_nodes
from arp.signal_lab.registry import ExperimentRecord, Recipe, Registry
from arp.signal_lab.text_store import TextStore
from arp.storage.safe_path import safe_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signals", tags=["signals"])

APP_RUNNABLE = frozenset({"panel", "price_momentum", "narrative_attention", "sestm", "transform", "composite"})

CutoffStatus = Literal["none", "recorded", "unknown"]


def _cutoff_status(record: ExperimentRecord, cutoffs: CutoffTable) -> CutoffStatus:
    if record.model is None:
        return "none"
    return "unknown" if cutoffs.cutoff_for(record.model) is None else "recorded"


def _http(exc: ValueError) -> HTTPException:
    # The app-wide ValueError handler answers 400; the library's message is the detail either way.
    return HTTPException(404 if str(exc).startswith("unknown experiment") else 422, detail=str(exc))


def _registry() -> Registry:
    return Registry(get_run_store())


class ExperimentSummary(BaseModel):
    experiment_id: str
    category: str
    method: str
    universe: str
    window_start: str
    window_end: str
    cost_bps: float
    model: str | None
    cutoff: str | None
    decision: Literal["none", "graduate", "shelve"]
    n_trials: int
    created_at: str
    cutoff_status: CutoffStatus


class ExperimentDetail(ExperimentRecord):
    cutoff_status: CutoffStatus


class MethodInfo(BaseModel):
    name: str
    runnable_in_app: bool


class CompareRequest(BaseModel):
    a: str
    b: str


class DecisionRequest(BaseModel):
    decision: Literal["graduate", "shelve"]


def _load_cutoffs() -> CutoffTable:
    return load_cutoff_table(get_settings().training_cutoffs_path)


def _detail(record: ExperimentRecord, cutoffs: CutoffTable) -> ExperimentDetail:
    return ExperimentDetail(**dict(record), cutoff_status=_cutoff_status(record, cutoffs))


def _summary(record: ExperimentRecord, cutoffs: CutoffTable) -> ExperimentSummary:
    r = record.recipe
    return ExperimentSummary(
        experiment_id=record.experiment_id, category=r.category, method=r.method, universe=r.universe,
        window_start=r.window_start, window_end=r.window_end, cost_bps=r.cost_bps, model=record.model,
        cutoff=record.cutoff, decision=record.decision, n_trials=record.evidence.n_trials,
        created_at=record.created_at, cutoff_status=_cutoff_status(record, cutoffs),
    )


@router.get("/experiments")
def list_experiments(registry: Registry = Depends(_registry)) -> list[ExperimentSummary]:
    cutoffs = _load_cutoffs()
    return [_summary(r, cutoffs) for r in reversed(registry.list_experiments())]


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str, registry: Registry = Depends(_registry)) -> ExperimentDetail:
    record = next((r for r in registry.list_experiments() if r.experiment_id == experiment_id), None)
    if record is None:
        raise _http(ValueError(f"unknown experiment {experiment_id!r}"))
    return _detail(record, _load_cutoffs())


@router.get("/methods")
def list_methods() -> list[MethodInfo]:
    return [MethodInfo(name=n, runnable_in_app=n in APP_RUNNABLE) for n in method_names()]


@router.post("/compare")
def compare(req: CompareRequest, registry: Registry = Depends(_registry)) -> Comparison:
    try:
        return compare_experiments(req.a, req.b, registry)
    except ValueError as exc:
        # Every compare error, an unknown id included, is a bad request body, not a missing URL.
        raise HTTPException(422, detail=str(exc)) from exc


@router.post("/experiments/{experiment_id}/decision")
def decide(
    experiment_id: str,
    req: DecisionRequest,
    principal: Principal = Depends(require_role("approver")),
    registry: Registry = Depends(_registry),
) -> ExperimentDetail:
    try:
        cutoffs = _load_cutoffs()
        if req.decision == "graduate":
            record = next((r for r in registry.list_experiments() if r.experiment_id == experiment_id), None)
            if record is not None and _cutoff_status(record, cutoffs) == "unknown":
                raise HTTPException(
                    422,
                    detail=f"cannot graduate {experiment_id}: model {record.model!r} has no recorded training "
                    "cutoff (cutoff unknown: not evidence)",
                )
        return _detail(registry.decide(experiment_id, req.decision, approver=principal.user_id, cutoffs=cutoffs), cutoffs)
    except ValueError as exc:
        raise _http(exc) from exc


def _run_upload(recipe_bytes: bytes, prices_bytes: bytes, panel_bytes: dict[str, bytes], registry: Registry) -> ExperimentDetail:
    """What `arp signals run` does, from uploaded bytes: same checks, same data version, same registry."""
    try:
        recipe = Recipe.model_validate_json(recipe_bytes)
    except ValidationError as exc:
        detail = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'recipe'}: {e['msg']}" for e in exc.errors())
        raise ValueError(f"invalid recipe: {detail}") from exc
    nodes = list(spec_nodes({"method": recipe.method, "params": recipe.params}))
    for node in nodes:
        get_method(node.get("method"))
    for node in nodes:
        if node["method"] not in APP_RUNNABLE:
            raise ValueError(
                f"{node['method']} runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app"
            )
    names = {node["method"] for node in nodes}
    with tempfile.TemporaryDirectory() as tmp:
        prices = Path(tmp) / "prices.csv"
        prices.write_bytes(prices_bytes)
        panels = {name: Path(tmp) / f"panel_{safe_id(name, label='panel name')}.csv" for name in panel_bytes}
        for name, path in panels.items():
            path.write_bytes(panel_bytes[name])
        texts = [] if names <= TEXTLESS_METHODS else TextStore(require_dsn(get_settings())).items()
        inp, data_version = load_inputs(recipe, prices, panels=panels, texts=texts)
        cutoffs = _load_cutoffs()
        record = run_recipe(recipe, inp, registry=registry, cutoffs=cutoffs, data_version=data_version)
    return _detail(record, cutoffs)


@router.post("/runs")
async def run(
    request: Request,
    _: Principal = Depends(require_role("analyst")),
    registry: Registry = Depends(_registry),
) -> ExperimentDetail:
    # Read the form by hand: the panel parts are named panel_<name>, a set FastAPI can't declare.
    async with request.form() as form:
        for key in ("recipe", "prices"):
            if not isinstance(form.get(key), UploadFile):
                raise HTTPException(422, detail=f"missing file part {key!r}")
        panel_bytes = {
            key.removeprefix("panel_"): await part.read()
            for key, part in form.multi_items()
            if key.startswith("panel_") and isinstance(part, UploadFile)
        }
        try:
            return await run_in_threadpool(
                _run_upload, await form["recipe"].read(), await form["prices"].read(), panel_bytes, registry
            )
        except ValueError as exc:
            raise _http(exc) from exc
        except Exception as exc:  # may carry library or database detail: the type only, never a traceback
            logger.exception("signals run failed")
            raise HTTPException(500, detail=f"Run failed: {type(exc).__name__}") from exc
