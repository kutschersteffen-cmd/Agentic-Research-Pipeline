from arp.api.routers.runs import _THEME_CSV_HEADER, _theme_csv_row
from arp.schemas.arbitration import ArbitrationContribution, ArbitrationResult
from arp.schemas.common import Citation, DocType
from arp.schemas.exposure import IndirectExposureResult
from arp.schemas.rd_exposure import RDExposureResult
from arp.schemas.revenue_exposure import MetricExposure, RevenueExposureResult
from arp.schemas.thematic import CompanyMatch, CompanyRole, ExposureEstimate, MatchVerdict
from tests.postgres_helpers import replace_results


def _full_match() -> CompanyMatch:
    citation = Citation(doc_id="d1", doc_type=DocType.ANNUAL_REPORT_10K, quote="We make EVs.", grounded=True)
    return CompanyMatch(
        company_id="c1", ticker="ACME", name="Acme Motors", activity_id="act1", activity_name="EV manufacturing",
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=0.8,
        adjudicator_rationale="Clear evidence.", citations=[citation],
        indirect_exposure=IndirectExposureResult(
            company_id="c1", isic_code="27", upstream_exposure=0.4, downstream_exposure=0.6, core_sector=True, icio_edition="test",
        ),
        revenue_exposure=RevenueExposureResult(
            activity_id="act1", revenue=MetricExposure(value_pct=0.3, source="extracted"),
            capex=MetricExposure(source="unresolved"), sector_relevant=True,
        ),
        rd_exposure=RDExposureResult(
            activity_id="act1", rd_intensity=MetricExposure(value_pct=0.2, source="extracted"),
            news_mentions=MetricExposure(value_pct=0.7, source="news"), sector_relevant=True,
        ),
        arbitration=ArbitrationResult(
            composite_score=0.55, methods_disagree=True, disagreement_spread=0.5, mid_band=True,
            contributions=[ArbitrationContribution(method="revenue_extracted", signal=0.3, weight=0.8)],
        ),
        company_role=CompanyRole.DIVERSIFIED,
        flagged_for_review=True,
    )


def test_theme_csv_row_length_matches_header():
    row = _theme_csv_row(_full_match())
    assert len(row) == len(_THEME_CSV_HEADER)


def test_theme_csv_row_field_values():
    row = _theme_csv_row(_full_match())
    as_dict = dict(zip(_THEME_CSV_HEADER, row, strict=True))
    assert as_dict["company_id"] == "c1"
    assert as_dict["company_role"] == "diversified"
    assert as_dict["revenue_pct"] == 0.3
    assert as_dict["revenue_source"] == "extracted"
    assert as_dict["indirect_upstream"] == 0.4
    assert as_dict["indirect_downstream"] == 0.6
    assert as_dict["rd_intensity_pct"] == 0.2
    assert as_dict["news_mentions_score"] == 0.7
    assert as_dict["arbitration_composite_score"] == 0.55
    assert as_dict["arbitration_disagree"] is True
    assert as_dict["citation_count"] == 1
    assert "We make EVs." in as_dict["citations_json"]


def test_theme_csv_row_handles_missing_optional_fields():
    match = CompanyMatch(
        company_id="c1", name="Acme", activity_id="act1", activity_name="EV manufacturing",
        verdict=MatchVerdict.EXCLUDE, exposure_estimate=ExposureEstimate.NONE, confidence=1.0,
        adjudicator_rationale="No evidence.",
    )
    row = _theme_csv_row(match)
    as_dict = dict(zip(_THEME_CSV_HEADER, row, strict=True))
    assert as_dict["company_role"] is None
    assert as_dict["revenue_pct"] is None
    assert as_dict["arbitration_composite_score"] is None
    assert as_dict["citation_count"] == 0
    assert as_dict["citations_json"] == ""


def test_csv_export_has_value_state_columns(tmp_path, pg):
    import csv
    import io

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from arp.api.deps import get_run_store
    from arp.api.routers import runs
    from arp.schemas.common import RunManifest
    from arp.storage.run_store import RunStore

    store = RunStore(pg, tmp_path)
    store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    f = {"field_name": "x", "confidence": 0.9, "grounded": True, "unit": "USD", "basis": "reported",
         "period_end": "2024-12-31", "canonical_unit": "USD"}
    rec = {"company_id": "c", "ticker": "T", "name": "N", "needs_review": False, "fields": [
        {**f, "value": 0.0, "value_state": "zero", "canonical_value": 0.0},
        {**f, "value": None, "value_state": "not_found", "canonical_value": None},
    ]}
    replace_results(store, "r1", [rec])
    app = FastAPI()
    app.include_router(runs.router)
    app.dependency_overrides[get_run_store] = lambda: store
    prefix = next(r.path for r in runs.router.routes if r.path.endswith("/export.csv")).removesuffix("/{run_id}/export.csv")
    rows = list(csv.DictReader(io.StringIO(TestClient(app).get(f"{prefix}/r1/export.csv").text)))
    assert [(r["value_state"], r["value"]) for r in rows] == [("zero", "0.0"), ("not_found", "")]
    assert rows[0]["period_end"] == "2024-12-31" and rows[0]["unit"] == "USD" and rows[0]["basis"] == "reported"


