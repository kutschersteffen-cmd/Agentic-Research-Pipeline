import numpy as np

from arp.research import funnel
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.thematic import ActivityDefinition

POS = "Makes electrolysers."
NEG = "Buys electrolysers."
CON = "Supplies catalysts."
ACT = ActivityDefinition(name="e", in_scope_description=POS, out_of_scope_description=NEG, contrast_statements=[CON])


def entail(row: dict, label: str, pos: str = POS) -> float:
    """Stand-in NLI score: the fixture's positive score (key POS, or P1/P2 for one statement) for either positive
    statement, else the label's own score; unspecified is 0.1."""
    if label.startswith(funnel.POSITIVE_PREFIX):
        own = "P2" if "the following:" in label else "P1"
        return row.get(own, row.get(pos, 0.1))
    return row.get(label, 0.1)


TH = {"k1": 25, "k2": 6, "t_rerank": 1.5, "t_entail": 0.8}


def _doc(i, text):
    return SourceDocument(doc_id=f"d{i}", company_id="c", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text=text)


class Calls:
    def __init__(self):
        self.embedded: list[str] = []


def stub(monkeypatch, rows, rerank_ok=True):
    """rows: {passage text: (cosine, rerank score, {statement: entailment})}; unspecified entailment is 0.1."""
    calls = Calls()

    def embed(texts, load=None):
        calls.embedded.extend(texts)
        out = []
        for t in texts:
            c = rows[t][0] if t in rows else 1.0  # anything not a passage is the query
            out.append([c, float(np.sqrt(max(0.0, 1 - c * c)))])
        return np.asarray(out, dtype=np.float32), {"model": "embed"}

    def rerank(query, texts, score=None):
        return ([rows[t][1] for t in texts] if rerank_ok else None), {"model": "rerank"}

    def classify(texts, labels, hypothesis="This text is about {}."):
        assert hypothesis == "{}"
        return [{lab: entail(rows[t][2], lab) for lab in labels} for t in texts], {"model": "nli"}

    monkeypatch.setattr(funnel.models, "embed", embed)
    monkeypatch.setattr(funnel.models, "rerank", rerank)
    monkeypatch.setattr(funnel.models, "classify", classify)
    return calls


def docs(rows):
    return [_doc(i, t) for i, t in enumerate(rows)]


def test_rerank_below_threshold_screens_out(monkeypatch):  # AC-4 data
    rows = {"P1 text.": (0.9, 0.5, {POS: 0.99})}
    stub(monkeypatch, rows)
    assert funnel.score_pair(docs(rows), ACT, TH).passed is False


def test_contrast_beats_positive_screens_out(monkeypatch):  # AC-7, AC-8
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.95, CON: 0.97})}
    stub(monkeypatch, rows)
    r = funnel.score_pair(docs(rows), ACT, TH)
    assert r.passed is False
    assert r.entail_negatives[CON] == 0.97
    assert set(r.entail_negatives) == {NEG, CON}


def test_second_passage_passes(monkeypatch):  # AC-9, AC-10
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.95, NEG: 0.97}), "P2 text.": (0.8, 2.0, {POS: 0.90, NEG: 0.2, CON: 0.2})}
    stub(monkeypatch, rows)
    r = funnel.score_pair(docs(rows), ACT, TH)
    assert r.passed is True
    assert r.best_passage == "P2 text."
    assert r.best_doc_id == "d1"
    assert r.entail_positive == 0.90
    assert r.rerank_max == 3.0


def test_tie_fails(monkeypatch):  # AC-11
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.90, NEG: 0.90})}
    stub(monkeypatch, rows)
    assert funnel.score_pair(docs(rows), ACT, TH).passed is False


def test_screened_best_passage_is_highest_positive(monkeypatch):  # AC-12
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.5}), "P3 text.": (0.8, 2.0, {POS: 0.70}), "P4 text.": (0.7, 2.0, {POS: 0.6})}
    stub(monkeypatch, rows)
    r = funnel.score_pair(docs(rows), ACT, TH)
    assert r.passed is False
    assert r.best_passage == "P3 text."
    assert r.entail_positive == 0.70


def test_k2_from_thresholds(monkeypatch):  # AC-15
    rows = {f"P{i} text.": (0.5 + i / 100, float(i), {POS: 0.9}) for i in range(10)}
    stub(monkeypatch, rows)
    r = funnel.score_pair(docs(rows), ACT, {**TH, "k2": 1})
    assert r.passages_scored == 1
    assert r.best_passage == "P9 text."


