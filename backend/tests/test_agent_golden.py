"""The exploration golden runner and `arp agent golden` without a model or a sandbox (spec agent-panel-code-mode
AC-51). The real-model run is the golden-set workflow."""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest
from typer.testing import CliRunner

from arp.agent import golden
from arp.agent.explorations import _ts
from arp.config import Settings


def test_load_cases_skips_blank_lines(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"id": "a"}\n\n{"id": "b"}\n')
    assert golden.load_cases(path) == [{"id": "a"}, {"id": "b"}]


def test_a_model_error_fails_the_case(monkeypatch):
    import asyncio

    async def boom(*args, **kwargs):
        raise ValueError("no key")

    monkeypatch.setattr(golden, "run_question", boom)
    why = asyncio.run(golden.run_case(None, None, {"question": "q", "expected_capabilities": []}))
    assert why == "model call failed: ValueError: no key"


def test_tool_route_serves_the_sandbox_tools_from_this_process():
    with golden.tool_route() as origin:
        assert httpx.get(f"{origin}/health").json() == {"ok": True}
        res = httpx.post(f"{origin}/api/sandbox/tools/benchmark_sectors", json={})
        assert res.status_code == 401  # no execution token
    assert not golden._answers(origin)


def test_an_answering_sandbox_is_used_as_it_is(monkeypatch):
    monkeypatch.setattr(golden.subprocess, "Popen", lambda *a, **k: pytest.fail("started a second sandbox"))
    with golden.tool_route() as origin, golden.sandbox_service(Settings(sandbox_url=origin), "http://unused"):
        pass


def test_no_npm_and_no_sandbox_is_an_error(monkeypatch):
    monkeypatch.setattr(golden, "_answers", lambda url: False)
    monkeypatch.setattr(golden.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="npm is not installed"), \
            golden.sandbox_service(Settings(sandbox_url="http://127.0.0.1:9"), "http://api"):
        pass


def test_starts_the_sandbox_with_an_empty_environment(monkeypatch, tmp_path):
    ran, started = [], {}

    class Proc:
        def terminate(self):
            started["terminated"] = True

        def wait(self, timeout):
            return 0

    def popen(cmd, cwd, env, **kwargs):
        started.update(cmd=cmd, cwd=cwd, env=env)
        return Proc()

    monkeypatch.setattr(golden, "SANDBOX_DIR", tmp_path)
    monkeypatch.setattr(golden, "_answers", lambda url: False)
    monkeypatch.setattr(golden, "_wait", lambda url, what: None)
    monkeypatch.setattr(golden.shutil, "which", lambda name: "/bin/npm")
    monkeypatch.setattr(golden.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(golden.subprocess, "Popen", popen)
    monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", "secret")
    with golden.sandbox_service(Settings(sandbox_url="http://127.0.0.1:8799"), "http://127.0.0.1:5555"):
        assert started["cmd"] == ["node", "server.mjs"]
    assert ran == [["/bin/npm", "ci", "--no-audit", "--no-fund"], ["/bin/npm", "run", "build"]]  # no node_modules yet
    assert set(started["env"]) == {"PATH", "HOME", "ARP_API_URL", "ARP_SANDBOX_PORT"}
    assert (started["env"]["ARP_API_URL"], started["env"]["ARP_SANDBOX_PORT"]) == ("http://127.0.0.1:5555", "8799")
    assert started["terminated"]


def test_wait_gives_up(monkeypatch):
    monkeypatch.setattr(golden, "_answers", lambda url: False)
    with pytest.raises(RuntimeError, match="sandbox/ did not start at http://x"):
        golden._wait("http://x", "sandbox/", seconds=0)


@pytest.mark.parametrize(("fails", "code"), [(2, 0), (3, 1)])
def test_cli_prints_each_case_and_gates_on_min_pass(monkeypatch, tmp_path, fails, code):
    from arp.cli import agent as cli
    from arp.llm import factory

    cases = tmp_path / "explore.jsonl"
    cases.write_text("\n".join(json.dumps({"id": f"c{i}", "question": f"q{i}", "expected_capabilities": []})
                               for i in range(10)))

    @contextmanager
    def nothing(*args):
        yield "http://tools"

    async def run_case(settings, llm, case):
        return "did not call x" if int(case["id"][1:]) < fails else None

    monkeypatch.setattr(factory, "build_llm_client", lambda settings: object())
    monkeypatch.setattr(golden, "tool_route", nothing)
    monkeypatch.setattr(golden, "sandbox_service", nothing)
    monkeypatch.setattr(golden, "run_case", run_case)
    out = CliRunner().invoke(cli.agent_app, ["golden", "--cases", str(cases), "--min-pass", "8"])
    assert out.exit_code == code, out.output
    assert "c0: fail: did not call x" in out.output
    assert "c9: pass" in out.output
    assert f"explore golden: {10 - fails}/10 passed (min 8)" in out.output


def test_ts_writes_enums_and_constants():
    assert _ts({"enum": ["a", 1]}, {}) == '"a" | 1'
    assert _ts({"const": "x"}, {}) == '"x"'
    assert _ts({"const": 2}, {}) == "2"
    assert _ts({"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}}, {}) == "(string | null)[]"
    assert _ts({"type": "object"}, {}) == "Record<string, unknown>"
