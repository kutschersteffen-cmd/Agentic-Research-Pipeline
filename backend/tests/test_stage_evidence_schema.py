"""Stage evidence fields of the taxonomy schema (spec: docs/superpowers/specs/2026-11-03-stage-evidence-schema-design.md).

Expected texts are written out here, not read from the module, so a change to the code's constants fails a test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arp.research.taxonomy_schema import build_taxonomy_schema, field_id_for
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

FIXTURE = Path(__file__).parent / "fixtures" / "stage_evidence" / "pct_fields_main.json"
PREFIX = (
    "Extract only what the company explicitly states about this specific activity, with a verbatim quote. "
    "Never estimate, infer or compute a value."
)
KEYS = [
    "revenue_amount", "capex_amount", "rd_amount", "rd_programme", "milestone", "capacity", "backlog",
    "partnerships", "news_momentum", "stage_ideation", "stage_innovation", "stage_commercial",
]
AMOUNT = "The stated amount for this activity, with currency and fiscal year in raw_value_text; company-wide totals do not count."
GUIDANCE = {
    "revenue_amount": AMOUNT, "capex_amount": AMOUNT, "rd_amount": AMOUNT, "backlog": AMOUNT,
    "rd_programme": "The name and one-line purpose of an R&D programme, project or research focus tied to this activity.",
    "milestone": (
        "The most advanced stage the company states it has reached: lab (research, prototype, proof of concept), "
        "pilot (pilot plant or line), demonstration (demonstrator, field test at scale), first_commercial (first "
        "commercial unit, first customer delivery, FID), series_production (serial manufacturing, ongoing sales)."
    ),
    "capacity": "Installed or planned capacity for this activity, with its unit and whether installed or planned, in raw_value_text.",
    "partnerships": "Each stated partnership, grant or offtake agreement for this activity, separated by '; '.",
    "news_momentum": (
        "Each stated recent event for this activity (launch, partnership, investment, expansion, order), with its "
        "date, separated by '; '. From the documents given, not from web search."
    ),
    "stage_ideation": "True only if a quote shows research, prototype, lab-scale or proof-of-concept work on this activity.",
    "stage_innovation": "True only if a quote shows a pilot, demonstrator, first commercial unit, pre-series production or a first order.",
    "stage_commercial": "True only if a quote shows ongoing sales, segment revenue, series production or a market position.",
}
KEYWORDS = {
    "revenue_amount": ["revenue", "sales", "turnover"],
    "capex_amount": ["capital expenditure", "capex", "investment", "invested"],
    "rd_amount": ["research and development", "R&D", "R&D expenses"],
    "rd_programme": ["research programme", "research project", "development programme"],
    "milestone": ["prototype", "pilot", "demonstrator", "first commercial", "series production"],
    "capacity": ["capacity", "MW", "GW", "production line", "plant"],
    "backlog": ["order backlog", "order intake", "orders"],
    "partnerships": ["partnership", "joint venture", "grant", "offtake", "agreement"],
    "news_momentum": ["launched", "announced", "signed", "expanded", "commissioned"],
    "stage_ideation": ["research programme", "prototype", "lab-scale", "proof of concept"],
    "stage_innovation": ["pilot plant", "demonstrator", "first commercial", "pre-series", "order", "FID"],
    "stage_commercial": ["segment revenue", "series production", "capacity", "backlog", "market share"],
}
SUFFIX = {
    "revenue_amount": "revenue amount", "capex_amount": "CapEx / investment amount", "rd_amount": "R&D spend amount",
    "rd_programme": "named R&D programme", "milestone": "most advanced development milestone",
    "capacity": "installed or planned capacity", "backlog": "orders / backlog",
    "partnerships": "partnerships, grants, offtake agreements", "news_momentum": "recent momentum events",
    "stage_ideation": "ideation-stage evidence", "stage_innovation": "innovation-stage evidence",
    "stage_commercial": "commercial-stage evidence",
}


def _act(activity_id: str, name: str, keywords: list[str]) -> ActivityDefinition:
    return ActivityDefinition(
        activity_id=activity_id, name=name, in_scope_description=f"{name} in scope.", out_of_scope_description="",
        seed_keywords=keywords,
    )


def _taxonomy(activities=None, status=TaxonomyStatus.RATIFIED) -> Taxonomy:
    if activities is None:
        activities = [_act("act_a", "Electrolyser manufacturing", ["electrolyser"]), _act("act_b", "Fuel cell manufacturing", [])]
    return Taxonomy(
        taxonomy_id="tax_fx", name="FX", version=1, theme=ThemeDefinition(name="FX", description="", activities=activities),
        derivation_method=DerivationMethod.MANUAL, status=status,
    )


@pytest.fixture
def fields():
    return {f.field_id: f for f in build_taxonomy_schema(_taxonomy()).fields}


def _f(fields, key, act="act_a"):
    return fields[f"tax_fx_{act}_{key}"]


def test_field_count():  # AC-1
    assert len(build_taxonomy_schema(_taxonomy()).fields) == 32


def test_field_order():  # AC-2
    ids = [f.field_id for f in build_taxonomy_schema(_taxonomy()).fields]
    for i, act in enumerate(("act_a", "act_b")):
        pct = [f"tax_fx_{act}_{m}_pct" for m in ("revenue", "capex", "opex", "rd")]
        assert ids[i * 16:(i + 1) * 16] == pct + [f"tax_fx_{act}_{k}" for k in KEYS]


def test_pct_fields_unchanged_from_main():  # AC-3
    expected = json.loads(FIXTURE.read_text())
    got = [f.model_dump(mode="json", exclude={"created_at", "effective_from"}) for f in build_taxonomy_schema(_taxonomy()).fields if f.field_id.endswith("_pct")]
    assert got == expected


def test_types(fields):  # AC-4a..e
    for key in ("revenue_amount", "capex_amount", "rd_amount", "backlog"):
        assert _f(fields, key).data_type.value == "currency_amount"
    for key in ("rd_programme", "partnerships", "news_momentum"):
        assert _f(fields, key).data_type.value == "string"
    assert _f(fields, "milestone").data_type.value == "enum"
    assert _f(fields, "capacity").data_type.value == "number" and _f(fields, "capacity").unit is None
    for key in ("stage_ideation", "stage_innovation", "stage_commercial"):
        assert _f(fields, key).data_type.value == "boolean"


def test_milestone_values(fields):  # AC-5
    assert _f(fields, "milestone").allowed_values == ["lab", "pilot", "demonstration", "first_commercial", "series_production"]


@pytest.mark.parametrize("key", KEYS)
def test_guidance(fields, key):  # AC-6, AC-6b
    assert _f(fields, key).extraction_instructions == f"{PREFIX} {GUIDANCE[key]}"


@pytest.mark.parametrize("key", KEYS)
def test_keywords(fields, key):  # AC-7
    assert _f(fields, key).seed_keywords == ["electrolyser", *KEYWORDS[key]]
    assert _f(fields, key, "act_b").seed_keywords == KEYWORDS[key]  # empty seed_keywords


@pytest.mark.parametrize("key", KEYS)
def test_names(fields, key):  # AC-7b
    assert _f(fields, key).name == f"Electrolyser manufacturing: {SUFFIX[key]}"


def test_descriptions_distinct(fields):  # AC-7c
    descs = [_f(fields, k).description for k in KEYS]
    assert all(descs) and len(set(descs)) == 12


def test_required_version_and_no_default(fields):  # AC-8, AC-14
    for key in KEYS:
        f = _f(fields, key)
        assert f.required is False and f.version == 1
        assert "default" not in f.model_dump() or f.model_dump()["default"] is None
    assert not {"stage", "stage_ideation", "stage_innovation", "stage_commercial"} & set(ActivityDefinition.model_fields)


def test_draft_refused():  # AC-9
    with pytest.raises(ValueError):
        build_taxonomy_schema(_taxonomy(status=TaxonomyStatus.DRAFT))


def test_rd_field_id_unchanged():  # AC-11
    assert field_id_for(build_taxonomy_schema(_taxonomy()), "act_a", "rd") == "tax_fx_act_a_rd_pct"


def test_punctuated_name_used_verbatim():
    fields = {f.field_id: f for f in build_taxonomy_schema(_taxonomy([_act("act_p", "Power-to-X", [])])).fields}
    assert fields["tax_fx_act_p_milestone"].name == "Power-to-X: most advanced development milestone"


def test_no_activities():
    assert build_taxonomy_schema(_taxonomy([])).fields == []
