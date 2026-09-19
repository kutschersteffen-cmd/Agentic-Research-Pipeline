from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from arp.api.routers.transition_barrier import (
    get_criterion,
    get_matrix,
    get_refresh_coverage,
    get_staleness,
    list_criteria,
    list_scores,
    list_sources,
    start_refresh_run,
)
from arp.config import Settings
from arp.schemas.transition_barrier import Pillar, Region
from arp.storage.run_store import RunStore
from arp.transition_barrier.refresh.pipeline import (
    RefreshDisabledError,
    create_refresh_run,
)


def _settings(**overrides) -> Settings:
    return Settings(anthropic_api_key="unused", **overrides)


@pytest.fixture
def run_store(tmp_path) -> RunStore:
    return RunStore(tmp_path / "runs")


def test_criteria_endpoint_returns_all_35():
    assert len(list_criteria()) == 35


def test_scores_endpoint_filters():
    assert len(list_scores()) == 105
    china_regulation = list_scores(region=Region.CHINA, pillar=Pillar.REGULATION)
    assert len(china_regulation) == 13
    assert {s.region for s in china_regulation} == {Region.CHINA}

    steel = list_scores(sector="Steel")
    assert len(steel) == 15  # 5 criteria x 3 regions

    highs = list_scores(rating="H")
    assert len(highs) == 24


def test_criterion_detail_joins_scores_and_sources():
    detail = get_criterion("OGU-R1")
    assert detail["criterion"]["code"] == "OGU-R1"
    assert len(detail["scores"]) == 3
    assert detail["sources"], "detail view must resolve the criterion -> source join"
    assert {s["region"] for s in detail["scores"]} == {r.value for r in Region}


def test_unknown_criterion_is_404():
    with pytest.raises(HTTPException) as exc:
        get_criterion("NOPE-T1")
    assert exc.value.status_code == 404


def test_matrix_endpoint_returns_105_cells_with_staleness():
    matrix = get_matrix(settings=_settings())
    assert len(matrix["criteria"]) == 35
    assert len(matrix["sectors"]) == 9
    assert sum(len(v) for v in matrix["cells"].values()) == 105
    assert matrix["distribution"]["overall"] == {"H": 24, "M": 49, "L": 32}

    cell = matrix["cells"]["PWR-T1"]["European Union"]
    assert cell["rating"] == "H"
    assert "stale" in cell and "staleness_days" in cell
    # The whole payload must survive a JSON round-trip for the frontend.
    assert json.loads(json.dumps(matrix))["cells"]["PWR-T1"]["European Union"]["rating"] == "H"


def test_sources_endpoint_returns_all_86():
    assert len(list_sources()) == 86


def test_staleness_endpoint_honours_the_configured_threshold():
    generous = get_staleness(settings=_settings(transition_barrier_staleness_days=100_000))
    assert generous.stale == 0
    assert generous.fresh == 105

    strict = get_staleness(settings=_settings(transition_barrier_staleness_days=1))
    assert strict.stale == 105
    assert strict.fresh == 0


def test_refresh_coverage_is_honest_about_what_is_not_automated():
    coverage = get_refresh_coverage()
    assert coverage["total_sources"] == 86
    assert coverage["automatable"] == 15
    assert coverage["manual"] == 71
    assert coverage["enabled_patterns"] == ["legal_regulatory_text"]


async def test_refresh_run_is_refused_while_the_feature_is_disabled(run_store):
    settings = _settings(transition_barrier_refresh_enabled=False)
    assert settings.transition_barrier_refresh_enabled is False

    with pytest.raises(HTTPException) as exc:
        await start_refresh_run(settings=settings, run_store=run_store)
    assert exc.value.status_code == 409
    assert "disabled" in str(exc.value.detail).lower()


def test_create_refresh_run_raises_when_disabled(run_store):
    with pytest.raises(RefreshDisabledError):
        create_refresh_run(_settings(transition_barrier_refresh_enabled=False), run_store)


def test_create_refresh_run_counts_sources_when_enabled(run_store):
    run_id = create_refresh_run(_settings(transition_barrier_refresh_enabled=True), run_store)
    manifest = run_store.load_manifest(run_id)
    assert manifest is not None
    assert manifest.run_type == "transition_barrier_refresh"
    assert manifest.company_count == 15, "the unit of work is one legal act, not one issuer"
