"""Versioned house policies for the stage studios: design a new version,
calibrate it against the active one, then activate it with a named approver.

Two policies so far:

- `coverage_rules`: the ZEN decision table that proposes coverage tiers (stage 2);
- `house_voting`: the house voting positions on the issue catalogue (stage 4).

Version 0 is the bundled draft in `data/`, always available as the baseline.
Saved versions are immutable files; activations are an append-only log, and
the active version is the last activation. Nothing is stored that fails
validation, and nothing becomes active without `approved_by`, who must not be
the person who saved that version (four-eyes).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from arp.schemas.engagement import EngagementRecord
from arp.stewardship.backtest import backtest
from arp.stewardship.policy_graph import evaluate as evaluate_votes
from arp.stewardship.policy_graph import generate
from arp.stewardship.policy_review import _validate_position, load
from arp.stewardship.tiers import TIER_LABELS, tier_contexts
from arp.stewardship.tiers import evaluate as evaluate_tiers
from arp.stewardship.tiers import load_graph as default_coverage_graph
from arp.storage.atomic_io import atomic_write_text


def _validate_coverage(graph: dict, sample: dict) -> None:
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("A coverage policy is a rule graph with nodes and edges")
    try:
        evaluate_tiers(graph, tier_contexts(sample, []))
    except RuntimeError as exc:
        raise ValueError(f"The coverage rules do not run: {exc}") from exc


def _validate_voting(policy: dict, sample: dict) -> None:
    catalogue = load("policy_issue_catalogue.json")
    issues = {i["issue_id"]: i for i in catalogue["issues"]}
    positions = policy.get("positions") or []
    ids = [p["issue_id"] for p in positions]
    if sorted(ids) != sorted(issues):
        missing, extra = set(issues) - set(ids), set(ids) - set(issues)
        raise ValueError(
            f"A voting policy needs exactly one position per catalogue issue (missing {sorted(missing)}, unknown {sorted(extra)})"
        )
    for p in positions:
        _validate_position(issues[p["issue_id"]], p, catalogue["position_actions"])
    evaluate_votes(generate(policy)["graph"], [])  # compiles


POLICIES: dict[str, dict[str, Callable]] = {
    "coverage_rules": {"default": default_coverage_graph, "validate": _validate_coverage},
    "house_voting": {"default": lambda: load("house_voting_policy_draft.json"), "validate": _validate_voting},
}


class PolicyStore:
    def __init__(self, root: Path) -> None:
        self.root = root / "policies"

    def _dir(self, policy_id: str) -> Path:
        if policy_id not in POLICIES:
            raise KeyError(policy_id)
        return self.root / policy_id

    def versions(self, policy_id: str) -> list[dict]:
        d = self._dir(policy_id)
        metas = [{"version": 0, "note": "Bundled draft", "created_by": "system", "created_at": None}]
        if d.exists():
            for path in sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:])):
                metas.append({k: v for k, v in json.loads(path.read_text()).items() if k != "content"})
        return metas

    def content(self, policy_id: str, version: int) -> dict:
        if version == 0:
            return POLICIES[policy_id]["default"]()
        path = self._dir(policy_id) / f"v{version}.json"
        if not path.exists():
            raise KeyError(f"{policy_id} v{version}")
        return json.loads(path.read_text())["content"]

    def activations(self, policy_id: str) -> list[dict]:
        path = self._dir(policy_id) / "activations.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []

    def active_version(self, policy_id: str) -> int:
        log = self.activations(policy_id)
        return log[-1]["version"] if log else 0

    def active(self, policy_id: str) -> dict:
        return self.content(policy_id, self.active_version(policy_id))

    def save(self, policy_id: str, content: dict, note: str, created_by: str, sample: dict) -> int:
        if not created_by.strip():
            raise ValueError("A policy version needs created_by")
        POLICIES[policy_id]["validate"](content, sample)
        version = max(v["version"] for v in self.versions(policy_id)) + 1
        if "policy_id" in content:  # stamp the store version into the policy, so reviews and builds cite it
            content = {**content, "version": f"v{version}"}
        d = self._dir(policy_id)
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "version": version,
            "note": note,
            "created_by": created_by,
            "created_at": datetime.now(UTC).isoformat(),
            "content": content,
        }
        atomic_write_text(d / f"v{version}.json", json.dumps(record, indent=2, ensure_ascii=False))
        return version

    def activate(self, policy_id: str, version: int, approved_by: str) -> dict:
        if not approved_by.strip():
            raise ValueError("Activating a policy version needs approved_by")
        self.content(policy_id, version)  # raises for an unknown version
        meta = next(v for v in self.versions(policy_id) if v["version"] == version)
        if version > 0 and meta["created_by"].strip().lower() == approved_by.strip().lower():
            raise ValueError("Four-eyes rule: a version must be activated by someone other than the person who saved it")
        row = {"version": version, "approved_by": approved_by, "approved_at": datetime.now(UTC).isoformat()}
        d = self._dir(policy_id)
        d.mkdir(parents=True, exist_ok=True)
        with (d / "activations.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        return row


def coverage_preview(candidate: dict, active: dict, sample: dict, records: list[EngagementRecord]) -> dict:
    """What a candidate coverage table would change against the active one."""
    contexts = tier_contexts(sample, records)
    new = evaluate_tiers(candidate, contexts)
    old = {r["issuer_id"]: r for r in evaluate_tiers(active, contexts)}
    changes = [
        {
            "issuer_id": r["issuer_id"],
            "company": r["name"],
            "from": TIER_LABELS[old[r["issuer_id"]]["tier"]],
            "to": TIER_LABELS[r["tier"]],
            "rule": r["rule"],
            "reason": r["reason"],
        }
        for r in new
        if r["tier"] != old[r["issuer_id"]]["tier"]
    ]
    return {
        "companies": len(new),
        "distribution_candidate": {TIER_LABELS[t]: n for t, n in Counter(r["tier"] for r in new).items()},
        "distribution_active": {TIER_LABELS[t]: n for t, n in Counter(r["tier"] for r in old.values()).items()},
        "rules_fired": dict(Counter(r["rule"] for r in new)),
        "changes": changes,
        "assignments": new,
    }


def voting_preview(candidate: dict, active: dict, sample: dict) -> dict:
    """Back-test of a candidate house voting policy against the active one."""
    bt = backtest(active, candidate, sample)
    changed = [r for r in bt["rows"] if r["changed"]]
    return {k: bt[k] for k in ("resolutions", "changed", "base_votes", "other_votes", "affected_by_issue", "masked_by_issue")} | {
        "changed_rows": changed[:100],
        "unused_parameters": generate(candidate)["unused_parameters"],
        "no_vote_effect": generate(candidate)["no_vote_effect"],
    }
