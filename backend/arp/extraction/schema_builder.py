from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from arp.llm.base import LLMClient, LLMUsage
from arp.normalise.units import lookup_unit, split_unit
from arp.schemas.common import DocType, new_id
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.rules import ComputedRule, FieldRule, RequiresRule, ThresholdRule, rule_inputs

_SYSTEM_PROMPT = """\
You design precise, machine-checkable extraction schemas for pulling data \
points out of company disclosures (10-Ks, sustainability reports, earnings \
call transcripts) at scale.

Given a short natural-language research request (e.g. "green capex", \
"forward-looking business outlook"), propose one or more fields that \
together capture what was asked. For each field:
- Write extraction_instructions precise enough that two different analysts \
  reading the same document would extract the same value: state exactly \
  what counts, common synonyms/phrasing to look for, how to handle a range \
  or multiple figures (e.g. take the most recently reported fiscal year), \
  and what to do when the figure is not disclosed (report as not found, \
  never estimate or infer).
- Pick the correct data_type and, for numeric fields, a unit: a plain unit   code such as "USD", "EUR", "%" or "tCO2e", or null when it varies by   company (e.g. each company's reporting currency). No scale words, no prose.
- Never tell the extractor to convert, rescale or round a number ("convert   to millions", "$1.2 billion -> 1200"): it copies the number and its unit   exactly as printed, and the app converts afterwards.
- Suggest 3-8 seed_keywords (including likely synonyms) that would appear \
  near this data point in text, to drive keyword-based evidence retrieval.
- Suggest which document types are most likely to contain it."""


def _readable_unit(unit: str | None) -> str | None:
    """The drafted unit, or None when the unit normaliser can't read it: free text such as
    "millions (report in the reporting currency)" would fail every conversion downstream."""
    return unit if unit and lookup_unit(split_unit(unit)[2]) is not None else None


class _FieldDraft(BaseModel):
    name: str
    description: str
    data_type: FieldDataType
    unit: str | None = None
    extraction_instructions: str
    allowed_values: list[str] | None = None
    seed_keywords: list[str] = Field(default_factory=list)
    source_doc_types: list[DocType] = Field(default_factory=list)


class _SchemaDraft(BaseModel):
    name: str
    description: str
    fields: list[_FieldDraft]


async def draft_schema(criteria_text: str, llm: LLMClient) -> tuple[DataPointSchema, LLMUsage]:
    """Turns a natural-language research request into a formal, editable
    DataPointSchema. The user reviews/edits the draft in the UI before any
    extraction run uses it -- this never runs unsupervised against real data.
    """
    prompt = f"Research request: {criteria_text}\n\nPropose the extraction schema per your instructions."
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_SchemaDraft)
    fields = [
        FieldDefinition(
            name=f.name,
            description=f.description,
            data_type=f.data_type,
            unit=_readable_unit(f.unit),
            extraction_instructions=f.extraction_instructions,
            allowed_values=f.allowed_values,
            seed_keywords=f.seed_keywords,
            source_doc_types=f.source_doc_types,
        )
        for f in draft.fields
    ]
    return DataPointSchema(name=draft.name, description=draft.description, fields=fields), usage


_RULES_PROMPT = """\
You propose validation rules for an extraction schema. A rule checks one \
field's extracted value against other fields' values; a failed rule only \
flags the row for a person to review.

Suggest ONLY these five kinds, with exactly these parameters:
- requires: field, equals. The other field must have this value.
- threshold: conditions, a list of {field, op, value} with op one of >=, <=, >, <, =. \
  Every condition must hold. Numeric fields only; the value is in that field's unit.
- series: field (numeric), years (1-5), trend (none, down or up). The field needs a value for \
  each of the last `years` fiscal years; down or up compares the last year with the first.
- label: field (an enum), not_in (values from that field's allowed values). The other field must not hold them.
- computed: formula (ratio_pct = inputs[0] / inputs[1] * 100, or sum), inputs (field ids), \
  tolerance (absolute, >= 0). This field must equal the formula's result.

Every rule has a rule_id (any short text) and an optional `when`: the value of the field the \
rule sits on that makes it apply (for example true); leave it empty to apply whenever the \
field was found. Each suggestion gives field_id, the field the rule sits on, and the rule.

Rules for you:
- Suggest a rule only for a dependency or threshold that the field's own description or \
  extraction instructions state (for example "50% by 2030", "past 5 years", "if no target ..."). \
  Never invent a threshold, a year count or a tolerance the text does not give.
- Refer to fields by their field_id, exactly as listed.
- If a rule needs a number or label that no listed field holds, add a helper field to \
  helper_fields (name, description, data_type, unit, extraction_instructions, allowed_values, \
  and a field_id) and refer to it by that field_id. Do not add a helper when a listed field already holds it.
- Suggest nothing when no field's text states a dependency or threshold. An empty answer is correct."""


