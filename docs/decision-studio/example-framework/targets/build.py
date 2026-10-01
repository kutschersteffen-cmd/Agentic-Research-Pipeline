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

# Steps 2-5 per question, in order: (source label, column the normalise node writes).
WATERFALL = {
    "Q2.1.1": [("MSCI", "msci_q2_1_1"), ("TPI", "tpi_q4l2"), ("WBA", "wba_targets"), ("CDP", "cdp_q2_1_1")],
    "Q2.1.2": [("MSCI", "msci_q2_1_2"), ("CA100+", "ca100_3_1"), ("WBA", "wba_s12_near_term_aim"), ("CDP", "cdp_q2_1_2")],
    "Q2.1.3": [("MSCI", "msci_q2_1_3"), ("CA100+", "ca100_3_2a"), ("WBA", "wba_s12_covers_95"), ("CDP", "cdp_q2_1_3")],
    "Q2.1.4": [
        ("MSCI", "msci_q2_1_4"),
        ("CA100+/WBA", "ca100_3_1_or_wba_s12_near_term_aim"),  # as the sheet has it; see README
        ("WBA", "wba_s3_material_categories"),
        ("CDP", "cdp_q2_1_4"),
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

KNOWN = "'Yes', 'No'"  # a decision-table cell: the source has information


def key(q: str) -> str:
    return "q" + q[1:].replace(".", "_").lower()  # Q2.1.1 -> q2_1_1


def node(node_id: str, kind: str, x: int, **content) -> dict:
    n = {"id": node_id, "type": kind, "name": node_id, "position": {"x": x, "y": 100}}
    if content:
        n["content"] = {"passThrough": True, "inputField": None, "outputPath": None, "executionMode": "single", **content}
    return n


def expressions(node_id: str, x: int, pairs: list[tuple[str, str]]) -> dict:
    return node(node_id, "expressionNode", x, expressions=[{"id": k, "key": k, "value": v} for k, v in pairs])


def table(name: str, x: int, inputs: list[tuple[str, str]], outputs: list[tuple[str, str]], rows: list[dict[str, str]]) -> dict:
    """A first-hit decision table: the first row whose cells all match wins.
    `inputs`/`outputs` are (column name, field); a row maps column names to
    cells, and a column a row leaves out matches anything."""
    ids = {label: f"c{i}" for i, (label, _) in enumerate([*inputs, *outputs])}
    n = node(
        slug_id(name),
        "decisionTableNode",
        x,
        hitPolicy="first",
        inputs=[{"id": ids[label], "name": label, "field": field} for label, field in inputs],
        outputs=[{"id": ids[label], "name": label, "field": field} for label, field in outputs],
        rules=[{"_id": f"r{r}", **{ids[label]: row.get(label, "") for label in ids}} for r, row in enumerate(rows, 1)],
    )
    n["name"] = name
    return n


def slug_id(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name.lower())


def chain(*nodes: dict) -> dict:
    """input -> each node in turn -> output; every node passes its input through."""
    ordered = [node("in", "inputNode", 0), *nodes, node("out", "outputNode", 300 * (len(nodes) + 1))]
    edges = [{"id": f"e{i}", "sourceId": a["id"], "targetId": b["id"], "type": "edge"} for i, (a, b) in enumerate(zip(ordered, ordered[1:], strict=False))]
    return {"nodes": ordered, "edges": edges}


def rule_graph() -> dict:
    sources = sorted({c for steps in WATERFALL.values() for _, c in steps} - {"ca100_3_1_or_wba_s12_near_term_aim"})
    normalise = expressions(
        "normalise",
        300,
        [
            ("sbti_answer", SBTI),
            *((f"{c}_answer", step(c)) for c in sources),
            ("ca100_3_1_or_wba_s12_near_term_aim_answer", either("ca100_3_1", "wba_s12_near_term_aim")),
            (
                "tpi_alignment_answer",
                " or ".join(f"lower(string({c} ?? '')) == '{v}'" for c in ("tpi_cp_alignment_2030", "tpi_cp_alignment_2035") for v in ("1.5 degrees", "below 2 degrees"))
                + " ? 'Yes' : (string(tpi_cp_alignment_2030 ?? '') == '' and string(tpi_cp_alignment_2035 ?? '') == '' ? 'No info' : 'No')",
            ),
        ],
    )
    questions = []
    for q, steps in WATERFALL.items():
        inputs = [("SBTi", "sbti_answer"), *((s, f"{c}_answer") for s, c in steps)]
        rows = [{"SBTi": "'Yes'", "Answer": "'Yes'", "Source": "'SBTi'"}]
        rows += [{s: KNOWN, "Answer": f"{c}_answer", "Source": f"'{s}'"} for s, c in steps]
        rows.append({"Answer": "'No info'", "Source": "'none'"})
        questions.append(table(q, 300 * (len(questions) + 2), inputs, [("Answer", key(q)), ("Source", f"{key(q)}_source")], rows))
    earlier = list(WATERFALL)
    q5 = table(
        "Q2.1.5",
        1800,
        [("SBTi", "sbti_answer"), *((q, key(q)) for q in earlier), ("TPI alignment", "tpi_alignment_answer")],
        [("Answer", "q2_1_5"), ("Source", "q2_1_5_source")],
        [
            {"SBTi": "'Yes'", "Answer": "'Yes'", "Source": "'SBTi'"},
            *({q: "'No'", "Answer": "'No'", "Source": "'Q2.1.1-4'"} for q in earlier),
            *({q: "'No info'", "Answer": "'No info'", "Source": "'Q2.1.1-4'"} for q in earlier),
            {"TPI alignment": KNOWN, "Answer": "tpi_alignment_answer", "Source": "'TPI'"},
            {"Answer": "'No info'", "Source": "'none'"},
        ],
    )
    answers = "[" + ", ".join(key(q) for q in QUESTIONS) + "]"
    counts = expressions(
        "counts",
        2100,
        [
            ("yes_count", f"len(filter({answers}, # == 'Yes'))"),
            ("no_info_count", f"len(filter({answers}, # == 'No info'))"),
            ("note", "string($.yes_count) + '/5 Yes'" + "".join(f" + ' · {q} ' + {key(q)} + ' (' + {key(q)}_source + ')'" for q in QUESTIONS)),
        ],
    )
    outcome = table(
        "Outcome",
        2400,
        [("Yes answers", "yes_count"), *((q, key(q)) for q in earlier), ("No info answers", "no_info_count")],
        [("Outcome", "outcome")],
        [
            {"Yes answers": "5", "Outcome": "'aligned'"},
            {**{q: "'Yes'" for q in earlier}, "Outcome": "'not_aligned'"},
            {"Yes answers": "> 0", "Outcome": "'partial'"},
            {"No info answers": "5", "Outcome": "'no_info'"},
            {"Outcome": "'none'"},
        ],
    )
    return chain(normalise, *questions, q5, counts, outcome)


def build() -> dict:
    keys = ["aligned", "not_aligned", "partial", "none", "no_info"]
    tier_table = table(
        "Tier",
        300,
        [("Outcome", "outcome")],
        [("Tier", "tier"), ("Note", "note")],
        [{"Outcome": f"'{k}'", "Tier": str(i + 1), "Note": "note"} for i, k in enumerate(keys)],
    )
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
        tier_graph=chain(tier_table),
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
    # encoding is explicit because ensure_ascii=False emits raw UTF-8 (this
    # framework uses U+00B7 and U+00B0): without it the file is written in
    # the platform locale, which on Windows means cp1252 bytes that every
    # reader here then decodes as UTF-8.
    (HERE / "framework.json").write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
