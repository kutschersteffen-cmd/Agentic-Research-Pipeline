"""Green and low-carbon revenue, CapEx and OpEx (E22 A), generated from the versioned criteria table.

Not limited to the EU Taxonomy: every green amount is captured, then split by EU status. Transition
activities are kept apart from green. Amounts stay in the company's reporting currency (no FX)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from arp.schemas.datapoints import CheckConfig, DataPointSchema, FieldDataType, FieldDefinition

GREEN_TABLE = "green_categories_v1"
SCHEMA_ID = "sch_green_lowcarbon"
METRICS = {"revenue": "revenue (turnover)", "capex": "capital expenditure (CapEx)", "opex": "operating expenditure (OpEx)"}
FRAMEWORKS = ["own_definition", "eu_taxonomy", "icma_gbp", "climate_bonds", "china_catalogue", "other"]
_TABLE_REF = f"criteria table {GREEN_TABLE} (table version {GREEN_TABLE.rsplit('_v', 1)[1]})"


@dataclass(frozen=True)
class GreenCategory:
    category_id: str
    label: str
    kind: str  # "green" | "transition"
    description: str
    include: str
    exclude: str
    eu_objective: str  # EU environmental objectives, ";"-separated: ccm, cca, wtr, ce, ppc, bio


@cache
def load_green_categories() -> list[GreenCategory]:
    with open(Path(__file__).parents[1] / "normalise" / "tables" / f"{GREEN_TABLE}.csv", encoding="utf8", newline="") as f:
        return [GreenCategory(**row) for row in csv.DictReader(f)]


def _rules(c: GreenCategory) -> str:
    return f"[{c.category_id}: {c.label}; EU objective {c.eu_objective}] Include: {c.include} Exclude: {c.exclude}"


def _common(metric: str) -> str:
    return (
        f"Capture every green or low-carbon {METRICS[metric]} amount the company discloses, whatever framework it uses "
        "(own definition, EU Taxonomy, ICMA Green Bond Principles, Climate Bonds Taxonomy, China catalogue or other), "
        "including amounts not aligned with or not covered by the EU Taxonomy, for EU, US and other firms alike. "
        f"Classify against {_TABLE_REF}. Count each amount in one category only. Report each fiscal year disclosed, in "
        "the reporting currency as printed (never convert currencies). Transition activities are never green."
    )


def _green_rules() -> str:
    return " Green category rules: " + " ".join(_rules(c) for c in load_green_categories() if c.kind == "green")


def _money(field_id: str, name: str, description: str, instructions: str, keywords: list[str], **checks) -> FieldDefinition:
    return FieldDefinition(
        field_id=field_id, name=name, description=description, data_type=FieldDataType.CURRENCY_AMOUNT,
        extraction_instructions=instructions, seed_keywords=keywords, required=False,
        check_config=CheckConfig(non_negative=True, **checks),
    )


def _metric_fields(m: str) -> list[FieldDefinition]:
    cats = load_green_categories()
    green = [c for c in cats if c.kind == "green"]
    (trans,) = [c for c in cats if c.kind == "transition"]
    word, common, all_green = METRICS[m], _common(m), _green_rules()
    total, gtotal, split = f"{m}_total", f"green_{m}_total", f"green_{m}_eu_split_total"
    cat_ids = [f"green_{m}_{c.category_id}" for c in green]
    status = {
        f"green_{m}_eu_aligned": ("EU Taxonomy-aligned", "the part the company reports as EU Taxonomy-aligned. Taxonomy-aligned fossil gas and nuclear activities (Complementary Delegated Act) are transition, not green: leave them out here"),
        f"green_{m}_eu_eligible_not_aligned": ("EU Taxonomy-eligible, not aligned", "the part the company reports as Taxonomy-eligible but not aligned"),
        f"green_{m}_eu_not_covered": ("not covered by the EU Taxonomy", "the part for activities the EU Taxonomy does not cover (not eligible), as the company states it. Never infer it: a firm without a Taxonomy assessment leaves this not found"),
    }
    kw = [f"green {m}", f"low-carbon {m}", f"sustainable {m}", f"climate solutions {m}"]
    fields = [
        _money(total, f"Total {word}", f"Total {word} for the fiscal year: the denominator of the green share.",
               f"{common} Use the total the company divides by for its green share; otherwise the consolidated total. "
               f"Not restricted by category: it is the denominator for {_TABLE_REF}.",
               [f"total {m}", word]),
        _money(gtotal, f"Green {word}",
               f"All {word} meeting the green include rules of {GREEN_TABLE}, whether or not EU Taxonomy-aligned.",
               f"{common} The sum of the green categories. Where the company's own green figure contains excluded items "
               "(for example gas or nuclear), subtract them when quantified; otherwise report the figure and quote what "
               f"it includes.{all_green}",
               kw, part_of=total, sum_of=cat_ids, le_of=[split]),
        FieldDefinition(
            field_id=f"green_{m}_share_pct", name=f"Green {word} share", data_type=FieldDataType.PERCENTAGE, unit="%",
            description=f"Green {word} as a percentage of total {word}.",
            extraction_instructions=f"{common} The share as the company reports it.{all_green}",
            seed_keywords=[f"share of green {m}", f"green {m} %"], required=False,
        ),
        _money(f"transition_{m}_total", f"Transition {word}",
               f"{word.capitalize()} from transition activities, kept separate from green and never added to it.",
               f"{common} Only the transition row applies. {_rules(trans)}",
               [f"transition {m}", f"transitional {m}", "gas", "nuclear"], part_of=total),
        *(_money(fid, f"Green {word}: {c.label}", f"{c.description} ({word})", f"{common} {_rules(c)}",
                 [c.label.lower(), f"{c.label.lower()} {m}"], part_of=gtotal)
          for fid, c in zip(cat_ids, green, strict=True)),
        *(_money(fid, f"Green {word}, {label}", f"Of green {word}: {what}.", f"{common} Of the green amount, {what}.{all_green}",
                 [*kw, "EU taxonomy", label], part_of=gtotal)
          for fid, (label, what) in status.items()),
        _money(split, f"Green {word}, EU status split total",
               f"Helper: the three EU status amounts added up; checked to equal green {word}.",
               f"{common} The total of the EU-aligned, eligible-not-aligned and not-covered green amounts, when the "
               f"company reports one.{all_green}",
               [*kw, "EU taxonomy"], sum_of=list(status), le_of=[gtotal]),
        FieldDefinition(
            field_id=f"green_{m}_framework", name=f"Green {word} framework", data_type=FieldDataType.ENUM,
            allowed_values=FRAMEWORKS, description=f"The framework the company's green {word} figure follows.",
            extraction_instructions=f"{common} Pick the framework the company names for its green figure.{all_green}",
            seed_keywords=[*kw, "taxonomy", "green bond principles", "climate bonds"], required=False,
        ),
        FieldDefinition(
            field_id=f"green_{m}_definition", name=f"Green {word} definition", data_type=FieldDataType.STRING,
            description=f"The company's own definition of green or low-carbon {word}, quoted.",
            extraction_instructions=f"{common} Quote the definition verbatim, with any thresholds, and say whether it "
                                    f"counts gas or nuclear.{all_green}",
            seed_keywords=[*kw, "we define", "definition"], required=False,
        ),
    ]
    return fields


def build_green_schema() -> DataPointSchema:
    return DataPointSchema(
        schema_id=SCHEMA_ID,
        name="Green and low-carbon revenue, CapEx and OpEx",
        description=f"All green and low-carbon amounts, beyond the EU Taxonomy, with transition kept separate; {_TABLE_REF}.",
        fields=[f for m in METRICS for f in _metric_fields(m)],
    )


class GreenSummaryRow(BaseModel):
    metric: str
    period_end: str | None
    unit: str | None
    green_total: float | None
    aligned: float | None
    share: float | None
    beyond_taxonomy: float | None
    flag: str | None = None


def _num(f: dict | None) -> float | None:
    if f is None:
        return None
    v = f.get("canonical_value")
    if v is None and isinstance(f.get("value"), (int, float)) and not isinstance(f.get("value"), bool):
        v = f["value"]
    return v


def green_summary(fields: list[dict]) -> list[GreenSummaryRow]:
    """Per metric and period: green total, aligned, share and green beyond the Taxonomy (never clipped)."""
    by = {(f.get("field_id"), f.get("period_end")): f for f in fields if _num(f) is not None}
    rows = []
    for m in METRICS:
        gid, aid = f"green_{m}_total", f"green_{m}_eu_aligned"
        for p in sorted({p for fid, p in by if fid in (gid, aid)}, key=lambda p: p or ""):
            g, a, s, t = (by.get((fid, p)) for fid in (gid, aid, f"green_{m}_share_pct", f"{m}_total"))
            beyond = flag = None
            if g and a:
                if g.get("canonical_unit") != a.get("canonical_unit"):
                    flag = "unit_mismatch"
                else:
                    beyond = _num(g) - _num(a)
                    flag = "aligned_exceeds_green" if beyond < 0 else None
            share = _num(s)
            if share is None and g and t and _num(t) and g.get("canonical_unit") == t.get("canonical_unit"):
                share = _num(g) / _num(t) * 100
            rows.append(GreenSummaryRow(
                metric=m, period_end=p, unit=(g or a).get("canonical_unit"), green_total=_num(g), aligned=_num(a),
                share=share, beyond_taxonomy=beyond, flag=flag,
            ))
    return rows
