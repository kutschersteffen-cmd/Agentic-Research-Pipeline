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
    monkeypatch.setattr(client, "healthz", lambda url: {"parser_version": "v", "cuda": True})
    monkeypatch.setattr(local_files, "_extract_pdf_text_local", lambda path: ("ARP compute check", [0], []))
    monkeypatch.setattr(client, "rerank_scores", lambda query, texts: [0.9, 0.1, 0.2])
    monkeypatch.setattr(rerank, "_get_model", lambda: _FakeLocalReranker())
    monkeypatch.setattr(client, "embed", lambda texts: np.ones((1, embeddings.EMBED_DIM), dtype=np.float32))
    monkeypatch.setattr(embeddings, "_get_model", lambda: _FakeLocalEmbedder())


@pytest.mark.usefixtures("healthy")
def test_all_ok():  # AC-29 (unit half)
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 0
    assert res.output == "parse OK\nrerank OK\nembed OK\n"


@pytest.mark.usefixtures("healthy")
def test_parse_failure_reported(monkeypatch):  # AC-30 (unit half)
    def unreachable(path, version):
        client.last_error["parse"] = "ConnectError: refused"

    monkeypatch.setattr(client, "parse_pdf", unreachable)
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 1
    assert res.output.splitlines() == ["parse FAIL: ConnectError: refused", "rerank OK", "embed OK"]


@pytest.mark.usefixtures("healthy")
def test_service_without_gpu_fails(monkeypatch):
    monkeypatch.setattr(client, "healthz", lambda url: {"parser_version": "v", "cuda": False})
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 1 and res.output.startswith("parse FAIL: ")


@pytest.mark.usefixtures("healthy")
def test_urls_unset(monkeypatch):
    monkeypatch.setattr(compute_cli, "get_settings", lambda: Settings(compute_parse_url="", compute_models_url=""))
    res = CliRunner().invoke(compute_app, ["check"])
    assert res.exit_code == 1
    assert "parse FAIL: ARP_COMPUTE_PARSE_URL not set" in res.output
    assert "rerank FAIL: ARP_COMPUTE_MODELS_URL not set" in res.output
