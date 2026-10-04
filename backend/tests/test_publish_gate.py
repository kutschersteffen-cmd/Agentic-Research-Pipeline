from __future__ import annotations

import hashlib

import pytest

from arp.publish.facts import Fact
from arp.publish.gate import lineage_error, reground, sample
from arp.schemas.common import Citation
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.document_store import DocumentContentStore

ORIGINAL = b"%PDF original bytes"
KEY = hashlib.sha256(ORIGINAL).hexdigest()
TEXT = "Emissions (in thousands of tonnes)\nScope 1  1,234  1,100\nScope 2  500  400\n"
QUOTE = "Scope 1  1,234"
START = TEXT.index(QUOTE)


def _citation(**kw) -> Citation:
    return Citation(**{
        "doc_id": "d1", "doc_type": "sustainability_report", "quote": QUOTE, "grounded": True,
        "content_key": KEY, "parser_version": "p1", "span_text": QUOTE, "char_start": START,
        "char_end": START + len(QUOTE), "match_method": "exact", **kw,
    })


def _fact(fact_id: str = "fact_1", **kw) -> Fact:
    return Fact(
        fact_id=fact_id, issuer_key="ISS1", issuer_scheme="LEI", field_id="f1", period_end="2024-12-31",
        value=1234.0, state="approved", citation=_citation(**kw), source_run_id="ext1",
        observed_at="2026-01-01T00:00:00.000000+00:00", item_key="ISS1:f1:2024-12-31", version=1,
        valid_from="2026-01-01T00:00:00.000000+00:00", release_id="rel_1",
    )


@pytest.fixture
def blobs(tmp_path):
    store = LocalBlobStore(tmp_path / "blobs")
    store.put(KEY, ORIGINAL)
    return store


@pytest.fixture
def texts(tmp_path):
    store = DocumentContentStore(tmp_path / "docs")
    store.store(KEY, key_kind="file", parser_version="p1", source_suffix=".pdf", byte_size=1, text=TEXT, page_breaks=[])
    return store


def test_missing_original_blocks(tmp_path):
    assert lineage_error(_citation(), LocalBlobStore(tmp_path / "empty")) == "original_missing"


def test_hash_mismatch_blocks(tmp_path):
    store = LocalBlobStore(tmp_path / "blobs")
    store.put(KEY, b"tampered bytes")
    assert lineage_error(_citation(), store) == "hash_mismatch"


def test_ungrounded_citation_blocks(blobs):
    assert lineage_error(None, blobs) == "no_grounded_citation"
    assert lineage_error(_citation(grounded=False), blobs) == "no_grounded_citation"
    assert lineage_error(_citation(content_key=None), blobs) == "no_grounded_citation"


def test_stored_original_passes(blobs):
    assert lineage_error(_citation(), blobs) is None


def test_reground_ok(blobs, texts):
    assert reground(_fact(), blob_store=blobs, content_store=texts, fuzzy_threshold=0.92) == "ok"


def test_reground_quote_gone_not_grounded(blobs, texts):
    fact = _fact(quote="9,999 tonnes of something else")
    assert reground(fact, blob_store=blobs, content_store=texts, fuzzy_threshold=0.92) == "not_grounded"


def test_reground_offset_moved(blobs, texts):
    fact = _fact(char_start=START + 3)
    assert reground(fact, blob_store=blobs, content_store=texts, fuzzy_threshold=0.92) == "offset_moved"


def test_reground_text_unavailable(blobs, tmp_path):
    disabled = DocumentContentStore(tmp_path / "off", enabled=False)
    assert reground(_fact(), blob_store=blobs, content_store=disabled, fuzzy_threshold=0.92) == "text_unavailable"
    assert reground(_fact(), blob_store=blobs, content_store=None, fuzzy_threshold=0.92) == "text_unavailable"


def test_reground_reports_lineage_error_first(tmp_path, texts):
    empty = LocalBlobStore(tmp_path / "empty")
    assert reground(_fact(), blob_store=empty, content_store=texts, fuzzy_threshold=0.92) == "original_missing"


def test_sample_deterministic_per_seed():
    facts = [_fact(f"fact_{i:02d}") for i in range(20)]
    ids = [f.fact_id for f in sample(facts, 20, seed="a")]
    assert ids == [f.fact_id for f in sample(list(reversed(facts)), 20, seed="a")]
    assert ids != [f.fact_id for f in sample(facts, 20, seed="b")]
    assert len(sample(facts, 5, seed="a")) == 5
    assert len(sample(facts, 50, seed="a")) == 20
