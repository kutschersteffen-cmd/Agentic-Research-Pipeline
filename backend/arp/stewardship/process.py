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

from arp.engagement.orchestrator import is_stalled
from arp.schemas.engagement import EngagementRecord, IssueStatus, MilestoneStage
from arp.stewardship import escalation, monitoring, tracking
from arp.stewardship.backtest import attach_impact, build_contexts
from arp.stewardship.drafting import DraftStore
from arp.stewardship.policies import PolicyStore
from arp.stewardship.policy_graph import evaluate, generate
from arp.stewardship.policy_review import DATA, build, decide, review
from arp.stewardship.tiers import TIER_LABELS, TIERS, TierStore, review_tiers, tier_contexts
from arp.stewardship.tiers import evaluate as evaluate_tiers
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


def _house_stages(
    records: list[EngagementRecord],
    sample: dict,
    policy: dict,
    sla_days: int,
    tiers: dict,
    triggers: list[dict],
    escalations: list[dict],
    exceptions: list[dict],
    drafts: list[dict],
) -> list[dict]:
    open_issues = list(_open_issues(records))
    all_issues = [i for r in records for i in r.issues]
    stalled = sum(1 for _, i in open_issues if is_stalled(i, sla_days))
    triggered = sum(1 for i in all_issues if i.source.value in ("controversy_screen", "sla_stall", "monitoring_rule"))
    fields = [v for issuer in sample["issuers"] for v in issuer["fields"].values()]
    missing = sum(v is None for v in fields) / len(fields) if fields else 0

    contexts = build_contexts(sample)
    results = evaluate(generate(policy)["graph"], [c for _, c in contexts])
    votes = Counter(r["expected_vote"] for r in results)
    deciders = Counter(i for r in results if r["expected_vote"] == "against" for i in r["decided_by"])
    sanctions = sum("stewardship.engagement_escalation" in r["decided_by"] for r in results)

    milestones = Counter(i.milestone_stage.value for _, i in open_issues)
    pending = [d for d in drafts if d["status"] == "draft"]
    tracked = tracking.triggers(records, sla_days)
    due = [c for c in tracking.commitments(records) if c["overdue"]]
    sent = [d for d in drafts if d["status"] == "sent"]
    commitments = Counter(c.status.value for i in all_issues for c in i.commitments)
    to_decide = [r for r in escalations if escalation.needs_decision(r)]
    live = [r for r in to_decide if r["source"] == "live"]

    s1 = _stage(
        "monitoring",
        1,
        "Continuous Monitoring & Detection",
        "house",
        "Watches every in-scope holding and raises triggers.",
        [
            _metric("Companies monitored", len(sample["issuers"]), "sample"),
            _metric("Values missing", f"{missing:.0%}", "sample", "warn" if missing > 0.05 else "neutral"),
            _metric("Triggers raised", len(triggers), "sample", hint="By the active monitoring rules, on company data"),
            _metric(
                "Tracking triggers",
                len(tracked),
                "live",
                "warn" if tracked else "good",
                "Missed or overdue commitments and stalled engagements (stage 6)",
            ),
            _metric(
                "Without an engagement",
                len({t["issuer_id"] for t in triggers if t["engagement_id"] is None}),
                "sample",
                "warn" if any(t["engagement_id"] is None for t in triggers) else "good",
                "Companies with a trigger and no open engagement on its theme",
            ),
            _metric(
                "Opened by triggers",
                triggered,
                "live",
                hint="Engagements opened by the controversy screen, the SLA sweep or a monitoring rule",
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
            _metric("Drafts at the checkpoint", len(pending), "live", "warn" if pending else "good"),
            _metric(
                "Advocacy / pressure",
                f"{sum(d['interaction_type'] == 'advocacy_pressure' for d in sent)} of {len(sent)}",
                "live",
                hint="Sent outreach tagged advocacy/pressure (E6)",
            ),
            _metric(
                "Style flags open",
                sum(len(d["style_flags"]) for d in pending),
                "live",
                "warn" if any(d["style_flags"] for d in pending) else "good",
                "E8 phrase blocklist, on drafts not yet approved",
            ),
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
            _metric(
                "Escalations to decide", len(live), "live", "warn" if live else "good", "Recommended by the escalation rules"
            ),
            _metric(
                "Sample recommendations",
                len(to_decide) - len(live),
                "sample",
                hint=f"{sum(r['promote_tier'] for r in to_decide)} at their tier's cap: promote the tier",
            ),
            _metric("Tier changes to confirm", len(tier_changes), "sample", "warn" if tier_changes else "good"),
            _metric(
                "Outreach to approve", len(pending), "live", "warn" if pending else "good", "Nothing is sent before approval"
            ),
            _metric(
                "Client escalations above the house",
                len(exceptions),
                "live",
                "warn" if exceptions else "good",
                "A client's escalation rules want a higher step: adopt or decline",
            ),
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
    for r in live:
        s5["decisions"].append(
            {
                "kind": "escalation",
                "company_id": r["company_id"],
                "company": r["company"],
                "issue_id": r["issue_id"],
                "theme": r["theme"],
                "current": r["current"],
                "next": r["recommended"] if r["escalate"] else None,
                "max_step": r["max_step"],
                "promote_tier": r["promote_tier"],
                "reason": f"{r['reason']} ({r['rule']})",
            }
        )
    for d in pending:
        s5["decisions"].append(
            {
                "kind": "outreach",
                "draft_id": d["draft_id"],
                "company": d["company"],
                "theme": d["theme"],
                "type": d["type"],
                "interaction_type": d["interaction_type"],
                "proposed_interaction_type": d["proposed_interaction_type"],
                "proposed_because": d["proposed_because"],
                "text": d["text"],
                "style_flags": d["style_flags"],
                "authors": sorted({h["by"] for h in d["history"] if h["action"] in ("created", "edited")}),
            }
        )
    for r in exceptions:
        s5["decisions"].append(
            {
                "kind": "client_exception",
                "stream_id": r["stream_id"],
                "client": r["client"],
                "company_id": r["company_id"],
                "company": r["company"],
                "issue_id": r["issue_id"],
                "theme": r["theme"],
                "current": r["current"],
                "house": r["house_recommended"],
                "client_step": r["recommended"],
                "reason": f"{r['reason']} ({r['rule']})",
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
            _metric("Past target date", len(due), "live", "warn" if due else "good", "Open commitments to verify or mark missed"),
            _metric(
                "Case studies ready",
                sum(1 for r in records for i in r.issues if i.status.value in ("resolved", "closed")),
                "live",
                hint="Closed engagements (E7)",
            ),
        ],
        details=[
            {
                "label": "Open engagements by milestone",
                "rows": [{"milestone": k, "engagements": v} for k, v in milestones.items()],
            }
        ],
    )
    s6["decisions"] = [{"kind": "commitment_due", **c} for c in due]
    return [s1, s2, s3, s4, s5, s6]


def _client_stages(
    stream: dict, sample: dict, house_policy: dict, escalations: list[dict], escalation_version: int
) -> list[dict]:
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
            _metric(
                "Escalation rules",
                f"v{escalation_version}" if escalation_version else "Same as house",
                "live",
            ),
            _metric(
                "Escalations above the house",
                sum(r["higher"] for r in escalations),
                "sample",
                hint="Live ones go to the house checkpoint (stage 5)",
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
            _metric("Client report", "ready", "live", "good", "Report and PowerPoint, rebuilt from current data on request"),
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
    house_policy = PolicyStore(streams.root).active("house_voting")
    tiers = tier_review(streams.root, sample, records)
    triggers = monitoring.evaluate(PolicyStore(streams.root).active("monitoring_rules"), sample, records)
    ctxs = escalation_contexts(streams.root, sample, records, sla_days, triggers)
    escalations = escalation.evaluate(PolicyStore(streams.root).active("escalation_rules"), ctxs)
    clients = {s["stream_id"]: client_escalations(streams.root, s["stream_id"], ctxs, escalations) for s in streams.list()}
    exceptions = [
        {**r, "stream_id": s["stream_id"], "client": s["name"]}
        for s in streams.list()
        for r in open_exceptions(s, clients[s["stream_id"]])
    ]
    drafts = DraftStore(streams.root).list()
    if stream_id == HOUSE:
        stream = {"stream_id": HOUSE, "name": "House program"}
        stages = _house_stages(
            records, sample, house_policy, sla_days, tiers, triggers, escalations, exceptions, drafts
        ) + _house_reporting(streams.list(), records)
    else:
        stream = streams.get(stream_id)
        if stream is None:
            raise KeyError(stream_id)
        policy = stream.get("built_policy") or house_policy
        stages = _house_stages(
            records, sample, policy, sla_days, tiers, triggers, escalations, exceptions, drafts
        ) + _client_stages(
            stream,
            sample,
            house_policy,
            clients[stream_id],
            client_store(streams.root, stream_id).active_version("escalation_rules"),
        )
    return {
        "stream": {k: stream[k] for k in ("stream_id", "name")} | {"mandate": stream.get("client_policy", {}).get("mandate")},
        "data_note": "Meeting and company data are a synthetic sample (fictional companies); engagement data is live.",
        "stages": stages,
        "edges": EDGES,
    }


def client_store(root: Path, stream_id: str) -> PolicyStore:
    StreamStore(root)._path(stream_id)  # validates the id before it becomes a path
    return PolicyStore(root / "clients" / stream_id, client=True)


def client_escalations(root: Path, stream_id: str, ctxs: list[dict], house: list[dict]) -> list[dict]:
    graph = client_store(root, stream_id).active("escalation_rules")
    return escalation.client_evaluate(graph, ctxs, house)


def open_exceptions(stream: dict, results: list[dict]) -> list[dict]:
    """Live engagements where the client's step is above the house's and the house
    has not yet decided on that step."""
    decided = {(d["issue_id"], d["client_step"]) for d in stream.get("exception_decisions", [])}
    return [r for r in results if r["higher"] and r["source"] == "live" and (r["issue_id"], r["recommended"]) not in decided]


def escalation_contexts(
    root: Path, sample: dict, records: list[EngagementRecord], sla_days: int, triggers: list[dict] | None = None
) -> list[dict]:
    """Engagement contexts for the escalation rules: the confirmed tier where there is
    one, else the proposed tier, and the triggers of the active monitoring rules."""
    store = PolicyStore(root)
    if triggers is None:
        triggers = monitoring.evaluate(store.active("monitoring_rules"), sample, records)
    return escalation.contexts(sample, records, current_tiers(root, sample, records), triggers, sla_days)


def current_tiers(root: Path, sample: dict, records: list[EngagementRecord]) -> dict[str, str]:
    """The tier per issuer: the confirmed one where there is one, else the proposed one."""
    proposals = evaluate_tiers(PolicyStore(root).active("coverage_rules"), tier_contexts(sample, records))
    return {p["issuer_id"]: p["tier"] for p in proposals} | {i: r["tier"] for i, r in TierStore(root).latest().items()}


def tier_review(root: Path, sample: dict, records: list[EngagementRecord]) -> dict:
    proposals = evaluate_tiers(PolicyStore(root).active("coverage_rules"), tier_contexts(sample, records))
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
