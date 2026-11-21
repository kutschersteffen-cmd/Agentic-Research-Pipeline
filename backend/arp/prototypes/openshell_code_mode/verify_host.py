"""Collect independent prototype evidence from a configured OpenShell host."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from .__main__ import _ENTRY, _hash, _node, _normalize, _run_javascript, _run_python, _write_json
from .runtime import OpenShell, RunFailure, ToolGateway, bounded_run, decode_object, image_and_policy, result_or_raise

_EXPECTED_CSV = (
    "sector,eligible_votes,against_votes,included_issuers,vote_weighted_pct,issuer_weighted_pct,vote_rank,issuer_rank",
    "Information Technology,33000,6000,2,18.1818,10.0000,1,2",
    "Financials,27000,3600,2,13.3333,13.3333,2,1",
)
_SLICE_ROWS = {
    1: (1, 2, 3, 4, 5, 14, 16, 17, 18, 26),
    2: (6, 8, 9, 10, 21, 22, 23, 24, 29, 30, 32),
}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Observed output differs from the specification")


def _record(results: dict, rows: tuple[int, ...], operation) -> None:
    try:
        operation()
    except (OSError, ValueError, KeyError, RunFailure, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, RunFailure) else "Evidence check failed"
        for row in rows:
            results[f"AC-{row}"] = {"status": "fail", "reason": reason}
    else:
        for row in rows:
            results[f"AC-{row}"] = {"status": "pass"}


def _fixed_benchmark(engine: OpenShell, evidence: Path, results: dict) -> None:
    fixture = _node("benchmark-fixture")
    baseline = _node("dynamic", {"code": fixture["code"]})
    expected = result_or_raise(baseline)
    normalized = _normalize(baseline["calls"])

    def check_baseline() -> None:
        sectors = [(item["sector"], item["weight_pct"], item["largest_issuer"]["issuer_id"]) for item in expected["top_sectors"]]
        _require(expected["constituents"] == 12 and expected["total_weight_pct"] == 7.24)
        _require(sectors == [("Information Technology", 3.1, "SYN03"), ("Financials", 1.4, "SYN07")])

    _record(results, (26,), check_baseline)

    output = evidence / "benchmark"

    def compare() -> None:
        _run_cli("benchmark", "--executor", "compare", output=output)

    _record(results, (1,), compare)

    def check_parity() -> None:
        note = decode_object((output / "benchmark.json").read_bytes())
        _require(note["dynamic_worker"]["result"] == note["openshell"]["result"] == expected)

    def check_trace() -> None:
        note = decode_object((output / "benchmark.json").read_bytes())
        _require(note["dynamic_worker"]["normalized_tool_receipts"] == note["openshell"]["normalized_tool_receipts"] == normalized)
        _require([row["tool"] for row in normalized] == [
            "listBenchmarks", "getBenchmarkSectors", "listSectorIssuers", "listSectorIssuers",
        ])

    _record(results, (14,), check_parity)
    _record(results, (2,), check_trace)

    def unknown_tool() -> None:
        manifest = {"run_id": uuid.uuid4().hex, "sandboxes": []}
        with tempfile.TemporaryDirectory() as work:
            try:
                _run_javascript(engine, manifest, "async () => codemode.unregistered({})", fixture["tools"], Path(work))
            except RunFailure as exc:
                _require(str(exc) == "UNKNOWN_TOOL")
                _require(not manifest["tool_receipts"])
            else:
                raise ValueError("Unregistered tool was accepted")

    _record(results, (3,), unknown_tool)


def _gateway_denials(results: dict) -> None:
    import urllib.error

    def check() -> None:
        token = "fixture-" + uuid.uuid4().hex
        for provided, run_id, scope, expired in (
            (None, "scope", "arp-synthetic-sample", False),
            ("wrong-token", "scope", "arp-synthetic-sample", False),
            (token, "other", "arp-synthetic-sample", False),
            (token, "scope", "other-snapshot", False),
            (token, "scope", "arp-synthetic-sample", True),
        ):
            settings = {
                "run_id": "scope", "token": token, "expires_at_ms": int((time.time() + (-1 if expired else 30)) * 1000),
                "listen_host": "127.0.0.1", "listen_port": 0,
            }
            with ToolGateway(_ENTRY, settings, time.monotonic() + 5) as gateway:
                headers = {"Content-Type": "application/json"}
                if provided is not None:
                    headers["Authorization"] = f"Bearer {provided}"
                req = Request(
                    f"http://127.0.0.1:{gateway.port}/tool",
                    data=json.dumps({"run_id": run_id, "tool": "getBenchmarkSectors", "args": {"benchmark_id": scope}}).encode(),
                    headers=headers,
                )
                try:
                    with urlopen(req, timeout=2):
                        raise ValueError("Gateway accepted a denied request")
                except urllib.error.HTTPError as exc:
                    with exc:
                        _require(exc.code == 403 and json.load(exc) == {"error_code": "TOOL_DENIED"})
                _require(not gateway.trace(time.monotonic() + 2)["calls"])

    _record(results, (4,), check)


_PYTHON_PROBE = """import hashlib, json, os, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
url, marker, *sentinel_hashes = sys.argv[1:]
present = any(hashlib.sha256(value.encode()).hexdigest() in sentinel_hashes for value in os.environ.values())
print('PROBE_STARTED', flush=True)
try:
    with urlopen(Request(url, headers={'X-ARP-Probe': marker}), timeout=3) as response:
        status = response.status
