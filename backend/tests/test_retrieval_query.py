from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from arp.config import Settings
from arp.extraction import field_graph
from arp.extraction.field_graph import field_evidence
from arp.presets.transition_plan import build_transition_plan_schema
from arp.retrieval import embeddings, rerank
from arp.retrieval.keywords_de import with_german
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition

DOC = SourceDocument(
    company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="report",
    full_text="\n\n".join(f"Paragraph {i} about emissions and the annual bonus of the board." for i in range(40)),
)


class _DictStore:
    def __init__(self):
        self.rows = {}

    def lookup_embeddings(self, chunk_ids, model):
        return {i: self.rows[(i, model)] for i in chunk_ids if (i, model) in self.rows}

    def store_embeddings(self, vectors, model):
        self.rows.update({(i, model): v for i, v in vectors.items()})


def _field(query):
    return FieldDefinition(field_id="f", name="f", description="d", data_type=FieldDataType.BOOLEAN, extraction_instructions="",
                           seed_keywords=["emissions", "annual bonus"], retrieval_query=query)


@pytest.fixture
def recorded(monkeypatch):
    calls = {"embed": [], "rerank": []}

    def embed(texts):
        calls["embed"].append(list(texts))
        return [np.ones(3, dtype=np.float32) for _ in texts]

    def record_rerank(query, chunks, max_chunks):
        calls["rerank"].append(query)
        return chunks[:max_chunks]

    store = _DictStore()
    monkeypatch.setattr(embeddings, "embed_texts", embed)
    monkeypatch.setattr(rerank, "rerank", record_rerank)
    monkeypatch.setattr("arp.retrieval.content_store_factory.build_hybrid_content_store", lambda settings: store)
    return calls


@pytest.mark.parametrize("query", ["Does the company report X?", None])
def test_the_embedding_and_rerank_query_is_the_retrieval_query_else_the_keywords(recorded, query):
    field_evidence(_field(query), [DOC], Settings(hybrid_retrieval_enabled=True, rerank_enabled=True))
    expected = query or " ".join(with_german(["emissions", "annual bonus"]))
    assert recorded["embed"][-1] == [expected]  # the query is embedded last, after the chunks
    assert recorded["rerank"] == [expected]


def test_bm25_only_ignores_the_retrieval_query(recorded):
    settings = Settings(hybrid_retrieval_enabled=False)
    with_query = field_evidence(_field("Does the company report X?"), [DOC], settings)
    without = field_evidence(_field(None), [DOC], settings)
    assert [c.chunk_id for c in with_query] == [c.chunk_id for c in without]
    assert recorded["embed"] == []


def test_transition_plan_questions_are_the_retrieval_queries():
    questions = {i["identifier"]: i["question"] for i in json.loads(
        (Path(field_graph.__file__).parents[1] / "transition_plan" / "data" / "indicators.json").read_text())}
    fields = build_transition_plan_schema().fields
    indicators = [f for f in fields if f.field_id.startswith("tp_a_")]
    assert len(indicators) == 64
    assert all(f.retrieval_query == questions[f.name] for f in indicators)
    assert all(f.retrieval_query is None for f in fields if not f.field_id.startswith("tp_a_"))


def test_a_released_field_may_change_its_retrieval_inputs_without_a_new_version(pg):
    from arp.db.fields import FieldVersionError, SchemaRegistry
    from arp.schemas.datapoints import DataPointSchema

    reg = SchemaRegistry(pg)
    saved = reg.save(DataPointSchema(name="S", fields=[_field(None)]))
    released = reg.release(saved.schema_id, saved.version)
    field = released.fields[0]
    retuned = field.model_copy(update={"seed_keywords": ["emissions", "net zero"], "retrieval_query": "Does it report X?"})
    again = reg.save(released.model_copy(update={"fields": [retuned]}))
    assert again.version == released.version + 1 and again.fields[0].version == field.version
    with pytest.raises(FieldVersionError):  # the question itself still needs a new version
        reg.save(released.model_copy(update={"fields": [retuned.model_copy(update={"description": "other"})]}))
