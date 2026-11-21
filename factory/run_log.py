"""Import and inspect recorded Factory events without contacting external systems."""

import argparse
from contextlib import closing
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
import sys


STAGES = ("intake", "spec", "holdout", "implement", "review", "merge", "regression")
KINDS = ("started", "waiting", "finished", "check", "approval", "artifact")
REQUIRED = {"run_id", "event_id", "factory_sha", "at", "stage", "kind"}
OPTIONAL = {"attempt", "detail", "source", "spec_sha", "head_sha", "cost_usd_micros"}
SHA = re.compile(r"[0-9a-f]{40}")
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    factory_sha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    event_id TEXT NOT NULL,
    at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, event_id)
);
CREATE INDEX IF NOT EXISTS events_timeline ON events (run_id, at, event_id);
CREATE UNIQUE INDEX IF NOT EXISTS finished_attempt ON events (
    run_id, json_extract(payload, '$.stage'), json_extract(payload, '$.attempt')
) WHERE json_extract(payload, '$.kind') = 'finished';
"""


def parse_event(value):
    if not isinstance(value, dict) or REQUIRED - value.keys() or value.keys() - REQUIRED - OPTIONAL:
        raise ValueError("event must contain all required fields and only documented fields")
    for field, item in value.items():
        if field == "cost_usd_micros":
            if type(item) is not int or item < 0 or value["kind"] != "finished":
                raise ValueError("cost_usd_micros must be a nonnegative integer on a finished event")
        elif not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must be a nonempty string")
    for field in ("factory_sha", "spec_sha", "head_sha"):
        if field in value and not SHA.fullmatch(value[field]):
            raise ValueError(f"{field} must be a full lowercase commit SHA")
    if value["stage"] not in STAGES or value["kind"] not in KINDS:
        raise ValueError("unknown stage or event kind")
    if value["kind"] in ("started", "finished") and "attempt" not in value:
        raise ValueError("a worker attempt ID is required for started and finished events")
    at = datetime.fromisoformat(value["at"])
    if at.tzinfo is None:
        raise ValueError("event time must include a timezone")
    return {**value, "at": at.astimezone(UTC).isoformat(timespec="microseconds")}


def import_events(db, source):
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    inserted = 0
    with db:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                event = parse_event(json.loads(line))
                run = event["run_id"]
                sha = event["factory_sha"]
                db.execute("INSERT INTO runs VALUES (?, ?) ON CONFLICT DO NOTHING", (run, sha))
                pinned = db.execute("SELECT factory_sha FROM runs WHERE run_id = ?", (run,)).fetchone()
                if pinned[0] != sha:
                    raise ValueError(f"factory revision changed for run {run}")
                payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
                previous = db.execute(
                    "SELECT payload FROM events WHERE run_id = ? AND event_id = ?",
                    (run, event["event_id"]),
                ).fetchone()
                if previous:
                    if previous[0] != payload:
                        raise ValueError(f"event {event['event_id']} conflicts with the recorded event")
                    continue
                db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (run, event["event_id"], event["at"], payload))
                inserted += 1
            except (ValueError, OverflowError, sqlite3.IntegrityError) as exc:
                raise ValueError(f"line {line_number}: {exc}") from exc
    return inserted


def report(db, run_id):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'runs'").fetchone()
    run = db.execute("SELECT factory_sha FROM runs WHERE run_id = ?", (run_id,)).fetchone() if exists else None
    if run is None:
        raise ValueError(f"unknown run {run_id!r}")
    events = [
        json.loads(payload)
        for (payload,) in db.execute(
            "SELECT payload FROM events WHERE run_id = ? ORDER BY at, event_id", (run_id,)
        )
    ]
    latest = {event["stage"]: event["event_id"] for event in events}
    finished = [event for event in events if event["kind"] == "finished"]
    costs = [event["cost_usd_micros"] for event in finished if "cost_usd_micros" in event]
    return {
        "run_id": run_id,
        "factory_sha": run[0],
        "latest_event_by_stage": {stage: latest[stage] for stage in STAGES if stage in latest},
        "finished_attempts": len(finished),
        "known_attempt_cost_usd_micros": sum(costs),
        "finished_attempts_without_cost": len(finished) - len(costs),
        "timeline": events,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import", help="import a normalized JSON Lines file").add_argument("file", type=Path)
    commands.add_parser("report", help="show an ordered run timeline").add_argument("run_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            with args.file.open(encoding="utf-8") as source, closing(sqlite3.connect(args.db)) as db:
                result = {"inserted": import_events(db, source)}
        else:
            if not args.db.is_file():
                raise ValueError(f"unknown run {args.run_id!r}: ledger does not exist")
            with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                result = report(db, args.run_id)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"factory run log: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

