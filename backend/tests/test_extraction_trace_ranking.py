"""extraction-trace-parse-report spec, slice A: every candidate's ranks, small-to-big pieces, gate and vision times."""

import pytest

from arp.config import Settings
from arp.retrieval.select_evidence import select_relevant_chunks
from tests.test_select_evidence_explain import F1, _chunk, _f1, scorer, vectors  # noqa: F401 - fixtures
from tests.test_walkthrough_field_graph import (  # noqa: F401 - pdf_doc is a fixture
    _LONG_DOC,
    _agreeing_llm,
    _field,
    _vision_entry,
    pdf_doc,
)

F150 = [_chunk(" ".join(["capex"] * (151 - i)) + f" filler {i}") for i in range(150)] + [
    _chunk(f"unrelated text {i}") for i in range(150, 160)
]
HYBRID = {"hybrid_retrieval_enabled": True, "content_store": object()}

P1, P2, P3 = _chunk("parent one"), _chunk("parent two"), _chunk("parent three")
A1, A2, B1 = _chunk("capex filler filler filler filler filler"), _chunk("capex capex capex filler"), _chunk("capex filler filler filler")
CS = [_chunk(f"unrelated words {k}") for k in range(1, 7)]
STB = [A1, A2, B1, *CS]
PARENTS = {A1.chunk_id: P1, A2.chunk_id: P1, B1.chunk_id: P2} | {c.chunk_id: P3 for c in CS}


def _stb(explain=None, **kw):
    explain = {} if explain is None else explain
    return select_relevant_chunks(STB, ["capex"], max_chunks=5, parents=PARENTS, explain=explain, **kw), explain


def test_bm25_ranks_every_hit():  # AC-1
    _, ex = _f1()
    assert ex["ranked_count"] == 10 and ex["ranks_capped"] is False
    assert ex["ranks"] == {F1[i].chunk_id: {"bm25": i + 1} for i in range(10)}


@pytest.mark.usefixtures("vectors")
def test_hybrid_ranks():  # AC-2
    out, ex = _f1(**HYBRID)
    assert ex["ranked_count"] == 20 and set(ex["ranks"]) == {c.chunk_id for c in F1}
    assert all(isinstance(r["vector"], int) and isinstance(r["fused"], int) for r in ex["ranks"].values())
    assert {cid for cid, r in ex["ranks"].items() if "bm25" in r} == {c.chunk_id for c in F1[:10]}
    assert all(ex["ranks"][c.chunk_id]["vector"] == ex["scores"][c.chunk_id]["vector_rank"] for c in out)
    assert [ex["ranks"][c.chunk_id]["fused"] for c in out] == [1, 2, 3, 4, 5]


@pytest.mark.usefixtures("scorer")
def test_rerank_ranks():  # AC-3
    out, ex = _f1(rerank_candidates=10)
    reranked = {cid: r["rerank"] for cid, r in ex["ranks"].items() if "rerank" in r}
    assert set(reranked) == {c.chunk_id for c in F1[:10]} and set(reranked.values()) == set(range(1, 11))
    assert [ex["ranks"][c.chunk_id]["rerank"] for c in out] == [1, 2, 3, 4, 5]


def test_cap_bm25():  # AC-4
    ex: dict = {}
    select_relevant_chunks(F150, ["capex"], max_chunks=12, explain=ex)
    assert (ex["ranked_count"], ex["ranks_capped"], len(ex["ranks"])) == (150, True, 100)
    assert set(ex["ranks"]) == {F150[i].chunk_id for i in range(100)}


@pytest.mark.usefixtures("vectors", "scorer")
def test_cap_keeps_returned_chunks():  # AC-5
    ex: dict = {}
    out = select_relevant_chunks(F150, ["capex"], max_chunks=12, rerank_candidates=120, explain=ex, **HYBRID)
    assert (ex["ranked_count"], ex["ranks_capped"], len(ex["ranks"])) == (160, True, 112)
    assert all(c.chunk_id in ex["ranks"] for c in out)


def test_no_terms_and_unranked():  # AC-6, AC-7
    ex: dict = {}
    select_relevant_chunks(F1, [], max_chunks=5, explain=ex)
    assert (ex["ranks"], ex["ranked_count"], ex["ranks_capped"]) == ({}, 0, False) and "pieces" not in ex
    ex = {}
    select_relevant_chunks(F1[10:], ["capex"], max_chunks=5, fallback_to_all=True, explain=ex)
    assert (ex["method"], ex["ranks"], ex["ranked_count"]) == ("unranked", {}, 0)


