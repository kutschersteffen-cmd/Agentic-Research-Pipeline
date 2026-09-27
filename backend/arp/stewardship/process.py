"""The stewardship process as an interactive flow: the eight stages of
docs/STEWARDSHIP_OPERATING_MODEL.md (Part 2), each with its key metrics and,
where a person has to decide something, the open decisions.

One House stream shows the house program. Client streams add a client's
envisioned policy on top: its policy review (decide per difference, then
build) and the back-test against the house.

Every metric says where its number comes from, because the stages are not
equally built yet:

- `live`: the running engagement record store;
- `sample`: the synthetic meeting sample (fictional companies);
- `not_built`: the stage needs something that does not exist yet.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arp.engagement.orchestrator import OrchestratorAction, decide_next_action, is_stalled, next_escalation_stage
from arp.schemas.engagement import EngagementRecord, IssueStatus, MilestoneStage
from arp.stewardship.backtest import attach_impact, build_contexts
from arp.stewardship.policy_graph import evaluate, generate
from arp.stewardship.policy_review import DATA, build, decide, load, review
from arp.stewardship.tiers import TIER_LABELS, TIERS, TierStore, review_tiers, tier_contexts
from arp.stewardship.tiers import evaluate as evaluate_tiers
from arp.stewardship.tiers import load_graph as load_tier_graph
from arp.storage.atomic_io import atomic_write_text

SAMPLE_PATH = DATA / "examples" / "sample_meetings.json"
HOUSE = "house"


class StreamStore:
    """One JSON file per client stream. The House stream is implicit."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, stream_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{1,64}", stream_id):
            raise ValueError("Invalid stream id")
        return self.root / f"{stream_id}.json"

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        return sorted((json.loads(p.read_text()) for p in self.root.glob("*.json")), key=lambda s: s["created_at"])

    def get(self, stream_id: str) -> dict | None:
        path = self._path(stream_id)
        return json.loads(path.read_text()) if path.exists() else None

    def save(self, stream: dict) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path(stream["stream_id"]), json.dumps(stream, indent=2, ensure_ascii=False))
        return stream

    def create(self, name: str, client_policy: dict, vehicle_type: str) -> dict:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "client"
        stream_id, n = base, 1
        while self.get(stream_id) is not None:
            n += 1
            stream_id = f"{base}-{n}"
        client_policy = {
            **client_policy,
            "client": name,
            "mandate": {**client_policy.get("mandate", {}), "vehicle_type": vehicle_type},
        }
        client_policy.setdefault("policy_id", f"{stream_id}_voting")
        review(client_policy)  # validates the positions against the catalogue before anything is stored
        return self.save(
            {
                "stream_id": stream_id,
                "name": name,
                "created_at": datetime.now(UTC).isoformat(),
                "client_policy": client_policy,
                "decisions": [],
                "built_policy": None,
            }
        )


def _metric(label: str, value: Any, source: str, tone: str = "neutral", hint: str | None = None) -> dict:
    return {"label": label, "value": value, "source": source, "tone": tone, "hint": hint}


def _stage(stage_id: str, number: int, title: str, layer: str, summary: str, metrics: list[dict], **extra: Any) -> dict:
    sources = {m["source"] for m in metrics}
    status = "live" if sources == {"live"} else "not_built" if sources == {"not_built"} else "partial"
    return {
        "id": stage_id,
        "number": number,
        "title": title,
        "layer": layer,
        "summary": summary,
        "status": status,
        "metrics": metrics,
        "decisions": [],
        "details": [],
        **extra,
    }


def _open_issues(records: list[EngagementRecord]):
    for record in records:
        for issue in record.issues:
            if issue.status in (IssueStatus.OPEN, IssueStatus.STALLED):
                yield record, issue