def test_k1_keeps_most_similar(monkeypatch):
    # only the most similar passage survives k1=1, even though another reranks higher
    rows = {"Near text.": (0.95, 2.0, {POS: 0.9}), "Far text.": (0.1, 9.0, {POS: 0.99})}
    stub(monkeypatch, rows)
    r = funnel.score_pair(docs(rows), ACT, {**TH, "k1": 1})
    assert r.best_passage == "Near text."
    assert r.rerank_max == 2.0


def test_rerank_unavailable_passes_on(monkeypatch):  # Review Focus 2
    rows = {"P1 text.": (0.9, 0.0, {POS: 0.1})}
    stub(monkeypatch, rows, rerank_ok=False)
    r = funnel.score_pair(docs(rows), ACT, TH)
    assert r.rerank_max is None
    assert r.passed is True


def test_fewer_chunks_than_k(monkeypatch):  # Review Focus 3
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.9}), "P2 text.": (0.8, 3.0, {POS: 0.9})}
    stub(monkeypatch, rows)
    assert funnel.score_pair(docs(rows), ACT, TH).passages_scored == 2


def test_models_provenance_and_thresholds_recorded(monkeypatch):
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.9})}
    stub(monkeypatch, rows)
    r = funnel.score_pair(docs(rows), ACT, TH)
    assert r.models == [{"model": "embed"}, {"model": "rerank"}, {"model": "nli"}]
    assert r.thresholds == TH


class FakeStore:
    def __init__(self):
        self.vectors = {}

    def lookup_embeddings(self, chunk_ids, embed_model):
        return {k: self.vectors[k] for k in chunk_ids if k in self.vectors}

    def store_embeddings(self, vectors_by_chunk_id, embed_model):
        self.vectors.update(vectors_by_chunk_id)


def test_passages_embedded_once_per_document_set(monkeypatch):
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.9}), "P2 text.": (0.8, 3.0, {POS: 0.9})}
    calls = stub(monkeypatch, rows)
    store = FakeStore()
    other = ActivityDefinition(name="o", in_scope_description=POS, out_of_scope_description=NEG)
    funnel.score_pair(docs(rows), ACT, TH, store)
    funnel.score_pair(docs(rows), other, TH, store)
    assert sorted(t for t in calls.embedded if t in rows) == ["P1 text.", "P2 text."]


def test_cached_vectors_used(monkeypatch):
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.9})}
    calls = stub(monkeypatch, rows)
    store = FakeStore()
    funnel.passage_vectors(funnel.chunks_for(docs(rows)), store)
    calls.embedded.clear()
    funnel.score_pair(docs(rows), ACT, TH, store)
    assert calls.embedded == [funnel.funnel_query(None, ACT).query]


def test_no_content_store_still_scores(monkeypatch):
    rows = {"P1 text.": (0.9, 3.0, {POS: 0.9})}
    stub(monkeypatch, rows)
    assert funnel.score_pair(docs(rows), ACT, TH, None).passed is True


def test_no_store_passages_embedded_once_across_activities(monkeypatch):  # review: no per-company cache without Postgres
    rows = {"Memo A text.": (0.9, 3.0, {POS: 0.9}), "Memo B text.": (0.8, 3.0, {POS: 0.9})}
    calls = stub(monkeypatch, rows)
    other = ActivityDefinition(name="o", in_scope_description=POS, out_of_scope_description=NEG)
    funnel.score_pair(docs(rows), ACT, TH, None)
    funnel.score_pair(docs(rows), other, TH, None)
    assert sorted(t for t in calls.embedded if t in rows) == ["Memo A text.", "Memo B text."]


def test_memo_keyed_by_text_not_only_chunk_id(monkeypatch):
    rows = {"First text.": (0.9, 3.0, {POS: 0.9}), "Second text.": (0.1, 3.0, {POS: 0.9})}
    stub(monkeypatch, rows)
    a = funnel.passage_vectors(funnel.chunks_for([_doc(0, "First text.")]), None)
    b = funnel.passage_vectors(funnel.chunks_for([_doc(0, "Second text.")]), None)
    assert not np.allclose(next(iter(a.values())), next(iter(b.values())))


def test_long_chunk_split_into_three_sentence_passages(monkeypatch):  # NLI saturates on long chunks
    text = "One a. Two b. Three c. Four d. Five e. Six f. Seven g."
    rows = {"One a. Two b. Three c.": (0.9, 3.0, {POS: 0.9}), "Four d. Five e. Six f.": (0.8, 2.0, {POS: 0.9}),
            "Seven g.": (0.7, 1.0, {POS: 0.9})}
    stub(monkeypatch, rows)
    r = funnel.score_pair([_doc(0, text)], ACT, TH)
    assert r.passages_scored == 3
    assert r.best_passage == "One a. Two b. Three c."
    assert r.best_doc_id == "d0"
