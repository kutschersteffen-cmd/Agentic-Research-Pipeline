"""ESG factors in executive pay: whether they exist, climate relation, weight in STI and LTI, and a multiplier alternative.

The effective weight and the 10% class are computed in remuneration_summary, never extracted."""

from __future__ import annotations

from pydantic import BaseModel

from arp.schemas.common import DocType
from arp.schemas.datapoints import CheckConfig, DataPointSchema, DocumentRouting, FieldDataType, FieldDefinition

SCHEMA_ID = "sch_esg_remuneration"
PLANS = {"sti": "short-term incentive (STI, annual bonus)", "lti": "long-term incentive (LTI, performance share plan)"}
CLIMATE_TYPES = ["emissions_reduction", "renewable_share", "green_revenue_or_capex", "sbti_target",
                 "transition_plan_milestone", "energy_efficiency", "other_climate"]
MECHANISMS = ["weighted", "multiplier", "underpin", "discretion", "none"]
YND = ["yes", "no", "not_disclosed"]
THRESHOLD_PCT = 10.0
_ROUTING = DocumentRouting(
    doc_types=[DocType.PROXY_DEF14A, DocType.ANNUAL_REPORT_10K, DocType.SUSTAINABILITY_REPORT],
    sections=["remuneration report", "compensation discussion", "short-term incentive", "annual bonus",
              "long-term incentive", "performance share"],
)
_KEYWORDS = ["remuneration report", "short-term incentive", "annual bonus", "performance share plan", "ESG",
             "sustainability", "climate", "modifier", "multiplier"]


SCOPE_NAMES = {"ceo": "ceo", "exco": "executive_committee"}
SCOPES = {"ceo": "the CEO", "exco": "the executive committee (other named executive officers)"}


def _common(sc: str, p: str) -> str:
    extra = (" Extract only where the executive committee's terms are disclosed separately from the CEO's; otherwise "
             "leave the field not disclosed and never copy the CEO's terms.") if sc == "exco" else ""
    return (
        f"Read the remuneration report or proxy statement (compensation discussion) for the {PLANS[p]} of {SCOPES[sc]}."
        f"{extra} Report what the company prints and never compute a weight. ESG means environmental, social or "
        "governance performance metrics in pay. Percentages are 0-100; multipliers are unit-less factors "
        "(0.9 = 90% of target payout), stated without any unit such as 'x' or the multiplication sign."
        + ' A "%" in a column header applies to the bare cells beneath it: report such a figure with unit "%".'
    )


def _f(fid: str, name: str, dtype: FieldDataType, what: str, sp: tuple[str, str] | None = None, **kw) -> FieldDefinition:
    return FieldDefinition(
        field_id=fid, name=name, data_type=dtype, description=what,
        extraction_instructions=f"{_common(*sp) if sp else _common('ceo', 'lti')} {what}",
        seed_keywords=_KEYWORDS, required=False, document_routing=_ROUTING, **kw,
    )


def _plan_fields(sc: str, p: str) -> list[FieldDefinition]:
    pre, sp = f"rem_{sc}_{p}", (sc, p)
    P, E, N = f"{p.upper()} ({sc.upper()})", FieldDataType.ENUM, FieldDataType.NUMBER
    pct = FieldDataType.PERCENTAGE
    return [
        _f(f"{pre}_esg_present", f"ESG metric in {P}", E, f"Whether the {P} contains any ESG metric.", sp, allowed_values=YND),
        _f(f"{pre}_esg_metrics", f"ESG metrics in {P}", FieldDataType.STRING,
           f"The names of the ESG metrics in the {P}, separated by semicolons.", sp),
        _f(f"{pre}_climate_related", f"Climate-related metric in {P}", E,
           f"Whether any {P} ESG metric is climate, low-carbon or transition related.", sp, allowed_values=YND),
        _f(f"{pre}_climate_metric_types", f"Climate metric types in {P}", FieldDataType.STRING,
           f"The climate metric types in the {P}, separated by semicolons, from: {', '.join(CLIMATE_TYPES)}.", sp),
        _f(f"{pre}_mechanism", f"ESG mechanism in {P}", E,
           f"How ESG enters the {P}: weighted metric, multiplier (modifier of the payout), underpin, discretion or none.",
           sp, allowed_values=MECHANISMS),
        _f(f"{pre}_esg_weight_pct", f"ESG weight in {P}", pct,
           f"The combined weight of all ESG metrics in the {P} as a percentage of the {P}.", sp, unit="%",
           check_config=CheckConfig(min_value=0, max_value=100)),
        _f(f"{pre}_climate_weight_pct", f"Climate weight in {P}", pct,
           f"The weight of the climate-related metrics in the {P} as a percentage of the {P}.", sp, unit="%",
           check_config=CheckConfig(le_of=[f"{pre}_esg_weight_pct"])),
        _f(f"{pre}_multiplier_min", f"ESG multiplier minimum in {P}", N,
           f"The lowest ESG multiplier factor of the {P} (0.9 = payout cut to 90%).", sp,
           check_config=CheckConfig(min_value=0, max_value=3, le_of=[f"{pre}_multiplier_max"])),
        _f(f"{pre}_multiplier_max", f"ESG multiplier maximum in {P}", N,
           f"The highest ESG multiplier factor of the {P} (1.1 = payout raised to 110%).", sp,
           check_config=CheckConfig(min_value=0, max_value=3)),
        _f(f"{pre}_multiplier_direction", f"ESG multiplier direction in {P}", E,
           f"Whether the ESG multiplier of the {P} can only raise (up), only cut (down) or do both.", sp,
           allowed_values=["up", "down", "both"]),
        _f(f"{pre}_has_multiplier_also", f"Weighted ESG metric also has a modifier in {P}", E,
           f"Whether an ESG metric weighted in the {P} also has an ESG multiplier or modifier on top.", sp,
           allowed_values=["yes", "no"]),
    ]