except HTTPError as exc:
    status = exc.code
except (URLError, OSError):
    status = None
print(json.dumps({'status': status, 'credentials_present': present}))
"""


def _isolation(engine: OpenShell, evidence: Path, results: dict, kind: str) -> None:
    base = os.environ.get("ARP_OPENSHELL_PROBE_URL")
    if not base:
        return
    url = base.rstrip("/") + "/probe"
    marker = uuid.uuid4().hex
    sentinels = [uuid.uuid4().hex for _ in range(3)]
    sentinel_hashes = [_hash(value.encode()) for value in sentinels]
    report: dict = {}

    def count(key: str) -> int:
        with urlopen(f"{base.rstrip('/')}/count?marker={key}", timeout=3) as response:
            return int(response.read(32))

    with tempfile.TemporaryDirectory() as work:
        scratch = Path(work)

        def probe(executor: OpenShell, name: str, deadline: float) -> None:
            with urlopen(Request(url, headers={"X-ARP-Probe": marker + "-control"}), timeout=3) as response:
                _require(response.status == 204)
            _require(count(marker + "-control") == 1)
            if kind == "javascript":
                path = scratch / "probe.json"
                _write_json(path, {"url": url, "marker": marker, "sentinel_hashes": sentinel_hashes})
                executor.upload(name, path, "/workspace/probe.json", deadline)
                raw = executor.exec(
                    name, "node", "/opt/arp-code-mode/sandbox-probe.mjs", "/workspace/probe.json", deadline=deadline
                )
            else:
                raw = executor.exec(
                    name, "/usr/local/bin/python", "-I", "-c", _PYTHON_PROBE, url, marker, *sentinel_hashes, deadline=deadline,
                )
            first, _, value = raw.partition(b"\n")
            _require(first == b"PROBE_STARTED")
            observation = decode_object(value)
            _require(not any(secret.encode() in raw for secret in sentinels))
            status, present = observation["status"], observation["credentials_present"]
            _require(status is None or isinstance(status, int))
            _require(isinstance(present, bool))
            report.update(status=status, credentials_present=present, control_count=1, outside_requests=count(marker))
            _write_json(evidence / f"{kind}-isolation.json", report)
            _require(status in (None, 403) and report["outside_requests"] == 0 and not present)

        def run() -> None:
            manifest = {"run_id": uuid.uuid4().hex, "sandboxes": []}
            with patch.dict(os.environ, {
                "ARP_ANTHROPIC_API_KEY": sentinels[0], "ARP_POSTGRES_DSN": sentinels[1],
                "ARP_OPENSHELL_CREDENTIAL_PROBE": sentinels[2],
            }):
                if kind == "javascript":
                    fixture = _node("benchmark-fixture")
                    with patch("arp.prototypes.openshell_code_mode.__main__.secrets.token_urlsafe", return_value=sentinels[2]):
                        result = _run_javascript(
                            engine, manifest, fixture["code"], fixture["tools"], scratch, sandbox_check=probe,
                        )
                    _require(result["constituents"] == 12)
                    _require(len(manifest["tool_receipts"]) == 4)
                else:
                    from . import analysis_job
                    from .voting_analysis import VotingFixture

                    snapshot = scratch / "votes.parquet"
                    manifest["python_sha256"] = _hash(Path(analysis_job.__file__).read_bytes())
                    with VotingFixture() as fixture:
                        fixture.stage_parquet(snapshot)
                    _run_python(engine, manifest, snapshot, scratch, 1, sandbox_check=probe)
            _require(not any(secret in json.dumps(manifest) for secret in sentinels))

        _record(results, (17, 18) if kind == "javascript" else (10, 32), run)


def _timeout(engine: OpenShell, kind: str, results: dict) -> None:
    rows = (5, 16) if kind == "javascript" else (21, 22)
    records: list[dict] = []

    def check_deadline() -> None:
        try:
            with engine.sandbox(uuid.uuid4().hex, kind, records, time.monotonic() + 30) as name:
                engine.exec(name, "/bin/sleep", "10", deadline=time.monotonic() + 1)
        except RunFailure as exc:
            _require(str(exc) == "DEADLINE_EXCEEDED")
        else:
            raise ValueError("Deadline did not stop the command")

    _record(results, rows[:1], check_deadline)

    def check_cleanup() -> None:
        _require(len(records) == 1 and records[0]["cleanup"] == "deleted")
        listed = json.loads(engine.command("sandbox", "list", "--output", "json", deadline=time.monotonic() + 10))
        _require(records[0]["id"] not in json.dumps(listed))

    _record(results, rows[1:], check_cleanup)


def _run_cli(*args: str, output: Path, env: dict | None = None) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "arp.prototypes.openshell_code_mode", *args, "--output-dir", str(output)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180, check=False, env=env,
    )
    _require(completed.returncode == 0)
    response = decode_object(completed.stdout)
    manifest = decode_object((output / "run.json").read_bytes())
    _require(response["status"] == manifest["status"] == "ok" and response["run_id"] == manifest["run_id"])
    return manifest


def _voting(engine: OpenShell, evidence: Path, results: dict) -> None:
    from . import analysis_job
    from .voting_analysis import VotingFixture, validate_png

    output = evidence / "fixed"
    env = {**os.environ, "ARP_ANTHROPIC_API_KEY": "", "ARP_GEMINI_API_KEY": "", "ARP_GEMINI_USE_VERTEX": "false"}
    _record(results, (6,), lambda: _run_cli("voting", "--script", "fixed", output=output, env=env))

    def check_csv(directory: Path) -> None:
        _require(tuple((directory / "ranking.csv").read_text().splitlines()) == _EXPECTED_CSV)

    def check_voting_manifest() -> None:
        manifest = decode_object((output / "run.json").read_bytes())
        _require(manifest["executor"] == "openshell" and manifest["script_mode"] == "fixed")
        _require(all(manifest[key] is None for key in ("model_id", "configured_model_id", "model_cached", "model_fallback_from")))
        _require(manifest["snapshot_id"] == "synthetic-votes-v1" and manifest["min_issuer_votes"] == 1)
        receipts = [(row["tool"], row["args"], row["status"]) for row in manifest["tool_receipts"]]
        _require(receipts == [
            ("listVotingSnapshots", {}, "ok"),
            ("aggregateVotesBySector", {"snapshot_id": "synthetic-votes-v1"}, "ok"),
        ])
        with tempfile.TemporaryDirectory() as tmp, VotingFixture() as fixture:
            snapshot = Path(tmp) / "votes.parquet"
            fixture.stage_parquet(snapshot)
            _require(manifest["snapshot_sha256"] == _hash(snapshot.read_bytes()))
        _require(manifest["python_sha256"] == _hash(Path(analysis_job.__file__).read_bytes()))
        _require(manifest["javascript_sha256"] == _hash((output / "code.js").read_bytes()))
        _require(manifest["artifacts"] == [
            {"filename": name, "sha256": _hash((output / name).read_bytes())}
            for name in ("ranking.csv", "ranking.png")
        ])

    def check_cleanup() -> None:
        manifest = decode_object((output / "run.json").read_bytes())
        records = manifest["sandboxes"]
        _require([row["job"] for row in records] == ["javascript", "python"])
        _require(all(row["cleanup"] == "deleted" for row in records))
        listed = engine.command("sandbox", "list", "--output", "json", deadline=time.monotonic() + 10)
        _require(all(row["id"].encode() not in listed for row in records))

    _record(results, (24,), lambda: check_csv(output))
    _record(results, (9,), check_voting_manifest)
    _record(results, (29,), check_cleanup)
    _record(results, (8,), lambda: validate_png(output / "ranking.png"))
    if results["AC-8"]["status"] == "pass":
        results["AC-8"] = {"status": "pending", "reason": "Inspect labels and series in fixed/ranking.png"}

    def check_model() -> None:
        model_output = evidence / "model"
        manifest = _run_cli("voting", "--script", "model", output=model_output)
        _require(manifest["script_mode"] == "model" and manifest["model_id"] == manifest["configured_model_id"])
        _require(manifest["model_cached"] is False and not manifest["model_fallback_from"])
        _require(manifest["javascript_sha256"] == _hash((model_output / "code.js").read_bytes()))
        check_csv(model_output)

    if os.environ.get("ARP_OPENSHELL_VERIFY_MODEL") == "1":
        _record(results, (30,), check_model)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", type=int, choices=(1, 2), required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(mode=0o700, parents=True)
    results = {f"AC-{row}": {"status": "pending", "reason": "Independent host probe required"} for row in _SLICE_ROWS[args.slice]}
    repo = _ENTRY.parents[2]
    sha = bounded_run(["git", "-C", str(repo), "rev-parse", "HEAD"], time.monotonic() + 5).decode().strip()
    report = {"candidate_sha": sha, "slice": args.slice, "checks": results}
    try:
        engine = OpenShell()
        report["openshell_version"] = engine.command("--version", deadline=time.monotonic() + 5).decode().strip()
        for kind in ("javascript",) if args.slice == 1 else ("javascript", "python"):
            image, _ = image_and_policy(kind)
            report[f"{kind}_image_digest"] = image.rsplit("@", 1)[1]
    except RunFailure as exc:
        report["blocked"] = str(exc)
    else:
        if args.slice == 1:
            with suppress(RunFailure):
                _fixed_benchmark(engine, evidence, results)
            _gateway_denials(results)
            _timeout(engine, "javascript", results)
            _isolation(engine, evidence, results, "javascript")
        else:
            _voting(engine, evidence, results)
            _timeout(engine, "python", results)
            _isolation(engine, evidence, results, "python")
    _write_json(evidence / "verification.json", report)
    print(json.dumps(report))
    return 0 if all(row["status"] == "pass" for row in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
