"""The credibility preset: the Stewardship Committee deck's five-question
test, class tree, red-flag cap, outlook and action, written as a rule graph
over an indicator list (docs/superpowers/specs/2026-10-01-credibility-from-indicator-list.md).

All grade logic lives in the rule graph, where values keep their types; the
tier graph only maps the letter to a tier. A calculated column holding only
0/1 would reach the tier graph as a boolean."""

from __future__ import annotations

from arp.decision.roles import slug
from arp.schemas.decision import AuditEntry, IndicatorSpec, MechanismConfig, TierDefinition

TIERS = ["A Credible", "B Credible, gaps", "C Partial", "D Not credible", "E Opaque"]


def level_expr(spec: IndicatorSpec) -> str:
    """The indicator's level on its scale; blank is the bottom (0 = absent)."""
    lo, hi = spec.scale_min, spec.scale_max
    if spec.direction == "lower":
        return f"({hi + lo} - number({slug(spec.id)} ?? {hi}))"
    return f"number({slug(spec.id)} ?? {lo})"


def _graph(name: str, expressions: list[tuple[str, str]]) -> dict:
    def node(node_id: str, kind: str, **content) -> dict:
        return {"id": node_id, "type": kind, "name": node_id, "position": {"x": 0, "y": 0}, **({"content": content} if content else {})}

    return {
        "nodes": [
            node("in", "inputNode"),
            node(name, "expressionNode", expressions=[{"id": k, "key": k, "value": v} for k, v in expressions]),
            node("out", "outputNode"),
        ],
        "edges": [
            {"id": "in-calc", "sourceId": "in", "targetId": name, "type": "edge"},
            {"id": "calc-out", "sourceId": name, "targetId": "out", "type": "edge"},
        ],
    }


def _ternary(cases: list[tuple[str, str]], otherwise: str) -> str:
    out = otherwise
    for when, then in reversed(cases):
        out = f"({when} ? {then} : {out})"
    return out


def apply_preset(config: MechanismConfig, specs: list[IndicatorSpec], audit: list[AuditEntry]) -> MechanismConfig:
    indicators = [s for s in specs if s.kind == "indicator"]
    lo, hi = indicators[0].scale_min, indicators[0].scale_max
    questions = sorted({s.question for s in indicators if s.question})
    q = [f"q{i + 1}" for i in range(5)]
    ex: list[tuple[str, str]] = []
    for key, label in zip(q, questions, strict=True):
        levels = [level_expr(s) for s in indicators if s.question == label]
        ex.append((f"{key}_pct", f"({' + '.join(levels)}) / {len(levels) * hi} * 100"))
        all_top = " and ".join(f"{v} == {hi}" for v in levels)
        any_low = " or ".join(f"{v} <= {lo + 1}" for v in levels)
        ex.append((f"{key}_answer", f"{all_top} ? 'Yes' : ({any_low} ? 'No' : 'Partly')"))
        audit.append(AuditEntry(stage="Indicator list", item=f"Question {label}", decision=key.upper(), why="Indicators: " + ", ".join(s.id for s in indicators if s.question == label)))
    answers = "[" + ", ".join(f"$.{k}_answer" for k in q) + "]"
    critical = "[" + ", ".join(level_expr(s) for s in indicators if s.critical) + "]"
    at_zero, at_low = f"len(filter({critical}, # == {lo}))", f"len(filter({critical}, # <= {lo + 1}))"
    def said_yes(s: IndicatorSpec) -> str:  # boolean when the column profiles as Yes/No, text when it does not
        return f"({slug(s.id)} == true or lower(string({slug(s.id)} ?? '')) == 'yes')"

    negative = " or ".join(said_yes(s) for s in specs if s.outlook == "Negative") or "false"
    watch = " or ".join(said_yes(s) for s in specs if s.outlook == "Watch") or "false"
    ex += [
        ("no_count", f"len(filter({answers}, # == 'No'))"),
        ("yes_count", f"len(filter({answers}, # == 'Yes'))"),
        ("verdict", "$.no_count > 0 ? 'Not credible' : ($.yes_count == 5 ? 'Credible' : 'Partly credible')"),
        (
            "tree_class",
            _ternary(
                [
                    ("$.q1_pct < 50", "5"),
                    (f"{at_zero} > 0", "4"),
                    ("$.q2_pct >= 60 and $.q3_pct >= 60", "($.q5_pct >= 70 ? 1 : 2)"),
                    ("$.q2_pct >= 60 or $.q3_pct >= 60", "3"),
                ],
                "4",
            ),
        ),
        ("cap_class", _ternary([(f"{at_zero} >= 2", "4"), (f"{at_zero} == 1", "3"), (f"{at_low} >= 2", "3"), (f"{at_low} == 1", "2")], "1")),
        ("grade", _ternary([(f"max([$.tree_class, $.cap_class]) == {i + 1}", f"'{t[0]}'") for i, t in enumerate(TIERS[:4])], "'E'")),
        ("outlook", f"{negative} ? 'Negative' : ({watch} ? 'Watch' : 'Stable')"),
        (
            "action",
            _ternary(
                [
                    ("($.grade == 'D' or $.grade == 'E') and $.outlook == 'Negative'", "'Escalate: voting sanctions, support climate resolutions'"),
                    ("$.grade == 'D' or $.grade == 'E'", "'Escalate: formal engagement, 12-month milestones'"),
                    ("$.grade == 'C'", "'Engage intensively; review in 12 months'"),
                    ("$.grade == 'A' and $.outlook == 'Stable'", "'Maintain: best-practice reference'"),
                    ("$.grade == 'A'", "'Maintain + targeted ask'"),
                    ("$.outlook == 'Stable'", "'Engage: routine'"),
                ],
                "'Engage on flagged issue'",
            ),
        ),
        ("note", "$.verdict + ' (' + string($.no_count) + ' No, ' + string($.yes_count) + ' Yes) · Outlook ' + $.outlook + ' · ' + $.action"),
    ]
    for view in sorted({v for s in indicators for v in s.views}):
        weighted = [(s.views[view], level_expr(s)) for s in indicators if s.views.get(view, 0) > 0]
        total = sum(w for w, _ in weighted)
        if not total:
            continue
        ex.append((f"view_{slug(view)}_pct", f"({' + '.join(f'{w:g} * {v}' for w, v in weighted)}) / {hi * total:g} * 100"))
    audit += [
        AuditEntry(stage="Indicator list", item="Critical indicators", decision=", ".join(s.id for s in indicators if s.critical) or "none", why="A critical at the bottom of the scale caps the grade."),
        AuditEntry(stage="Indicator list", item="Cut-points", decision="unused", why="The grade sets the tier; every score lands in band 1 and the tier rules move it down."),
    ]
    tier = _ternary([(f"grade == '{t[0]}'", str(i + 1)) for i, t in enumerate(TIERS[:4])], "5")
    return config.model_copy(
        update={
            "rule_graph": _graph("credibility", ex),
            "tier_graph": _graph("grade", [("tier", tier), ("note", "note")]),
            "tiers": [TierDefinition(rank=i + 1, name=t) for i, t in enumerate(TIERS)],
            # ponytail: score bands are unused, the tier graph grades; real cuts if the preset ever ranks by score
            "pinned_cuts": [0, 0, 0, 0],
        }
    )
