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


def _common(p: str) -> str:
    return (
        f"Read the remuneration report or proxy statement (compensation discussion) for the {PLANS[p]} of the CEO; "
        "also the executive committee where the company discloses it (state which in rem_scope). Report what the company "
        "prints and never compute a weight. ESG means environmental, social or governance performance metrics in pay. "
        "Percentages are 0-100; multipliers are factors (0.9 = 90% of target payout)."
    )


def _f(fid: str, name: str, dtype: FieldDataType, what: str, p: str | None = None, **kw) -> FieldDefinition:
    return FieldDefinition(
        field_id=fid, name=name, data_type=dtype, description=what,
        extraction_instructions=f"{_common(p) if p else _common('lti')} {what}",
        seed_keywords=_KEYWORDS, required=False, document_routing=_ROUTING, **kw,
    )


def _plan_fields(p: str) -> list[FieldDefinition]:
    P, E, N = p.upper(), FieldDataType.ENUM, FieldDataType.NUMBER
    pct = FieldDataType.PERCENTAGE
    return [
        _f(f"rem_{p}_esg_present", f"ESG metric in {P}", E, f"Whether the {P} contains any ESG metric.", p, allowed_values=YND),
        _f(f"rem_{p}_esg_metrics", f"ESG metrics in {P}", FieldDataType.STRING,
           f"The names of the ESG metrics in the {P}, separated by semicolons.", p),
        _f(f"rem_{p}_climate_related", f"Climate-related metric in {P}", E,
           f"Whether any {P} ESG metric is climate, low-carbon or transition related.", p, allowed_values=YND),
        _f(f"rem_{p}_climate_metric_types", f"Climate metric types in {P}", FieldDataType.STRING,
           f"The climate metric types in the {P}, separated by semicolons, from: {', '.join(CLIMATE_TYPES)}.", p),
        _f(f"rem_{p}_mechanism", f"ESG mechanism in {P}", E,
           f"How ESG enters the {P}: weighted metric, multiplier (modifier of the payout), underpin, discretion or none.",
           p, allowed_values=MECHANISMS),
        _f(f"rem_{p}_esg_weight_pct", f"ESG weight in {P}", pct,
           f"The combined weight of all ESG metrics in the {P} as a percentage of the {P}.", p, unit="%",
           check_config=CheckConfig(min_value=0, max_value=100)),
        _f(f"rem_{p}_climate_weight_pct", f"Climate weight in {P}", pct,
           f"The weight of the climate-related metrics in the {P} as a percentage of the {P}.", p, unit="%",
           check_config=CheckConfig(le_of=[f"rem_{p}_esg_weight_pct"])),
        _f(f"rem_{p}_multiplier_min", f"ESG multiplier minimum in {P}", N,
           f"The lowest ESG multiplier factor of the {P} (0.9 = payout cut to 90%).", p,
           check_config=CheckConfig(min_value=0, max_value=3, le_of=[f"rem_{p}_multiplier_max"])),
        _f(f"rem_{p}_multiplier_max", f"ESG multiplier maximum in {P}", N,
           f"The highest ESG multiplier factor of the {P} (1.1 = payout raised to 110%).", p,
           check_config=CheckConfig(min_value=0, max_value=3)),
        _f(f"rem_{p}_multiplier_direction", f"ESG multiplier direction in {P}", E,
           f"Whether the ESG multiplier of the {P} can only raise (up), only cut (down) or do both.", p,
           allowed_values=["up", "down", "both"]),
        _f(f"rem_{p}_has_multiplier_also", f"Weighted ESG metric also has a modifier in {P}", E,
           f"Whether an ESG metric weighted in the {P} also has an ESG multiplier or modifier on top.", p,
           allowed_values=["yes", "no"]),
    ]


def build_remuneration_schema() -> DataPointSchema:
    return DataPointSchema(
        schema_id=SCHEMA_ID,
        name="ESG factors in executive remuneration",
        description="Whether ESG and climate metrics are in CEO and executive pay, their weight in STI and LTI, "
                    "and the multiplier range; the effective weight is computed afterwards.",
        fields=[
            _f("rem_scope", "Disclosure scope", FieldDataType.ENUM,
               "Which group the remuneration disclosure covers: ceo or executive_committee.",
               allowed_values=["ceo", "executive_committee"]),
            _f("rem_esg_in_pay", "ESG factors in executive pay", FieldDataType.ENUM,
               "Whether any ESG factor is part of executive pay.", allowed_values=YND),
            *(f for p in PLANS for f in _plan_fields(p)),
        ],
    )


class RemunerationSummary(BaseModel):
    plan: str
    period_end: str | None = None
    scope: str | None = None
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
    """Per plan and period: effective weight = weight (weighted) or max(max-1, 1-min) x 100 (multiplier);
    underpin and discretion have none. 10.0 counts as '10_or_above'."""
    by = {(f.get("field_id"), f.get("period_end")): f for f in fields}
    rows = []
    for p in PLANS:
        for pe in sorted({pe for (fid, pe) in by if fid.startswith(f"rem_{p}_")}, key=lambda x: x or ""):
            g = lambda s, p=p, pe=pe: _v(by.get((f"rem_{p}_{s}", pe)))  # noqa: E731
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
                plan=p, period_end=pe, scope=_v(by.get(("rem_scope", pe))), esg_present=g("esg_present"),
                climate_related=g("climate_related"), mechanism=mech, weight_pct=weight,
                multiplier_range=(lo, hi) if has_mult else None,
                effective_weight_pct=eff,
                threshold_class=None if eff is None else "10_or_above" if eff >= THRESHOLD_PCT else "below_10",
                also_multiplier=g("has_multiplier_also"), notes=notes,
            ))
    return rows
