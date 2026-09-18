from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from arp.api.deps import get_decision_store, get_portfolio_store, get_run_store, settings_dep
from arp.config import Settings
from arp.decision import sources
from arp.decision.compare import compare_results
from arp.decision.dataset import Dataset, build_dataset
from arp.decision.diffing import describe_changes
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.parsing import load_table
from arp.decision.profiling import profile_dataset
from arp.decision.roles import propose_roles
from arp.decision.sensitivity import tipping_points
from arp.schemas.decision import (
    AuditEntry,
    ColumnProfile,
    DecisionComparison,
    DecisionResult,
    EntitySensitivity,
    MechanismConfig,
    RoleProposal,
)
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_filename

router = APIRouter(prefix="/api/decision", tags=["decision"])

_PREVIEW_ROWS = 25


class DatasetSummary(BaseModel):
    """What the Data and Profile tabs render. Rows are capped: a 4,000-row
    universe is scored server-side and only ever previewed in the UI."""

    dataset_id: str
    name: str
    source: str
    source_ref: str | None = None
    as_of: str | None = None
    row_count: int
    columns: list[str]
    preview: list[dict[str, str]]
    profiles: list[ColumnProfile]
    proposals: list[RoleProposal]
    has_confidence: bool = False


def _summarise(dataset: Dataset) -> DatasetSummary:
    profiles = profile_dataset(dataset)
    return DatasetSummary(
        dataset_id=dataset.dataset_id,
        name=dataset.name,
        source=dataset.source,
        source_ref=dataset.source_ref,
        as_of=dataset.as_of,
        row_count=dataset.row_count,
        columns=dataset.columns,
        preview=dataset.rows[:_PREVIEW_ROWS],
        profiles=[profiles[c] for c in dataset.columns],
        proposals=propose_roles(profiles, dataset.columns),
        has_confidence=bool(dataset.confidence),
    )


def _load_dataset(dataset_id: str, store: DecisionStore) -> Dataset:
    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(404, f"Unknown dataset: {dataset_id}")
    return dataset


def _resolve_config(req_config: MechanismConfig | None, framework_id: str | None, version: int | None, store: DecisionStore) -> MechanismConfig:
    """A request may carry a framework inline (the UI's live editing case)
    or name a stored one (the reproducible case). Naming a version is what
    makes a result citable later, so both are supported and the result
    records which framework version it used either way."""
    if req_config is not None:
        return req_config
    if not framework_id:
        raise HTTPException(400, "Provide either `config` or `framework_id`.")
    config = store.get(framework_id, version)
    if config is None:
        raise HTTPException(404, f"Unknown framework: {framework_id}" + (f" v{version}" if version else ""))
    return config


# --- datasets ---


