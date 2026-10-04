"""Retention rules and the cleanup job (E5). Nothing is deleted inside its retention period:
`delete_expired` re-checks the file's own mtime (lstat, never following a link) and refuses."""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

DECISION_LOG_NAMES = {"review_decisions.jsonl", "review_cosigns.jsonl"}
DECISION_LOG_DIRS = {"snapshots"}
SIDECARS = {".lock", ".worker"}  # lock files never count towards a run's age
ACTIVE_STATUSES = {"running", "pending"}


class RetentionViolation(Exception):
    pass


@dataclass(frozen=True)
class RetentionPolicy:
    runs: timedelta
    decision_logs: timedelta
    originals: timedelta

    @classmethod
    def from_settings(cls, s) -> RetentionPolicy:
        return cls(
            runs=timedelta(days=s.retention_runs_days),
            decision_logs=timedelta(days=s.retention_decision_logs_days),
            originals=timedelta(days=s.retention_originals_days),
        )


@dataclass
class CleanupReport:
    deleted: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    kept: int = 0


def _age(path: Path, now: datetime) -> timedelta:
    return now - datetime.fromtimestamp(path.lstat().st_mtime, UTC)


def delete_expired(path: Path, retention: timedelta, *, now: datetime) -> None:
    if _age(path, now) < retention:
        raise RetentionViolation(f"{path} is younger than its retention period of {retention}")
    path.unlink()  # a file or a symlink itself; never a link target, never rmtree


def _files(root: Path) -> list[Path]:
    """Every non-directory entry under root. Symlinks (even to directories) are entries, never followed."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)
        out += [d / n for n in filenames]
        out += [d / n for n in dirnames if (d / n).is_symlink()]
    return out


def _is_decision_log(path: Path, run_dir: Path) -> bool:
    rel = path.relative_to(run_dir)
    return path.name in DECISION_LOG_NAMES or any(p in DECISION_LOG_DIRS for p in rel.parts[:-1])


def _status(run_dir: Path) -> str | None:
    try:
        return json.loads((run_dir / "manifest.json").read_text()).get("status")
    except (OSError, ValueError, AttributeError):
        return None


def _prune_empty(root: Path) -> None:
    for dirpath, _, _ in os.walk(root, topdown=False, followlinks=False):
        if Path(dirpath) != root:
            with contextlib.suppress(OSError):  # not empty
                os.rmdir(dirpath)


def _children(root: Path):
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()) if root.is_dir() else []


def cleanup(
    settings,
    *,
    apply: bool,
    now: datetime | None = None,
    held_runs: set[str] = frozenset(),
    held_keys: set[str] = frozenset(),
) -> CleanupReport:
    now = now or datetime.now(UTC)
    policy = RetentionPolicy.from_settings(settings)
    report = CleanupReport()

    def expire(path: Path, retention: timedelta) -> None:
        report.deleted.append(str(path))
        if apply:
            delete_expired(path, retention, now=now)

    for run_dir in _children(settings.runs_dir):
        if run_dir.name in held_runs:
            report.held.append(run_dir.name)
            continue
        if _status(run_dir) in ACTIVE_STATUSES:
            report.kept += 1
            continue
        logs, rest = [], []
        for f in _files(run_dir):
            (logs if _is_decision_log(f, run_dir) else rest).append(f)
        for f in logs:
            if _age(f, now) >= policy.decision_logs:
                expire(f, policy.decision_logs)
            else:
                report.kept += 1
        aged = [f for f in rest if f.name not in SIDECARS]
        # all-or-nothing: only once the newest non-sidecar file is past the period
        if aged and min(_age(f, now) for f in aged) >= policy.runs:
            for f in rest:
                # sidecars go with the run: the run's age is what authorises it
                expire(f, timedelta(0) if f.name in SIDECARS else policy.runs)
        else:
            report.kept += len(rest)
        if apply:
            _prune_empty(run_dir)
            with contextlib.suppress(OSError):
                run_dir.rmdir()

    for prefix in _children(settings.blob_store_dir):
        for f in _files(prefix):
            if f.name in held_keys:
                report.held.append(f.name)
            elif _age(f, now) >= policy.originals:
                expire(f, policy.originals)
            else:
                report.kept += 1
        if apply:
            _prune_empty(prefix)
            with contextlib.suppress(OSError):
                prefix.rmdir()
    return report
