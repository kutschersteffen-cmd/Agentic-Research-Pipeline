from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user
from arp.api.deps import get_llm_client, get_run_store, get_verifier_llm_client, settings_dep
from arp.config import Settings
from arp.discovery.academic_search import ArxivSearchClient, CompositeSearchClient, SemanticScholarSearchClient
from arp.discovery.site_finder import build_web_search_client
from arp.llm.base import LLMClient
from arp.orchestration.review_queue import decision_history, latest_decisions, record_review_decision
from arp.replication._wide_csv import check_wide_csv
from arp.replication.characteristics_data import CsvCharacteristicSource
from arp.replication.paper_discovery import discover_candidate_papers, rank_candidate_papers
from arp.replication.pipeline import run_replication
from arp.replication.price_data import CsvPriceSource
from arp.replication.regime_analysis import regime_stratified_report
from arp.replication.run_detail import ReplicationRunDetail, load_run_detail
from arp.replication.sanity_check import sanity_check_report
from arp.replication.spec_graph import extract_strategy_spec
from arp.replication.spec_revision import revise_spec_via_instruction
from arp.schemas.common import JobStatus, RunManifest, new_id
from arp.schemas.strategy_replication import StrategySpec
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/replication", tags=["replication"])

# A spec draft is reviewed as a single item under this fixed key -- the
# whole StrategySpec is one reviewable unit, unlike the Extraction Engine's
# per-field review keys. Reuses arp/orchestration/review_queue.py (already
# shared by 5 other routers) rather than a new approval mechanism:
# "approved" = the LATEST decision recorded for this key is "approve" (any
# edit afterwards becomes the new latest decision and un-approves it, with
# no separate bookkeeping needed).
_SPEC_ITEM_KEY = "spec"
_SPEC_RUN_TYPE = "strategy_replication_spec"


class DiscoverRequest(BaseModel):
    topic: str
    max_candidates: int = 10


class CreateSpecRequest(BaseModel):
    paper_citation: str
    paper_text: str = Field(..., description="A pasted paper excerpt, or the user's own free-form methodology description -- mechanically identical to the extractor.")


class ReviseSpecRequest(BaseModel):
    instruction: str


class ApproveSpecRequest(BaseModel):
    pass  # reviewer comes from the signed-in principal; a legacy `reviewer` body field is ignored


class BacktestRequest(BaseModel):
    tickers: list[str]
    prices_ref: str = Field(description="File name returned by POST .../datasets/prices.")
    characteristics_refs: dict[str, str] = Field(default_factory=dict, description="characteristic_name -> file name returned by POST .../datasets/characteristics/{name}.")
    price_kind: str = "price"
    benchmark: str | None = None
    out_of_sample_start: str | None = None
    out_of_sample_end: str | None = None


class DatasetUploadResponse(BaseModel):
    ref: str = Field(description="Stored file name; pass it back as prices_ref or a characteristics_refs value.")
    tickers: list[str] = Field(description="The header's ticker names, in file order.")
    rows: int
    first_date: str
    last_date: str


_MAX_CHARACTERISTIC_NAME = 100
_PRICES_FILE = "prices.csv"
_CHARACTERISTICS_FILE = re.compile(rf"characteristics_[A-Za-z0-9_-]{{1,{_MAX_CHARACTERISTIC_NAME}}}\.csv")


def _spec_run_or_404(run_store: RunStore, spec_run_id: str) -> RunManifest:
    manifest = run_store.load_manifest(spec_run_id)
    if manifest is None or manifest.run_type != _SPEC_RUN_TYPE:
        raise HTTPException(404, "Spec draft not found")
    return manifest


def _draft_row(run_store: RunStore, spec_run_id: str) -> dict:
    rows = run_store.read_results(spec_run_id)
    draft_row = next((r for r in rows if r.get("type") == "draft"), None)
    if draft_row is None:
        raise HTTPException(404, "Spec draft not found")
    return draft_row