def build_remuneration_schema() -> DataPointSchema:
    return DataPointSchema(
        schema_id=SCHEMA_ID,
        name="ESG factors in executive remuneration",
        description="Whether ESG and climate metrics are in CEO and executive pay, their weight in STI and LTI, "
                    "and the multiplier range; the effective weight is computed afterwards.",
        fields=[
            _f("rem_esg_in_pay", "ESG factors in executive pay", FieldDataType.ENUM,
               "Whether any ESG factor is part of executive pay.", allowed_values=YND),
            *(f for sc in SCOPES for p in PLANS for f in _plan_fields(sc, p)),
        ],
    )


class RemunerationSummary(BaseModel):
    scope: str
    plan: str
    period_end: str | None = None
    esg_in_pay: str | None = None
    esg_present: str | None = None
    climate_related: str | None = None
    mechanism: str | None = None
    weight_pct: float | None = None
    multiplier_range: tuple[float | None, float | None] | None = None
    effective_weight_pct: float | None = None
    threshold_class: str | None = None
    also_multiplier: str | None = None
    notes: list[str] = []


def _v(f: dict | None):
    if f is None:
        return None
    v = f.get("canonical_value")
    return v if v is not None else f.get("value")


def remuneration_summary(fields: list[dict]) -> list[RemunerationSummary]:
    """Per scope (ceo, executive committee), plan and period: effective weight = weight (weighted) or max(max-1, 1-min) x 100 (multiplier);
    underpin and discretion have none. 10.0 counts as '10_or_above'."""
    by = {(f.get("field_id"), f.get("period_end")): f for f in fields}
    pay = sorted((pe or "", _v(f)) for (fid, pe), f in by.items() if fid == "rem_esg_in_pay" and _v(f) is not None)
    rows = []
    for sc, p in ((sc, p) for sc in SCOPES for p in PLANS):
        pre = f"rem_{sc}_{p}_"
        for pe in sorted({pe for (fid, pe) in by if fid.startswith(pre)}, key=lambda x: x or ""):
            g = lambda s, pe=pe, pre=pre: _v(by.get((pre + s, pe)))  # noqa: E731
            # same-period value, else the latest one disclosed
            in_pay = _v(by.get(("rem_esg_in_pay", pe))) or (pay[-1][1] if pay else None)
            weight, lo, hi, mech = g("esg_weight_pct"), g("multiplier_min"), g("multiplier_max"), g("mechanism")
            has_mult = lo is not None or hi is not None
            mech = mech or ("weighted" if weight is not None else "multiplier" if has_mult else None)
            notes, eff = [], None
            if mech == "weighted":
                eff = weight
                if g("has_multiplier_also") == "yes":
                    notes.append("also has an ESG multiplier")
            elif mech == "multiplier":
                swings = [x for x in (hi - 1 if hi is not None else None, 1 - lo if lo is not None else None) if x is not None]
                eff = round(max(swings) * 100, 6) if swings else None
            rows.append(RemunerationSummary(
                scope=SCOPE_NAMES[sc], plan=p, period_end=pe, esg_in_pay=in_pay, esg_present=g("esg_present"),
                climate_related=g("climate_related"), mechanism=mech, weight_pct=weight,
                multiplier_range=(lo, hi) if has_mult else None,
                effective_weight_pct=eff,
                threshold_class=None if eff is None else "10_or_above" if eff >= THRESHOLD_PCT else "below_10",
                also_multiplier=g("has_multiplier_also"), notes=notes,
            ))
    return rows
