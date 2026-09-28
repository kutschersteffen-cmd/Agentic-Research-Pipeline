from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from arp.api.deps import get_decision_store, get_portfolio_store, get_run_store, settings_dep
from arp.config import Settings
from arp.decision import sources, templates
from arp.decision.compare import compare_results
from arp.decision.dataset import Dataset, build_dataset
from arp.decision.diffing import describe_changes
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.parsing import load_table
from arp.decision.profiling import profile_dataset
from arp.decision.publish import publish
from arp.decision.roles import propose_roles, slug
from arp.decision.rules import apply_rules, rule_inputs
from arp.decision.sensitivity import tipping_points
from arp.schemas.decision import (
    AuditEntry,
    ColumnProfile,
    DecisionComparison,
    DecisionResult,
    EntitySensitivity,
    MechanismConfig,
    PublishedDecision,
    RoleProposal,
    check_rule_graph,
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
    rule_inputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="The preview rows typed exactly as the rule engine sees them -- what the browser evaluates a "
        "rule graph against while it is being edited, so its preview and the server's score agree.",
    )
    calculated_columns: list[str] = Field(default_factory=list)
    rule_audit: list[AuditEntry] = Field(default_factory=list)


def _summarise(dataset: Dataset, *, base: Dataset | None = None, calculated: list[str] | None = None, rule_audit: list[AuditEntry] | None = None) -> DatasetSummary:
    profiles = profile_dataset(dataset)
    base = base or dataset
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
        rule_inputs=rule_inputs(base, rows=base.rows[:_PREVIEW_ROWS]),
        calculated_columns=calculated or [],
        rule_audit=rule_audit or [],
    )


def _apply(dataset: Dataset, config: MechanismConfig, **kwargs) -> DecisionResult:
    try:
        return apply_mechanism(dataset, config, **kwargs)
    except ValueError as exc:  # a rule graph that does not compile
        raise HTTPException(400, str(exc)) from exc


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
    source: str = Field(
        description="transition_plan_run | extraction_run | theme_run | portfolio_snapshot | "
        "transition_barrier | emerging_themes_run | replication_runs"
    )
    run_id: str | None = None
    include_indicators: bool = Field(default=False, description="transition_plan_run: one Yes/No column per indicator.")
    run_ids: list[str] | None = Field(default=None, description="replication_runs: defaults to every strategy_replication run.")
    as_of: str | None = None
    portfolio_ids: list[str] | None = None
    region: str | None = Field(default=None, description="transition_barrier: one of the matrix's three jurisdictions.")
    sectors: list[str] | None = None


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
            dataset = sources.from_transition_plan_run(
                run_store, _require(req.run_id, "run_id"), include_indicators=req.include_indicators
            )
        elif req.source == "extraction_run":
            dataset = sources.from_extraction_run(run_store, _require(req.run_id, "run_id"))
        elif req.source == "theme_run":
            dataset = sources.from_theme_run(run_store, _require(req.run_id, "run_id"))
        elif req.source == "portfolio_snapshot":
            dataset = sources.from_portfolio_snapshot(portfolio_store, req.as_of, req.portfolio_ids)
        # The three below score something other than a company -- a sector in
        # a jurisdiction, a theme, a strategy. The engine does not care.
        elif req.source == "transition_barrier":
            dataset = sources.from_transition_barrier(req.region, req.sectors)
        elif req.source == "emerging_themes_run":
            dataset = sources.from_emerging_themes_run(run_store, _require(req.run_id, "run_id"))
        elif req.source == "replication_runs":
            dataset = sources.from_replication_runs(run_store, req.run_ids)
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


class CalculatedRequest(BaseModel):
    rule_graph: dict[str, Any]

    @field_validator("rule_graph")
    @classmethod
    def _declarative_rules_only(cls, graph: dict[str, Any]) -> dict[str, Any]:
        return check_rule_graph(graph)


@router.post("/datasets/{dataset_id}/calculated", response_model=DatasetSummary)
def calculated_columns(dataset_id: str, req: CalculatedRequest, store: DecisionStore = Depends(get_decision_store)) -> DatasetSummary:
    """The table as a rule graph extends it: calculated columns profiled over
    every row and given role proposals, so they can be made criteria or
    gates. Evaluated server-side over the whole table; the browser's own
    evaluation only ever covers the preview rows."""
    dataset = _load_dataset(dataset_id, store)
    try:
        augmented, audit = apply_rules(dataset, req.rule_graph)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _summarise(augmented, base=dataset, calculated=augmented.columns[len(dataset.columns) :], rule_audit=audit)


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


