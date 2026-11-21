import io
import json
from pathlib import Path
import sqlite3
import unittest

from factory.run_log import import_events, report


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "demo.jsonl"


def stream(*events):
    return io.StringIO("\n".join(json.dumps(event) for event in events))


class TestRunLog(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.observations = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
        self.run_id = "demo-csv"

    def seed(self):
        return import_events(self.db, stream(*self.observations))

    def test_report_reconstructs_observed_run(self):
        self.assertEqual(self.seed(), 11)
        result = report(self.db, self.run_id)
        self.assertEqual(result["factory_sha"], self.observations[0]["factory_sha"])
        self.assertEqual(
            list(result["latest_event_by_stage"]),
            ["intake", "spec", "holdout", "implement", "review", "merge", "regression"],
        )
        timeline = result["timeline"]
        self.assertEqual([item["event_id"] for item in timeline], [f"{i:03}" for i in range(11)])
        self.assertEqual(timeline[1]["source"], "fixture://owner/approval-A")
        self.assertEqual(timeline[4]["source"], "fixture://ci/run-1")
        self.assertEqual([timeline[i]["attempt"] for i in (3, 6)], ["builder-1", "builder-2"])
        self.assertNotEqual(timeline[4]["head_sha"], timeline[8]["head_sha"])
        self.assertEqual(result["known_attempt_cost_usd_micros"], 1250000)
        self.assertEqual(result["finished_attempts_without_cost"], 3)

    def test_reimport_descending_order_preserves_the_report(self):
        self.seed()
        original = report(self.db, self.run_id)
        self.assertEqual(import_events(self.db, stream(*reversed(self.observations))), 0)
        self.assertEqual(report(self.db, self.run_id), original)

    def test_conflicts_and_malformed_batches_roll_back(self):
        self.seed()
        original = report(self.db, self.run_id)
        extra = {**self.observations[-1], "event_id": "new"}
        for conflict in (
            {**self.observations[0], "detail": "conflict"},
            {**self.observations[-1], "event_id": "wrong", "factory_sha": "0" * 40},
            {**self.observations[-1], "at": "2026-11-21T14:00:00"},
            {**self.observations[0], "event_id": "duplicate-finish"},
        ):
            with self.subTest(conflict=conflict):
                with self.assertRaisesRegex(ValueError, "line 2:"):
                    import_events(self.db, stream(extra, conflict))
                self.assertEqual(report(self.db, self.run_id), original)

    def test_empty_ledger_reports_unknown_run(self):
        with self.assertRaisesRegex(ValueError, "unknown run"):
            report(self.db, "missing")