class RuleSuggestion(BaseModel):
    field_id: str = Field(description="The field the rule sits on and checks.")
    rule: FieldRule


class RuleSuggestions(BaseModel):
    rules: list[RuleSuggestion] = Field(default_factory=list)
    helper_fields: list[FieldDefinition] = Field(
        default_factory=list, description="Fields the rules need that the schema lacks."
    )


def _remap(rule: FieldRule, ids: dict[str, str]) -> FieldRule:
    def g(i: str) -> str:
        return ids.get(i, i)

    if isinstance(rule, ThresholdRule):
        return rule.model_copy(update={"conditions": [c.model_copy(update={"field": g(c.field)}) for c in rule.conditions]})
    if isinstance(rule, ComputedRule):
        return rule.model_copy(update={"inputs": [g(i) for i in rule.inputs]})
    return rule.model_copy(update={"field": g(rule.field)})


def _fits(v, f: FieldDefinition) -> bool:
    """A `when`/`equals` that can match the field's value: typed equality never matches "true" to true."""
    if f.data_type == FieldDataType.BOOLEAN:
        return isinstance(v, bool)
    if f.data_type == FieldDataType.ENUM:
        return isinstance(v, str) and v in (f.allowed_values or [])
    if f.data_type in (FieldDataType.NUMBER, FieldDataType.CURRENCY_AMOUNT, FieldDataType.PERCENTAGE):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, str)


def _describe(f: FieldDefinition) -> str:
    return (
        f"- field_id: {f.field_id}; name: {f.name}; data_type: {f.data_type.value}; unit: {f.unit or 'none'}; "
        f"allowed_values: {', '.join(f.allowed_values) if f.allowed_values else 'none'}\n"
        f"  description: {f.description}\n  extraction_instructions: {f.extraction_instructions}"
    )


async def suggest_rules(schema: DataPointSchema, llm: LLMClient) -> tuple[RuleSuggestions, LLMUsage]:
    """Proposes rules (and the helper fields they need) for a drafted schema. Nothing applies until
    the user accepts it, but the output is untrusted: helpers are merged by name, rules get fresh ids
    and each is validated against the schema plus helpers, so an invalid one is dropped."""
    prompt = "Schema fields:\n" + "\n".join(_describe(f) for f in schema.fields) + "\n\nPropose the rules per your instructions."
    out, usage = await llm.complete_structured(system=_RULES_PROMPT, prompt=prompt, output_model=RuleSuggestions)

    by_name = {f.name.strip().casefold(): f.field_id for f in schema.fields}
    used_ids = {f.field_id for f in schema.fields}
    ids: dict[str, str] = {}
    helpers: list[FieldDefinition] = []
    for h in out.helper_fields:
        # A helper only holds a value: keep the draft's keys, so no model-set rule or setting applies on Accept.
        h = FieldDefinition(
            field_id=h.field_id, **h.model_dump(include=set(_FieldDraft.model_fields) - {"unit"}), unit=_readable_unit(h.unit)
        )
        key = h.name.strip().casefold()
        if key in by_name:
            ids[h.field_id] = by_name[key]
            continue
        if h.field_id in used_ids:  # the model reused an id that names another field
            new = new_id("fld")
            ids[h.field_id], h = new, h.model_copy(update={"field_id": new})
        by_name[key] = h.field_id
        used_ids.add(h.field_id)
        helpers.append(h)

    fields = [*schema.fields, *helpers]
    by_id = {f.field_id: f for f in fields}
    kept: list[RuleSuggestion] = []
    for sug in out.rules:
        target = ids.get(sug.field_id, sug.field_id)
        rule = _remap(sug.rule, ids).model_copy(update={"rule_id": new_id("rule")})
        if target not in used_ids:
            continue
        if (rule.when is not None and not _fits(rule.when, by_id[target])) or (
            isinstance(rule, RequiresRule) and rule.field in by_id and not _fits(rule.equals, by_id[rule.field])
        ):
            continue
        try:
            DataPointSchema(
                name=schema.name,
                fields=[f.model_copy(update={"rules": [*f.rules, rule]}) if f.field_id == target else f for f in fields],
            )
        except ValidationError:
            continue
        kept.append(RuleSuggestion(field_id=target, rule=rule))

    named = {i for k in kept for i in (*rule_inputs(k.rule), k.field_id)}
    return RuleSuggestions(rules=kept, helper_fields=[h for h in helpers if h.field_id in named]), usage
