"""Run the prototype from an ARP source checkout with python -m."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from .runtime import (
    MAX_ARTIFACT_BYTES,
    MAX_SCRIPT_CHARS,
    OpenShell,
    RunFailure,
    ToolGateway,
    bounded_run,
    decode_object,
    gateway_url,
    image_and_policy,
    result_or_raise,
)

_ENTRY = Path(__file__).resolve().parents[4] / "scripts" / "openshell-code-mode" / "host.mjs"
SandboxCheck = Callable[[OpenShell, str, float], None]
_BENCHMARK_RECEIPT_KEYS = ("tool", "args", "status", "source")
_VOTING_QUESTION = (
    "Analyze 60,000 proxy votes. Which sectors had the highest opposition, "
    "and does the ranking change if every issuer gets equal weight?"
)
_VOTING_SCRIPT = """async () => {
  const [snapshot] = await codemode.listVotingSnapshots({});
  const {sectors} = await codemode.aggregateVotesBySector({snapshot_id: snapshot.snapshot_id});
  return {snapshot_id: snapshot.snapshot_id, sectors};
}
"""


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(dest: Path, value: object) -> None:
    dest.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _node(mode: str, payload: dict | None = None) -> dict:
    return decode_object(
        bounded_run(
            ["node", str(_ENTRY), mode],
            time.monotonic() + 15,
            data=_json_bytes(payload) if payload is not None else b"",
            error="NODE_RUNTIME_FAILED",
        )
    )


def _normalize(calls: list[dict]) -> list[dict]:
    try:
        values = [{key: row[key] for key in _BENCHMARK_RECEIPT_KEYS} for row in calls]
        if len(values) >= 2 and all(row["tool"] == "listSectorIssuers" for row in values[2:]):
            values[2:] = sorted(values[2:], key=lambda row: row["args"]["sector"])
        return values
    except (KeyError, TypeError) as exc:
        raise RunFailure("INVALID_RESULT") from exc


def _gateway_bind() -> tuple[str, int]:
    host = os.environ.get("ARP_OPENSHELL_TOOL_GATEWAY_BIND_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("ARP_OPENSHELL_TOOL_GATEWAY_BIND_PORT", "8788"))
        if not 1 <= port <= 65_535:
            raise ValueError
    except ValueError as exc:
        raise RunFailure("OPENSHELL_UNAVAILABLE") from exc
    return host, port


def _run_javascript(
    engine: OpenShell,
    manifest: dict,
    code: str,
    tools: list[str],
    scratch: Path,
    *,
    voting: dict | None = None,
    sandbox_check: SandboxCheck | None = None,
) -> object:
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_SCRIPT_CHARS:
        raise RunFailure("INVALID_SCRIPT")
    manifest["javascript_sha256"] = _hash(code.encode())
    endpoint = gateway_url()
    bind_host, bind_port = _gateway_bind()
    run_id = manifest["run_id"]
    token = secrets.token_urlsafe(32)
    deadline = time.monotonic() + 30
    settings = {
        "run_id": run_id,
        "token": token,
        "expires_at_ms": int((time.time() + 30) * 1_000),
        "listen_host": bind_host,
        "listen_port": bind_port,
        "voting": voting,
    }
    if voting is None:
        del settings["voting"]
    job = scratch / "job.json"
    descriptor = os.open(job, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(
            _json_bytes({"code": code, "gateway_url": endpoint, "run_id": run_id, "token": token, "tools": tools})
        )
    with ToolGateway(_ENTRY, settings, deadline) as gateway:
        if gateway.port != bind_port:
            raise RunFailure("GATEWAY_FAILED")
        try:
            with engine.sandbox(run_id, "javascript", manifest["sandboxes"], deadline) as name:
                engine.upload(name, job, "/workspace/job.json", deadline)
                raw = engine.exec(
                    name, "node", "/opt/arp-code-mode/sandbox.mjs", "/workspace/job.json",
                    deadline=deadline,
                )
                if token.encode() in raw:
                    raise RunFailure("INVALID_RESULT")
                outcome = decode_object(raw)
                if sandbox_check is not None:
                    sandbox_check(engine, name, deadline)
        except RunFailure:
            with suppress(RunFailure):
                manifest["tool_receipts"] = gateway.trace(time.monotonic() + 2)["calls"]
            raise
        trace = gateway.trace(time.monotonic() + 2)
        manifest["tool_receipts"] = trace["calls"]
        if trace.get("error_code"):
            result_or_raise(trace)
    return result_or_raise(outcome)


def _benchmark(engine: OpenShell, manifest: dict, scratch: Path, output: Path) -> None:
    fixture = _node("benchmark-fixture")
    code = fixture["code"]
    manifest["snapshot_id"] = fixture["snapshot_id"]
    manifest["snapshot_sha256"] = fixture["snapshot_sha256"]
    reference = _node("dynamic", {"code": code})
    actual = _run_javascript(engine, manifest, code, fixture["tools"], scratch)
    expected_result = result_or_raise(reference)
    report = {
        "dynamic_worker": {
            "result": expected_result,
            "normalized_tool_receipts": _normalize(reference["calls"]),
        },
        "openshell": {
            "result": actual,
            "normalized_tool_receipts": _normalize(manifest["tool_receipts"]),
        },
    }
    _write_json(output / "benchmark.json", report)
    if report["dynamic_worker"] != report["openshell"]:
        raise RunFailure("RUNTIME_MISMATCH")
    (output / "code.js").write_bytes(code.encode())


async def _generate_voting_script(manifest: dict, typescript: str) -> str:
    from pydantic import BaseModel, Field

    from arp.config import get_settings
    from arp.llm.factory import build_llm_client

    class GeneratedScript(BaseModel):
        code: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS)

    settings = get_settings()
    configured = settings.llm_model
    manifest["configured_model_id"] = configured
    if "llm_model" not in settings.model_fields_set or settings.standins_dir is not None:
        raise RunFailure("MODEL_PROVENANCE_MISMATCH")
    overrides = {"llm_cache_enabled": False, "llm_batch": False}
    if not configured.startswith("gemini-"):
        overrides.update(gemini_api_key=None, gemini_use_vertex=False)
    try:
        client = build_llm_client(settings.model_copy(update=overrides), cache_refresh=True)
        out, usage = await asyncio.wait_for(
            client.complete_structured(
                system=(
                    "Write one async JavaScript arrow function. Call each supplied tool once in the order shown. "
                    "Return only an object with snapshot_id and sectors. Preserve every returned sector and its exact "
                    "counts, in the order returned by the aggregate tool. A later approved Python job computes "
                    "issuer weighting. Here are the registered tools:\n" + typescript
                ),
                prompt=_VOTING_QUESTION,
                output_model=GeneratedScript,
                max_tokens=1_024,
            ),
            timeout=30,
        )
    except Exception as exc:
        raise RunFailure("MODEL_FAILED") from exc
    manifest.update(model_id=usage.model, model_cached=usage.cached, model_fallback_from=usage.fallback_from)
    if not configured or usage.cached or usage.fallback_from or usage.model != configured:
        raise RunFailure("MODEL_PROVENANCE_MISMATCH")
    return out.code


def _check_voting_result(result: object, receipts: list[dict], expected: dict) -> None:
    keys = [(row.get("tool"), row.get("args"), row.get("status")) for row in receipts]
    if keys != [
        ("listVotingSnapshots", {}, "ok"),
        ("aggregateVotesBySector", {"snapshot_id": expected["snapshot_id"]}, "ok"),
    ] or result != expected or receipts[1].get("result") != expected:
        raise RunFailure("INVALID_RESULT")


def _run_python(
    engine: OpenShell, manifest: dict, snapshot: Path, scratch: Path, minimum: int,
    *, sandbox_check: SandboxCheck | None = None,
) -> list[Path]:
    deadline = time.monotonic() + 60
    outputs = [scratch / "ranking.csv", scratch / "ranking.png"]
    with engine.sandbox(manifest["run_id"], "python", manifest["sandboxes"], deadline) as name:
        engine.upload(name, snapshot, "/inputs/votes.parquet", deadline)
        code_digest = engine.exec(
            name, "/usr/local/bin/python", "-I", "-c",
            "from hashlib import sha256; from pathlib import Path; "
            "print(sha256(Path('/opt/arp-code-mode/analysis_job.py').read_bytes()).hexdigest())",
            deadline=deadline,
        )
        if code_digest.strip() != manifest["python_sha256"].encode():
            raise RunFailure("IMAGE_MISMATCH")
        engine.exec(
            name, "/usr/local/bin/python", "/opt/arp-code-mode/analysis_job.py",
            "--input", "/inputs/votes.parquet", "--output-dir", "/workspace",
            "--min-issuer-votes", str(minimum), deadline=deadline,
        )
        sizes = engine.exec(
            name, "/usr/local/bin/python", "-I", "-c",
            "from pathlib import Path; "
            "print(sum((Path('/workspace') / p).stat().st_size for p in ('ranking.csv', 'ranking.png')))",
            deadline=deadline,
        )
        try:
            total_size = int(sizes.strip())
        except ValueError as exc:
            raise RunFailure("INVALID_RESULT") from exc
        if total_size > MAX_ARTIFACT_BYTES:
            raise RunFailure("OUTPUT_LIMIT")
        for path in outputs:
            engine.download(name, f"/workspace/{path.name}", path, deadline)
        if any(path.is_symlink() or not path.is_file() for path in outputs):
            raise RunFailure("INVALID_RESULT")
        if sum(path.stat().st_size for path in outputs) > MAX_ARTIFACT_BYTES:
            raise RunFailure("OUTPUT_LIMIT")
        if sandbox_check is not None:
            sandbox_check(engine, name, deadline)
    return outputs


def _voting(engine: OpenShell, manifest: dict, scratch: Path, output: Path) -> None:
    from . import analysis_job
    from .voting_analysis import SNAPSHOT_ID, VotingFixture, validate_png

    minimum = manifest["min_issuer_votes"]
    if not 1 <= minimum <= 60_000:
        raise RunFailure("INVALID_ARGUMENT")
    image_and_policy("python")
    catalog = _node("voting-tools")
    code = _VOTING_SCRIPT
    if manifest["script_mode"] == "model":
        code = asyncio.run(_generate_voting_script(manifest, catalog["typescript"]))
    with VotingFixture() as fixture:
        expected = {
            "snapshot_id": SNAPSHOT_ID,
            "sectors": fixture.aggregate_votes_by_sector({"snapshot_id": SNAPSHOT_ID}),
        }
        result = _run_javascript(engine, manifest, code, catalog["tools"], scratch, voting=expected)
        _check_voting_result(result, manifest["tool_receipts"], expected)
        manifest["snapshot_id"] = SNAPSHOT_ID
        snapshot = scratch / "votes.parquet"
        fixture.stage_parquet(snapshot)
        manifest["snapshot_sha256"] = _hash(snapshot.read_bytes())
        manifest["python_sha256"] = _hash(Path(analysis_job.__file__).read_bytes())
        csv_path, png_path = _run_python(engine, manifest, snapshot, scratch, minimum)
        try:
            fixture.validate_csv(csv_path, minimum)
            validate_png(png_path)
        except (ValueError, OSError) as exc:
            raise RunFailure("INVALID_RESULT") from exc
    artifacts = [
        {"filename": path.name, "sha256": _hash(path.read_bytes())} for path in (csv_path, png_path)
    ]
    for path in (csv_path, png_path):
        path.replace(output / path.name)
    (output / "code.js").write_bytes(code.encode())
    manifest["artifacts"] = artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--executor", choices=["compare"], required=True)
    voting = commands.add_parser("voting")
    voting.add_argument("--script", choices=["fixed", "model"], required=True)
    voting.add_argument("--min-issuer-votes", type=int, default=1)
    for cmd in (benchmark, voting):
        cmd.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    is_benchmark = args.command == "benchmark"
    manifest = {
        "run_id": uuid.uuid4().hex,
        "status": "failed",
        "error_code": None,
        "executor": "compare" if is_benchmark else "openshell",
        "script_mode": "fixed" if is_benchmark else args.script,
        "configured_model_id": None,
        "model_id": None,
        "model_cached": None,
        "model_fallback_from": None,
        "snapshot_id": None,
        "snapshot_sha256": None,
        "javascript_sha256": None,
        "python_sha256": None,
        "min_issuer_votes": None if is_benchmark else args.min_issuer_votes,
        "tool_receipts": [],
        "artifacts": [],
        "sandboxes": [],
    }
    output = args.output_dir.expanduser().absolute()
    try:
        output.mkdir(mode=0o700, parents=True)
    except OSError:
        print(json.dumps({"run_id": manifest["run_id"], "status": "failed", "error_code": "OUTPUT_DIR_UNAVAILABLE"}))
        return 1
    try:
        if not is_benchmark and not 1 <= args.min_issuer_votes <= 60_000:
            raise RunFailure("INVALID_ARGUMENT")
        engine = OpenShell()
        with tempfile.TemporaryDirectory(prefix=".arp-staging-", dir=output) as scratch:
            execute = _benchmark if is_benchmark else _voting
            execute(engine, manifest, Path(scratch), output)
        manifest["status"] = "ok"
    except RunFailure as exc:
        manifest["error_code"] = str(exc)
    except KeyboardInterrupt:
        manifest["error_code"] = "INTERRUPTED"
    except (OSError, ValueError, ImportError, KeyError, TypeError):
        manifest["error_code"] = "PROTOTYPE_FAILED"
    if manifest["status"] == "failed":
        for name in ("ranking.csv", "ranking.png"):
            (output / name).unlink(missing_ok=True)
        manifest["artifacts"] = []
    _write_json(output / "run.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("run_id", "status", "error_code")}))
    return int(manifest["status"] != "ok")


if __name__ == "__main__":
    raise SystemExit(main())
