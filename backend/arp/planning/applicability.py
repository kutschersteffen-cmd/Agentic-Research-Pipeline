"""Rule-based per-field applicability (E64): no model call decides whether a field applies."""

from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldDefinition, ValueState


def _norm(values: list[str]) -> set[str]:
    return {v.strip().casefold() for v in values}


def not_applicable_reason(field: FieldDefinition, company: CompanyRef) -> str | None:
    rules = field.applicability_rules
    if rules is None:
        return None
    isic = (company.isic_code or "").strip()
    if rules.sector_codes and isic and not any(isic.startswith(p.strip()) for p in rules.sector_codes):
        return f"isic {isic} not in sector_codes {rules.sector_codes}"
    if rules.countries and company.country and not _norm([company.country]) & _norm(rules.countries):
        return f"country {company.country} not in countries {rules.countries}"
    if rules.regimes and company.regimes and not _norm(company.regimes) & _norm(rules.regimes):
        return f"regimes {company.regimes} not in regimes {rules.regimes}"
    return None


def plan_fields(schema: DataPointSchema, company: CompanyRef) -> tuple[list[FieldDefinition], list[ExtractedField]]:
    to_extract: list[FieldDefinition] = []
    skipped: list[ExtractedField] = []
    for field in schema.fields:
        reason = not_applicable_reason(field, company)
        if reason is None:
            to_extract.append(field)
            continue
        skipped.append(
            ExtractedField(
                field_id=field.field_id, field_name=field.name, value=None, confidence=0.0, grounded=True,
                value_state=ValueState.NOT_APPLICABLE, route_reasons=["not_applicable_by_rule"],
                verifier_notes=reason, review_reasons=[],
            )
        )
    return to_extract, skipped
