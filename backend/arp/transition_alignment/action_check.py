"""P5's sector check on `ta_action_id`, kept free of extraction imports: arp.checks registers it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from arp.schemas.datapoints import CheckOutcome, CheckResult, ExtractedField, FieldDefinition, Severity, ValueState
from arp.transition_alignment.benchmarks import load_benchmarks, sector_for_isic
from arp.transition_barrier import dataset
from arp.transition_barrier.rule_book import load_rule_book

if TYPE_CHECKING:
    from arp.checks.runner import CheckContext


def sector_actions(sector: str | None) -> list[dict]:
    """The active rule book's actions for the sector ({id, label}); none for no sector."""
    return load_rule_book(dataset.data_dir())[0].actions.get(sector or "", [])


def check_action_id(spec: FieldDefinition, field: ExtractedField, ctx: CheckContext) -> list[CheckResult]:
    """P5: the classification must be one of the company's sector's rule-book ids, or `other`. Run by the check
    runner (registered in arp.checks), so check_record, which replaces a row's checks, keeps it."""
    if spec.field_id != "ta_action_id" or field.value_state != ValueState.FOUND:
        return []
    allowed = {a["id"] for a in sector_actions(sector_for_isic(load_benchmarks(), ctx.company.isic_code))} | {"other"}
    ok = field.value in allowed
    return [CheckResult(check_id="action_id", layer=1, outcome=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
                        severity=Severity.BLOCK, detail="" if ok else f"Unknown action id '{field.value}'")]
