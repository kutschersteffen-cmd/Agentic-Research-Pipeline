"""Policy review: compare an envisioned custom client voting policy with the
house policy, issue by issue, and return a structured difference register.

Deterministic, no LLM: both policies arrive as positions on the shared
issue catalogue (`data/policy_issue_catalogue.json`), so alignment is an
exact join on `issue_id` and "stricter/looser" comes from the direction
each catalogue parameter declares. Reading a client's written guidelines
into positions is an upstream step (the extraction engine); this module
starts from positions.

Stricter means more demanding of the company, i.e. more votes against
management. See docs/STEWARDSHIP_OPERATING_MODEL.md, section 5.7.

    python -m arp.stewardship.policy_review data/examples/client_policy_example.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"

# How strongly an action opposes management, for issues on management
# proposals. Inverted for shareholder-proposal issues, where "for" opposes
# management.
_ACTION_RANK = {"for": 0, "abstain": 1, "case_by_case": 1, "escalate": 1, "against": 2}
_POOLED = {"CCF", "ETF"}


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def _param_change(spec: dict, house: Any, client: Any) -> str | None:
    if house == client:
        return None
    direction = spec.get("stricter")
    if direction is None:
        return "changed"
    if house is None:  # client applies a parameter the house leaves unset
        return "stricter"
    if client is None:
        return "looser"
    if spec["type"] == "bool":
        return "stricter" if client == direction else "looser"
    higher = client > house
    return "stricter" if higher == (direction == "higher") else "looser"


def _opposes_management(issue: dict, action: str) -> int:
    rank = _ACTION_RANK[action]
    if all(r.startswith("shareholder_proposal") for r in issue["resolution_categories"]):
        return 2 - rank
    return rank


def _classify(issue: dict, house: dict, client: dict) -> tuple[str, list[dict]]:
    changes: list[dict] = []
    if client["action"] != house["action"]:
        changes.append({"field": "action", "house": house["action"], "client": client["action"]})
    if client["vote_target"] != house["vote_target"]:
        changes.append({"field": "vote_target", "house": house["vote_target"], "client": client["vote_target"]})
    param_kinds = []
    for name, spec in issue["parameters"].items():
        kind = _param_change(spec, house["parameters"].get(name), client["parameters"].get(name))
        if kind:
            param_kinds.append(kind)
            changes.append(
                {
                    "field": name,
                    "house": house["parameters"].get(name),
                    "client": client["parameters"].get(name),
                    "direction": kind,
                }
            )
    if client["scope"] != house["scope"]:
        changes.append({"field": "scope", "house": house["scope"], "client": client["scope"]})

    if client["action"] != house["action"]:
        return "different_action", changes
    directional = {k for k in param_kinds if k != "changed"}
    if directional == {"stricter"}:
        return "stricter", changes
    if directional == {"looser"}:
        return "looser", changes
    if directional:
        return "mixed", changes
    if param_kinds:
        return "changed", changes
    if client["vote_target"] != house["vote_target"]:
        return "different_target", changes
    if client["scope"] != house["scope"]:
        return "scope_change", changes
    return "identical", changes


def _direction(issue: dict, kind: str, house: dict, client: dict) -> str:
    if kind == "different_action":
        delta = _opposes_management(issue, client["action"]) - _opposes_management(issue, house["action"])
        return "more_against_management" if delta > 0 else "fewer_against_management" if delta < 0 else "different"
    return {"stricter": "more_against_management", "looser": "fewer_against_management"}.get(kind, "different")


def _assess(issue: dict, kind: str, house: dict, client: dict, changes: list[dict], mandate: dict) -> dict:
    flags: list[str] = []
    vehicle = mandate.get("vehicle_type")
    process_only = {n for n, spec in issue["parameters"].items() if spec.get("affects_vote") is False}
    if {c["field"] for c in changes} <= process_only:
        split = "none"
    else:
        split = "not_deliverable" if vehicle in _POOLED else "separate_vote_required"
    if split == "not_deliverable":
        flags.append(f"Deviating votes cannot be cast separately in a pooled {vehicle}.")
    changed_fields = {c["field"] for c in changes}
    if any("threshold" in f for f in changed_fields) and any(d.startswith("score.") for d in issue["data_fields"]):
        flags.append("Threshold set on a placeholder score whose scale is not yet defined.")
    if house["action"] == "escalate" and client["action"] != "escalate":
        flags.append("Bypasses the house engagement-first sequence (house escalates through engagement before voting).")
    if issue["category"] == "stewardship" or client["action"] == "escalate":
        flags.append("Engagement-linked: check pressure-type engagement rules (E6).")
    effort = []
    if client["action"] == "case_by_case" and house["action"] != "case_by_case":
        effort.append("Manual review of every affected resolution.")
    if client["action"] == "escalate" and house["action"] != "escalate":
        effort.append("Engagement capacity before any vote.")

    if split == "not_deliverable":
        recommendation = "decline_or_change_vehicle"
    elif "Threshold set on a placeholder score whose scale is not yet defined." in flags:
        recommendation = "adopt_when_scale_defined"
    elif house["action"] == "escalate" and client["action"] != "escalate":
        recommendation = "adopt_with_modification"
    elif (
        issue["category"] == "stewardship"
        or client["action"] == "escalate"
        or kind in ("looser", "mixed")
        or _direction(issue, kind, house, client) == "fewer_against_management"
    ):
        recommendation = "review_with_house"
    else:
        recommendation = "adopt"
    return {
        "direction": _direction(issue, kind, house, client),
        "split_vote": split,
        "data_fields": issue["data_fields"],
        "effort": effort,
        "flags": flags,
        "impact": None,  # needs ingested voting history; see back-test in section 5.2
        "recommendation": recommendation,
    }


def review(client_policy: dict, house_policy: dict | None = None, catalogue: dict | None = None) -> dict:
    catalogue = catalogue or load("policy_issue_catalogue.json")
    house_policy = house_policy or load("house_voting_policy_draft.json")
    issues = {i["issue_id"]: i for i in catalogue["issues"]}
    house = {p["issue_id"]: p for p in house_policy["positions"]}
    client = {p["issue_id"]: p for p in client_policy.get("positions", [])}
    unclear = {u["issue_id"]: u for u in client_policy.get("unclear", [])}
    mandate = client_policy.get("mandate", {})
    unknown = (set(client) | set(unclear)) - set(issues)
    if unknown:
        raise ValueError(f"Issues not in the catalogue: {sorted(unknown)}")

    register: list[dict] = []
    for issue_id, issue in issues.items():
        h = house.get(issue_id)
        row = {"issue_id": issue_id, "category": issue["category"], "title": issue["title"]}
        if issue_id in unclear:
            u = unclear[issue_id]
            register.append(
                {
                    **row,
                    "kind": "unclear",
                    "source": u.get("source"),
                    "question": u["question"],
                    "assessment": {"recommendation": "clarify"},
                    "decision": None,
                }
            )
            continue
        if issue_id not in client:
            register.append({**row, "kind": "house_only" if h else "no_position", "decision": None})
            continue
        c = client[issue_id]
        if h is None:
            register.append(
                {
                    **row,
                    "kind": "client_only",
                    "client_position": c,
                    "assessment": {"recommendation": "review_with_house"},
                    "decision": None,
                }
            )
            continue
        # A questionnaire states only what differs; the rest is the house value.
        merged = {
            "action": c.get("action", h["action"]),
            "vote_target": c.get("vote_target", h["vote_target"]),
            "parameters": {**h["parameters"], **c.get("parameters", {})},
            "scope": c.get("scope", h["scope"]),
        }
        kind, changes = _classify(issue, h, merged)
        entry = {**row, "kind": kind, "source": c.get("source"), "changes": changes, "decision": None}
        if kind != "identical":
            entry["assessment"] = _assess(issue, kind, h, merged, changes, mandate)
        register.append(entry)
    for i, u in enumerate(client_policy.get("unmapped", []), 1):
        register.append(
            {
                "issue_id": f"unmapped.{i}",
                "category": "unmapped",
                "title": u.get("suggested_issue", ""),
                "kind": "unmapped",
                "source": u["source"],
                "assessment": {"recommendation": "clarify_or_add_issue"},
                "decision": None,
            }
        )

    return {
        "client": client_policy.get("client"),
        "client_policy_id": client_policy.get("policy_id"),
        "house_policy": f"{house_policy['policy_id']} {house_policy['version']}",
        "catalogue_version": catalogue["version"],
        "mandate": mandate,
        "summary": {
            "by_kind": dict(Counter(r["kind"] for r in register)),
            "by_recommendation": dict(Counter(r["assessment"]["recommendation"] for r in register if "assessment" in r)),
            "separate_vote_required": sum(
                1 for r in register if r.get("assessment", {}).get("split_vote") == "separate_vote_required"
            ),
            "not_deliverable": sum(1 for r in register if r.get("assessment", {}).get("split_vote") == "not_deliverable"),
            "differences_by_category": dict(
                Counter(r["category"] for r in register if r["kind"] not in ("identical", "house_only", "no_position"))
            ),
        },
        "register": register,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_fmt(v)}" for k, v in value.items())
    return str(value)


def to_markdown(result: dict) -> str:
    s = result["summary"]
    lines = [
        f"**Client:** {result['client']} · **Client policy:** `{result['client_policy_id']}` · "
        f"**House policy:** `{result['house_policy']}` · **Catalogue:** `{result['catalogue_version']}` · "
        f"**Mandate:** {_fmt(result['mandate'])}",
        "",
        f"Differences that change how the client's shares are voted: **{s['separate_vote_required']}** need a separate vote "
        f"of the client's shares, **{s['not_deliverable']}** cannot be delivered in a pooled vehicle. "
        "Impact per difference (resolutions affected) is not computed yet: it needs ingested voting history.",
        "",
        "| Kind | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(s["by_kind"].items(), key=lambda kv: -kv[1])],
        "",
        "| Recommendation | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(s["by_recommendation"].items(), key=lambda kv: -kv[1])],
        "",
        "### Difference register",
        "",
        "| Issue | Kind | Changes (house → client) | Direction | Flags | Recommendation |",
        "|---|---|---|---|---|---|",
    ]
    for r in result["register"]:
        if r["kind"] in ("identical", "house_only", "no_position", "unclear", "unmapped"):
            continue
        a = r.get("assessment", {})
        changes = "<br>".join(f"`{c['field']}`: {_fmt(c['house'])} → {_fmt(c['client'])}" for c in r.get("changes", []))
        flags = "<br>".join(a.get("flags", []) + a.get("effort", [])) or "—"
        lines.append(
            f"| `{r['issue_id']}` | {r['kind']} | {changes} | {a.get('direction', '—')} | {flags} | **{a['recommendation']}** |"
        )
    unclear = [r for r in result["register"] if r["kind"] == "unclear"]
    if unclear:
        lines += ["", "### Questions for the client (unclear)", "", "| Issue | Client text | Question |", "|---|---|---|"]
        lines += [f"| `{r['issue_id']}` | {r['source']} | {r['question']} |" for r in unclear]
    unmapped = [r for r in result["register"] if r["kind"] == "unmapped"]
    if unmapped:
        lines += ["", "### Unmapped client clauses", "", "| Client text | Suggested catalogue issue |", "|---|---|"]
        lines += [f"| {r['source']} | `{r['title']}` |" for r in unmapped]
    same = [r["issue_id"] for r in result["register"] if r["kind"] == "identical"]
    inherited = [r["issue_id"] for r in result["register"] if r["kind"] == "house_only"]
    lines += [
        "",
        f"**Identical to house ({len(same)}):** " + (", ".join(f"`{i}`" for i in same) or "—"),
        "",
        f"**Client silent, inherits house ({len(inherited)}):** " + ", ".join(f"`{i}`" for i in inherited),
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    result = review(json.loads(Path(sys.argv[1]).read_text()))
    print(to_markdown(result) if "--json" not in sys.argv else json.dumps(result, indent=2))