@router.post("/datasets", response_model=DatasetSummary)
async def upload_dataset(
    file: UploadFile,
    settings: Settings = Depends(settings_dep),
    store: DecisionStore = Depends(get_decision_store),
) -> DatasetSummary:
    """Uploads a CSV/TSV/XLSX table and profiles it.

    Parsing happens here rather than in the browser: an Excel file needs a
    parser (openpyxl, already a dependency), and a score computed in a
    browser tab is not reproducible, not citable and not reviewable --
    which is the whole reason this layer lives server-side.
    """
    try:
        name = safe_filename(file.filename)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc
    dest_dir = settings.frameworks_dir / "_uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / name
    dest_path.write_bytes(await file.read())
    try:
        matrix = load_table(dest_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    dataset = build_dataset(name, matrix, source="upload", source_ref=str(dest_path))
    store.save_dataset(dataset)
    return _summarise(dataset)


class FromSourceRequest(BaseModel):
    source: str = Field(description="transition_plan_run | extraction_run | theme_run | portfolio_snapshot")
    run_id: str | None = None
    as_of: str | None = None
    portfolio_ids: list[str] | None = None


@router.post("/datasets/from-source", response_model=DatasetSummary)
def dataset_from_source(
    req: FromSourceRequest,
    store: DecisionStore = Depends(get_decision_store),
    run_store: RunStore = Depends(get_run_store),
    portfolio_store=Depends(get_portfolio_store),
) -> DatasetSummary:
    """Builds the decision table from data this system already produced,
    instead of from an upload -- which is the point of having this layer
    here rather than in a spreadsheet."""
    try:
        if req.source == "transition_plan_run":
            dataset = sources.from_transition_plan_run(run_store, _require(req.run_id, "run_id"))
        elif req.source == "extraction_run":
            dataset = sources.from_extraction_run(run_store, _require(req.run_id, "run_id"))
        elif req.source == "theme_run":
            dataset = sources.from_theme_run(run_store, _require(req.run_id, "run_id"))
        elif req.source == "portfolio_snapshot":
            dataset = sources.from_portfolio_snapshot(portfolio_store, req.as_of, req.portfolio_ids)
        else:
            raise HTTPException(400, f"Unknown source: {req.source}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    store.save_dataset(dataset)
    return _summarise(dataset)


def _require(value: str | None, field: str) -> str:
    if not value:
        raise HTTPException(400, f"`{field}` is required for this source.")
    return value


@router.get("/datasets", response_model=list[DatasetSummary])
def list_datasets(store: DecisionStore = Depends(get_decision_store)) -> list[DatasetSummary]:
    return [_summarise(ds) for ds in store.list_datasets()]


@router.get("/datasets/{dataset_id}", response_model=DatasetSummary)
def get_dataset(dataset_id: str, store: DecisionStore = Depends(get_decision_store)) -> DatasetSummary:
    return _summarise(_load_dataset(dataset_id, store))


# --- frameworks ---


class DeriveRequest(BaseModel):
    dataset_id: str
    name: str | None = None
    cluster_threshold: float = 0.72
    save: bool = Field(default=False, description="Persist the derived framework as v1 straight away.")


class MechanismEnvelope(BaseModel):
    config: MechanismConfig
    audit: list[AuditEntry] = Field(default_factory=list)


@router.post("/mechanisms/derive", response_model=MechanismEnvelope)
def derive(req: DeriveRequest, store: DecisionStore = Depends(get_decision_store)) -> MechanismEnvelope:
    dataset = _load_dataset(req.dataset_id, store)
    config, audit = derive_mechanism(dataset, name=req.name, cluster_threshold=req.cluster_threshold)
    if req.save:
        store.save(config, audit)
    return MechanismEnvelope(config=config, audit=audit)


class SaveRequest(BaseModel):
    config: MechanismConfig
    base_version: int | None = Field(
        default=None,
        description="The version the edits were made on top of. Supplying it produces the human-origin half of the "
        "audit log -- which rules a person changed, as against which the data proposed.",
    )
    by: str | None = None


@router.post("/mechanisms", response_model=MechanismEnvelope)
def save_mechanism(req: SaveRequest, store: DecisionStore = Depends(get_decision_store)) -> MechanismEnvelope:
    """Saves a new version of a framework. Never an in-place edit: the
    version the last decision cited stays readable exactly as it was."""
    previous = store.get(req.config.framework_id, req.base_version)
    audit = list(store.get_audit(req.config.framework_id, previous.version) if previous else [])
    if previous is not None:
        audit.extend(describe_changes(previous, req.config, by=req.by))
    saved = store.new_version(req.config, audit) if previous is not None else store.save(req.config, audit)
    return MechanismEnvelope(config=saved, audit=audit)


@router.get("/mechanisms", response_model=list[MechanismConfig])
def list_mechanisms(store: DecisionStore = Depends(get_decision_store)) -> list[MechanismConfig]:
    return store.list_frameworks()


@router.get("/mechanisms/{framework_id}", response_model=MechanismEnvelope)
def get_mechanism(framework_id: str, version: int | None = None, store: DecisionStore = Depends(get_decision_store)) -> MechanismEnvelope:
    config = store.get(framework_id, version)
    if config is None:
        raise HTTPException(404, f"Unknown framework: {framework_id}")
    return MechanismEnvelope(config=config, audit=store.get_audit(framework_id, config.version))


@router.get("/mechanisms/{framework_id}/versions", response_model=list[int])
def list_mechanism_versions(framework_id: str, store: DecisionStore = Depends(get_decision_store)) -> list[int]:
    return store.list_versions(framework_id)


@router.post("/mechanisms/{framework_id}/ratify", response_model=MechanismConfig)
def ratify_mechanism(framework_id: str, version: int | None = None, store: DecisionStore = Depends(get_decision_store)) -> MechanismConfig:
    try:
        return store.ratify(framework_id, version)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# --- scoring ---


class ScoreRequest(BaseModel):
    dataset_id: str
    config: MechanismConfig | None = None
    framework_id: str | None = None
    version: int | None = None


@router.post("/score", response_model=DecisionResult)
def score(req: ScoreRequest, store: DecisionStore = Depends(get_decision_store)) -> DecisionResult:
    """Deterministic and synchronous -- no LLM call anywhere in this path,
    so there is nothing to schedule and nothing to poll."""
    dataset = _load_dataset(req.dataset_id, store)
    config = _resolve_config(req.config, req.framework_id, req.version, store)
    audit = store.get_audit(config.framework_id, config.version) if req.config is None else None
    return apply_mechanism(dataset, config, derivation_audit=audit)


@router.post("/export.csv", response_class=PlainTextResponse)
def export_csv(req: ScoreRequest, store: DecisionStore = Depends(get_decision_store)) -> PlainTextResponse:
    dataset = _load_dataset(req.dataset_id, store)
    config = _resolve_config(req.config, req.framework_id, req.version, store)
    result = apply_mechanism(dataset, config)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["rank", "name", "segment", "cohort", "score", "tier", "tier_name", "action", "status", "coverage_pct", "grounded_coverage_pct", "rank_min", "rank_max", "size", "leverage", "leverage_rank", "notes"])
    for entity in sorted(result.entities, key=lambda e: (e.rank is None, e.rank or 0, e.name)):
        writer.writerow(
            [
                entity.rank or "",
                entity.name,
                entity.segment or "",
                entity.cohort or "",
                f"{entity.score:.2f}" if entity.score is not None else "",
                entity.tier or "",
                entity.tier_name or "",
                entity.tier_action or "",
                entity.status,
                f"{entity.coverage * 100:.0f}",
                f"{entity.grounded_coverage * 100:.0f}" if entity.grounded_coverage is not None else "",
                entity.rank_min or "",
                entity.rank_max or "",
                f"{entity.size:g}" if entity.size is not None else "",
                f"{entity.leverage:.2f}" if entity.leverage is not None else "",
                entity.leverage_rank or "",
                "; ".join(entity.notes),
            ]
        )
    return PlainTextResponse(buffer.getvalue(), media_type="text/csv")


class SensitivityRequest(ScoreRequest):
    entity_keys: list[str] | None = None
    steps: int = Field(default=13, ge=3, le=41)


@router.post("/sensitivity", response_model=list[EntitySensitivity])
def sensitivity(req: SensitivityRequest, store: DecisionStore = Depends(get_decision_store)) -> list[EntitySensitivity]:
    """How far a weight must move before a tier changes. Re-runs the whole
    mechanism once per weight step, so it is requested for the entities a
    reviewer is actually questioning rather than computed for every row on
    every score."""
    dataset = _load_dataset(req.dataset_id, store)
    config = _resolve_config(req.config, req.framework_id, req.version, store)
    return tipping_points(dataset, config, entity_keys=req.entity_keys, steps=req.steps)


class CompareRequest(BaseModel):
    dataset_id_before: str
    dataset_id_after: str
    config: MechanismConfig | None = None
    framework_id: str | None = None
    version: int | None = None


@router.post("/compare", response_model=DecisionComparison)
def compare(req: CompareRequest, store: DecisionStore = Depends(get_decision_store)) -> DecisionComparison:
    """The same framework over two snapshots. Pinning the framework version
    is what makes the movement attributable to the companies rather than
    to a change in how they were judged."""
    before = _load_dataset(req.dataset_id_before, store)
    after = _load_dataset(req.dataset_id_after, store)
    config = _resolve_config(req.config, req.framework_id, req.version, store)
    return compare_results(
        apply_mechanism(before, config),
        apply_mechanism(after, config),
        label_before=before.as_of or before.name,
        label_after=after.as_of or after.name,
    )