def _house_stages(records: list[EngagementRecord], sample: dict, policy: dict, sla_days: int, tiers: dict) -> list[dict]:
    open_issues = list(_open_issues(records))
    all_issues = [i for r in records for i in r.issues]
    stalled = sum(1 for _, i in open_issues if is_stalled(i, sla_days))
    triggered = sum(1 for i in all_issues if i.source.value in ("controversy_screen", "sla_stall"))
    fields = [v for issuer in sample["issuers"] for v in issuer["fields"].values()]
    missing = sum(v is None for v in fields) / len(fields) if fields else 0

    contexts = build_contexts(sample)
    results = evaluate(generate(policy)["graph"], [c for _, c in contexts])
    votes = Counter(r["expected_vote"] for r in results)
    deciders = Counter(i for r in results if r["expected_vote"] == "against" for i in r["decided_by"])
    sanctions = sum("stewardship.engagement_escalation" in r["decided_by"] for r in results)

    milestones = Counter(i.milestone_stage.value for _, i in open_issues)
    commitments = Counter(c.status.value for i in all_issues for c in i.commitments)
    flagged = [
        (record, issue)
        for record, issue in open_issues
        if decide_next_action(issue, sla_days).action == OrchestratorAction.FLAG_FOR_ESCALATION_DECISION
    ]

    s1 = _stage(
        "monitoring",
        1,
        "Continuous Monitoring & Detection",
        "house",
        "Watches every in-scope holding and raises triggers.",
        [
            _metric("Companies monitored", len(sample["issuers"]), "sample"),
            _metric("Values missing", f"{missing:.0%}", "sample", "warn" if missing > 0.05 else "neutral"),
            _metric(
                "Opened by triggers", triggered, "live", hint="Engagements opened by the controversy screen or the SLA sweep"
            ),
            _metric("Stalled engagements", stalled, "live", "warn" if stalled else "good", f"No activity for {sla_days} days"),
        ],
    )
    s2 = _stage(
        "selection",
        2,
        "Research & Selection",
        "house",
        "Assigns coverage tiers and opens engagements; researches every new one.",
        [
            _metric("Open engagements", len(open_issues), "live"),
            _metric("Awaiting research", milestones.get(MilestoneStage.IDENTIFIED.value, 0), "live"),
            _metric(
                "Tiers confirmed",
                f"{tiers['confirmed']} of {tiers['in_scope']}",
                "sample",
                "warn" if tiers["changes"] or tiers["reevaluation_due"] else "good",
                "Quarterly re-evaluation is due"
                if tiers["reevaluation_due"]
                else "Coverage tiers (E1) from the house coverage rules",
            ),
        ],
        details=[
            {
                "label": "Confirmed coverage tiers",
                "rows": [{"tier": TIER_LABELS[t], "companies": tiers["distribution"].get(t, 0)} for t in TIERS],
            },
        ],
    )
    s3 = _stage(
        "drafting",
        3,
        "Drafting",
        "house",
        "Prepares outreach and meeting summaries; tags advocacy interactions.",
        [
            _metric("Summaries to draft", milestones.get(MilestoneStage.RESPONSE_RECEIVED.value, 0), "live"),
            _metric("Awaiting response", milestones.get(MilestoneStage.CONTACTED.value, 0), "live"),
        ],
    )
    s4 = _stage(
        "voting",
        4,
        "Link Engagement ↔ Voting",
        "house",
        "Expected votes from the policy graph; checks votes cast; feeds vote outcomes back as triggers.",
        [
            _metric("Resolutions", len(results), "sample", hint="Evaluated with the policy graph"),
            _metric("Expected against", f"{votes.get('against', 0) / len(results):.0%}" if results else "—", "sample"),
            _metric("Case-by-case", votes.get("case_by_case", 0), "sample"),
            _metric("Sanction votes", sanctions, "sample", hint="Votes against because an engagement reached the vote step"),
        ],
        details=[
            {
                "label": "Most frequent reasons to vote against",
                "rows": [{"issue": i, "resolutions": n} for i, n in deciders.most_common(6)],
            }
        ],
    )
    tier_changes = tiers["changes"]
    s5 = _stage(
        "checkpoint",
        5,
        "Human Checkpoint",
        "house",
        "Every escalation, sanction list, outreach and disclosure is decided by a person.",
        [
            _metric("Escalations to decide", len(flagged), "live", "warn" if flagged else "good"),
            _metric("Tier changes to confirm", len(tier_changes), "sample", "warn" if tier_changes else "good"),
        ],
    )
    for change in tier_changes:
        s5["decisions"].append(
            {
                "kind": "tier_change",
                "issuer_id": change["issuer_id"],
                "company": change["name"],
                "current": TIER_LABELS.get(change["current_tier"], "none"),
                "proposed": TIER_LABELS[change["tier"]],
                "rule": change["rule"],
                "reason": change["reason"],
            }
        )
    for record, issue in flagged:
        nxt = next_escalation_stage(issue.escalation_stage)
        s5["decisions"].append(
            {
                "kind": "escalation",
                "company_id": record.company_id,
                "company": record.name,
                "issue_id": issue.issue_id,
                "theme": issue.theme,
                "current": issue.escalation_stage.value,
                "next": nxt.value if nxt else None,
                "reason": decide_next_action(issue, sla_days).reason,
            }
        )
    s6 = _stage(
        "tracking",
        6,
        "Tracking",
        "house",
        "Logs outcomes and commitments; missed dates and stalls go back to monitoring.",
        [
            _metric("Commitments open", commitments.get("open", 0), "live"),
            _metric("Commitments met", commitments.get("verified", 0), "live", "good"),
            _metric(
                "Commitments missed", commitments.get("missed", 0), "live", "bad" if commitments.get("missed") else "neutral"
            ),
        ],
        details=[
            {
                "label": "Open engagements by milestone",
                "rows": [{"milestone": k, "engagements": v} for k, v in milestones.items()],
            }
        ],
    )
    return [s1, s2, s3, s4, s5, s6]


