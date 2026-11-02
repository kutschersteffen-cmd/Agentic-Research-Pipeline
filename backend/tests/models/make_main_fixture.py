"""Writes fixtures/main_vectors.npz from the code on PYTHONPATH (run once against origin/main).

Stand-in fastembed classes return deterministic functions of the text, so the test can
install the same stand-ins and compare the new code path against main's output.
Usage: ARP_COMPUTE_MODELS_URL= ARP_COMPUTE_PARSE_URL= python make_main_fixture.py OUT.npz
"""
import hashlib
import sys
import types
from pathlib import Path

import numpy as np

TEXTS = ["Scope 1 emissions fell 12% in 2025.", "Die Emissionen sanken deutlich.", "Board pay rose.", ""]
QUERY = "greenhouse gas emissions"


def _vec(text: str, dim: int = 384) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")
    return np.random.default_rng(seed).standard_normal(dim).astype(np.float32)


class StandInTextEmbedding:
    def __init__(self, model_name, **kw):
        self.model_name = model_name

    def embed(self, texts):
        return (_vec(t) for t in texts)


class StandInCrossEncoder:
    def __init__(self, model_name, **kw):
        self.model_name = model_name

    def rerank(self, query, texts):
        return (float(_vec(query + "\x00" + t, 1)[0]) for t in texts)


def install(monkeypatch=None) -> None:
    """Puts the stand-ins in sys.modules under fastembed's import paths."""
    fe = types.ModuleType("fastembed")
    fe.TextEmbedding = StandInTextEmbedding
    ce = types.ModuleType("fastembed.rerank.cross_encoder")
    ce.TextCrossEncoder = StandInCrossEncoder
    mods = {"fastembed": fe, "fastembed.rerank": types.ModuleType("fastembed.rerank"),
            "fastembed.rerank.cross_encoder": ce}
    for name, mod in mods.items():
        if monkeypatch is None:
            sys.modules[name] = mod
        else:
            monkeypatch.setitem(sys.modules, name, mod)


if __name__ == "__main__":
    install()
    from arp.retrieval import embeddings, rerank

    vectors = embeddings.embed_texts(TEXTS)
    scores = np.asarray(rerank._score(QUERY, TEXTS))
    np.savez(Path(sys.argv[1]), texts=np.array(TEXTS), query=np.array(QUERY), vectors=vectors, scores=scores)
