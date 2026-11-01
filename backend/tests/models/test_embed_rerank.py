import subprocess
from pathlib import Path

import numpy as np
import pytest

from arp import models
from arp.compute import client
from arp.models import local
from arp.retrieval import embeddings, rerank
from tests.models import make_main_fixture

BACKEND = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "main_vectors.npz"


@pytest.fixture
def stand_in_models(monkeypatch):
    monkeypatch.setattr(local, "_pipes", {})
    monkeypatch.setattr(client, "models_configured", lambda: False)
    monkeypatch.setattr(client, "_configured", lambda cap: None)
    make_main_fixture.install(monkeypatch)


def test_embed_matches_main(stand_in_models):  # spec AC-15
    f = np.load(FIXTURE)
    vec, prov = models.embed(list(f["texts"]))
    assert np.allclose(vec, f["vectors"], atol=1e-6)
    assert prov == {"model": "embed", "revision": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42", "where": "local"}
    assert np.allclose(embeddings.embed_texts(list(f["texts"])), f["vectors"], atol=1e-6)


def test_rerank_matches_main(stand_in_models):  # spec AC-15
    f = np.load(FIXTURE)
    scores, prov = models.rerank(str(f["query"]), list(f["texts"]))
    assert np.allclose(scores, f["scores"], atol=1e-6)
    assert prov["where"] == "local" and prov["model"] == "rerank"
    assert np.allclose(rerank._score(str(f["query"]), list(f["texts"])), f["scores"], atol=1e-6)


def test_rerank_cloud_failure_returns_none_without_local_load(monkeypatch):
    monkeypatch.setattr(client, "models_configured", lambda: True)
    monkeypatch.setattr(client, "rerank_scores", lambda q, t: None)
    monkeypatch.setattr(local, "cross_encoder", lambda name: pytest.fail("local reranker built"))
    assert models.rerank("q", ["a"]) == (None, {"model": "rerank", "revision": "main", "where": "cloud"})


def test_text_embedding_cached_per_name(stand_in_models):
    assert local.text_embedding("a") is local.text_embedding("a")
    assert local.text_embedding("a") is not local.text_embedding("b")


def test_no_loaders_outside_models():  # spec AC-16, Review Focus 5
    out = subprocess.run(["grep", "-rnE", r'from_pretrained|TextEmbedding\(|GLiNER\(|transformers\.pipeline\(|pipeline\("', "arp", "--include=*.py"], capture_output=True, text=True, cwd=BACKEND).stdout
    assert all(line.startswith(("arp/models/", "arp/compute/server.py")) for line in out.splitlines())
