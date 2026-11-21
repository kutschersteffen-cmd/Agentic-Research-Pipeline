import json
import sys
import time
from pathlib import Path

import pytest

from arp.prototypes.openshell_code_mode import __main__ as cli
from arp.prototypes.openshell_code_mode import runtime
from arp.prototypes.openshell_code_mode.runtime import OpenShell, RunFailure

_IMAGE = "registry.example.test/arp/node@sha256:" + "a" * 64


def test_unavailable_gateway_writes_failure_manifest(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["prototype", "benchmark", "--executor", "compare", "--output-dir", str(out)])
    assert cli.main() == 1
    response = json.loads(capsys.readouterr().out)
    manifest = json.loads((out / "run.json").read_bytes())
    assert response["error_code"] == manifest["error_code"] == "OPENSHELL_UNAVAILABLE"
    assert response["run_id"] == manifest["run_id"]
    assert manifest["sandboxes"] == []


def test_timeout_still_deletes_sandbox(tmp_path, monkeypatch):
    policy = tmp_path / "policy.yaml"
    policy.write_text("version: 1\n")
    monkeypatch.setenv("ARP_OPENSHELL_JAVASCRIPT_IMAGE", _IMAGE)
    monkeypatch.setenv("ARP_OPENSHELL_JAVASCRIPT_POLICY", str(policy))
    calls = []
    engine = OpenShell.__new__(OpenShell)
    def command(*args, deadline):
        calls.append(args)
        return b'[{"name":"another-sandbox"}]' if args[:2] == ("sandbox", "list") else b""

    monkeypatch.setattr(engine, "command", command)
    monkeypatch.setattr(engine, "_validate_policy", lambda *_args: None)
    records = []
    with pytest.raises(RunFailure, match="^DEADLINE_EXCEEDED$"), engine.sandbox(
        "fixture", "javascript", records, time.monotonic() + 30
    ):
        raise RunFailure("DEADLINE_EXCEEDED")
    assert calls[0] == ("sandbox", "create", "--name", "arp-fixture-javascript", "--from", _IMAGE, "--policy", str(policy), "--detach")
    assert calls[1] == ("sandbox", "delete", "arp-fixture-javascript")
    assert calls[2] == ("sandbox", "list", "--output", "json")
    assert records == [{"id": "arp-fixture-javascript", "job": "javascript", "image_digest": "sha256:" + "a" * 64, "cleanup": "deleted"}]


@pytest.mark.parametrize("bytes_count", [1_048_577, 4_194_304])
def test_host_process_stdout_is_bounded(bytes_count):
    with pytest.raises(RunFailure, match="^OUTPUT_LIMIT$"):
        runtime.bounded_run(
            [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b'x' * {bytes_count})"],
            time.monotonic() + 3,
        )


def test_different_benchmark_result_publishes_comparison(tmp_path, monkeypatch):
    reference = {"result": {"identity": "baseline"}, "calls": []}
    fixture = {"code": "async () => 1", "snapshot_id": "fixture", "snapshot_sha256": "sha", "tools": []}
    monkeypatch.setattr(cli, "_node", lambda mode, *args: fixture if mode == "benchmark-fixture" else reference)

    def run(_engine, manifest, *_args):
        manifest["tool_receipts"] = []
        return {"identity": "other"}

    monkeypatch.setattr(cli, "_run_javascript", run)
    with pytest.raises(RunFailure, match="^RUNTIME_MISMATCH$"):
        cli._benchmark(object(), {}, tmp_path, tmp_path)
    assert json.loads((tmp_path / "benchmark.json").read_bytes()) == {
        "dynamic_worker": {"result": {"identity": "baseline"}, "normalized_tool_receipts": []},
        "openshell": {"result": {"identity": "other"}, "normalized_tool_receipts": []},
    }


def test_modified_voting_result_is_rejected():
    expected = {"snapshot_id": "synthetic-votes-v1", "sectors": [{"sector": "Utilities", "eligible_votes": 60, "against_votes": 20}]}
    receipts = [
        {"tool": "listVotingSnapshots", "args": {}, "status": "ok"},
        {"tool": "aggregateVotesBySector", "args": {"snapshot_id": "synthetic-votes-v1"}, "status": "ok", "result": expected},
    ]
    cli._check_voting_result(expected, receipts, expected)
    with pytest.raises(RunFailure, match="^INVALID_RESULT$"):
        cli._check_voting_result({**expected, "sectors": []}, receipts, expected)


