"""The optional steps before extraction, run per company inside a run."""

import asyncio
from types import SimpleNamespace

import pytest

from arp.config import Settings
from arp.discovery import crawler, downloader, identity_graph
from arp.discovery.crawler import CandidateDocumentLink
from arp.extraction.pre_steps import PreStepFailed, prepare_company
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


def _prepare(tmp_path, settings, company=ACME, docs=None):
    """(prepared company or the PreStepFailed it raised, the company's step view)."""
    store = RunStore(tmp_path / "runs")

    async def run():
        with tally_run(store, "run_1"), on_company(company.company_id):
            try:
                return await prepare_company(company, settings=settings, llm=None, registry=DocumentSourceRegistry([docs or _Docs()]))
            except PreStepFailed as exc:
                return exc

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


def test_parse_index_counts_documents_and_chunks(tmp_path):
    prepared, view = _prepare(tmp_path, _settings(tmp_path, parse_index=True))
    assert prepared == ACME
    assert view["details"]["parse_index"]["documents"] == 1 and view["details"]["parse_index"]["chunks"] > 1


def test_a_failing_step_stops_the_company_with_an_error_report(tmp_path, monkeypatch):
    async def resolve(company, **kwargs):
        return SimpleNamespace(verdict=IdentityVerdict.RESOLVED, flagged_for_review=False, resolved_website="https://acme.example", resolved_cik="1", confidence=0.9), []

    async def crawl(root, config):
        raise RuntimeError("crawler down")

    monkeypatch.setattr(identity_graph, "resolve_company_identity", resolve)
    monkeypatch.setattr(crawler, "crawl_for_documents", crawl)
    failed, view = _prepare(tmp_path, _settings(tmp_path, identity=True, content_search=True, parse_index=True))
    assert isinstance(failed, PreStepFailed)
    report = failed.report
    assert report["failed_step"] == "content_search" and "crawler down" in report["error"]
    assert report["found_before"]["identity"]["resolved"] is True  # what was known when it stopped
    assert "restart it from Content search" in report["rationale"]
    # It stopped there: parse & index never ran.
    assert view["counts"] == {"identity": 1, "content_search": 1} and view["details"]["content_search"]["failed"] is True


@pytest.mark.parametrize(
    ("on", "why"),
    [
        ({"identity": True}, "identity unclear"),
        ({"content_search": True}, "no report links"),
        ({"document_mgmt": True}, "no documents for the company"),
        ({"parse_index": True}, "no documents found in any source"),
    ],
)
def test_finding_nothing_usable_counts_as_failing(tmp_path, monkeypatch, on, why):
    async def resolve(company, **kwargs):
        return SimpleNamespace(verdict=IdentityVerdict.UNCERTAIN, flagged_for_review=True, resolved_website=None, resolved_cik=None, confidence=0.3, rationale="two candidates"), []

    async def crawl(root, config):
        return []

    class _None(DocumentSource):
        name = "none"

        async def fetch(self, company, doc_types=None):
            return []

    monkeypatch.setattr(identity_graph, "resolve_company_identity", resolve)
    monkeypatch.setattr(crawler, "crawl_for_documents", crawl)
    failed, _ = _prepare(tmp_path, _settings(tmp_path, **on), ACME.model_copy(update={"website": "https://acme.example"}), docs=_None())
    assert isinstance(failed, PreStepFailed) and why in failed.report["error"]


def test_a_stopped_company_goes_to_review_not_failed(tmp_path):
    """End to end through run_company_batch: the report reaches the review
    queue, the errors file, the manifest and the company list."""
    from arp.api.routers.extraction import get_run_companies
    from arp.extraction.pipeline import run_extraction
    from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition

    class _None(DocumentSource):
        name = "none"

        async def fetch(self, company, doc_types=None):
            return []

    settings = _settings(tmp_path, parse_index=True)
    store = RunStore(settings.runs_dir)
    schema = DataPointSchema(name="s", fields=[FieldDefinition(name="f", description="d", data_type=FieldDataType.STRING, extraction_instructions="i", seed_keywords=["x"])])
    run_id = asyncio.run(run_extraction(schema, [ACME], llm=None, registry=DocumentSourceRegistry([_None()]), settings=settings, run_store=store))

    manifest = store.load_manifest(run_id)
    assert (manifest.completed_count, manifest.failed_count, manifest.review_count) == (0, 0, 1)
    (queued,) = store.read_jsonl(store.review_queue_path(run_id))
    assert queued["item_key"] == "acme" and queued["failed_step"] == "parse_index"
    (error,) = store.read_jsonl(store.errors_path(run_id))
    assert error["review"] is True and error["report"]["failed_step"] == "parse_index"
    assert store.read_jsonl(store.results_path(run_id)) == []
    (row,) = get_run_companies(run_id, run_store=store)["companies"]
    assert row["status"] == "review"