def _current_spec(run_store: RunStore, spec_run_id: str) -> StrategySpec:
    draft_row = _draft_row(run_store, spec_run_id)
    # The newest decision that carries a spec wins; an approval carries none, so it must not hide an edit.
    for decision in reversed(decision_history(run_store, spec_run_id, _SPEC_ITEM_KEY)):
        if decision.get("edited_value") is not None:
            return StrategySpec.model_validate(decision["edited_value"])
    return StrategySpec.model_validate({k: v for k, v in draft_row.items() if k != "type"})


def _is_approved(run_store: RunStore, spec_run_id: str) -> bool:
    decision = latest_decisions(run_store, spec_run_id).get(_SPEC_ITEM_KEY)
    return decision is not None and decision["decision"] == "approve"


def _spec_state(run_store: RunStore, spec_run_id: str) -> dict:
    spec = _current_spec(run_store, spec_run_id)
    return {
        "spec_run_id": spec_run_id,
        "spec": spec.model_dump(mode="json"),
        "approved": _is_approved(run_store, spec_run_id),
    }


# ---- Stage A: Propose --------------------------------------------------------


@router.post("/discover")
async def discover_papers(
    req: DiscoverRequest, settings: Settings = Depends(settings_dep), llm: LLMClient = Depends(get_llm_client)
) -> dict:
    """Searches for candidate 'outperformance' papers on `req.topic` and
    ranks them by replication-worthiness -- the API equivalent of
    `arp replicate discover-papers`, using every search source
    (arXiv + Semantic Scholar + generic web) merged/deduped, same as that
    CLI command's default. Proposes candidates; nothing is fetched or
    turned into a spec automatically -- picking one is a separate
    POST /specs call."""
    search_client = CompositeSearchClient(
        [ArxivSearchClient(), SemanticScholarSearchClient(), build_web_search_client(settings.discovery_user_agent)]
    )
    candidates = await discover_candidate_papers(req.topic, search_client, max_candidates=req.max_candidates)
    if not candidates:
        return {"candidates": []}
    ranked, _usage = await rank_candidate_papers(req.topic, candidates, llm)
    return {"candidates": [c.model_dump(mode="json") for c in ranked]}


# ---- Stage B: Spec draft & review --------------------------------------------


