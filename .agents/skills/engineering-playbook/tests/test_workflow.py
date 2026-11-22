"""Deterministic helper tests; no API, model, database or private holdout access."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow.py"
spec = importlib.util.spec_from_file_location("engineering_workflow", SCRIPT)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
SHA, SPEC, TESTS = "a" * 40, "b" * 40, "c" * 40


def run():
    return w.new_run("Fix approval disagreement", SHA, SPEC, "builder", ["AC-1", "AC-2"], now=100)


def evidence():
    def result(**extra):
        return dict(result="pass", actor="independent-verifier", candidate_sha=SHA,
                    spec_sha=SPEC, source="https://example.test/evidence/123", **extra)
    return dict(candidate_sha=SHA, spec_sha=SPEC, test_sha=TESTS, environment="production",
                approval_a=dict(actor="owner", subject_sha=SPEC, source="owner-approval-A"),
                approval_b=dict(actor="owner", subject_sha=SHA, environment="production", source="owner-approval-B"),
                acceptance=[result(id="AC-1"), result(id="AC-2")],
                controls={f"V{i}": result() for i in range(1, 9)},
                checks={name: result() for names in w.CHECKS.values() for name in names})


class BudgetTests(unittest.TestCase):
    def test_parallel_workers_share_one_clock(self):
        state = w.transition(run(), "worker-start", worker="one", now=110)
        state = w.transition(state, "worker-start", worker="two", now=110)
        self.assertEqual(w.checkpoint(state, now=130)["used_seconds"], 30)

    def test_human_wait_preserves_balance_and_records_wait(self):
        state = w.transition(run(), "pause", reason="owner-approval", now=130)
        state = w.transition(state, "resume", now=1130)
        state = w.checkpoint(state, now=1140)
        self.assertEqual(state["used_seconds"], 40)
        self.assertEqual(state["waits"], [{"reason": "owner-approval", "seconds": 1000}])

    def test_cannot_pause_with_active_worker(self):
        state = w.transition(run(), "worker-start", worker="ci", now=110)
        with self.assertRaisesRegex(ValueError, "no registered workers"):
            w.transition(state, "pause", reason="owner-approval", now=120)

    def test_deadline_blocks_even_with_complete_evidence(self):
        result = w.evaluate_run(run(), evidence(), gate="done", now=1000)
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["execution_remaining_seconds"], 0)
        with self.assertRaisesRegex(ValueError, "no reset"):
            w.transition(w.checkpoint(run(), now=1000), "resume", now=1001)

    def test_cleanup_reserve_and_carry_forward(self):
        state = w.new_run("Fix", SHA, SPEC, "builder", ["AC-1", "AC-2"], now=100, spent_seconds=840)
        self.assertTrue(w.evaluate_run(state, evidence(), now=100)["reserve_cleanup"])
        self.assertEqual(w.checkpoint(state, now=110)["used_seconds"], 850)

    def test_clock_rollback_and_budget_tampering_fail(self):
        with self.assertRaises(ValueError):
            w.checkpoint(run(), now=99)
        state = run(); state["budget_seconds"] = 901
        with self.assertRaises(ValueError):
            w.checkpoint(state, now=110)

    def test_invalid_numbers_fail(self):
        for value in (float("nan"), float("inf"), -1, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                w.new_run("Fix", SHA, SPEC, "builder", ["AC-1"], now=100, spent_seconds=value)

    def test_duplicate_worker_and_untracked_finish_fail(self):
        state = w.transition(run(), "worker-start", worker="ci", now=100)
        with self.assertRaises(ValueError):
            w.transition(state, "worker-start", worker="ci", now=100)
        with self.assertRaises(ValueError):
            w.transition(state, "worker-end", worker="other", now=100)

    def test_cleanup_can_unregister_worker_after_exhaustion(self):
        state = w.transition(run(), "worker-start", worker="ci", now=100)
        state = w.transition(state, "worker-end", worker="ci", now=1000)
        self.assertEqual(state["workers"], [])
        self.assertEqual(state["mode"], "blocked")


class GateTests(unittest.TestCase):
    def test_all_gates_and_pure_function(self):
        state, packet = run(), evidence(); before = copy.deepcopy((state, packet))
        for gate in w.GATES:
            self.assertEqual(w.evaluate_run(state, packet, gate=gate, now=110)["outcome"], "advisory-ready")
        self.assertEqual((state, packet), before)

    def test_stale_candidate_spec_or_test_revision_blocks(self):
        for key in ("candidate_sha", "spec_sha", "test_sha"):
            packet = evidence(); packet[key] = "bad"
            self.assertEqual(w.evaluate_run(run(), packet, now=110)["outcome"], "blocked")

    def test_missing_duplicate_and_extra_acceptance_rows_block(self):
        for ids in (["AC-1"], ["AC-1", "AC-1"], ["AC-1", "AC-2", "AC-3"]):
            packet = evidence(); sample = packet["acceptance"][0]
            packet["acceptance"] = [{**sample, "id": name} for name in ids]
            self.assertIn("acceptance manifest missing, duplicated or unexpected rows",
                          w.evaluate_run(run(), packet, now=110)["blockers"])

    def test_skipped_missing_or_failed_holdout_cannot_pass(self):
        for status in ("skip", "not_run", "blocked", "fail"):
            packet = evidence(); packet["checks"]["holdout"]["result"] = status
            self.assertEqual(w.evaluate_run(run(), packet, now=110)["outcome"], "blocked")
        packet = evidence(); del packet["checks"]["holdout"]
        self.assertEqual(w.evaluate_run(run(), packet, now=110)["outcome"], "blocked")

    def test_builder_cannot_verify_own_result(self):
        packet = evidence(); packet["controls"]["V5"]["actor"] = "builder"
        self.assertEqual(w.evaluate_run(run(), packet, now=110)["outcome"], "blocked")

    def test_not_applicable_needs_independent_reason(self):
        packet = evidence(); control = packet["controls"]["V3"]; control["result"] = "not_applicable"
        self.assertEqual(w.evaluate_run(run(), packet, now=110)["outcome"], "blocked")
        control["reason"] = "No numerical behavior changed; confirmed against approved scope"
        self.assertEqual(w.evaluate_run(run(), packet, now=110)["outcome"], "advisory-ready")

    def test_release_is_readiness_not_deployment_permission(self):
        packet = evidence(); del packet["approval_b"]
        result = w.evaluate_run(run(), packet, gate="release", now=110)
        self.assertEqual(result["outcome"], "advisory-ready")
        self.assertIs(result["deployment_authorized"], False)
        self.assertEqual(w.evaluate_run(run(), packet, gate="done", now=110)["outcome"], "blocked")

    def test_wrong_release_environment_blocks_done(self):
        packet = evidence(); packet["approval_b"]["environment"] = "staging"
        self.assertEqual(w.evaluate_run(run(), packet, gate="done", now=110)["outcome"], "blocked")

    def test_paused_or_unfinished_work_blocks_gate(self):
        state = w.transition(run(), "pause", reason="human-testing", now=110)
        self.assertEqual(w.evaluate_run(state, evidence(), now=120)["outcome"], "blocked")
        state = w.transition(run(), "worker-start", worker="ci", now=110)
        self.assertEqual(w.evaluate_run(state, evidence(), now=120)["outcome"], "blocked")

    def test_stale_individual_evidence_and_missing_owner_approval_block(self):
        packet = evidence(); packet["acceptance"][0]["candidate_sha"] = "d" * 40
        packet.pop("approval_a")
        self.assertGreaterEqual(len(w.evaluate_run(run(), packet, now=110)["blockers"]), 2)


class CliTests(unittest.TestCase):
    def call(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def test_init_is_idempotency_guarded_and_status_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.json")
            args = ("init", "--state", path, "--task", "Task", "--candidate-sha", SHA,
                    "--spec-sha", SPEC, "--implementer", "builder", "--rows", "AC-1")
            self.assertEqual(self.call(*args)[0], 0)
            self.assertEqual(self.call(*args)[0], 2)
            code, data = self.call("status", "--state", path)
            self.assertEqual(code, 0); self.assertGreater(data["used_seconds"], 0)

    def test_lock_prevents_overwriting_other_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            with w.ledger(path):
                with self.assertRaisesRegex(ValueError, "locked"):
                    with w.ledger(path):
                        self.fail("second writer acquired lock")

    def test_rejected_pause_leaves_ledger_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = run(); state["last_at"] = w.time.time(); state["workers"] = ["ci"]
            w.save(path, state); before = path.read_bytes()
            code, data = self.call("pause", "--state", str(path), "--reason", "owner-approval")
            self.assertEqual(code, 2); self.assertEqual(data["outcome"], "blocked")
            self.assertEqual(path.read_bytes(), before)

    def test_forbidden_commands_are_rejected_without_creating_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            for action in ("deploy", "merge", "install", "cancel-remote"):
                p = subprocess.run([sys.executable, str(SCRIPT), action, "--state", str(Path(tmp)/"state.json")], capture_output=True)
                self.assertEqual(p.returncode, 2)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_malformed_evidence_is_blocked_and_clock_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, packet = Path(tmp) / "state.json", Path(tmp) / "evidence.json"
            state = run(); state["last_at"] = w.time.time() - 10; w.save(path, state)
            packet.write_text("not json")
            self.assertEqual(self.call("check", "--state", str(path), "--evidence", str(packet))[0], 2)
            self.assertGreaterEqual(json.loads(path.read_text())["used_seconds"], 10)


class PackageTests(unittest.TestCase):
    def test_skill_defaults_to_plan_and_declares_all_controls(self):
        root = SCRIPT.parents[4]
        skill = (SCRIPT.parents[1]/"SKILL.md").read_text()
        playbook = (SCRIPT.parents[1]/"references/playbook.md").read_text()
        self.assertIn("invocation without a mode means **plan**", skill)
        for i in range(1, 9):
            self.assertIn(f"| V{i} |", playbook)
        self.assertIn("allow_implicit_invocation: false", (SCRIPT.parents[1]/"agents/openai.yaml").read_text())
        manifest = json.loads((root/".claude/mods/engineering-playbook/.claude-plugin/plugin.json").read_text())
        self.assertFalse({"hooks", "mcpServers", "lspServers"} & manifest.keys())
        self.assertNotIn("engineering-playbook", (root/".claude/hooks/install-plugins.sh").read_text())


if __name__ == "__main__":
    unittest.main()
