"""Builds framework.json: the 'Logic of targets' sheet (Q2.1.1-Q2.1.5) as a
Decision Studio framework. Format and column meanings: README.md here.

Run from backend/:  PYTHONPATH=. python3 ../docs/decision-studio/example-framework/targets/build.py

Each question takes its answer from the first source with information
(SBTi -> MSCI -> TPI/CA100+ -> WBA -> CDP). A source's Yes or No ends the
waterfall; a blank cell is "No info" and passes to the next source.
"""

from __future__ import annotations

import json
from pathlib import Path

from arp.decision.templates import export_template
from arp.schemas.decision import AuditEntry, Dimension, LevelCriterion, LevelRule, MechanismConfig, TierDefinition

HERE = Path(__file__).resolve().parent

QUESTIONS = {
    "Q2.1.1": "Has the company set quantitative GHG emissions-reduction targets?",
    "Q2.1.2": "Does the company have at least one interim target for 2029-2035?",
    "Q2.1.3": "Do the interim targets cover at least 95% of Scope 1 and Scope 2 emissions?",
    "Q2.1.4": "Does the company have Scope 3 targets, where appropriate?",
    "Q2.1.5": "Are the company's GHG emissions-reduction targets explicitly validated or assessed as aligned with a 1.5°C or well-below-2°C pathway?",
}

TIERS = ["Aligned targets", "Targets, alignment not shown", "Partial targets", "No targets", "No information"]


def yes(c: str) -> str:  # a Yes/No column profiles as boolean, or stays text if it has odd values
    return f"({c} == true or lower(string({c} ?? '')) == 'yes')"


def no(c: str) -> str:
    return f"({c} == false or lower(string({c} ?? '')) == 'no')"


def step(c: str) -> str:
    return f"({yes(c)} ? 'Yes' : ({no(c)} ? 'No' : 'No info'))"


def either(a: str, b: str) -> str:
    return f"(({yes(a)} or {yes(b)}) ? 'Yes' : (({no(a)} or {no(b)}) ? 'No' : 'No info'))"


SBTI = (
    "(lower(string(sbti_near_term_status ?? '')) == 'targets set' and number(sbti_near_term_target_year ?? 0) >= 2029"
    " and number(sbti_near_term_target_year ?? 0) <= 2035 ? 'Yes' : 'No info')"
)

# Steps 2-5 per question, in order: (source label, expression giving Yes / No / No info).
WATERFALL = {
    "Q2.1.1": [("MSCI", step("msci_q2_1_1")), ("TPI", step("tpi_q4l2")), ("WBA", step("wba_targets")), ("CDP", step("cdp_q2_1_1"))],
    "Q2.1.2": [("MSCI", step("msci_q2_1_2")), ("CA100+", step("ca100_3_1")), ("WBA", step("wba_s12_near_term_aim")), ("CDP", step("cdp_q2_1_2"))],
    "Q2.1.3": [("MSCI", step("msci_q2_1_3")), ("CA100+", step("ca100_3_2a")), ("WBA", step("wba_s12_covers_95")), ("CDP", step("cdp_q2_1_3"))],
    "Q2.1.4": [
        ("MSCI", step("msci_q2_1_4")),
        ("CA100+/WBA", either("ca100_3_1", "wba_s12_near_term_aim")),  # as the sheet has it; see README
        ("WBA", step("wba_s3_material_categories")),
        ("CDP", step("cdp_q2_1_4")),
    ],
}

COLUMNS = [
    "Company", "sbti_near_term_status", "sbti_near_term_target_year",
    "msci_q2_1_1", "msci_q2_1_2", "msci_q2_1_3", "msci_q2_1_4",
    "tpi_q4l2", "ca100_3_1", "ca100_3_2a",
    "wba_targets", "wba_s12_near_term_aim", "wba_s12_covers_95", "wba_s3_material_categories",
    "cdp_q2_1_1", "cdp_q2_1_2", "cdp_q2_1_3", "cdp_q2_1_4",
    "tpi_cp_alignment_2030", "tpi_cp_alignment_2035",
]  # fmt: skip


def key(q: str) -> str:
    return "q" + q[1:].replace(".", "_").lower()  # Q2.1.1 -> q2_1_1


def chain(cases: list[tuple[str, str]], otherwise: str) -> str:
    out = otherwise
    for when, then in reversed(cases):
        out = f"({when} ? {then} : {out})"
    return out