def _client_stages(stream: dict, sample: dict, house_policy: dict) -> list[dict]:
    result = review(stream["client_policy"], house_policy)
    decide(result, stream["decisions"])
    attach_impact(result, house_policy, sample, "synthetic sample")
    s, bt = result["summary"], result["summary"]["backtest"]
    differences = [r for r in result["register"] if "assessment" in r]
    open_rows = [r for r in differences if r["decision"] is None]

    s7 = _stage(
        "client_policy",
        7,
        "Client Policy Evaluation",
        "client",
        "The client's policy against the house policy: decide every difference, then build.",
        [
            _metric("To decide", len(open_rows), "live", "warn" if open_rows else "good"),
            _metric("Differences", len(differences), "live"),
            _metric("Separate votes", s["separate_vote_required"], "live"),
            _metric("Not deliverable", s["not_deliverable"], "live", "bad" if s["not_deliverable"] else "neutral"),
            _metric(
                "Votes changed",
                f"{bt['changed']} of {bt['resolutions']}",
                "sample",
                hint="Back-test of the envisioned policy against the house",
            ),
        ],
        can_build=not open_rows and stream.get("built_policy") is None,
    )
    for r in differences:
        a = r["assessment"]
        s7["decisions"].append(
            {
                "kind": "policy_difference",
                "issue_id": r["issue_id"],
                "title": r["title"],
                "difference": r["kind"],
                "changes": r.get("changes", []),
                "source": r.get("source"),
                "question": r.get("question"),
                "direction": a.get("direction"),
                "flags": a.get("flags", []) + a.get("effort", []),
                "votes_changed": (a.get("impact") or {}).get("votes_changed"),
                "recommendation": a["recommendation"],
                "decision": r["decision"],
            }
        )
    built = stream.get("built_policy")
    s8 = _stage(
        "reporting",
        8,
        "Reporting & Disclosure",
        "client",
        "Client report and disclosure from house truth plus this client's policy.",
        [
            _metric("Custom policy", "built" if built else "pending", "live", "good" if built else "neutral"),
            _metric("Client positions", sum(p["origin"] == "client" for p in built["positions"]) if built else "—", "live"),
            _metric("Client report", "—", "not_built", hint="Per-client reports (stage 8) are designed but not built."),
        ],
    )
    return [s7, s8]


