from arp.config import Settings
from arp.discovery import pipeline as pipeline_module
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.crawler import HomepageUnreachableError
from arp.discovery.pipeline import _discover_for_company, execute_discovery_run
from arp.discovery.site_finder import WebSearchClient
from arp.schemas.common import CompanyRef


class _NullSearchClient(WebSearchClient):
    async def search(self, query: str, max_results: int = 5) -> list:
        return []


async def test_discover_for_company_catches_homepage_unreachable(tmp_path, monkeypatch):
    async def _raise(*args, **kwargs):
        raise HomepageUnreachableError("simulated: proxy blocked this host (403)")

    monkeypatch.setattr(pipeline_module, "crawl_for_documents", _raise)

    settings = Settings(documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state")
    company = CompanyRef(company_id="ACME", name="Acme Corp", website="https://acme.example/investors")
    change_detector = ChangeDetector(
        state_dir=settings.discovery_state_dir,
        global_events_path=settings.documents_dir / "_events.jsonl",
    )

    result = await _discover_for_company(
        company,
        settings=settings,
        search_client=_NullSearchClient(),
        change_detector=change_detector,
        doc_types=None,
    )

    assert result.homepage_unreachable is True
    assert result.homepage_used == "https://acme.example/investors"
    assert "403" in (result.crawl_error or "")
    assert result.documents_found == []


async def test_discover_for_company_no_homepage_known_is_not_unreachable(tmp_path):
    settings = Settings(documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state")
    company = CompanyRef(company_id="ACME", name="Acme Corp", website=None)
    change_detector = ChangeDetector(
        state_dir=settings.discovery_state_dir,
        global_events_path=settings.documents_dir / "_events.jsonl",
    )

    result = await _discover_for_company(
        company,
        settings=settings,
        search_client=_NullSearchClient(),
        change_detector=change_detector,
        doc_types=None,
    )

    assert result.homepage_used is None
    assert result.homepage_unreachable is False


async def test_execute_discovery_run_flags_unreachable_homepage_for_review(tmp_path, monkeypatch):
    async def _raise(*args, **kwargs):
        raise HomepageUnreachableError("simulated network failure")

    monkeypatch.setattr(pipeline_module, "crawl_for_documents", _raise)

    settings = Settings(
        documents_dir=tmp_path / "documents",
        discovery_state_dir=tmp_path / "state",
        runs_dir=tmp_path / "runs",
    )
    from arp.storage.run_store import RunStore

    run_store = RunStore(settings.runs_dir)
    companies = [CompanyRef(company_id="ACME", name="Acme Corp", website="https://acme.example/")]

    from arp.discovery.pipeline import create_discovery_run

    run_id = create_discovery_run(companies, None, "manual", run_store)
    await execute_discovery_run(
        run_id, companies, settings=settings, run_store=run_store, search_client=_NullSearchClient()
    )

    manifest = run_store.load_manifest(run_id)
    assert manifest.review_count == 1
    assert manifest.failed_count == 0
    assert manifest.completed_count == 1

    rows = run_store.read_jsonl(run_store.results_path(run_id))
    assert len(rows) == 1
    assert rows[0]["homepage_unreachable"] is True