def test_small_to_big_pieces():  # AC-8, AC-10
    out, ex = _stb()
    assert out == [P1, P2]
    assert ex["ranks"] == {P1.chunk_id: {"bm25": 1}, P2.chunk_id: {"bm25": 2}}
    assert ex["pieces"] == {P1.chunk_id: {"bm25": A2.chunk_id}, P2.chunk_id: {"bm25": B1.chunk_id}}
    assert "pieces" not in _f1()[1]


@pytest.mark.usefixtures("vectors")
def test_small_to_big_pieces_hybrid():  # AC-9
    out, ex = _stb(**HYBRID)
    assert out == [P1, P2, P3]
    assert ex["pieces"] == {
        P1.chunk_id: {"bm25": A2.chunk_id, "vector": A2.chunk_id},
        P2.chunk_id: {"bm25": B1.chunk_id, "vector": B1.chunk_id},
        P3.chunk_id: {"vector": CS[-1].chunk_id},
    }


def test_second_call_on_one_explain():  # AC-11
    _, ex = _stb()
    select_relevant_chunks(F1, ["capex"], max_chunks=5, explain=ex)
    fresh = _f1()[1]
    assert "pieces" not in ex
    assert all(ex[k] == fresh[k] for k in ("ranks", "ranked_count", "ranks_capped"))


@pytest.mark.usefixtures("vectors", "scorer")
def test_explain_never_changes_the_pick():  # AC-12
    cases = [
        (F1, 5, {}), (F1, 5, HYBRID), (F1, 5, {"rerank_candidates": 10}),
        (F150, 12, {**HYBRID, "rerank_candidates": 120}),
        (STB, 5, {"parents": PARENTS}), (STB, 5, {"parents": PARENTS, **HYBRID}),
    ]
    for chunks, n, kw in cases:
        with_explain = select_relevant_chunks(chunks, ["capex"], max_chunks=n, explain={}, **kw)
        assert [c.chunk_id for c in with_explain] == [c.chunk_id for c in select_relevant_chunks(chunks, ["capex"], max_chunks=n, **kw)]


async def _long_entry(fake_llm, settings=None):
    from arp.extraction.field_graph import extract_one_field

    llm, sink = _agreeing_llm(fake_llm), {}
    await extract_one_field(
        "Acme", _field(), documents=[_LONG_DOC], documents_by_id={_LONG_DOC.doc_id: _LONG_DOC}, llm=llm,
        verifier_llm=llm, fuzzy_threshold=0.9, confidence_review_threshold=0.6, trace_sink=sink, settings=settings,
    )
    return sink["scope1"]


async def test_entry_ranking(fake_llm):  # AC-13, AC-18
    e = await _long_entry(fake_llm)
    r = e["ranking"]
    assert set(r) == {"ranks", "ranked_count", "ranks_capped"} and r["ranks_capped"] is False
    assert r["ranked_count"] == len(r["ranks"]) >= len(e["passages"]) + 4
    for i, p in enumerate(e["passages"], start=1):
        assert r["ranks"][f"chk_{p['doc_id']}_{p['char_start']}_{p['char_end']}"] == {"bm25": i}
    assert e["sub_seconds"] == {}


async def test_entry_ranking_small_to_big(fake_llm):  # AC-14
    e = await _long_entry(fake_llm, Settings(small_to_big_enabled=True, hybrid_retrieval_enabled=False))
    pieces = e["ranking"]["pieces"]
    assert set(pieces) == {f"chk_{p['doc_id']}_{p['char_start']}_{p['char_end']}" for p in e["passages"]}
    assert all(set(v) == {"bm25"} and v["bm25"].startswith(f"chk_{_LONG_DOC.doc_id}_") for v in pieces.values())


async def test_gate_time(fake_llm):  # AC-17
    from arp.extraction import evidence_gate
    from tests.test_evidence_gate import GateAnswer, Stub, _gate

    token = evidence_gate._current.set(_gate(Stub(GateAnswer(keep=[5]))))
    try:
        e = await _long_entry(fake_llm)
    finally:
        evidence_gate._current.reset(token)
    assert set(e["sub_seconds"]) == {"gate"}
    assert 0 <= e["sub_seconds"]["gate"] <= e["seconds"]["gather_evidence"]
    assert set(e["seconds"]) == {"try_tagged", "gather_evidence", "extract", "verify", "aggregate"}


async def test_vision_time(fake_llm, request):  # AC-19
    e, _ = await _vision_entry(fake_llm, request.getfixturevalue("pdf_doc"), enabled=True)
    assert set(e["sub_seconds"]) == {"vision"}
    assert 0 <= e["sub_seconds"]["vision"] <= e["seconds"]["aggregate"]
