#!/usr/bin/env python3
"""Advisory evidence evaluator and single-coordinator execution ledger. No network calls."""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

BUDGET = 900
GATES = ("merge", "release", "done")
CONTROLS = {
    "merge": ("V1", "V2", "V3", "V4", "V5", "V7"),
    "release": ("V8",),
    "done": ("V6",),
}
CHECKS = {
    "merge": ("ci", "holdout", "mutation", "independent_review"),
    "release": ("integrated_regression", "recovery_readiness"),
    "done": ("production_smoke",),
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("expected a finite non-negative number")
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise ValueError("expected a full lowercase commit SHA")
    return value


def new_run(task, candidate_sha, spec_sha, implementer, rows, *, now=None, spent_seconds=0):
    if not task.strip() or not implementer.strip() or not rows or len(rows) != len(set(rows)):
        raise ValueError("task, implementer and unique acceptance rows are required")
    if any(not re.fullmatch(r"AC-[1-9][0-9]*", row) for row in rows):
        raise ValueError("acceptance IDs must be AC-1, AC-2, ...")
    now = _number(time.time() if now is None else now)
    spent_seconds = _number(spent_seconds)
    return {"schema_version": 1, "task": task, "candidate_sha": _sha(candidate_sha),
            "spec_sha": _sha(spec_sha), "implementer": implementer, "rows": list(rows),
            "budget_seconds": BUDGET, "used_seconds": spent_seconds, "last_at": now,
            "mode": "blocked" if spent_seconds >= BUDGET else "running", "workers": [],
            "waits": [], "wait_since": None, "wait_reason": None}


def checkpoint(run, *, now=None):
    """Return a snapshot without mutating input. Parallel workers share one clock."""
    out = copy.deepcopy(run)
    if out.get("schema_version") != 1 or out.get("budget_seconds") != BUDGET:
        raise ValueError("unsupported ledger or altered 900-second budget")
    now = _number(time.time() if now is None else now)
    last = _number(out["last_at"])
    used = _number(out["used_seconds"])
    if now < last:
        raise ValueError("clock moved backwards; reconcile the ledger before continuing")
    if out["mode"] not in ("running", "waiting", "blocked"):
        raise ValueError("invalid clock mode")
    if out["mode"] == "running":
        used += now - last
    out.update(used_seconds=used, last_at=now)
    if used >= BUDGET:
        out["mode"] = "blocked"
    return out


def transition(run, action, *, now=None, reason=None, worker=None):
    out = checkpoint(run, now=now)
    if action == "worker-end":
        if worker not in out["workers"]:
            raise ValueError("unknown worker")
        out["workers"].remove(worker)
        return out
    if out["mode"] == "blocked":
        raise ValueError("execution budget exhausted; no reset or resume")
    if action == "pause":
        if out["mode"] != "running" or out["workers"]:
            raise ValueError("pause requires running coordinator and no registered workers")
        if reason not in ("owner-approval", "human-testing", "infrastructure"):
            raise ValueError("use an explicit owner-approval, human-testing or infrastructure wait")
        out.update(mode="waiting", wait_since=out["last_at"], wait_reason=reason)
    elif action == "resume":
        if out["mode"] != "waiting":
            raise ValueError("only a waiting ledger can resume")
        out["waits"].append({"reason": out["wait_reason"], "seconds": out["last_at"] - out["wait_since"]})
        out.update(mode="running", wait_since=None, wait_reason=None)
    elif action == "worker-start":
        if out["mode"] != "running" or not worker or worker in out["workers"]:
            raise ValueError("worker must be unique and the coordinator must be running")
        out["workers"].append(worker)
    else:
        raise ValueError("unknown transition")
    return out


def evaluate_run(run, evidence, *, gate="merge", now=None):
    """Pure function: validate supplied evidence structure, never authenticate external claims."""
    if gate not in GATES:
        raise ValueError("gate must be merge, release or done")
    state = checkpoint(run, now=now)
    errors = []
    if state["mode"] == "blocked":
        errors.append("execution budget exhausted")
    if state["mode"] == "waiting":
        errors.append("execution is paused; complete the recorded wait before evaluating a gate")
    if state["workers"]:
        errors.append("registered workers are unfinished")
    if evidence.get("candidate_sha") != state["candidate_sha"] or evidence.get("spec_sha") != state["spec_sha"]:
        errors.append("candidate or specification evidence is stale")
    try:
        _sha(evidence.get("test_sha"))
    except ValueError:
        errors.append("full test revision SHA is missing or invalid")

    def approval(name, subject):
        item = evidence.get(name, {})
        if not isinstance(item, dict) or not (item.get("subject_sha") == subject
                and item.get("actor") and item.get("actor") != state["implementer"] and item.get("source")):
            errors.append(f"{name}: missing subject-bound owner approval reference")

    approval("approval_a", state["spec_sha"])

    def result(name, item, *, independent=False):
        if not isinstance(item, dict):
            errors.append(f"{name}: missing result")
            return
        if item.get("candidate_sha") != state["candidate_sha"] or item.get("spec_sha") != state["spec_sha"]:
            errors.append(f"{name}: stale candidate/spec")
        if not item.get("source") or not item.get("actor"):
            errors.append(f"{name}: missing evidence source/actor")
        if independent and item.get("actor") == state["implementer"]:
            errors.append(f"{name}: verifier must differ from implementer")
        if item.get("result") == "not_applicable":
            if not item.get("reason") or not independent or item.get("actor") == state["implementer"]:
                errors.append(f"{name}: unjustified not-applicable result")
        elif item.get("result") != "pass":
            errors.append(f"{name}: not passed")

    rows = evidence.get("acceptance", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        errors.append("acceptance results must be a list of objects")
        rows = []
    ids = [row.get("id") for row in rows]
    if sorted(str(i) for i in ids) != sorted(state["rows"]):
        errors.append("acceptance manifest missing, duplicated or unexpected rows")
    for row in rows:
        result(str(row.get("id")), row, independent=True)
    for stage in GATES[:GATES.index(gate) + 1]:
        for control in CONTROLS[stage]:
            result(control, evidence.get("controls", {}).get(control), independent=True)
        for check in CHECKS[stage]:
            result(check, evidence.get("checks", {}).get(check), independent=True)
    if gate in ("release", "done") and not evidence.get("environment"):
        errors.append("release environment is missing")
    if gate == "done":
        approval("approval_b", state["candidate_sha"])
        if evidence.get("approval_b", {}).get("environment") != evidence.get("environment"):
            errors.append("release approval does not match environment")
    return {"gate": gate, "outcome": "blocked" if errors else "advisory-ready",
            "deployment_authorized": False,
            "execution_used_seconds": state["used_seconds"],
            "execution_remaining_seconds": max(0, BUDGET - state["used_seconds"]),
            "reserve_cleanup": state["used_seconds"] >= 840, "waits": state["waits"],
            "limitations": "Local records are untrusted: verify approval authority, provenance and CI externally. No merge/deploy authorization is granted.",
            "blockers": errors}


@contextlib.contextmanager
def ledger(path):
    """Fail fast on concurrent writers; retain a crashed lock for explicit reconciliation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("ledger locked; reconcile active/crashed writer, do not overwrite") from None
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def save(path, state):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".engineering-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "status", "pause", "resume", "worker-start", "worker-end", "check"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--spec-sha")
    parser.add_argument("--implementer")
    parser.add_argument("--rows", nargs="+")
    parser.add_argument("--spent-seconds", type=float, default=0)
    parser.add_argument("--reason")
    parser.add_argument("--worker")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--gate", choices=GATES, default="merge")
    args = parser.parse_args(argv)
    try:
        with ledger(args.state):
            if args.action == "init":
                if args.state.exists():
                    raise ValueError("ledger already exists; initialization cannot reset a budget")
                if not all((args.task, args.candidate_sha, args.spec_sha, args.implementer, args.rows)):
                    raise ValueError("init needs task, candidate/spec SHA, implementer and rows")
                state = new_run(args.task, args.candidate_sha, args.spec_sha, args.implementer, args.rows,
                                spent_seconds=args.spent_seconds)
            else:
                state = json.loads(args.state.read_text())
                if args.action in ("pause", "resume", "worker-start", "worker-end"):
                    state = transition(state, args.action, reason=args.reason, worker=args.worker)
                else:
                    state = checkpoint(state)
            # Persist elapsed work even when evidence is malformed or incomplete.
            save(args.state, state)
            if args.action == "check":
                if args.evidence is None:
                    raise ValueError("check requires --evidence")
                output = evaluate_run(state, json.loads(args.evidence.read_text()), gate=args.gate, now=state["last_at"])
            else:
                output = state
        print(json.dumps(output, indent=2, allow_nan=False))
        return 2 if output.get("outcome") == "blocked" or state["mode"] == "blocked" else 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({"outcome": "blocked", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
