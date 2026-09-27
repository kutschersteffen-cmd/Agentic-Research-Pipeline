"""Generates an executable ZEN (GoRules JDM) graph from a voting policy's
positions, for the `vote_expectation` domain: given one resolution and its
context, what vote does the policy expect?

The graph has three nodes between input and output:

1. `conditions` (expression node): one boolean per position -- does it fire
   on this resolution? Resolution category, vote target, scope and the
   issue's red-flag condition, with the policy's parameter values written in
   as literals, so an analyst sees and edits `< 66` directly in the editor.
2. `votes` (decision table, hit policy `collect`): one row per position,
   `_id` = issue id, outputting the vote. Collected under `hits`.
3. `decision` (expression node): the expected vote by precedence
   (against > case_by_case > abstain > for), or management's recommendation
   when nothing fired, plus the issues that decided it.

Positions with action `escalate` produce no row: they act through engagement,
and vote only via `stewardship.engagement_escalation`.

Context contract (one evaluation per resolution):

    issuer:      company data, nested by field id (`governance.board_independence_pct`
                 -> issuer.governance.board_independence_pct), plus `region`, `sector`
    resolution:  category, management_recommendation, topic (shareholder proposals),
                 roles (director elections: e.g. ["board_chair"]), director {independent,
                 committee_member, is_executive, mandates, chair_mandates, attendance_pct},
                 is_bundled, size_pct, preemptive_rights, max_premium_pct, duration_years,
                 creates_unequal_voting, allows_virtual_only, independent_review,
                 value_pct_of_assets, introduces_supermajority, prescriptive
    engagement:  per theme: {at_vote_step, months_without_progress}, e.g.
                 engagement.climate_transition.at_vote_step

A missing value never fires a rule: every comparison is guarded, because ZEN
fails the whole evaluation on a comparison with null.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import cache
from typing import Any

import zen

from arp.stewardship.policy_review import load

# --- expression helpers -------------------------------------------------------


def _lit(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return "'" + v.replace("'", "") + "'"
    if isinstance(v, list):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    return str(v)


def _cmp(path: str, op: str, v: Any) -> str:
    return "false" if v is None else f"({path} != null and {path} {op} {_lit(v)})"


def _is(path: str, v: Any = True) -> str:
    return f"{path} == {_lit(v)}"


def _when(flag: Any, expr: str) -> str:
    return expr if flag else "false"


def _any(*xs: str) -> str:
    xs = tuple(x for x in xs if x != "false")
    if "true" in xs:
        return "true"
    return "false" if not xs else xs[0] if len(xs) == 1 else "(" + " or ".join(xs) + ")"


def _all(*xs: str) -> str:
    if "false" in xs:
        return "false"
    xs = tuple(x for x in xs if x != "true")
    return "true" if not xs else xs[0] if len(xs) == 1 else "(" + " and ".join(xs) + ")"


class _Params(dict):
    """Records which parameters a template reads, to report unused ones."""

    def __init__(self, values: dict) -> None:
        super().__init__(values)
        self.read: set[str] = set()

    def __getitem__(self, key: str) -> Any:
        self.read.add(key)
        return self.get(key)


G, P, A, C, D, R = "issuer.governance", "issuer.pay", "issuer.audit", "issuer.climate", "resolution.director", "resolution"

# --- red-flag conditions per issue --------------------------------------------
# For `against`/`abstain`/`case_by_case` positions the condition is the red
# flag that triggers the vote; for `for` positions it is the gate for support.

_CONDITIONS: dict[str, Callable[[_Params], str]] = {
    "board.independence": lambda p: _any(
        _all(_is(f"{G}.controlled_company"), _cmp(f"{G}.board_independence_pct", "<", p["controlled_company_min_pct"])),
        _all(f"{G}.controlled_company != true", _cmp(f"{G}.board_independence_pct", "<", p["min_independent_pct"])),
    ),
    "board.committee_independence": lambda p: _any(
        _cmp(f"{G}.audit_committee_independence_pct", "<", p["audit_min_independent_pct"]),
        _cmp(f"{G}.remuneration_committee_independence_pct", "<", p["remuneration_min_independent_pct"]),
        _cmp(f"{G}.nomination_committee_independence_pct", "<", p["nomination_min_independent_pct"]),
    ),
    "board.chair_ceo_separation": lambda p: _any(
        _is(f"{G}.chair_ceo_combined")
        if p["require_separation"]
        else _all(_is(f"{G}.chair_ceo_combined"), f"{G}.lead_independent_director != true")
        if p["accept_lead_independent_director"]
        else _is(f"{G}.chair_ceo_combined"),
        _when(p["oppose_former_ceo_as_chair"], _is(f"{G}.chair_is_former_ceo")),
    ),
    "board.overboarding": lambda p: _any(
        _all(
            f"{D}.is_executive != true",
            f"{D}.mandates != null and {D}.chair_mandates != null",
            f"({D}.mandates + {D}.chair_mandates * {_lit((p['chair_counts_as'] or 1) - 1)}) > {_lit(p['max_mandates_non_executive'])}"
            if p["max_mandates_non_executive"] is not None
            else "false",
        ),
        _all(_is(f"{D}.is_executive"), _cmp(f"{D}.mandates", ">", p["max_mandates_executive"])),
    ),
    "board.attendance": lambda p: _cmp(f"{D}.attendance_pct", "<", p["min_attendance_pct"]),
    "board.gender_diversity": lambda p: (
        _cmp(
            f"{G}.board_female_pct",
            "<",
            p["min_underrepresented_gender_pct"],
        )
        if not p["markets_with_higher_threshold"]
        else _any(
            *[
                _all(_is("issuer.region", market), _cmp(f"{G}.board_female_pct", "<", pct))
                for market, pct in p["markets_with_higher_threshold"].items()
            ],
            _all(
                f"not (issuer.region in {_lit(list(p['markets_with_higher_threshold']))})",
                _cmp(f"{G}.board_female_pct", "<", p["min_underrepresented_gender_pct"]),
            ),
        )
    ),
    "board.tenure_refreshment": lambda p: _any(
        _cmp(f"{G}.longest_independent_tenure_years", ">", p["max_tenure_for_independence_years"]),
        _cmp(f"{G}.average_board_tenure_years", ">", p["max_average_tenure_years"]),
    ),
    "board.election_practices": lambda p: _any(
        _when(p["require_annual_election"], _is(f"{G}.staggered_board")),
        _when(p["oppose_bundled_elections"], _is(f"{R}.is_bundled")),
        _when(p["require_majority_voting"], _is(f"{G}.majority_voting", False)),
    ),
    "board.responsiveness": lambda p: _any(
        _all(
            _cmp("issuer.voting.prior_year_dissent_pct", ">", p["dissent_threshold_pct"]),
            _is("issuer.voting.dissent_addressed", False),
        ),
        _when(p["ignore_majority_proposal"], _is("issuer.voting.majority_proposal_not_implemented")),
    ),
    "pay.quantum": lambda p: _any(
        _cmp(f"{P}.ceo_peer_percentile", ">", p["max_peer_percentile"]),
        _cmp(f"{P}.ceo_pay_ratio", ">", p["max_ceo_worker_pay_ratio"]),
    ),
    "pay.performance_alignment": lambda p: _any(
        _cmp(f"{P}.misalignment_years", ">", p["max_misalignment_years"]),
        _cmp(f"{P}.long_term_incentive_pct", "<", p["min_long_term_share_pct"]),
        _cmp(f"{P}.vesting_period_years", "<", p["min_vesting_period_years"]),
    ),
    "pay.esg_metrics": lambda p: _any(
        _when(
            p["require_esg_metric"],
            _any(_is(f"{P}.esg_metric_included", False), _cmp(f"{P}.esg_metric_weight_pct", "<", p["min_esg_weight_pct"])),
        ),
        _when(
            p["require_climate_metric_for_high_emitters"],
            _all(_is(f"{C}.high_emitter"), _is(f"{P}.climate_metric_included", False)),
        ),
    ),
    "pay.equity_plans": lambda p: _any(
        _cmp(f"{P}.plan_dilution_pct", ">", p["max_dilution_pct"]),
        _when(p["oppose_repricing"], _is(f"{P}.repricing_allowed")),
        _cmp(f"{P}.plan_discount_pct", ">", p["max_discount_pct"]),
    ),
    "pay.severance": lambda p: _any(
        _cmp(f"{P}.severance_multiple", ">", p["max_severance_multiple"]),
        _when(p["oppose_single_trigger"], _is(f"{P}.single_trigger_vesting")),
    ),
    "pay.disclosure": lambda p: _any(
        _when(p["require_ex_post_target_disclosure"], _is(f"{P}.targets_disclosed", False)),
        _when(p["oppose_undisclosed_discretion"], _all(_is(f"{P}.discretion_used"), _is(f"{P}.discretion_explained", False))),
    ),
    "pay.non_executive_fees": lambda p: _any(
        _when(p["oppose_performance_pay_for_nonexecs"], _is(f"{P}.nonexec_performance_pay")),
        _cmp(f"{P}.nonexec_fee_change_pct", ">", p["max_fee_increase_pct"]),
    ),
    "audit.non_audit_fees": lambda p: _cmp(f"{A}.non_audit_fee_ratio", ">", p["max_non_audit_to_audit_ratio"]),
    "audit.auditor_tenure": lambda p: _any(
        _cmp(f"{A}.auditor_tenure_years", ">", p["max_auditor_tenure_years"]),
        _when(p["require_tender_disclosure"], _is(f"{A}.tender_disclosed", False)),
    ),
    "audit.financial_statements": lambda p: _any(
        _when(p["oppose_on_qualified_opinion"], _is(f"{A}.qualified_opinion")),
        _when(p["oppose_on_material_weakness"], _is(f"{A}.material_weakness")),
    ),
    "audit.discharge": lambda p: _any(
        _when(p["oppose_on_open_investigation"], _is(f"{G}.open_investigation")),
        _cmp("issuer.controversy.max_severity", ">=", p["min_controversy_severity"]),
    ),
    "capital.share_issuance": lambda p: _any(
        _all(_is(f"{R}.preemptive_rights"), _cmp(f"{R}.size_pct", ">", p["max_with_preemption_pct"])),
        _all(_is(f"{R}.preemptive_rights", False), _cmp(f"{R}.size_pct", ">", p["max_without_preemption_pct"])),
    ),
    "capital.share_buybacks": lambda p: _any(
        _cmp(f"{R}.size_pct", ">", p["max_buyback_pct"]),
        _cmp(f"{R}.max_premium_pct", ">", p["max_premium_pct"]),
        _when(p["oppose_during_takeover"], _is(f"{G}.takeover_period")),
    ),
    "capital.dividend_allocation": lambda p: _any(
        _cmp("issuer.financial.payout_ratio_pct", "<", p["min_payout_ratio_pct"]),
        _cmp("issuer.financial.payout_ratio_pct", ">", p["max_payout_ratio_pct"]),
    ),
    "capital.one_share_one_vote": lambda p: _any(
        _when(p["oppose_new_multiple_voting_classes"], _is(f"{R}.creates_unequal_voting")),
        _all(
            _is(f"{G}.dual_class"),
            f"({G}.dual_class_sunset_years == null or {G}.dual_class_sunset_years > {_lit(p['require_sunset_years'])})",
        )
        if p["require_sunset_years"] is not None
        else "false",
    ),
    "capital.takeover_defences": lambda p: _any(
        _when(p["oppose_poison_pill_without_approval"], _is(f"{G}.poison_pill_unapproved")),
        _cmp(f"{R}.duration_years", ">", p["max_pill_duration_years"]),
    ),
    "capital.related_party_transactions": lambda p: _any(
        _when(p["require_independent_review"], _is(f"{R}.independent_review", False)),
        _cmp(f"{R}.value_pct_of_assets", ">", p["max_value_pct_of_assets"]),
    ),
    "rights.shareholder_rights": lambda p: _when(p["oppose_supermajority"], _is(f"{R}.introduces_supermajority")),
    "rights.virtual_meetings": lambda p: _all(
        _when(p["oppose_virtual_only"], _is(f"{R}.allows_virtual_only")),
        f"{R}.allows_hybrid != true" if p["accept_hybrid"] else "true",
    ),
    "climate.laggard_accountability": lambda p: _all(
        _cmp(f"issuer.{p['score_field']}", "<", p["laggard_threshold"]) if p["score_field"] else "false",
        _is(f"{C}.high_emitter") if p["high_emitters_only"] else "true",
        _cmp("engagement.climate_transition.months_without_progress", ">=", p["min_months_engaged_without_progress"]),
    ),
    "climate.disclosure": lambda p: _any(
        _when(p["require_scope_1_2"], _is(f"{C}.scope1_2_disclosed", False)),
        _when(p["require_scope_3_material"], _is(f"{C}.scope3_disclosed", False)),
        _when(p["require_aligned_framework"], _is(f"{C}.tcfd_aligned", False)),
    ),
    "climate.targets": lambda p: _any(
        _when(p["require_net_zero_target"], _is(f"{C}.net_zero_target", False)),
        _when(p["require_interim_targets"], _is(f"{C}.interim_target", False)),
        _when(p["require_validated_targets"], _is(f"{C}.sbti_validated", False)),
    ),
    "climate.say_on_climate": lambda p: _any(
        _cmp("issuer.score.transition_plan", "<", p["min_plan_score"]),
        _when(p["require_capex_alignment"], _is(f"{C}.capex_alignment_disclosed", False)),
    ),
    "nature.laggard_accountability": lambda p: _all(
        _cmp(f"issuer.{p['score_field']}", "<", p["laggard_threshold"]) if p["score_field"] else "false",
        _is("issuer.nature.high_impact_sector") if p["high_impact_sectors_only"] else "true",
    ),
    "nature.disclosure": lambda p: _when(p["require_tnfd_aligned"], _is("issuer.nature.tnfd_aligned", False)),
    "social.human_rights": lambda p: _any(
        _cmp("issuer.controversy.human_rights_severity", ">=", p["min_controversy_severity"]),
        _when(p["ungc_fail_triggers_action"], _is("issuer.controversy.ungc_status", "fail")),
    ),
    "social.workforce": lambda p: _all(
        _is(f"{R}.topic", "workforce"), _when(p["support_workforce_disclosure_proposals"], "true")
    ),
    "gov.controversy_accountability": lambda p: _cmp(
        "issuer.controversy.governance_severity", ">=", p["min_controversy_severity"]
    ),
    "gov.lobbying_political": lambda p: _all(
        _is(f"{R}.topic", "lobbying"),
        _any(_when(p["support_lobbying_disclosure"], "true"), _when(p["require_climate_lobbying_alignment"], "true")),
    ),
    "gov.tax_transparency": lambda p: _all(_is(f"{R}.topic", "tax"), _when(p["support_cbcr_proposals"], "true")),
    "stewardship.engagement_escalation": lambda p: _any(
        *[
            _all(_is(f"engagement.{theme}.at_vote_step"), _target(target))
            for theme, target in (p["target_by_theme"] or {}).items()
        ]
    ),
}

# Issues whose vote is a stance (`default_action`) rather than a red flag.
_STANCE_VOTES = {
    "support_if_reasonable": "'for'",
    "follow_management": "resolution.management_recommendation ?? 'for'",
    "case_by_case": "'case_by_case'",
    "against_on_red_flag": "'for'",  # red flags come from the other remuneration issues
}

# Stance issues fire on every resolution they govern; these parameters turn
# the stance into a vote against when their condition holds.
_AGAINST_OVERRIDES: dict[str, Callable[[_Params], str]] = {
    "climate.shareholder_proposals": lambda p: _when(p["oppose_if_prescriptive"], _is(f"{R}.prescriptive")),
    "capital.mergers_acquisitions": lambda p: _when(p["require_fairness_opinion"], _is(f"{R}.fairness_opinion", False)),
}

# --- targets and scope ----------------------------------------------------------

_DIRECTOR_TARGETS = {
    "non_independent_nominees": f"{D}.independent == false",
    "non_independent_committee_members": f"({D}.independent == false and {D}.committee_member == true)",
    "overboarded_director": "true",  # the condition itself is about this director
    "low_attendance_director": "true",
    "long_tenured_director": "true",
    "bundled_slate": f"{R}.is_bundled == true",
    "committee_chair_responsible": f"({R}.roles != null and some({R}.roles, # in "
    "['audit_committee_chair', 'remuneration_committee_chair', 'nomination_committee_chair']))",
    "other": "true",
}
_ROLE_ALIASES = {"combined_chair_ceo": "board_chair"}


@cache
def _resolution_categories() -> frozenset[str]:
    return frozenset(load("policy_issue_catalogue.json")["resolution_categories"])


def _target(target: str) -> str:
    if target in _DIRECTOR_TARGETS:
        return _DIRECTOR_TARGETS[target]
    if target in _resolution_categories():
        return _is(f"{R}.category", target)
    role = _ROLE_ALIASES.get(target, target)
    return f"({R}.roles != null and contains({R}.roles, {_lit(role)}))"


def _scope(scope: dict) -> str:
    parts = []
    markets = scope.get("markets", "all")
    if markets != "all":
        parts.append(f"issuer.region in {_lit(markets)}")
    sectors = scope.get("sectors")
    if sectors == "high_emitters":
        parts.append(_is(f"{C}.high_emitter"))
    elif sectors == "high_impact_nature":
        parts.append(_is("issuer.nature.high_impact_sector"))
    elif sectors:
        parts.append(f"issuer.sector in {_lit(sectors)}")
    return _all(*parts) if parts else "true"


# --- graph ----------------------------------------------------------------------


def _slug(issue_id: str) -> str:
    return issue_id.replace(".", "_")


def _node(node_id: str, node_type: str, x: int, **content: Any) -> dict:
    node = {"id": node_id, "type": node_type, "name": node_id, "position": {"x": x, "y": 100}}
    if content:
        node["content"] = {"passThrough": True, "inputField": None, "outputPath": None, "executionMode": "single", **content}
    return node


def _position_rule(issue: dict, position: dict) -> tuple[str, str, set[str]] | None:
    """(fire expression, vote expression, parameters read), or None when the
    position has no direct vote effect."""
    if position["action"] == "escalate":
        return None
    params = _Params(position["parameters"])
    issue_id = issue["issue_id"]
    applies = f"{R}.category in {_lit(issue['resolution_categories'])}"
    target = "true" if issue_id == "stewardship.engagement_escalation" else _target(position["vote_target"])
    in_scope = _all(applies, target, _scope(position["scope"]))

    if "default_action" in issue["parameters"]:  # a stance: fires on every resolution it governs
        # The action is the vote; only `for` is refined by the stance (support if
        # reasonable, follow management, for unless a red flag). Against, abstain and
        # case-by-case are votes in their own right, and then default_action is unused.
        if position["action"] in ("against", "abstain", "case_by_case"):
            vote = _lit(position["action"])
            if position["parameters"].get("default_action") == position["action"]:
                params["default_action"]  # agrees with the action, so it is not an unused parameter
        else:
            vote = _STANCE_VOTES.get(params["default_action"], _lit(params["default_action"]))
        against = position["action"] == "against"
        override = _AGAINST_OVERRIDES[issue_id](params) if issue_id in _AGAINST_OVERRIDES and not against else "false"
        if override != "false":
            vote = f"{override} ? 'against' : {vote}"
        return in_scope, vote, params.read
    condition = _CONDITIONS[issue_id](params) if issue_id in _CONDITIONS else "true"
    return _all(in_scope, condition), _lit(position["action"]), params.read


def generate(policy: dict, catalogue: dict | None = None) -> dict:
    """The JDM graph for a voting policy, plus a report of what did not become a rule."""
    catalogue = catalogue or load("policy_issue_catalogue.json")
    issues = {i["issue_id"]: i for i in catalogue["issues"]}
    expressions, rows, no_vote_effect, unused = [], [], [], {}
    for position in policy["positions"]:
        issue = issues[position["issue_id"]]
        rule = _position_rule(issue, position)
        if rule is None:
            no_vote_effect.append(position["issue_id"])
            continue
        fire, vote, read = rule
        key = f"c.{_slug(issue['issue_id'])}"
        expressions.append({"id": _slug(issue["issue_id"]), "key": key, "value": fire})
        rows.append(
            {
                "_id": issue["issue_id"],
                "_description": position.get("rationale", ""),
                "i1": f"{key} == true",
                "o1": vote,
                "o2": _lit(issue["issue_id"]),
            }
        )
        extra = sorted(set(position["parameters"]) - read)
        if extra:
            unused[issue["issue_id"]] = extra

    decision = (
        "len(hits) == 0 ? (resolution.management_recommendation ?? 'for') : "
        "some(hits, #.vote == 'against') ? 'against' : "
        "some(hits, #.vote == 'case_by_case') ? 'case_by_case' : "
        "some(hits, #.vote == 'abstain') ? 'abstain' : hits[0].vote"
    )
    nodes = [
        _node("input", "inputNode", 0),
        _node("conditions", "expressionNode", 300, expressions=expressions),
        _node(
            "votes",
            "decisionTableNode",
            600,
            hitPolicy="collect",
            outputPath="hits",
            inputs=[{"id": "i1", "name": "Position fires"}],
            outputs=[{"id": "o1", "name": "Vote", "field": "vote"}, {"id": "o2", "name": "Issue", "field": "issue_id"}],
            rules=rows,
        ),
        _node(
            "decision",
            "expressionNode",
            900,
            passThrough=False,
            expressions=[
                {"id": "expected_vote", "key": "expected_vote", "value": decision},
                {"id": "decided_by", "key": "decided_by", "value": "map(filter(hits, #.vote == $.expected_vote), #.issue_id)"},
                {"id": "all_hits", "key": "all_hits", "value": "hits"},
            ],
        ),
        _node("output", "outputNode", 1200),
    ]
    order = [n["id"] for n in nodes]
    edges = [{"id": f"{a}-{b}", "sourceId": a, "targetId": b, "type": "edge"} for a, b in zip(order, order[1:], strict=False)]
    return {
        "graph": {"nodes": nodes, "edges": edges},
        "policy_id": policy["policy_id"],
        "rules": len(rows),
        "no_vote_effect": no_vote_effect,
        "unused_parameters": unused,
    }


def issuer_fields(issue_id: str) -> list[str]:
    """Company data fields an issue's condition can read, across parameter
    settings: what the field catalogue must provide for the issue."""
    issue = next(i for i in load("policy_issue_catalogue.json")["issues"] if i["issue_id"] == issue_id)
    if issue_id not in _CONDITIONS:
        return []
    fields: set[str] = set()
    for flag in (True, False):
        values = {}
        for name, spec in issue["parameters"].items():
            values[name] = {
                "bool": flag,
                "number": 1,
                "enum": (spec.get("values") or [None])[0],
                "map": {"x": "board_chair"} if name == "target_by_theme" else {"EU": 1},
                "field": "score.x",
            }[spec["type"]]
        expr = _CONDITIONS[issue_id](_Params(values))
        fields |= set(re.findall(r"issuer\.([a-z0-9_]+(?:\.[a-z0-9_]+)*)", expr))
    fields.discard("score.x")
    return sorted(fields)


def evaluate(graph: dict, contexts: list[dict]) -> list[dict]:
    """Expected vote per resolution context. Raises ValueError if the graph does not compile."""
    content = json.dumps(graph)
    try:
        zen.ZenEngine().create_decision(content).validate()
    except RuntimeError as exc:
        raise ValueError(f"Policy graph does not compile: {exc}") from exc
    engine = zen.ZenEngine({"loader": lambda _key: content})
    return [engine.evaluate("policy", c)["result"] for c in contexts]


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate the ZEN graph for a voting policy.")
    parser.add_argument("policy", type=Path, help="A policy with positions (house draft or built client policy)")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the JDM graph")
    args = parser.parse_args()
    result = generate(json.loads(args.policy.read_text()))
    evaluate(result["graph"], [])  # compile check
    args.out.write_text(json.dumps(result["graph"], indent=2, ensure_ascii=False) + "\n")
    print(f"{result['policy_id']}: {result['rules']} rules -> {args.out}")
    if result["no_vote_effect"]:
        print("No direct vote rule (act through engagement):", ", ".join(result["no_vote_effect"]))
    for issue_id, params in result["unused_parameters"].items():
        print(f"Not part of the vote rule: {issue_id}: {', '.join(params)}")