@router.get("/mechanisms/{framework_id}/export")
def export_mechanism(framework_id: str, version: int | None = None, store: DecisionStore = Depends(get_decision_store)) -> JSONResponse:
    """One framework version as a downloadable scoring template."""
    config = store.get(framework_id, version)
    if config is None:
        raise HTTPException(404, f"Unknown framework: {framework_id}")
    filename = f"{slug(config.name) or 'framework'}_v{config.version}.template.json"
    return JSONResponse(
        templates.export_template(config, store.get_audit(framework_id, config.version)),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ImportRequest(BaseModel):
    template: dict[str, Any]
    by: str | None = None


@router.post("/mechanisms/import", response_model=MechanismEnvelope)
def import_mechanism(req: ImportRequest, store: DecisionStore = Depends(get_decision_store)) -> MechanismEnvelope:
    """A template file -> a new, unratified framework in this installation."""
    try:
        config, audit = templates.import_template(req.template, by=req.by)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    store.save(config, audit)
    return MechanismEnvelope(config=config, audit=audit)


class TemplateMatchRequest(BaseModel):
    run_type: str | None = Field(default=None, description="extraction | transition_plan -- the columns such a run will produce.")
    field_names: list[str] = Field(default_factory=list, description="extraction: the schema's field names.")
    columns: list[str] | None = Field(default=None, description="Or the table's columns directly.")


class TemplateMatch(BaseModel):
    config: MechanismConfig
    required_columns: list[str]
    missing_columns: list[str]


@router.post("/templates/match", response_model=list[TemplateMatch])
def match_templates(req: TemplateMatchRequest, store: DecisionStore = Depends(get_decision_store)) -> list[TemplateMatch]:
    """Every saved framework (latest version), with the columns it needs that
    this table or schema would not supply. Fitting templates first."""
    if req.columns is not None:
        columns = req.columns
    elif req.run_type:
        try:
            columns = templates.expected_run_columns(req.run_type, req.field_names)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        raise HTTPException(400, "Provide `columns` or `run_type`.")
    matches = [
        TemplateMatch(config=c, required_columns=templates.required_columns(c), missing_columns=templates.missing_columns(c, columns))
        for c in store.list_frameworks()
    ]
    return sorted(matches, key=lambda m: len(m.missing_columns))


@router.post("/mechanisms/{framework_id}/ratify", response_model=MechanismConfig)
def ratify_mechanism(
    framework_id: str,
    version: int | None = None,
    ratified_by: str | None = None,
    store: DecisionStore = Depends(get_decision_store),
) -> MechanismConfig:
    """`ratified_by` names the person ratifying; the UI always sends it."""
    try:
        return store.ratify(framework_id, version, ratified_by=ratified_by.strip() if ratified_by else None)
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
    return _apply(dataset, config, derivation_audit=audit)


@router.post("/export.csv", response_class=PlainTextResponse)
def export_csv(req: ScoreRequest, store: DecisionStore = Depends(get_decision_store)) -> PlainTextResponse:
    dataset = _load_dataset(req.dataset_id, store)
    config = _resolve_config(req.config, req.framework_id, req.version, store)
    result = _apply(dataset, config)
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
    try:
        return tipping_points(dataset, config, entity_keys=req.entity_keys, steps=req.steps)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# --- scoring templates attached to runs ---


def template_for_run(
    store: DecisionStore, run_type: str, framework_id: str, version: int | None, field_names: list[str] | None = None
) -> MechanismConfig:
    """Resolves the framework a run is being started (or re-scored) with and
    refuses one that needs columns the run cannot produce -- found now, not
    after an hour of extraction. Resolving pins today's latest version."""
    config = store.get(framework_id, version)
    if config is None:
        raise HTTPException(404, f"Unknown framework: {framework_id}" + (f" v{version}" if version else ""))
    try:
        missing = templates.missing_columns(config, templates.expected_run_columns(run_type, field_names))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if missing:
        raise HTTPException(400, f"{config.name} v{config.version} needs columns this run will not produce: {', '.join(missing)}")
    return config


class AttachRequest(BaseModel):
    framework_id: str
    version: int | None = None


@router.put("/runs/{run_id}/framework")
def attach_framework(
    run_id: str,
    req: AttachRequest,
    store: DecisionStore = Depends(get_decision_store),
    run_store: RunStore = Depends(get_run_store),
) -> dict:
    """Attaches (or replaces) the scoring template on an existing run."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    field_names = None
    if manifest.run_type == "extraction":
        schema = run_store.run_dir(run_id) / "schema.json"
        field_names = [f["name"] for f in json.loads(schema.read_text()).get("fields", [])] if schema.exists() else []
    config = template_for_run(store, manifest.run_type, req.framework_id, req.version, field_names)
    return templates.attach_to_run(run_store, run_id, config).params["decision_framework"]


class RunDecision(BaseModel):
    framework: dict[str, Any]
    ratified: bool = Field(default=False, description="Whether the pinned version is ratified -- only then can it be published.")
    run_status: str
    missing_columns: list[str]
    result: DecisionResult


def _run_scoring(run_id: str, store: DecisionStore, run_store: RunStore):
    """The run's manifest, pinned framework version and current table."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    pinned = manifest.params.get("decision_framework")
    if not pinned:
        raise HTTPException(404, "No scoring template is attached to this run.")
    config = store.get(pinned["framework_id"], pinned.get("version"))
    if config is None:
        raise HTTPException(404, f"Attached framework {pinned['framework_id']} v{pinned.get('version')} no longer exists.")
    try:
        dataset = templates.run_dataset(run_store, manifest)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return manifest, pinned, config, dataset


@router.get("/runs/{run_id}/decision", response_model=RunDecision)
def run_decision(
    run_id: str, store: DecisionStore = Depends(get_decision_store), run_store: RunStore = Depends(get_run_store)
) -> RunDecision:
    """The run's results scored with its pinned template. Computed on request
    rather than stored: the template version is fixed and results only
    grow, so the same request always gives the same answer, and a run still
    in progress is scored on what it has so far (`run_status` says so)."""
    manifest, pinned, config, dataset = _run_scoring(run_id, store, run_store)
    return RunDecision(
        framework=pinned,
        ratified=config.ratified,
        run_status=manifest.status.value,
        missing_columns=templates.missing_columns(config, dataset.columns),
        result=_apply(dataset, config, derivation_audit=store.get_audit(config.framework_id, config.version)),
    )


class RunPublishRequest(BaseModel):
    published_by: str
    note: str = ""


# A run in these states will not gain more results, so its tiers are final.
_FINISHED = {"completed", "partially_completed", "cancelled"}


@router.post("/runs/{run_id}/publish", response_model=PublishedDecision)
def publish_run(
    run_id: str,
    req: RunPublishRequest,
    store: DecisionStore = Depends(get_decision_store),
    run_store: RunStore = Depends(get_run_store),
) -> PublishedDecision:
    """Publishes a run's tiers straight from the run, with the pinned version.

    Stricter than publishing from the studio in two ways, both because nobody
    looks at a table here before signing: the run must have finished (tiers
    from half a run would be frozen as if they covered the universe), and no
    column the template needs may be missing (criteria on a missing column
    are skipped, which changes the score without saying so). The scored table
    is saved as a dataset, so the snapshot's dataset_id opens in the studio."""
    manifest, _pinned, config, dataset = _run_scoring(run_id, store, run_store)
    if manifest.status.value not in _FINISHED:
        raise HTTPException(409, f"The run is {manifest.status.value}; publish once it has finished.")
    missing = templates.missing_columns(config, dataset.columns)
    if missing:
        raise HTTPException(422, f"Not published: the results lack columns the template scores on: {', '.join(missing)}")
    try:
        snapshot = publish(dataset, config, _apply(dataset, config), published_by=req.published_by, note=req.note or f"From run {run_id}")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.save_dataset(dataset)
    return store.save_published(snapshot)


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
        _apply(before, config),
        _apply(after, config),
        label_before=before.as_of or before.name,
        label_after=after.as_of or after.name,
    )


