"""Gemini through Vertex AI (spec bank-jupyter-launch, AC-1/2/3/12/30).

The recorder replaces only the SDK's HTTP transport and the Google credentials; the client is built by
the production code path.
"""

import httpx
import pytest
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

from arp.config import Settings
from arp.llm import gemini_client
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.llm.gemini_client import GeminiClient

MODEL = "gemini-3.6-flash"


class Answer(BaseModel):
    ok: bool


@pytest.fixture
def vertex_recorder(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
        })

    real = genai.Client

    def client(**kw):
        if kw.get("vertexai"):
            kw["credentials"] = Credentials(token="test-token")  # stands in for application default credentials
        retry = kw["http_options"].retry_options
        kw["http_options"] = types.HttpOptions(retry_options=retry, async_client_args={"transport": httpx.MockTransport(handler)})
        return real(**kw)

    monkeypatch.setattr(gemini_client.genai, "Client", client)
    return seen


def vertex_settings(tmp_path, **kw):
    kw.setdefault("llm_model", MODEL)
    kw.setdefault("llm_verifier_model", MODEL)
    return Settings(_env_file=None, anthropic_api_key=None, gemini_use_vertex=True, gcp_project="p",
                    cache_dir=tmp_path, llm_cache_enabled=False, **{"gemini_api_key": None, **kw})


async def one_call(client):
    result, _ = await client.complete_structured(system="s", prompt="p", output_model=Answer)
    assert result.ok


def assert_vertex(request: httpx.Request):
    assert request.url.host.endswith("aiplatform.googleapis.com")
    assert "projects/p/locations/global" in request.url.path
    assert "x-goog-api-key" not in request.headers
    assert b"key=" not in request.url.query


async def test_vertex_request_goes_to_aiplatform(tmp_path, vertex_recorder):
    await one_call(build_llm_client(vertex_settings(tmp_path)))
    assert len(vertex_recorder) == 1
    assert_vertex(vertex_recorder[0])


async def test_vertex_verifier_client(tmp_path, vertex_recorder):
    await one_call(build_verifier_llm_client(vertex_settings(tmp_path)))
    assert_vertex(vertex_recorder[0])


async def test_vertex_ignores_api_key(tmp_path, vertex_recorder):
    await one_call(build_llm_client(vertex_settings(tmp_path, gemini_api_key="k")))
    assert_vertex(vertex_recorder[0])


async def test_api_key_mode_unchanged(tmp_path, vertex_recorder):
    settings = Settings(_env_file=None, anthropic_api_key=None, gemini_api_key="k", llm_model=MODEL,
                        cache_dir=tmp_path, llm_cache_enabled=False)
    await one_call(build_llm_client(settings))
    assert [r.url.host for r in vertex_recorder] == ["generativelanguage.googleapis.com"]
    assert vertex_recorder[0].headers["x-goog-api-key"] == "k"


@pytest.mark.parametrize("project", [None, ""])
def test_vertex_without_project_fails(tmp_path, project):
    with pytest.raises(ValueError, match="ARP_GCP_PROJECT"):
        Settings(_env_file=None, gemini_use_vertex=True, gcp_project=project, cache_dir=tmp_path)


def test_vertex_replaces_claude_model_without_anthropic_key(tmp_path):
    client = build_llm_client(vertex_settings(tmp_path, llm_model="claude-sonnet-5-5"))
    assert isinstance(client, GeminiClient)
    assert client.fallback_from == "claude-sonnet-5-5"


def test_vertex_with_standins_rejected(tmp_path):
    with pytest.raises(ValueError, match="ARP_STANDINS_DIR"):
        Settings(_env_file=None, gemini_use_vertex=True, gcp_project="p", standins_dir=tmp_path, cache_dir=tmp_path)
