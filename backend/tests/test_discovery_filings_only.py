"""`Official filings` in Argus step 2: discovery with web=False uses EDGAR/ESEF only, never search or the crawler."""

from arp.config import Settings
from arp.discovery import pipeline as pipeline_module
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.pipeline import _discover_for_company
from arp.discovery.site_finder import WebSearchClient
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import DiscoveredDocument


class _FailingSearch(WebSearchClient):
    async def search(self, query: str, max_results: int = 5) -> list:
        raise AssertionError("web search must not run")


async def test_web_off_uses_filings_only(tmp_path, monkeypatch):
    async def _no(*a, **k):
        raise AssertionError("must not run")

    async def _filings(company, edgar, doc_types):
        return [DiscoveredDocument(company_id=company.company_id, doc_type="10-K", url="https://sec.example/10k", sha256="x")]

    for name in ("crawl_for_documents", "homepage_from_ids", "resolve_company_homepage", "check_homepage"):
        monkeypatch.setattr(pipeline_module, name, _no)
    monkeypatch.setattr(pipeline_module, "_edgar_filings", _filings)
    settings = Settings(documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state")
    company = CompanyRef(company_id="aapl", name="Apple", cik="0000320193", website="https://apple.example")
    detector = ChangeDetector(state_dir=settings.discovery_state_dir, global_events_path=settings.documents_dir / "_events.jsonl")

    result = await _discover_for_company(company, settings=settings, search_client=_FailingSearch(), change_detector=detector,
                                         doc_types=None, edgar=object(), web=False)

    assert [d.url for d in result.documents_found] == ["https://sec.example/10k"]
    assert result.homepage_used is None