def test_failed_run_clears_unpublished_artifacts(tmp_path, monkeypatch, capsys):
    output = tmp_path / "out"
    monkeypatch.setattr(cli, "OpenShell", lambda: object())
    monkeypatch.setattr(sys, "argv", ["prototype", "voting", "--script", "fixed", "--output-dir", str(output)])

    def fail(_engine, _manifest, _temp, requested_output):
        assert requested_output == output
        (output / "ranking.csv").write_text("partial")
        (output / "ranking.png").write_bytes(b"incomplete")
        raise RunFailure("INVALID_RESULT")

    monkeypatch.setattr(cli, "_voting", fail)
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "INVALID_RESULT"
    assert {entry.name for entry in output.iterdir()} == {"run.json"}


def test_fixed_voting_orchestration_publishes_exact_results(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    output = tmp_path / "out"
    monkeypatch.setattr(cli, "OpenShell", lambda: object())
    monkeypatch.setattr(cli, "image_and_policy", lambda kind: ("image", Path("policy")))
    monkeypatch.setattr(cli, "_node", lambda mode: {"tools": ["listVotingSnapshots", "aggregateVotesBySector"]})
    monkeypatch.setattr(sys, "argv", ["prototype", "voting", "--script", "fixed", "--output-dir", str(output)])

    def fake_javascript(_engine, manifest, _script, _tools, _stage, *, voting):
        manifest["tool_receipts"] = [
            {"tool": "listVotingSnapshots", "args": {}, "status": "ok"},
            {"tool": "aggregateVotesBySector", "args": {"snapshot_id": voting["snapshot_id"]}, "status": "ok", "result": voting},
        ]
        manifest["javascript_sha256"] = cli._hash(_script.encode())
        manifest["sandboxes"].append({"job": "javascript", "cleanup": "deleted"})
        return voting

    def local_analysis(_engine, manifest, snapshot, stage, minimum):
        from arp.prototypes.openshell_code_mode.analysis_job import main

        with monkeypatch.context() as scoped:
            scoped.setattr(sys, "argv", ["analysis", "--input", str(snapshot), "--output-dir", str(stage), "--min-issuer-votes", str(minimum)])
            main()
        manifest["sandboxes"].append({"job": "python", "cleanup": "deleted"})
        return [stage / "ranking.csv", stage / "ranking.png"]

    monkeypatch.setattr(cli, "_run_javascript", fake_javascript)
    monkeypatch.setattr(cli, "_run_python", local_analysis)
    assert cli.main() == 0
    manifest = json.loads((output / "run.json").read_bytes())
    assert manifest["script_mode"] == "fixed" and manifest["model_id"] is None
    assert manifest["snapshot_id"] == "synthetic-votes-v1"
    assert (output / "ranking.csv").read_text().splitlines()[1:] == [
        "Information Technology,33000,6000,2,18.1818,10.0000,1,2",
        "Financials,27000,3600,2,13.3333,13.3333,2,1",
    ]
    assert [item["filename"] for item in manifest["artifacts"]] == ["ranking.csv", "ranking.png"]


@pytest.mark.parametrize("mode", ["enforce", "audit"])
def test_effective_js_policy_requires_enforcement(monkeypatch, mode):
    monkeypatch.setenv("ARP_OPENSHELL_TOOL_GATEWAY_URL", "https://tools.example.test/tool")
    engine = OpenShell.__new__(OpenShell)
    policy = {
        "network_policies": {
            "tools": {
                "binaries": [{"path": "/usr/local/bin/node"}],
                "endpoints": [{
                    "host": "tools.example.test", "port": 443, "protocol": "rest",
                    "enforcement": mode, "rules": [{"allow": {"method": "POST", "path": "/tool"}}],
                }],
            },
        },
    }
    monkeypatch.setattr(engine, "command", lambda *_args, **_kw: json.dumps(policy).encode())
    if mode == "enforce":
        engine._validate_policy("fixture", "javascript", time.monotonic() + 1)
    else:
        with pytest.raises(RunFailure, match="^POLICY_MISMATCH$"):
            engine._validate_policy("fixture", "javascript", time.monotonic() + 1)


def test_cleanup_waits_for_sandbox_to_disappear(monkeypatch):
    engine = OpenShell.__new__(OpenShell)
    samples = iter([b'[{"id":"missing-name"}]', b'[{"name":"fixture"}]', b'[]'])
    calls = []

    def command(*args, deadline):
        calls.append(args[:2])
        return next(samples) if args[:2] == ("sandbox", "list") else b""

    monkeypatch.setattr(engine, "command", command)
    monkeypatch.setattr(runtime.time, "sleep", lambda _: None)
    engine._delete("fixture")
    assert calls == [("sandbox", "delete"), ("sandbox", "list"), ("sandbox", "list"), ("sandbox", "list")]
