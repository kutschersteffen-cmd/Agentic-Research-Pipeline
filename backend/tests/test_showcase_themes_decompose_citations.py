"""Showcase fixes, R&D Lab: a decomposed theme is saved as a draft; web documents' citations link to their source
(spec showcase-themes-fixes 5, 6)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.routers import taxonomies as taxonomies_router
from arp.config import Settings
from arp.grounding import ground_citations
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.storage.taxonomy_store import TaxonomyStore


def _activity(name: str) -> dict:
    return {"name": name, "in_scope_description": "in", "out_of_scope_description": "out"}


def test_llm_draft_with_a_theme_is_stored_without_a_model_call(pg, tmp_path, monkeypatch):  # AC-36
    settings = Settings(runs_dir=tmp_path / "runs", taxonomies_dir=tmp_path / "tax")
    store = TaxonomyStore(settings.taxonomies_dir)
    app = FastAPI()
    app.include_router(taxonomies_router.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    app.dependency_overrides[deps.get_taxonomy_store] = lambda: store

    def no_model():
        raise AssertionError("no model call expected")
    monkeypatch.setattr(taxonomies_router, "get_llm_client", no_model)
    theme = {"name": "Grid storage", "description": "d", "activities": [_activity("Batteries"), _activity("Pumped hydro")]}
    r = TestClient(app).post("/api/taxonomies", json={"name": "Grid storage", "description": "d",
                                                      "derivation_method": "llm_draft", "theme": theme})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["version"], body["status"], body["derivation_method"]) == (1, "draft", "llm_draft")
    assert [a["name"] for a in body["theme"]["activities"]] == ["Batteries", "Pumped hydro"]


def test_web_document_citation_carries_its_url():  # AC-39
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="Revenue rose 5% in 2025.",
                         page_breaks=[0], source_url="https://www.sec.gov/x.htm")
    cited = ground_citations([Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Revenue rose 5%")],
                             {doc.doc_id: doc})[0]
    assert cited.grounded is True
    assert (cited.source_url, cited.source_filename) == ("https://www.sec.gov/x.htm", None)


def test_local_document_citation_keeps_its_file():
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text="Revenue rose 5% in 2025.",
                         page_breaks=[0], source_url="https://x.org/r.pdf", local_path="/data/r.pdf")
    cited = ground_citations([Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Revenue rose 5%")],
                             {doc.doc_id: doc})[0]
    assert (cited.source_filename, cited.source_url) == ("r.pdf", None)