def _house_reporting(streams: list[dict], records: list[EngagementRecord]) -> list[dict]:
    open_decisions = 0
    for stream in streams:
        decided = {d["issue_id"] for d in stream["decisions"]}
        result = review(stream["client_policy"])
        open_decisions += sum(1 for r in result["register"] if "assessment" in r and r["issue_id"] not in decided)
    return [
        _stage(
            "client_policy",
            7,
            "Client Policy Evaluation",
            "client",
            "Client streams apply their own policies on top of the house results.",
            [
                _metric("Client streams", len(streams), "live"),
                _metric("Decisions open", open_decisions, "live", "warn" if open_decisions else "good"),
            ],
        ),
        _stage(
            "reporting",
            8,
            "Reporting & Disclosure",
            "client",
            "Stewardship reports and public vote disclosure.",
            [
                _metric("Engagements", sum(len(r.issues) for r in records), "live"),
                _metric("Vote disclosure", "—", "not_built", hint="Disclosure records (E2) need the voting feed."),
            ],
        ),
    ]


EDGES = [
    {"from": "monitoring", "to": "selection"},
    {"from": "selection", "to": "drafting"},
    {"from": "drafting", "to": "voting"},
    {"from": "voting", "to": "checkpoint"},
    {"from": "checkpoint", "to": "tracking"},
    {"from": "tracking", "to": "monitoring", "label": "missed commitments, stalls"},
    {"from": "monitoring", "to": "client_policy"},
    {"from": "checkpoint", "to": "client_policy"},
    {"from": "client_policy", "to": "checkpoint", "label": "client exceptions"},
    {"from": "client_policy", "to": "reporting"},
]


def flow(stream_id: str, streams: StreamStore, records: list[EngagementRecord], sla_days: int) -> dict:
    sample = json.loads(SAMPLE_PATH.read_text())
    house_policy = load("house_voting_policy_draft.json")
    tiers = tier_review(streams.root, sample, records)
    if stream_id == HOUSE:
        stream = {"stream_id": HOUSE, "name": "House program"}
        stages = _house_stages(records, sample, house_policy, sla_days, tiers) + _house_reporting(streams.list(), records)
    else:
        stream = streams.get(stream_id)
        if stream is None:
            raise KeyError(stream_id)
        policy = stream.get("built_policy") or house_policy
        stages = _house_stages(records, sample, policy, sla_days, tiers) + _client_stages(stream, sample, house_policy)
    return {
        "stream": {k: stream[k] for k in ("stream_id", "name")} | {"mandate": stream.get("client_policy", {}).get("mandate")},
        "data_note": "Meeting and company data are a synthetic sample (fictional companies); engagement data is live.",
        "stages": stages,
        "edges": EDGES,
    }


def tier_review(root: Path, sample: dict, records: list[EngagementRecord]) -> dict:
    proposals = evaluate_tiers(load_tier_graph(), tier_contexts(sample, records))
    return review_tiers(proposals, TierStore(root).latest())


def confirm_tiers(root: Path, records: list[EngagementRecord], decided_by: str, issuer_ids: list[str] | None = None) -> int:
    """Confirms the proposed tier changes (all of them, or the listed issuers)."""
    changes = tier_review(root, json.loads(SAMPLE_PATH.read_text()), records)["changes"]
    wanted = [c for c in changes if issuer_ids is None or c["issuer_id"] in issuer_ids]
    store = TierStore(root)
    for change in wanted:
        store.confirm({k: v for k, v in change.items() if k != "current_tier"}, decided_by)
    return len(wanted)


def record_decision(stream: dict, decision: dict, house_policy: dict | None = None) -> dict:
    """Validates one policy-review decision against the register, then stores it
    (replacing an earlier decision on the same difference)."""
    if stream.get("built_policy") is not None:
        raise ValueError("The policy is already built; start a new stream to change it")
    decisions = [d for d in stream["decisions"] if d["issue_id"] != decision["issue_id"]] + [decision]
    decide(review(stream["client_policy"], house_policy), decisions)  # raises on an invalid decision
    return {**stream, "decisions": decisions}


def build_stream_policy(stream: dict, house_policy: dict | None = None) -> dict:
    result = decide(review(stream["client_policy"], house_policy), stream["decisions"])
    return {**stream, "built_policy": build(result, house_policy)}