def rule_graph() -> dict:
    ex: list[tuple[str, str]] = [("sbti", SBTI)]
    for q, steps in WATERFALL.items():
        k = key(q)
        ex.append((f"{k}_source", chain([("$.sbti == 'Yes'", "'SBTi'"), *((f"{e} != 'No info'", f"'{s}'") for s, e in steps)], "'none'")))
        ex.append((k, chain([("$.sbti == 'Yes'", "'Yes'"), *((f"{e} != 'No info'", e) for _, e in steps)], "'No info'")))
    earlier = [f"$.{key(q)}" for q in WATERFALL]
    aligned = " or ".join(f"lower(string({c} ?? '')) == '{v}'" for c in ("tpi_cp_alignment_2030", "tpi_cp_alignment_2035") for v in ("1.5 degrees", "below 2 degrees"))
    tpi_blank = "string(tpi_cp_alignment_2030 ?? '') == '' and string(tpi_cp_alignment_2035 ?? '') == ''"
    any_no = " or ".join(f"{c} == 'No'" for c in earlier)
    any_info = " or ".join(f"{c} == 'No info'" for c in earlier)
    ex += [
        ("q2_1_5_source", chain([("$.sbti == 'Yes'", "'SBTi'"), (f"{any_no} or {any_info}", "'Q2.1.1-4'"), (tpi_blank, "'none'")], "'TPI'")),
        ("q2_1_5", chain([("$.sbti == 'Yes'", "'Yes'"), (any_no, "'No'"), (any_info, "'No info'"), (aligned, "'Yes'"), (tpi_blank, "'No info'")], "'No'")),
    ]
    answers = "[" + ", ".join(f"$.{key(q)}" for q in QUESTIONS) + "]"
    ex += [
        ("yes_count", f"len(filter({answers}, # == 'Yes'))"),
        ("no_info_count", f"len(filter({answers}, # == 'No info'))"),
        (
            "outcome",
            chain(
                [
                    ("$.yes_count == 5", "'aligned'"),
                    (" and ".join(f"{c} == 'Yes'" for c in earlier), "'not_aligned'"),
                    ("$.yes_count > 0", "'partial'"),
                    ("$.no_info_count == 5", "'no_info'"),
                ],
                "'none'",
            ),
        ),
        (
            "note",
            "string($.yes_count) + '/5 Yes'"
            + "".join(f" + ' · {q} ' + $.{key(q)} + ' (' + $.{key(q)}_source + ')'" for q in QUESTIONS),
        ),
    ]
    return graph("targets", ex)


def graph(name: str, expressions: list[tuple[str, str]]) -> dict:
    def node(node_id: str, kind: str, x: int, **content) -> dict:
        return {"id": node_id, "type": kind, "name": node_id, "position": {"x": x, "y": 100}, **({"content": content} if content else {})}

    return {
        "nodes": [
            node("in", "inputNode", 0),
            node(name, "expressionNode", 300, expressions=[{"id": k, "key": k, "value": v} for k, v in expressions]),
            node("out", "outputNode", 700),
        ],
        "edges": [
            {"id": "in-calc", "sourceId": "in", "targetId": name, "type": "edge"},
            {"id": "calc-out", "sourceId": name, "targetId": "out", "type": "edge"},
        ],
    }


def build() -> dict:
    keys = ["aligned", "not_aligned", "partial", "none", "no_info"]
    tier = chain([(f"outcome == '{k}'", str(i + 1)) for i, k in enumerate(keys[:-1])], "5")
    config = MechanismConfig(
        name="Logic of targets (Q2.1)",
        mode="levels",
        level_min=0,
        level_max=1,
        dimensions=[Dimension(id="targets", name="Targets")],
        level_criteria=[
            LevelCriterion(id=key(q), name=q, dimension_id="targets", hint=text, rules=[LevelRule(level=1, when=yes(key(q)))], otherwise=0)
            for q, text in QUESTIONS.items()
        ],
        rule_graph=rule_graph(),
        tier_graph=graph("tier", [("tier", tier), ("note", "note")]),
        tiers=[TierDefinition(rank=i + 1, name=t) for i, t in enumerate(TIERS)],
        cut_mode="absolute",
        pinned_cuts=[0, 0, 0, 0],  # the answers set the tier, not the score
        label_column="Company",
        source_columns=COLUMNS,
        min_coverage_pct=0,
    )

    def why(item: str, decision: str, reason: str) -> AuditEntry:
        return AuditEntry(stage="Logic of targets", item=item, decision=decision, why=reason, origin="human")

    audit = [
        why("Step 1", "SBTi near-term target set for 2029-2035 answers Yes to every question", "Sheet, Step 1."),
        why("No info", "a blank cell passes to the next source; a Yes or No ends the waterfall", "Sheet: each step runs 'if the previous step returns No info'."),
        why("No source", "all steps blank -> No info", "Not in the sheet; ruled here."),
        why("Q2.1.5", "No if Q2.1.1-4 has a No; No info if it has a No info; else TPI 2030 or 2035 alignment", "Sheet: 'Yes only if all previous questions are Yes'; No info propagates (ruled here)."),
        why("MSCI and CDP", "one Yes/No column per question", "Both report per target; the per-target conditions are applied before the table is loaded (README)."),
        why("Tiers", ", ".join(TIERS), "Not in the sheet: 5/5 Yes; Q2.1.1-4 Yes; some Yes; no Yes; all No info."),
    ]
    return export_template(config, audit)


if __name__ == "__main__":
    (HERE / "framework.json").write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n")
