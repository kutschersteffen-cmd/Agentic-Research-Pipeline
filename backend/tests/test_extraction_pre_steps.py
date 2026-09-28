"""The optional steps before extraction, run per company inside a run."""

import asyncio
from types import SimpleNamespace

from arp.config import Settings
from arp.discovery import crawler, downloader, identity_graph
from arp.discovery.crawler import CandidateDocumentLink
from arp.extraction.pre_steps import prepare_company
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.step_tally import on_company, step_counts, tally_run
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.discovery import DiscoveredDocument, IdentityVerdict
from arp.storage.run_store import RunStore

ACME = CompanyRef(company_id="acme", name="Acme Corp")


class _Docs(DocumentSource):
    name = "fixed"

    async def fetch(self, company, doc_types=None):
        return [SourceDocument(company_id=company.company_id, doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="Net zero by 2040. " * 400)]


def _settings(tmp_path, **on) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
        **{f"pre_{k}_enabled": v for k, v in on.items()},
    )


def _prepare(tmp_path, settings, company=ACME):
    store = RunStore(tmp_path / "runs")

    async def run():
        with tally_run(store, "run_1"), on_company(company.company_id):
            return await prepare_company(company, settings=settings, llm=None, registry=DocumentSourceRegistry([_Docs()]))

    prepared = asyncio.run(run())
    return prepared, step_counts(store, "run_1", company.company_id)[0]


def test_all_off_leaves_the_company_alone(tmp_path):
    prepared, view = _prepare(tmp_path, _settings(tmp_path))
    assert prepared == ACME and view["counts"] == {}


def test_identity_fills_in_a_clear_match(tmp_path, monkeypatch):
    async def resolve(company, **kwargs):
        return SimpleNamespace(verdict=IdentityVerdict.RESOLVED, flagged_for_review=False, resolved_website="https://acme.example", resolved_cik="0000123", confidence=0.95), []

    monkeypatch.setattr(identity_graph, "resolve_company_identity", resolve)
    prepared, view = _prepare(tmp_path, _settings(tmp_path, identity=True))
    assert (prepared.website, prepared.cik) == ("https://acme.example", "0000123")
    assert view["counts"] == {"identity": 1} and view["details"]["identity"]["resolved"] is True


def test_content_search_then_document_mgmt_downloads_and_takes_stock(tmp_path, monkeypatch):
    settings = _settings(tmp_path, content_search=True, document_mgmt=True)

    async def crawl(root, config):
        return [CandidateDocumentLink(url=f"https://acme.example/r{i}.pdf", doc_type=DocType.SUSTAINABILITY_REPORT, link_text=f"r{i}") for i in range(2)]

    async def download(company, candidates, documents_dir, user_agent):
        out = []
        for c in candidates:
            path = documents_dir / company.company_id / c.doc_type.value / f"{c.link_text}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 1000)
            out.append(DiscoveredDocument(company_id=company.company_id, doc_type=c.doc_type, url=c.url, local_path=str(path), sha256=c.link_text))
        return out

    monkeypatch.setattr(crawler, "crawl_for_documents", crawl)
    monkeypatch.setattr(downloader, "download_documents", download)
    prepared, view = _prepare(tmp_path, settings, ACME.model_copy(update={"website": "https://acme.example"}))
    assert view["details"]["content_search"]["links"] == 2
    assert view["details"]["document_mgmt"] == {"downloaded": 2, "new_or_changed": 2, "documents": 2, "bytes": 2000}


def test_a_failing_step_is_recorded_and_the_company_carries_on(tmp_path, monkeypatch):
    async def crawl(root, config):
        raise RuntimeError("crawler down")

    monkeypatch.setattr(crawler, "crawl_for_documents", crawl)
    prepared, view = _prepare(tmp_path, _settings(tmp_path, content_search=True, parse_index=True), ACME.model_copy(update={"website": "https://acme.example"}))
    assert view["details"]["content_search"]["failed"] is True
    assert view["details"]["parse_index"]["documents"] == 1 and view["details"]["parse_index"]["chunks"] > 1
    assert prepared.company_id == "acme"
