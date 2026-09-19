from arp.agents.calibration_agent import (
    check_company_staleness,
    create_calibration_run,
    execute_calibration_run,
    run_calibration_pass,
)
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef, DocType, JobStatus, RunManifest, SourceDocument
from arp.schemas.thematic import CompanyMatch, ExposureEstimate, MatchVerdict
from arp.storage.run_store import RunStore


def _match(company_id="c1", name="Acme Corp", activity_id="a1", generated_at="2026-01-01T00:00:00+00:00") -> CompanyMatch:
    return CompanyMatch(
        company_id=company_id, name=name, activity_id=activity_id, activity_name="EV manufacturing",
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=0.8,
        adjudicator_rationale="x", generated_at=generated_at,
    )


def _doc(company_id="c1", fetched_at="2026-01-01T00:00:00+00:00") -> SourceDocument:
    return SourceDocument(company_id=company_id, doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="x", fetched_at=fetched_at)


class _FakeSource:
    name = "fake"

    def __init__(self, docs: list[SourceDocument]) -> None:
        self.docs = docs

    async def fetch(self, company: CompanyRef, doc_types=None) -> list[SourceDocument]:
        return [d for d in self.docs if d.company_id == company.company_id]


def _registry(docs: list[SourceDocument]) -> DocumentSourceRegistry:
    return DocumentSourceRegistry([_FakeSource(docs)])


async def test_check_company_staleness_flags_when_newer_document_exists():
    company = CompanyRef(company_id="c1", name="Acme Corp")
    matches = [_match(generated_at="2026-01-01T00:00:00+00:00")]
    registry = _registry([_doc(fetched_at="2026-02-01T00:00:00+00:00")])

    flags = await check_company_staleness(company, matches, registry, "src-run-1")
    assert len(flags) == 1
    assert flags[0].company_id == "c1"
    assert flags[0].activity_id == "a1"
    assert flags[0].old_verdict == MatchVerdict.INCLUDE
    assert flags[0].newest_document_at == "2026-02-01T00:00:00+00:00"


async def test_check_company_staleness_no_flag_when_nothing_newer():
    company = CompanyRef(company_id="c1", name="Acme Corp")
    matches = [_match(generated_at="2026-02-01T00:00:00+00:00")]
    registry = _registry([_doc(fetched_at="2026-01-01T00:00:00+00:00")])

    flags = await check_company_staleness(company, matches, registry, "src-run-1")
    assert flags == []


async def test_check_company_staleness_empty_registry_returns_no_flags():
    company = CompanyRef(company_id="c1", name="Acme Corp")
    matches = [_match()]
    registry = _registry([])

    flags = await check_company_staleness(company, matches, registry, "src-run-1")
    assert flags == []


def _write_theme_run(run_store: RunStore, run_id: str, matches: list[CompanyMatch], status=JobStatus.COMPLETED) -> None:
    manifest = RunManifest(run_id=run_id, run_type="theme", status=status, params={}, company_count=len(matches))
    run_store.save_manifest(manifest)
    for m in matches:
        run_store.append_jsonl(run_store.results_path(run_id), {"company_matches": [m.model_dump(mode="json")]})


async def test_execute_calibration_run_scans_completed_theme_runs_and_groups_by_company(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    _write_theme_run(
        run_store, "theme-run-1",
        [_match(company_id="c1", activity_id="a1", generated_at="2026-01-01T00:00:00+00:00"),
         _match(company_id="c1", activity_id="a2", generated_at="2026-01-01T00:00:00+00:00")],
    )
    registry = _registry([_doc(company_id="c1", fetched_at="2026-02-01T00:00:00+00:00")])

    run_id = create_calibration_run(run_store, "manual")
    await execute_calibration_run(run_id, registry=registry, run_store=run_store)

    rows = run_store.read_jsonl(run_store.results_path(run_id))
    assert len(rows) == 2
    assert {r["activity_id"] for r in rows} == {"a1", "a2"}
    assert all(r["company_id"] == "c1" for r in rows)

    manifest = run_store.load_manifest(run_id)
    assert manifest.status == JobStatus.COMPLETED
    assert manifest.review_count == 2


async def test_execute_calibration_run_skips_non_completed_and_non_theme_runs(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    _write_theme_run(run_store, "theme-run-running", [_match()], status=JobStatus.RUNNING)
    other_manifest = RunManifest(run_id="discovery-run-1", run_type="discovery", status=JobStatus.COMPLETED, params={}, company_count=0)
    run_store.save_manifest(other_manifest)

    registry = _registry([_doc(fetched_at="2026-02-01T00:00:00+00:00")])
    run_id = await run_calibration_pass(registry=registry, run_store=run_store, triggered_by="manual")

    rows = run_store.read_jsonl(run_store.results_path(run_id))
    assert rows == []
    manifest = run_store.load_manifest(run_id)
    assert manifest.company_count == 0
