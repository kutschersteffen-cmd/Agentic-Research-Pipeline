"""Host-side process and sandbox lifecycle for the opt-in CLI."""

from __future__ import annotations

import json
import math
import os
import re
import selectors
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

MAX_SCRIPT_CHARS = 8_000
MAX_JSON_BYTES = 16_384
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
_COMMAND_OUTPUT_LIMIT = 1024 * 1024
_JOB_ERRORS = {
    "CALL_LIMIT",
    "DEADLINE_EXCEEDED",
    "INVALID_RESULT",
    "INVALID_ARGUMENTS",
    "OUTPUT_LIMIT",
    "SCRIPT_FAILED",
    "TOOL_DENIED",
    "UNKNOWN_TOOL",
}


class RunFailure(Exception):
    """An externally reportable failure with no subprocess or credential text."""


def remaining(deadline: float) -> float:
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise RunFailure("DEADLINE_EXCEEDED")
    return budget


def bounded_run(
    command: list[str], deadline: float, *, data: bytes = b"", error: str = "RUNTIME_FAILED"
) -> bytes:
    """Collect bounded stdout, discard untrusted stderr, and reap the wrapper."""
    remaining(deadline)
    with tempfile.TemporaryFile() as stdin:
        stdin.write(data)
        stdin.seek(0)
        try:
            process = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise RunFailure(error) from exc
        assert process.stdout is not None
        output = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if not selector.select(remaining(deadline)):
                        raise RunFailure("DEADLINE_EXCEEDED")
                    chunk = os.read(process.stdout.fileno(), 65_536)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > _COMMAND_OUTPUT_LIMIT:
                        raise RunFailure("OUTPUT_LIMIT")
            if process.wait(timeout=remaining(deadline)):
                raise RunFailure(error)
        except subprocess.TimeoutExpired as exc:
            raise RunFailure("DEADLINE_EXCEEDED") from exc
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
    return bytes(output)


def decode_object(raw: bytes) -> dict:
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RunFailure("INVALID_RESULT") from exc
    if not isinstance(result, dict):
        raise RunFailure("INVALID_RESULT")
    return result


def image_and_policy(kind: str) -> tuple[str, Path]:
    prefix = f"ARP_OPENSHELL_{kind.upper()}"
    image = os.environ.get(f"{prefix}_IMAGE", "")
    policy_value = os.environ.get(f"{prefix}_POLICY")
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image) or not policy_value:
        raise RunFailure("OPENSHELL_UNAVAILABLE")
    policy = Path(policy_value).expanduser().resolve()
    if not policy.is_file():
        raise RunFailure("OPENSHELL_UNAVAILABLE")
    return image, policy


def gateway_url() -> str:
    url = os.environ.get("ARP_OPENSHELL_TOOL_GATEWAY_URL") or os.environ.get("ARP_CODE_MODE_TOOL_GATEWAY_URL", "")
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path != "/tool"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
    except ValueError as exc:
        raise RunFailure("OPENSHELL_UNAVAILABLE") from exc
    return url