@router.post("/specs")
async def create_spec_draft(
    req: CreateSpecRequest,
    run_store: RunStore = Depends(get_run_store),
    llm: LLMClient = Depends(get_llm_client),
    verifier_llm: LLMClient = Depends(get_verifier_llm_client),
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Drafts a StrategySpec from `req.paper_text` via the same extractor/
    independent-verifier/grounding pipeline as `arp replicate extract-spec`
    -- `paper_text` may be a real paper excerpt or the user's own free-form
    methodology description, handled identically. The draft is NOT approved
    yet; review/edit/approve it via the endpoints below before backtesting."""
    spec, _needs_review, _usages = await extract_strategy_spec(
        req.paper_citation,
        req.paper_text,
        llm=llm,
        verifier_llm=verifier_llm,
        settings=settings,
        fuzzy_threshold=settings.grounding_fuzzy_threshold,
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    run_id = new_id("run")
    manifest = RunManifest(
        run_id=run_id, run_type=_SPEC_RUN_TYPE, status=JobStatus.COMPLETED, params={"paper_citation": req.paper_citation}
    )
    run_store.save_manifest(manifest)
    run_store.append_result(run_id, {"type": "draft", **spec.model_dump(mode="json")})
    return {"spec_run_id": run_id, "spec": spec.model_dump(mode="json"), "approved": False}


@router.get("/specs/{spec_run_id}")
def get_spec_draft(spec_run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    _spec_run_or_404(run_store, spec_run_id)
    state = _spec_state(run_store, spec_run_id)
    state["history"] = decision_history(run_store, spec_run_id, _SPEC_ITEM_KEY)
    return state


@router.put("/specs/{spec_run_id}")
def update_spec_draft(
    spec_run_id: str,
    spec: StrategySpec,
    run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Direct full-object edit -- the user's own corrected StrategySpec,
    validated by the schema itself. Recorded as an 'edit' decision (never
    overwrites the draft row in place), which un-approves the spec."""
    _spec_run_or_404(run_store, spec_run_id)
    record_review_decision(
        run_store, spec_run_id, _SPEC_ITEM_KEY, "edit", None, spec.model_dump(mode="json"),
        comment="direct edit", principal=principal,
    )
    return _spec_state(run_store, spec_run_id)


@router.post("/specs/{spec_run_id}/revise")
async def revise_spec_draft(
    spec_run_id: str,
    req: ReviseSpecRequest,
    run_store: RunStore = Depends(get_run_store),
    llm: LLMClient = Depends(get_llm_client),
    principal: Principal = Depends(current_user),
) -> dict:
    """Applies a natural-language instruction to the current spec (see
    arp/replication/spec_revision.py) -- any field it actually changes has
    its grounding/confidence cleared and a note appended, enforced in code."""
    _spec_run_or_404(run_store, spec_run_id)
    current = _current_spec(run_store, spec_run_id)
    revised, _usage = await revise_spec_via_instruction(current, req.instruction, llm)
    record_review_decision(
        run_store, spec_run_id, _SPEC_ITEM_KEY, "edit", None, revised.model_dump(mode="json"),
        comment=req.instruction, principal=principal,
    )
    return _spec_state(run_store, spec_run_id)


@router.post("/specs/{spec_run_id}/approve")
def approve_spec_draft(
    spec_run_id: str,
    req: ApproveSpecRequest | None = None,
    run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
) -> dict:
    _spec_run_or_404(run_store, spec_run_id)
    record_review_decision(run_store, spec_run_id, _SPEC_ITEM_KEY, "approve", None, None, comment=None, principal=principal)
    return _spec_state(run_store, spec_run_id)


# ---- Stage C: datasets, backtest, results ------------------------------------


async def _store_dataset(run_store: RunStore, spec_run_id: str, file_name: str, file: UploadFile, max_bytes: int) -> DatasetUploadResponse:
    """Size cap, then content check, then write: a refused upload leaves an earlier file as it was."""
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File is larger than the {max_bytes // 1_000_000} MB upload limit.")
    try:
        summary = check_wide_csv(data)
    except ValueError as exc:
        raise HTTPException(400, f"Not a usable CSV: {exc}") from exc
    (run_store.run_dir(spec_run_id) / file_name).write_bytes(data)
    return DatasetUploadResponse(ref=file_name, **vars(summary))


@router.post("/specs/{spec_run_id}/datasets/prices", response_model=DatasetUploadResponse)
async def upload_price_dataset(
    spec_run_id: str, file: UploadFile, run_store: RunStore = Depends(get_run_store), settings: Settings = Depends(settings_dep)
) -> DatasetUploadResponse:
    _spec_run_or_404(run_store, spec_run_id)
    return await _store_dataset(run_store, spec_run_id, _PRICES_FILE, file, settings.max_upload_bytes)


@router.post("/specs/{spec_run_id}/datasets/characteristics/{name:path}", response_model=DatasetUploadResponse)
async def upload_characteristics_dataset(
    spec_run_id: str, name: str, file: UploadFile, run_store: RunStore = Depends(get_run_store), settings: Settings = Depends(settings_dep)
) -> DatasetUploadResponse:
    """`name` may hold `/` ("B/M"); only the stored file name is slugged, the name itself is not changed."""
    _spec_run_or_404(run_store, spec_run_id)
    if not name:
        raise HTTPException(400, "Characteristic name is empty.")
    if len(name) > _MAX_CHARACTERISTIC_NAME:
        raise HTTPException(400, f"Characteristic name is longer than {_MAX_CHARACTERISTIC_NAME} characters.")
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    return await _store_dataset(run_store, spec_run_id, f"characteristics_{slug}.csv", file, settings.max_upload_bytes)


def _data_file(run_dir: Path, ref: str) -> Path:
    """The spec's own uploaded file named by `ref`; anything else is the same 400, so a caller learns nothing about the server's files."""
    if ref == _PRICES_FILE or _CHARACTERISTICS_FILE.fullmatch(ref):
        path = run_dir / ref
        if path.is_file():
            return path
    raise HTTPException(400, f"Data file not found: {ref.rsplit('/', 1)[-1]}")


@router.post("/specs/{spec_run_id}/backtest")
def run_backtest_from_spec(spec_run_id: str, req: BacktestRequest, run_store: RunStore = Depends(get_run_store)) -> dict:
    """Runs the deterministic backtest engine against the spec's CURRENT
    (approved) state -- 403s if the latest review decision for this spec
    isn't 'approve', re-checked here server-side rather than trusted from
    the caller/UI."""
    _spec_run_or_404(run_store, spec_run_id)
    if not _is_approved(run_store, spec_run_id):
        raise HTTPException(403, "Spec is not approved -- approve it before running a backtest.")
    spec = _current_spec(run_store, spec_run_id)
    run_dir = run_store.run_dir(spec_run_id)
    price_source = CsvPriceSource(_data_file(run_dir, req.prices_ref), kind=req.price_kind)
    characteristics_sources = {name: CsvCharacteristicSource(_data_file(run_dir, ref)) for name, ref in req.characteristics_refs.items()}
    try:
        run_id, report = run_replication(
            spec,
            req.tickers,
            price_source,
            run_store=run_store,
            characteristics_sources=characteristics_sources or None,
            benchmark_ticker=req.benchmark,
            out_of_sample_start=req.out_of_sample_start,
            out_of_sample_end=req.out_of_sample_end,
        )
    except ValueError as exc:
        # The sources name a file by its full path; the screen only ever sees the file name.
        raise HTTPException(400, str(exc).replace(f"{run_dir}/", "")) from exc
    return {"run_id": run_id, "verdict": report.verdict.value}


@router.get("/runs/{run_id}", response_model=ReplicationRunDetail)
def get_replication_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> ReplicationRunDetail:
    detail = load_run_detail(run_store, run_id)
    if detail is None:
        raise HTTPException(404, "Run not found or backtest not completed")
    return detail


@router.post("/runs/{run_id}/sanity-check")
async def trigger_sanity_check(run_id: str, run_store: RunStore = Depends(get_run_store), llm: LLMClient = Depends(get_llm_client)) -> dict:
    """Runs the qualitative LLM sanity-check pass on demand (see
    arp/replication/sanity_check.py) and appends the result -- the one
    deliberate on-demand-from-the-UI action in this router, since a
    real interactive review tool should let the user ask for this without
    a separate CLI step."""
    detail = load_run_detail(run_store, run_id)
    if detail is None:
        raise HTTPException(404, "Run not found or backtest not completed")
    assessment, _usage = await sanity_check_report(detail.spec, detail.comparison, llm)
    run_store.append_result(run_id, {"type": "sanity_check", **assessment.model_dump(mode="json")})
    return assessment.model_dump(mode="json")


@router.post("/runs/{run_id}/regime-report")
def trigger_regime_report(run_id: str, trailing_window_months: int = 12, run_store: RunStore = Depends(get_run_store)) -> dict:
    detail = load_run_detail(run_store, run_id)
    if detail is None:
        raise HTTPException(404, "Run not found or backtest not completed")
    report = regime_stratified_report(detail.in_sample, trailing_window_months=trailing_window_months)
    run_store.append_result(run_id, {"type": "regime_report", **report.model_dump(mode="json")})
    return report.model_dump(mode="json")
