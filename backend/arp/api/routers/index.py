from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_index_store
from arp.index.fields import DataQualityBlock, available_fields
from arp.index.mock_data import demo_price_panel, demo_risk_model, demo_universe
from arp.index.calc import level_series
from arp.index.pipeline import run_review
from arp.index.presets import PRESETS, SCREEN_BUNDLES, build_preset, rule_catalogue
from arp.schemas.index import (
    ConstructionSpec,
    IndexCalibration,
    IndexCandidate,
    IndexLevelPoint,
    ReviewResult,
)
from arp.storage.index_store import IndexStore

router = APIRouter(prefix="/api/index", tags=["index"])


def _universe(candidates: list[IndexCandidate] | None) -> list[IndexCandidate]:
    """Falls back to the built-in demo universe so every endpoint is usable
    before a real data feed is connected."""
    return candidates if candidates else demo_universe()


@router.get("/catalogue")
def get_catalogue() -> dict:
    """Every rule type, its parameters and defaults, plus the presets and
    screen bundles. The UI builds its pickers from this, so adding a rule
    type on the backend surfaces it in the UI without a frontend change."""
    catalogue = rule_catalogue()
    catalogue["fields"] = available_fields(demo_universe())
    return catalogue


@router.get("/universe")
def get_universe(limit: int = 500) -> dict:
    """The demo universe, with the field inventory the rule pickers need."""
    universe = demo_universe()
    return {
        "count": len(universe),
        "fields": available_fields(universe),
        "candidates": [c.model_dump() for c in universe[:limit]],
    }


# ------------------------------------------------------------ calibrations


class CalibrationRequest(BaseModel):
    name: str
    effective_from: str = Field(description="ISO date. The first review date this version governs.")
    spec: ConstructionSpec
    notes: str = ""
    approved_by: list[str] = Field(default_factory=list)


@router.get("/calibrations", response_model=list[IndexCalibration])
def list_calibrations(store: IndexStore = Depends(get_index_store)) -> list[IndexCalibration]:
    return store.list_calibrations()


@router.post("/calibrations", response_model=IndexCalibration)
def create_calibration(req: CalibrationRequest, store: IndexStore = Depends(get_index_store)) -> IndexCalibration:
    return store.create_calibration(
        req.name, req.spec, effective_from=req.effective_from, notes=req.notes, approved_by=req.approved_by
    )


@router.get("/calibrations/{calibration_id}", response_model=IndexCalibration)
def get_calibration(
    calibration_id: str, version: int | None = None, store: IndexStore = Depends(get_index_store)
) -> IndexCalibration:
    calibration = store.get_calibration(calibration_id, version)
    if calibration is None:
        raise HTTPException(404, f"Unknown calibration: {calibration_id}")
    return calibration


@router.get("/calibrations/{calibration_id}/versions", response_model=list[IndexCalibration])
def list_calibration_versions(calibration_id: str, store: IndexStore = Depends(get_index_store)) -> list[IndexCalibration]:
    versions = store.list_calibration_versions(calibration_id)
    if not versions:
        raise HTTPException(404, f"Unknown calibration: {calibration_id}")
    return versions


