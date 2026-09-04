from arp.orchestration.job_manager import JobManager
from arp.research.pipeline import load_theme_run_matches, rank_theme_matches
from arp.schemas.arbitration import ArbitrationResult
from arp.schemas.thematic import CompanyMatch, ExposureEstimate, MatchVerdict
from arp.storage.run_store import RunStore


def _match(company_id, activity_id, composite_score) -> CompanyMatch:
    arbitration = ArbitrationResult(
        composite_score=composite_score, methods_disagree=False, disagreement_spread=0.0, mid_band=False, contributions=[],
    )
    return CompanyMatch(
        company_id=company_id, name="Acme", activity_id=activity_id, activity_name="EV manufacturing",
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=0.8,
        adjudicator_rationale="x", arbitration=arbitration,
    )


def test_load_theme_run_matches_flattens_company_matches_rows(tmp_path):
    store = RunStore(tmp_path)
    manifest = JobManager(store).create_run("theme", {}, company_count=2)
    store.append_jsonl(store.results_path(manifest.run_id), {"company_matches": [_match("c1", "act1", 0.5).model_dump(mode="json")]})
    store.append_jsonl(store.results_path(manifest.run_id), {"company_matches": [_match("c2", "act1", 0.9).model_dump(mode="json")]})

    matches = load_theme_run_matches(store, manifest.run_id)
    assert matches is not None
    assert {m.company_id for m in matches} == {"c1", "c2"}


def test_load_theme_run_matches_returns_none_for_missing_run(tmp_path):
    store = RunStore(tmp_path)
    assert load_theme_run_matches(store, "run_nope") is None


def test_load_theme_run_matches_returns_none_for_non_theme_run(tmp_path):
    store = RunStore(tmp_path)
    manifest = JobManager(store).create_run("extraction", {}, company_count=1)
    assert load_theme_run_matches(store, manifest.run_id) is None


def test_rank_theme_matches_sorts_by_composite_score_descending():
    matches = [_match("c1", "act1", 0.2), _match("c2", "act1", 0.9), _match("c3", "act1", 0.5)]
    ranked = rank_theme_matches(matches)
    assert [m.company_id for m in ranked] == ["c2", "c3", "c1"]


def test_rank_theme_matches_sorts_missing_arbitration_last():
    with_score = _match("c1", "act1", 0.5)
    no_arbitration = CompanyMatch(
        company_id="c2", name="Beta", activity_id="act1", activity_name="EV manufacturing",
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=0.8,
        adjudicator_rationale="x", arbitration=None,
    )
    ranked = rank_theme_matches([no_arbitration, with_score])
    assert [m.company_id for m in ranked] == ["c1", "c2"]