# --- publishing: the handoff to stewardship coverage and index construction ---


class PublishRequest(BaseModel):
    dataset_id: str
    framework_id: str
    version: int | None = None
    published_by: str
    id_column: str | None = Field(default=None, description="Column matching rows to issuers; found automatically when omitted.")
    note: str = ""


@router.post("/publish", response_model=PublishedDecision)
def post_publish(req: PublishRequest, store: DecisionStore = Depends(get_decision_store)) -> PublishedDecision:
    """Freezes a ratified framework's result so Steward Workflow and Index
    Construction can read it. Publishing proposes: coverage tiers still need
    confirming at the checkpoint, and an index still needs its own run."""
    dataset = _load_dataset(req.dataset_id, store)
    config = _resolve_config(None, req.framework_id, req.version, store)
    try:
        snapshot = publish(
            dataset, config, _apply(dataset, config), published_by=req.published_by, id_column=req.id_column, note=req.note
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return store.save_published(snapshot)


@router.get("/published", response_model=list[PublishedDecision])
def list_published(store: DecisionStore = Depends(get_decision_store)) -> list[PublishedDecision]:
    return store.list_published()


@router.get("/published/{snapshot_id}", response_model=PublishedDecision)
def get_published(snapshot_id: str, store: DecisionStore = Depends(get_decision_store)) -> PublishedDecision:
    snapshot = store.get_published(snapshot_id)
    if snapshot is None:
        raise HTTPException(404, f"Unknown published decision: {snapshot_id}")
    return snapshot
