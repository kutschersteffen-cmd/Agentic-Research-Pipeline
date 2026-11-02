import httpx
import pytest

from arp import models
from arp.compute import client
from arp.models import cache, local, registry

TEXT = "We reduce the credit risk"
GOOD = {"label": "risk", "text": "credit risk", "start": 14, "end": 25, "score": 0.9}


class StandIn:
    def __init__(self, found):
        self.found, self.loads = found, 0

    def __call__(self, e, device):
        self.loads += 1
        return type("M", (), {"predict_entities": lambda _, t, labels, threshold: list(self.found)})()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    class S:
        cache_dir = tmp_path
    monkeypatch.setattr(cache, "get_settings", lambda: S)
    monkeypatch.setattr(local, "_pipes", {})
    monkeypatch.setattr(client, "_cooldown_until", {})


@pytest.fixture
def no_cloud(monkeypatch):
    monkeypatch.setattr(client, "models_configured", lambda: False)
    monkeypatch.setattr(client, "_configured", lambda cap: None)


def local_returns(monkeypatch, found):
    s = StandIn(found)
    monkeypatch.setattr(local, "_gliner", s)
    return s


def cloud_returns(monkeypatch, body, status=200):
    local_returns(monkeypatch, [])  # a cloud-path regression fails on an assert, not by loading a model

    def handler(request):
        assert request.headers["x-arp-model"] == registry.model_header(registry.entry("gliner"))
        return httpx.Response(status, json=body)
    monkeypatch.setattr(client, "models_configured", lambda: True)
    monkeypatch.setattr(client, "_configured", lambda cap: "https://arp-models.example")
    monkeypatch.setattr(client, "_auth", lambda url: {})
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    monkeypatch.setattr(client, "_http", httpx.Client(transport=httpx.MockTransport(handler)))


def test_span_returned(monkeypatch):  # spec AC-5
    cloud_returns(monkeypatch, {"spans": [[GOOD]]})
    res, prov = models.spans([TEXT], ["risk"])
    assert res == [[GOOD]] and prov["where"] == "cloud"


def test_span_with_wrong_offsets_dropped(monkeypatch):  # spec AC-6
    cloud_returns(monkeypatch, {"spans": [[{**GOOD, "start": 15, "end": 26}]]})
    assert models.spans([TEXT], ["risk"])[0] == [[]]


def test_spans_empty_input(no_cloud):  # Review Focus 1
    assert models.spans([], ["risk"])[0] == []


def test_local_spans_filtered_and_cached(no_cloud, monkeypatch):
    s = local_returns(monkeypatch, [GOOD, {**GOOD, "start": 0, "end": 5}])
    assert models.spans([TEXT], ["risk"]) [0] == [[GOOD]]
    res, prov = models.spans([TEXT], ["risk"])
    assert res == [[GOOD]] and prov["where"] == "local" and s.loads == 1


def test_bad_cached_span_not_returned(no_cloud, monkeypatch):
    local_returns(monkeypatch, [{**GOOD, "start": 15, "end": 26}])
    models.spans([TEXT], ["risk"])
    assert models.spans([TEXT], ["risk"])[0] == [[]]


def test_threshold_is_part_of_cache_key(no_cloud, monkeypatch):
    s = local_returns(monkeypatch, [GOOD])
    models.spans([TEXT], ["risk"], 0.5)
    models.spans([TEXT], ["risk"], 0.9)
    assert s.loads == 1  # model loaded once, but both calls computed
    assert len(list((cache.get_settings().cache_dir / "models" / "gliner").rglob("*.json"))) == 2


def test_cloud_500_falls_back(monkeypatch):
    cloud_returns(monkeypatch, {}, status=500)
    local_returns(monkeypatch, [GOOD])
    res, prov = models.spans([TEXT], ["risk"])
    assert res == [[GOOD]] and prov["where"] == "local"