class OpenShell:
    def __init__(self) -> None:
        executable = shutil.which("openshell")
        if not executable:
            raise RunFailure("OPENSHELL_UNAVAILABLE")
        self.executable = executable
        try:
            self.command("sandbox", "list", "--output", "json", deadline=time.monotonic() + 5)
        except RunFailure as exc:
            raise RunFailure("OPENSHELL_UNAVAILABLE") from exc

    def command(self, *args: str, deadline: float) -> bytes:
        return bounded_run([self.executable, *args], deadline)

    def _validate_policy(self, name: str, kind: str, deadline: float) -> None:
        import yaml

        raw = self.command("sandbox", "get", name, "--policy-only", deadline=deadline)
        try:
            policy = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise RunFailure("POLICY_MISMATCH") from exc
        if not isinstance(policy, dict) or policy.get("network_middlewares"):
            raise RunFailure("POLICY_MISMATCH")
        network = policy.get("network_policies") or {}
        if not isinstance(network, dict):
            raise RunFailure("POLICY_MISMATCH")
        if kind == "python":
            paths = policy.get("filesystem_policy") or {}
            if not isinstance(paths, dict):
                raise RunFailure("POLICY_MISMATCH")
            readable, writable = paths.get("read_only", []), paths.get("read_write", [])
            if (
                network or not isinstance(readable, list) or "/inputs" not in readable
                or not isinstance(writable, list)
                or any(
                    not isinstance(path, str) or path.rstrip("/") in ("", "/inputs") or path.startswith("/inputs/")
                    for path in writable
                )
            ):
                raise RunFailure("POLICY_MISMATCH")
            return
        if len(network) != 1:
            raise RunFailure("POLICY_MISMATCH")
        rule = next(iter(network.values()))
        if not isinstance(rule, dict):
            raise RunFailure("POLICY_MISMATCH")
        endpoints, binaries = rule.get("endpoints", []), rule.get("binaries", [])
        expected = urlsplit(gateway_url())
        if not isinstance(endpoints, list) or len(endpoints) != 1 or binaries != [{"path": "/usr/local/bin/node"}]:
            raise RunFailure("POLICY_MISMATCH")
        endpoint = endpoints[0]
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("host") != expected.hostname or endpoint.get("port") != (expected.port or 443)
            or endpoint.get("protocol") != "rest" or endpoint.get("access")
            or endpoint.get("enforcement") != "enforce" or endpoint.get("tls") == "skip"
            or endpoint.get("rules") != [{"allow": {"method": "POST", "path": "/tool"}}]
        ):
            raise RunFailure("POLICY_MISMATCH")

    def _delete(self, name: str) -> None:
        deadline = time.monotonic() + 15
        acknowledged = False
        while remaining(deadline):
            attempt = min(deadline, time.monotonic() + 3)
            if not acknowledged:
                try:
                    self.command("sandbox", "delete", name, deadline=attempt)
                except RunFailure:
                    pass
                else:
                    acknowledged = True
            if acknowledged:
                try:
                    raw = self.command(
                        "sandbox", "list", "--output", "json", deadline=min(deadline, time.monotonic() + 3),
                    )
                    listed = json.loads(raw)
                    rows = listed.get("sandboxes") if isinstance(listed, dict) else listed
                    has_more = isinstance(listed, dict) and bool(listed.get("next_page_token"))
                    if (
                        not has_more and isinstance(rows, list)
                        and all(isinstance(row, dict) and isinstance(row.get("name"), str) for row in rows)
                        and not any(row["name"] == name for row in rows)
                    ):
                        return
                except (ValueError, RunFailure):
                    pass
            time.sleep(min(0.25, remaining(deadline)))

    @contextmanager
    def sandbox(self, run_id: str, kind: str, records: list[dict], deadline: float) -> Iterator[str]:
        image, policy = image_and_policy(kind)
        name = f"arp-{run_id}-{kind}"
        record = {"id": name, "job": kind, "image_digest": image.rsplit("@", 1)[1], "cleanup": "failed"}
        records.append(record)
        had_error = True
        try:
            self.command(
                "sandbox", "create", "--name", name, "--from", image, "--policy", str(policy),
                "--detach", deadline=deadline,
            )
            self._validate_policy(name, kind, deadline)
            yield name
            had_error = False
        finally:
            try:
                self._delete(name)
            except RunFailure:
                if not had_error:
                    raise RunFailure("CLEANUP_FAILED") from None
            else:
                record["cleanup"] = "deleted"

    def upload(self, name: str, local: Path, remote: str, deadline: float) -> None:
        self.command("sandbox", "upload", name, str(local), remote, "--no-git-ignore", deadline=deadline)

    def exec(self, name: str, *args: str, deadline: float) -> bytes:
        return self.command(
            "sandbox", "exec", "--name", name, "--timeout", str(math.ceil(remaining(deadline))),
            "--no-login-shell", "--no-tty", "--", *args, deadline=deadline,
        )

    def download(self, name: str, remote: str, local: Path, deadline: float) -> None:
        self.command("sandbox", "download", name, remote, str(local), deadline=deadline)


class ToolGateway:
    """Node gateway owns the registered tools and its trace."""

    def __init__(self, entry: Path, settings: dict, deadline: float) -> None:
        self.entry, self.settings, self.deadline = entry, settings, deadline

    def __enter__(self) -> ToolGateway:
        try:
            self.process = subprocess.Popen(
                ["node", str(self.entry), "gateway"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as exc:
            raise RunFailure("NODE_UNAVAILABLE") from exc
        try:
            ready = self.exchange(self.settings, self.deadline)
            if not isinstance(ready.get("port"), int) or not 1 <= ready["port"] <= 65_535:
                raise RunFailure("GATEWAY_FAILED")
        except BaseException:
            self.__exit__()
            raise
        self.port = ready["port"]
        return self

    def exchange(self, obj: dict, deadline: float) -> dict:
        assert self.process.stdin is not None and self.process.stdout is not None
        try:
            self.process.stdin.write(json.dumps(obj).encode() + b"\n")
        except OSError as exc:
            raise RunFailure("GATEWAY_FAILED") from exc
        response = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                if not selector.select(remaining(deadline)):
                    raise RunFailure("DEADLINE_EXCEEDED")
                chunk = os.read(self.process.stdout.fileno(), 65_536)
                if not chunk:
                    raise RunFailure("GATEWAY_FAILED")
                response.extend(chunk)
                if len(response) > _COMMAND_OUTPUT_LIMIT:
                    raise RunFailure("OUTPUT_LIMIT")
                if b"\n" in response:
                    return decode_object(bytes(response))

    def trace(self, deadline: float) -> dict:
        result = self.exchange({"command": "trace"}, deadline)
        calls = result.get("calls")
        if not isinstance(calls, list) or any(not isinstance(row, dict) for row in calls):
            raise RunFailure("INVALID_RESULT")
        return result

    def __exit__(self, *_: object) -> None:
        assert self.process.stdin is not None and self.process.stdout is not None
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        finally:
            self.process.stdin.close()
            self.process.stdout.close()


def result_or_raise(outcome: dict) -> object:
    code = outcome.get("error_code")
    if code is not None:
        raise RunFailure(code if isinstance(code, str) and code in _JOB_ERRORS else "SCRIPT_FAILED")
    if "result" not in outcome:
        raise RunFailure("INVALID_RESULT")
    result = outcome["result"]
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_JSON_BYTES:
        raise RunFailure("OUTPUT_LIMIT")
    return result
