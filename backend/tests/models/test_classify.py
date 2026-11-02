import httpx
import pytest

from arp import models
from arp.compute import client
from arp.models import cache, local, registry


class StandInNLI:
    def __init__(self):
        self.loads = 0
        self.kwargs = {}

    def __call__(self, task, e, **kw):
        self.loads += 1

        def pipe(texts, candidate_labels, **kwargs):
            self.kwargs = kwargs
            return [{"labels": list(candidate_labels), "scores": [1.0 / (i + 1) for i in range(len(candidate_labels))]}
                    for _ in texts]
        return pipe


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


@pytest.fixture
def stand_in_nli(monkeypatch):
    s = StandInNLI()
    monkeypatch.setattr(local, "_pipeline", s)
    return s


class Cloud:
    def __init__(self, status, body=None):
        self.status, self.body, self.requests = status, body, 0

    def __call__(self, request):
        self.requests += 1
        assert request.headers["x-arp-model"] == registry.model_header(registry.entry("nli"))
        return httpx.Response(self.status, json=self.body)


def _cloud(monkeypatch, handler):
    monkeypatch.setattr(client, "models_configured", lambda: True)
    monkeypatch.setattr(client, "_configured", lambda cap: "https://arp-models.example")
    monkeypatch.setattr(client, "_auth", lambda url: {})
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    monkeypatch.setattr(client, "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    return handler


@pytest.fixture
def cloud_ok(monkeypatch):
    return _cloud(monkeypatch, Cloud(200, {"scores": [{"x": 0.9, "y": 0.1}]}))


@pytest.fixture
def cloud_500(monkeypatch):
    return _cloud(monkeypatch, Cloud(500, {}))


def test_classify_local_keys_and_where(no_cloud, stand_in_nli):  # spec AC-1
    res, prov = models.classify(["a"], ["x", "y"])
    assert set(res[0]) == {"x", "y"} and prov["where"] == "local"


def test_classify_cloud(cloud_ok):  # spec AC-2
    res, prov = models.classify(["a"], ["x", "y"])
    assert res == [{"x": 0.9, "y": 0.1}] and prov["where"] == "cloud"


def test_cloud_500_falls_back_and_cools(cloud_500, stand_in_nli):  # spec AC-3, AC-4
    models.classify(["a"], ["x"])
    _, prov = models.classify(["b"], ["x"])
    assert cloud_500.requests == 1 and prov["where"] == "local"


def test_empty_input(no_cloud, stand_in_nli):  # Review Focus 1
    assert models.classify([], ["x"])[0] == [] and stand_in_nli.loads == 0


def test_label_order_irrelevant(no_cloud, stand_in_nli):  # Review Focus 3
    assert models.classify(["a"], ["x", "y"])[0][0]["x"] == models.classify(["a"], ["y", "x"])[0][0]["x"]


def test_truncation_requested(no_cloud, stand_in_nli):  # Review Focus 4
    models.classify(["w " * 5000], ["x"])
    assert stand_in_nli.kwargs["truncation"] is True


def test_tag_unknown_key():  # spec AC-7
    with pytest.raises(KeyError):
        models.tag("not_in_registry", ["a"])


def test_provenance_revision(no_cloud, stand_in_nli):  # spec AC-14
    _, prov = models.classify(["a"], ["x"])
    assert set(prov) == {"model", "revision", "where"} and prov["revision"] == registry.entry("nli").revision


def test_tag_local(no_cloud, monkeypatch):
    monkeypatch.setattr(local, "_pipeline", lambda task, e, **kw: lambda texts, **k: [{"label": "yes", "score": 0.7}
                                                                                   for _ in texts])
    res, prov = models.tag("climate_detector", ["a", "b"])
    assert res == [{"label": "yes", "score": 0.7}] * 2 and prov["model"] == "climate_detector"
