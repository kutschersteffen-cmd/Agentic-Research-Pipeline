"""Spec small-to-big-retrieval AC-0: with the setting off, the retrieval gold set's evidence (hybrid off) is
main's, chunk id for chunk id. Needs the gold-set PDFs (`arp golden-set retrieval --cases ...` downloads them)
and Postgres for the content store, so it skips where those are missing (the unit CI job)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

import arp.golden_set.retrieval as retrieval
from arp.config import get_settings

GOLD = Path(__file__).parent / "golden" / "retrieval"
SNAPSHOT = GOLD / "evidence_off_snapshot.json"


def _have_documents() -> bool:
    listed = json.loads((GOLD / "documents.json").read_text())
    return all((GOLD / "documents" / d["company_id"] / d["document"]).exists() for d in listed)


@pytest.mark.skipif(not (_have_documents() and os.environ.get("ARP_POSTGRES_DSN")), reason="gold-set PDFs or Postgres missing")
def test_off_evidence_is_mains(monkeypatch):
    calls: list[list] = []
    real = retrieval.field_evidence

    def recording(field, documents, settings, *a, **kw):
        evidence = real(field, documents, settings, *a, **kw)
        calls.append([field.field_id, [c.chunk_id for c in evidence]])
        return evidence

    monkeypatch.setattr(retrieval, "field_evidence", recording)
    settings = get_settings().model_copy(update={"hybrid_retrieval_enabled": False, "small_to_big_enabled": False})
    asyncio.run(retrieval.run_cases_retrieval_eval(GOLD / "cases.json", documents_dir=GOLD / "documents", settings=settings))
    assert calls == json.loads(SNAPSHOT.read_text())