def test_barrier_refresh_csv_needs_review_follows_the_finding_rule(tmp_path, pg):
    import csv
    import io

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from arp.api.deps import get_run_store
    from arp.api.routers import runs
    from arp.schemas.common import RunManifest
    from arp.schemas.transition_barrier import BarrierRefreshFinding, Rating, RefreshOutcome, Region
    from arp.storage.run_store import RunStore

    store = RunStore(pg, tmp_path)
    store.save_manifest(RunManifest(run_id="r1", run_type="transition_barrier_refresh"))
    replace_results(store, "r1", [
        BarrierRefreshFinding(
            code="POL-T1", region=Region.EUROPEAN_UNION, source_key="s1", outcome=outcome, current_rating=Rating.HIGH,
        ).model_dump(mode="json")
        for outcome in (RefreshOutcome.FETCH_FAILED, RefreshOutcome.UNCHANGED)
    ])
    app = FastAPI()
    app.include_router(runs.router)
    app.dependency_overrides[get_run_store] = lambda: store
    prefix = next(r.path for r in runs.router.routes if r.path.endswith("/export.csv")).removesuffix("/{run_id}/export.csv")
    rows = list(csv.DictReader(io.StringIO(TestClient(app).get(f"{prefix}/r1/export.csv").text)))
    assert [(r["outcome"], r["needs_review"]) for r in rows] == [("fetch_failed", "True"), ("unchanged", "False")]


def test_csv_export_leaves_out_values_that_still_wait_for_review(tmp_path, pg, monkeypatch):
    """The app promises "No flagged item reaches an export until a named person approves it"; the CSV wrote every
    value. A value routed to review is exported only once it is approved (as corrected, when it was corrected)."""
    import csv
    import io

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from arp.api.deps import get_run_store
    from arp.api.routers import runs
    from arp.schemas.common import RunManifest
    from arp.storage.run_store import RunStore

    store = RunStore(pg, tmp_path)
    store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    f = {"confidence": 0.9, "grounded": True, "unit": "USD", "value_state": "reported", "canonical_unit": "USD", "period_end": "2024-12-31"}
    fields = [
        {**f, "field_id": "auto", "field_name": "auto", "value": 1.0, "canonical_value": 1.0, "route": "auto_accept"},
        {**f, "field_id": "open", "field_name": "open", "value": 2.0, "canonical_value": 2.0, "route": "review"},
        {**f, "field_id": "ok", "field_name": "ok", "value": 3.0, "canonical_value": 3.0, "route": "review"},
        {**f, "field_id": "fixed", "field_name": "fixed", "value": 4.0, "canonical_value": 4.0, "route": "review"},
        {**f, "field_id": "no", "field_name": "no", "value": 5.0, "canonical_value": 5.0, "route": "hold"},
        {**f, "field_id": "old", "field_name": "old", "value": 6.0, "canonical_value": 6.0},  # written before routing
    ]
    replace_results(store, "r1", [{"company_id": "c", "issuer_key": "ISS", "ticker": "T", "name": "N", "needs_review": True, "fields": fields}])
    monkeypatch.setattr(runs, "effective_decisions", lambda run_store, run_id: {
        "ISS:ok:2024-12-31": {"decision": "approve"},
        "ISS:fixed:2024-12-31": {"decision": "correct", "corrected_value": {"value": 44.0}},
        "ISS:no:2024-12-31": {"decision": "reject"},
    })
    app = FastAPI()
    app.include_router(runs.router)
    app.dependency_overrides[get_run_store] = lambda: store
    prefix = next(r.path for r in runs.router.routes if r.path.endswith("/export.csv")).removesuffix("/{run_id}/export.csv")
    rows = list(csv.DictReader(io.StringIO(TestClient(app).get(f"{prefix}/r1/export.csv").text)))
    assert [(r["field_name"], r["value"], r["canonical_value"], r["review_status"]) for r in rows] == [
        ("auto", "1.0", "1.0", ""),
        ("open", "", "", "awaiting review"),
        ("ok", "3.0", "3.0", "approve"),
        ("fixed", "44.0", "", "correct"),
        ("no", "", "", "reject"),
        ("old", "6.0", "6.0", ""),
    ]
