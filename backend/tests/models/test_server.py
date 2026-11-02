import pytest
from fastapi.testclient import TestClient

from arp.compute import server
from arp.models import local
from arp.models.registry import entry, model_header


@pytest.fixture
def c():
    return TestClient(server.app)


def test_classify_model_mismatch_409(c):  # spec AC-9
    r = c.post("/classify", json={"texts": ["a"], "labels": ["x"], "hypothesis": "{}"}, headers={"x-arp-model": "wrong"})
    assert r.status_code == 409


def test_tag_model_mismatch_409(c):  # spec AC-11
    r = c.post("/tag", json={"key": "climate_detector", "texts": ["a"]}, headers={"x-arp-model": "wrong"})
    assert r.status_code == 409


def test_spans_model_mismatch_409(c):  # spec AC-10
    r = c.post("/spans", json={"texts": ["a"], "labels": ["x"], "threshold": 0.5}, headers={"x-arp-model": "wrong"})
    assert r.status_code == 409


def test_tag_rejects_non_tag_key_404(c, monkeypatch):
    calls = []
    monkeypatch.setattr(local, "tag_scores", lambda *a, **k: calls.append(1))
    r = c.post("/tag", json={"key": "nli", "texts": ["a"]}, headers={"x-arp-model": model_header(entry("nli"))})
    assert r.status_code == 404 and not calls