@router.post("/calibrations/{calibration_id}/versions", response_model=IndexCalibration)
def new_calibration_version(
    calibration_id: str, req: CalibrationRequest, store: IndexStore = Depends(get_index_store)
) -> IndexCalibration:
    try:
        return store.new_calibration_version(
            calibration_id, req.spec, effective_from=req.effective_from, notes=req.notes, approved_by=req.approved_by
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/calibrations/{calibration_id}")
def delete_calibration(calibration_id: str, store: IndexStore = Depends(get_index_store)) -> dict:
    """Refuses to delete a calibration any review was built from: a
    published number must stay reconstructable from the methodology that
    produced it."""
    for index_id in store.list_indices():
        for review_date in store.list_review_dates(index_id):
            review = store.get_review(index_id, review_date)
            if review and review.calibration_id == calibration_id:
                raise HTTPException(
                    409,
                    f"Calibration {calibration_id} produced review {index_id}/{review_date}; "
                    "it cannot be deleted. Supersede it with a new version instead.",
                )
    if not store.delete_calibration(calibration_id):
        raise HTTPException(404, f"Unknown calibration: {calibration_id}")
    return {"deleted": calibration_id}


# ------------------------------------------------------------------ presets


@router.get("/presets")
def list_presets() -> list[dict]:
    return [{"name": name, "label": preset["label"], "description": preset["description"]} for name, preset in sorted(PRESETS.items())]


@router.get("/presets/{name}", response_model=ConstructionSpec)
def get_preset(name: str) -> ConstructionSpec:
    try:
        return build_preset(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/screen-bundles/{name}")
def get_screen_bundle(name: str) -> dict:
    """Expands a named bundle into ordinary screens the UI then shows and
    lets the user edit or delete individually -- a preset is a shortcut, not
    a black box."""
    bundle = SCREEN_BUNDLES.get(name)
    if bundle is None:
        raise HTTPException(404, f"Unknown screen bundle: {name}. Known: {', '.join(sorted(SCREEN_BUNDLES))}")
    return {"name": name, "screens": [s.model_dump() for s in bundle()]}


# ------------------------------------------------------------------ reviews


class RunRequest(BaseModel):
    index_id: str = "demo_index"
    review_date: str
    spec: ConstructionSpec | None = Field(default=None, description="Ad-hoc spec. Mutually exclusive with calibration_id.")
    calibration_id: str | None = Field(default=None, description="Run the calibration version in force on review_date.")
    candidates: list[IndexCandidate] | None = Field(default=None, description="Omit to use the built-in demo universe.")
    persist: bool = Field(default=False, description="False previews without writing anything.")
    use_prior_state: bool = Field(default=True, description="Chain from the most recent stored review before this date.")
    returns_panel: dict[str, dict[str, float]] | None = Field(
        default=None,
        description="{period: {company_id: return}} used to estimate the risk model. Omit to use the built-in demo panel.",
    )


def _resolve_spec(req: RunRequest, store: IndexStore) -> tuple[ConstructionSpec, str | None, int | None]:
    if req.calibration_id:
        calibration = store.resolve_for_date(req.calibration_id, req.review_date)
        if calibration is None:
            raise HTTPException(
                404,
                f"No version of calibration {req.calibration_id} is in force on {req.review_date} -- "
                "a review cannot run under a methodology that was not yet approved.",
            )
        return calibration.spec, calibration.calibration_id, calibration.version
    if req.spec is None:
        raise HTTPException(400, "Provide either `spec` or `calibration_id`.")
    return req.spec, None, None


@router.post("/run", response_model=ReviewResult)
def run(req: RunRequest, store: IndexStore = Depends(get_index_store)) -> ReviewResult:
    spec, calibration_id, version = _resolve_spec(req, store)
    prior_state = store.latest_state_before(req.index_id, req.review_date) if req.use_prior_state else None

    universe = _universe(req.candidates)
    settings = spec.constraints.solver
    risk_model = None
    if settings.method in ("min_tracking_error", "max_score") or settings.tracking_error_budget is not None:
        from arp.index.risk import RiskModelError, build_risk_model

        try:
            risk_model = (
                build_risk_model(settings.risk_model, universe, req.returns_panel)
                if req.returns_panel
                else demo_risk_model(universe, settings.risk_model)
            )
        except RiskModelError as exc:
            raise HTTPException(422, f"Risk model: {exc}") from exc

    try:
        result = run_review(
            spec,
            universe,
            index_id=req.index_id,
            review_date=req.review_date,
            prior_state=prior_state,
            calibration_id=calibration_id,
            calibration_version=version,
            risk_model=risk_model,
        )
    except DataQualityBlock as exc:
        # The "fail loud" path: a missing value stopped the run rather than
        # defaulting. 422 rather than 500 -- it is the request's data, not a
        # server fault.
        raise HTTPException(422, f"Data quality block: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if req.persist:
        store.save_review(result)
    return result


@router.get("/{index_id}/reviews")
def list_reviews(index_id: str, store: IndexStore = Depends(get_index_store)) -> dict:
    return {"index_id": index_id, "review_dates": store.list_review_dates(index_id)}


@router.get("/{index_id}/reviews/{review_date}", response_model=ReviewResult)
def get_review(index_id: str, review_date: str, store: IndexStore = Depends(get_index_store)) -> ReviewResult:
    review = store.get_review(index_id, review_date)
    if review is None:
        raise HTTPException(404, f"No review for {index_id} on {review_date}")
    return review


@router.get("/{index_id}/levels/{review_date}", response_model=list[IndexLevelPoint])
def get_levels(
    index_id: str, review_date: str, days: int = 8, store: IndexStore = Depends(get_index_store)
) -> list[IndexLevelPoint]:
    """Index levels from a stored review, with its index shares held fixed
    across a demo price path -- the point being that weights drift with
    price between rebalances rather than being recomputed daily."""
    review = store.get_review(index_id, review_date)
    if review is None:
        raise HTTPException(404, f"No review for {index_id} on {review_date}")
    if review.state.divisor is None:
        raise HTTPException(409, "That review carries no divisor")
    members = {c.company_id for c in review.constituents}
    universe = [c for c in demo_universe() if c.company_id in members]
    if len(universe) != len(members):
        raise HTTPException(409, "Level series is only available for reviews run on the built-in demo universe")
    dates = [f"{review_date[:8]}{d:02d}" for d in range(1, min(days, 28) + 1)]
    panel = demo_price_panel(universe, dates)
    shares = {c.company_id: c.index_shares for c in review.constituents}
    return level_series(shares, panel, divisor=review.state.divisor, rounding=None)

