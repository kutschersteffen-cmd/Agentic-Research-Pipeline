import numpy as np
import pytest
from typer.testing import CliRunner

from arp.cli import compute as compute_cli
from arp.cli.compute import compute_app
from arp.compute import client
from arp.config import Settings
from arp.ingestion import local_files
from arp.retrieval import embeddings, rerank


class _FakeLocalReranker:
    def rerank(self, query, texts):
        return [5.0, 1.0, 2.0]


class _FakeLocalEmbedder:
    def embed(self, texts):
        return [np.ones(embeddings.EMBED_DIM)]


@pytest.fixture
def healthy(monkeypatch, tmp_path):
    settings = Settings(
        compute_parse_url="https://arp-parse.example.run.app", compute_models_url="https://arp-models.example.run.app"
    )
    monkeypatch.setattr(compute_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(client, "last_error", {})
    monkeypatch.setattr(client, "parse_pdf", lambda path, version: ("ARP compute check", [0], []))
    monkeypatch.setattr(client, "healthz", lambda url: {"parser_version": "v", "cuda": True, "device": "cuda"})
    monkeypatch.setattr(local_files, "_extract_pdf_text_local", lambda path: ("ARP compute check", [0], []))
    monkeypatch.setattr(client, "rerank_scores", lambda query, texts: [0.9, 0.1, 0.2])
    monkeypatch.setattr(rerank, "_get_model", lambda: _FakeLocalReranker())
    monkeypatch.setattr(client, "embed", lambda texts: np.ones((1, embeddings.EMBED_DIM), dtype=np.float32))
    monkeypatch.setattr(embeddings, "_get_model", lambda: _FakeLocalEmbedder())


@pytest.mark.usefixtures("healthy")
def test_all_ok():  # AC-29 (unit half)
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 0
    assert res.output == "parse OK (device=cuda)\nrerank OK (device=cuda)\nembed OK (device=cuda)\n"


@pytest.mark.usefixtures("healthy")
def test_parse_failure_reported(monkeypatch):  # AC-30 (unit half)
    def unreachable(path, version):
        client.last_error["parse"] = "ConnectError: refused"

    monkeypatch.setattr(client, "parse_pdf", unreachable)
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 1
    assert res.output.splitlines() == ["parse FAIL: ConnectError: refused", "rerank OK (device=cuda)", "embed OK (device=cuda)"]


@pytest.mark.usefixtures("healthy")
def test_service_without_gpu_passes(monkeypatch):  # portable-docker-images: CPU is a valid device now
    monkeypatch.setattr(client, "healthz", lambda url: {"parser_version": "v", "cuda": False, "device": "cpu"})
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 0 and res.output == "parse OK (device=cpu)\nrerank OK (device=cpu)\nembed OK (device=cpu)\n"


@pytest.mark.usefixtures("healthy")
def test_urls_unset(monkeypatch):
    monkeypatch.setattr(compute_cli, "get_settings", lambda: Settings(compute_parse_url="", compute_models_url=""))
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 1
    assert "parse FAIL: ARP_COMPUTE_PARSE_URL not set" in res.output
    assert "rerank FAIL: ARP_COMPUTE_MODELS_URL not set" in res.output


class _ServerReranker:
    def rerank(self, query, texts):
        return [0.9, 0.1, 0.2]


class _ServerEmbedder:
    def embed(self, texts):
        return [np.ones(embeddings.EMBED_DIM) for _ in texts]


def test_check_against_cpu_service(monkeypatch, tmp_path):  # portable-docker-images AC-24
    from fastapi.testclient import TestClient

    from arp.compute import server

    key = tmp_path / "key.json"
    key.write_text("{}")
    settings = Settings(compute_models_url="http://compute.test", compute_credentials_file=str(key))
    monkeypatch.setattr(compute_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    monkeypatch.setattr(client, "_auth", lambda url: {})
    monkeypatch.setattr(client, "_http", TestClient(server.app))  # every URL goes to the compute app
    monkeypatch.setattr(client, "_cooldown_until", {})
    monkeypatch.setattr(client, "last_error", {})
    monkeypatch.delenv("ARP_COMPUTE_DEVICE", raising=False)
    monkeypatch.setattr(server, "_cuda_available", lambda: False)
    monkeypatch.setattr(server, "_models", {})
    monkeypatch.setattr(server, "_load_reranker", lambda key, device: _ServerReranker())
    monkeypatch.setattr(server, "_load_embedder", lambda key, device: _ServerEmbedder())
    monkeypatch.setattr(rerank, "_get_model", lambda: _FakeLocalReranker())
    monkeypatch.setattr(embeddings, "_get_model", lambda: _FakeLocalEmbedder())
    lines = CliRunner().invoke(compute_app, ["check"]).output.splitlines()
    assert "rerank OK (device=cpu)" in lines and "embed OK (device=cpu)" in lines
    assert not any("no GPU" in line for line in lines)


@pytest.mark.usefixtures("healthy")
def test_device_comes_from_each_service(monkeypatch):  # portable-docker-images: device per service URL
    asked = []
    devices = {"https://arp-parse.example.run.app": {"device": "cuda"}, "https://arp-models.example.run.app": {"device": "cpu"}}
    monkeypatch.setattr(client, "healthz", lambda url: asked.append(url) or devices[url])
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.output == "parse OK (device=cuda)\nrerank OK (device=cpu)\nembed OK (device=cpu)\n"
    assert asked == ["https://arp-parse.example.run.app"] + ["https://arp-models.example.run.app"] * 2


@pytest.mark.usefixtures("healthy")
@pytest.mark.parametrize("health", [None, {"parser_version": "v", "cuda": False}])
def test_device_unknown_without_healthz_device(monkeypatch, health):
    monkeypatch.setattr(client, "healthz", lambda url: health)
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 0
    assert res.output == "parse OK (device=unknown)\nrerank OK (device=unknown)\nembed OK (device=unknown)\n"


@pytest.mark.usefixtures("healthy")
def test_parse_text_mismatch_fails(monkeypatch):
    monkeypatch.setattr(local_files, "_extract_pdf_text_local", lambda path: ("something else", [0], []))
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 1
    assert res.output.splitlines()[0] == "parse FAIL: the cloud text differs from the local parse"


@pytest.mark.usefixtures("healthy")
def test_urls_unset_lines(monkeypatch):
    monkeypatch.setattr(compute_cli, "get_settings", lambda: Settings(compute_parse_url="", compute_models_url=""))
    assert CliRunner().invoke(compute_app, ["check"]).output.splitlines() == [
        "parse FAIL: ARP_COMPUTE_PARSE_URL not set",
        "rerank FAIL: ARP_COMPUTE_MODELS_URL not set",
        "embed FAIL: ARP_COMPUTE_MODELS_URL not set",
    ]


@pytest.mark.usefixtures("healthy")
def test_rerank_and_embed_disagreement_fail(monkeypatch):
    asked = {}

    class _Local:
        def rerank(self, query, texts):
            asked["rerank"] = (query, texts)
            return [0.0, 0.0, 9.0]

        def embed(self, texts):
            asked["embed"] = texts
            return [np.array([1.0] + [0.0] * (embeddings.EMBED_DIM - 1))]

    monkeypatch.setattr(rerank, "_get_model", lambda: _Local())
    monkeypatch.setattr(embeddings, "_get_model", lambda: _Local())
    monkeypatch.setattr(client, "embed", lambda texts: np.full((1, embeddings.EMBED_DIM), 2.0, dtype=np.float32))
    lines = CliRunner().invoke(compute_app, ["check"]).output.splitlines()
    assert lines[1] == "rerank FAIL: the cloud and local rerankers rank a different text first"
    assert lines[2] == f"embed FAIL: cosine(cloud, local) = {1 / embeddings.EMBED_DIM ** 0.5:.3f} < 0.99"
    assert asked == {"rerank": (compute_cli._QUERY, compute_cli._TEXTS), "embed": compute_cli._TEXTS[:1]}
