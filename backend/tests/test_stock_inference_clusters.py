import numpy as np

from arp.research.stock_inference import clusters as mod
from arp.research.stock_inference.clusters import build_clusters, cluster_points
from arp.schemas.common import DocumentChunk

WORDS_A = "turbine blade wind offshore generator rotor gearbox tower nacelle windfarm"
WORDS_B = "insulin diabetes therapy clinical trial oncology antibody vaccine patient biotech"
WORDS_BENCH = "software cloud subscription analytics platform"


def _chunk(cid, text):
    return DocumentChunk(doc_id="d", company_id=cid, doc_type="10-K", text=text, char_start=0, char_end=len(text))


def _fixture():
    chunks = {
        "s1": [_chunk("s1", f"{WORDS_A} variant{i}") for i in range(8)],
        "s2": [_chunk("s2", f"{WORDS_A} extra{i}") for i in range(8)],
        "s3": [_chunk("s3", f"{WORDS_B} other{i}") for i in range(8)],
    }
    rng = np.random.default_rng(0)
    a, b = np.zeros(384), np.zeros(384)
    a[0], b[1] = 1.0, 1.0
    vec = {"s1": a, "s2": a, "s3": b}

    def embed(texts):
        # Row order follows the call order: fund chunks s1, s2, s3 then benchmark.
        rows = [vec[c.company_id] + rng.normal(0, 0.01, 384) for cs in chunks.values() for c in cs]
        rows += [rng.normal(0, 1, 384) for _ in range(len(texts) - len(rows))]
        return np.array(rows, dtype=np.float32)

    return chunks, embed


def test_ac25_two_clusters():
    chunks, embed = _fixture()
    out = build_clusters(chunks, {"s1": 1.0, "s2": 1.0, "s3": 2.0}, [], embed=embed)
    assert [c.cluster_id for c in out] == sorted(c.cluster_id for c in out)
    # HDBSCAN label numbering is arbitrary, so compare membership order-free.
    assert sorted(c.members for c in out) == [["s1", "s2"], ["s3"]]
    assert all(len(c.terms) == 10 for c in out)
    assert [c.weight_share for c in out] == [0.5, 0.5]


def test_ac26_all_noise():
    chunks, embed = _fixture()
    out = build_clusters(chunks, {}, [], cluster=lambda e: np.full(len(e), -1), embed=embed)
    assert out == []


def test_fewer_than_three_points_skips_umap(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("UMAP must not run")

    monkeypatch.setattr(mod, "_run_once", boom)
    chunks = {"s1": [_chunk("s1", "alpha beta"), _chunk("s1", "gamma delta")]}
    assert build_clusters(chunks, {}, [], embed=lambda t: np.ones((len(t), 4))) == []
    assert list(cluster_points(np.ones((2, 4)))) == [-1, -1]


def test_unweighted_share_none_and_benchmark_not_member():
    chunks, embed = _fixture()
    bench = [_chunk("bm1", WORDS_BENCH + " " + WORDS_A)]
    plain = build_clusters(chunks, {"s1": None, "s2": None, "s3": None}, [], embed=embed)
    chunks, embed = _fixture()
    with_b = build_clusters(chunks, {}, bench, embed=embed)
    assert all(c.weight_share is None for c in plain)
    assert sorted(c.members for c in with_b) == [["s1", "s2"], ["s3"]]
    assert [c.terms for c in plain] != [c.terms for c in with_b]
