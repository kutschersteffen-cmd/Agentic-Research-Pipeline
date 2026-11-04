from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from arp.config import Settings
from arp.db.session import transaction
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.stock_inference import profile as profile_mod
from arp.research.stock_inference.profile import DESCRIPTION_SCHEMA, profile_all
from arp.research.stock_inference.schemas import InferStock
from arp.schemas.common import Citation, DocType, DocumentChunk, SourceDocument
from arp.schemas.datapoints import ExtractedField

TEXT = "Annual report. We make PEM stacks. They power hydrogen electrolysers for industry."


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs_by_company):
        self.docs = docs_by_company

    async def fetch(self, company, doc_types=None):
        return self.docs.get(company.company_id, [])


def _doc(doc_id, company_id, text=TEXT):
    return SourceDocument(doc_id=doc_id, company_id=company_id, doc_type=DocType.ANNUAL_REPORT_10K, title="AR",
                          full_text=text)


def _result(value, quote, doc_id):
    cites = [Citation(doc_id=doc_id, doc_type=DocType.ANNUAL_REPORT_10K, quote=quote)] if quote else []
    field = ExtractedField(field_id="f", field_name="description", value=value, citations=cites, confidence=0.9)
    return SimpleNamespace(record=SimpleNamespace(fields=[field]))


def _validation_error():
    try:
        InferStock.model_validate({})
    except ValidationError as e:
        return e


def _extract(behaviour):
    """behaviour[company_id] is an exception to raise or a (value, quote) pair; default grounds in the company's doc."""
    async def extract(company, schema, *, documents, **_):
        assert schema is DESCRIPTION_SCHEMA
        b = behaviour.get(company.company_id, ("Makes PEM stacks.", "We make PEM stacks."))
        if isinstance(b, Exception):
            raise b
        return _result(*b, documents[0].doc_id)
    return extract


class _Discover:
    def __init__(self, source=None, found=None):
        self.calls, self.source, self.found = [], source, found or {}

    async def __call__(self, stocks, settings):
        self.calls.append([s.company_id for s in stocks])
        self.source.docs.update(self.found)


STOCKS = [InferStock(company_id=f"s{i}", name=f"Stock {i}") for i in range(1, 6)]


async def _run(pg, tmp_path, docs, behaviour=None, found=None):
    source = _FixedDocSource(docs)
    discover = _Discover(source, found)
    profiles, chunks = await profile_all(
        STOCKS, registry=DocumentSourceRegistry([source]), llm=None, verifier_llm=None,
        settings=Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs"), discover=discover,
        extract=_extract(behaviour or {}), session_factory=lambda: transaction(pg), segments={},
    )
    return {p.company_id: p for p in profiles}, chunks, discover


def _all_docs():
    return {f"s{i}": [_doc(f"D{i}", f"s{i}")] for i in range(1, 6)}


@pytest.mark.asyncio
async def test_extract_raise_is_isolated_to_its_stock(pg, tmp_path):  # AC-10/11
    by_id, _, _ = await _run(pg, tmp_path, _all_docs(), {"s3": _validation_error()})
    assert by_id["s3"].error.startswith("ValidationError: ")
    assert by_id["s3"].description is None
    for cid in ("s1", "s2", "s4", "s5"):
        assert by_id[cid].description == "Makes PEM stacks." and by_id[cid].error is None
        assert by_id[cid].db_match == "none"


@pytest.mark.asyncio
async def test_no_document_after_discovery(pg, tmp_path):  # AC-12
    docs = _all_docs()
    del docs["s3"]
    by_id, chunks, discover = await _run(pg, tmp_path, docs)
    assert by_id["s3"].error == "no_document"
    assert discover.calls == [["s3"]]
    assert chunks["s3"] == []


@pytest.mark.asyncio
async def test_discovery_supplies_a_document(pg, tmp_path):  # AC-13
    docs = _all_docs()
    del docs["s5"]
    by_id, _, discover = await _run(pg, tmp_path, docs, found={"s5": [_doc("D5", "s5")]})
    assert discover.calls == [["s5"]]
    assert by_id["s5"].citation.doc_id == "D5"


@pytest.mark.asyncio
async def test_no_discovery_when_every_stock_has_documents(pg, tmp_path):
    _, _, discover = await _run(pg, tmp_path, _all_docs())
    assert discover.calls == []


@pytest.mark.asyncio
async def test_grounded_quote_is_kept(pg, tmp_path):  # AC-16
    by_id, _, _ = await _run(pg, tmp_path, _all_docs())
    assert by_id["s1"].citation.quote == "We make PEM stacks."
    assert by_id["s1"].citation.doc_id == "D1"


@pytest.mark.asyncio
async def test_ungrounded_quote_drops_description_and_citation(pg, tmp_path):  # AC-17
    by_id, _, _ = await _run(pg, tmp_path, _all_docs(), {"s2": ("Makes wind turbines.", "We make wind turbines.")})
    assert by_id["s2"].error == "ungrounded_quote"
    assert by_id["s2"].description is None and by_id["s2"].citation is None


@pytest.mark.asyncio
async def test_no_value_is_not_found(pg, tmp_path):  # AC-18
    by_id, _, _ = await _run(pg, tmp_path, _all_docs(), {"s4": (None, None)})
    assert by_id["s4"].error == "not_found"
    assert by_id["s4"].description is None


@pytest.mark.asyncio
async def test_large_document_gives_eight_chunks_and_no_text_in_profile(pg, tmp_path, monkeypatch):  # Review Focus 3
    secret = "Confidential segment detail nobody should copy."
    docs = _all_docs()
    docs["s1"] = [_doc("D1", "s1", TEXT + " " + secret)]
    big = [DocumentChunk(doc_id="D1", company_id="s1", doc_type=DocType.ANNUAL_REPORT_10K, text=f"{secret} products {i}",
                         char_start=i, char_end=i + 1) for i in range(2000)]
    real = profile_mod.chunk_document
    monkeypatch.setattr(profile_mod, "chunk_document", lambda d, **kw: big if d.doc_id == "D1" else real(d, **kw))
    by_id, chunks, _ = await _run(pg, tmp_path, docs)
    assert len(chunks["s1"]) == 8
    dumped = by_id["s1"].model_dump_json()
    assert "We make PEM stacks." in dumped
    assert secret not in dumped and "hydrogen electrolysers" not in dumped
