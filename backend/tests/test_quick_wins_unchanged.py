"""AC-18 and AC-22: the paths the typed answer format leaves alone keep accepting loose answers.

The snapshots were captured from main before the change (ARP_WRITE_SNAPSHOTS=1 rewrites them)."""

import json
import os
from pathlib import Path

import pytest

from arp.extraction.extractor_agent import extract_group
from arp.extraction.financials_extractor_agent import extract_financials
from arp.extraction.tnfd_extractor_agent import extract_tnfd
from arp.llm.base import LLMUsage
from arp.presets.transition_plan_actions import build_transition_plan_actions_schema
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition
from arp.transition_alignment.plan_extraction import extract_plan

_SNAP = Path(__file__).parent / "fixtures" / "quick_wins"
_DOC = SourceDocument(doc_id="doc_fixed", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="Report", full_text="Text.")


class _Validating:
    """A stand-in that validates a raw tool input against the requested format, as the real client does."""

    def __init__(self, raw: dict) -> None:
        self.raw, self.calls = raw, 0

    async def complete_structured(self, *, system, prompt, output_model, **_):
        self.calls += 1
        return output_model.model_validate(self.raw), LLMUsage(provider="fake")


def _check(name: str, result, calls: int) -> None:
    path = _SNAP / f"{name}.json"
    got = {"result": json.loads(json.dumps(result, default=str)), "calls": calls}
    if os.environ.get("ARP_WRITE_SNAPSHOTS"):
        path.write_text(json.dumps(got, indent=2, sort_keys=True))
    assert got == json.loads(path.read_text())


_PLAN = {"actions": [{"text": {"value": "Close lignite units", "quote": "q"}, "ghg_saving": {"value": "Not disclosed"}}],
         "confidence": 0.8}
_FIN = {"capex": {"total": {"value": "Not disclosed"}}, "confidence": 0.7}
_TNFD = {"general_requirements": {"materiality_approach": "a", "disclosure_scope": "b", "location_specificity": "c",
                                  "iplc_engagement_described": "Not disclosed"}, "confidence": 0.6}


async def _plan():
    llm = _Validating(_PLAN)
    fields = [f for f in build_transition_plan_actions_schema().fields if f.field_id == "ta_action_text"]
    rows, _ = await extract_plan(CompanyRef(company_id="c1", name="Acme"), None, _DOC, [], llm,
                                 fields=fields, fuzzy_threshold=0.9)
    keep = ("field_id", "value", "value_state", "basis", "review_reasons", "grounded")
    return [{k: r.model_dump(mode="json")[k] for k in keep} for r in rows], llm.calls


async def test_ac22_plan_row_unchanged():
    rows, _ = await _plan()
    _check("ac22_plan", rows, 1)


async def test_ac22_calls():
    _, calls = await _plan()
    assert calls == json.loads((_SNAP / "ac22_plan.json").read_text())["calls"]


@pytest.mark.parametrize("name,raw,run", [
    ("ac22b_financials", _FIN, lambda llm: extract_financials("Acme", [], llm)),
    ("ac22c_tnfd", _TNFD, lambda llm: extract_tnfd("Acme", None, [], llm)),
])
async def test_ac22bc_unchanged(name, raw, run):
    llm = _Validating(raw)
    try:
        draft, _ = await run(llm)
        result = draft.model_dump(mode="json")
    except Exception as exc:  # today's behaviour is snapshotted, whichever it is
        result = {"error": type(exc).__name__}
    _check(name, result, llm.calls)


_BOOL = FieldDefinition(field_id="b1", name="b1", description="d", data_type=FieldDataType.BOOLEAN,
                        extraction_instructions="look", high_risk=False)


async def test_ac18_group_call_keeps_loose_format():
    llm = _Validating({"fields": [{"field_id": "b1", "draft": {"values": [{"value": "yes"}], "confidence": 0.7}}]})
    drafts, _ = await extract_group("Acme", [_BOOL], [], llm)
    assert drafts["b1"].values[0].value == "yes"


async def test_ac18b_group_call_one_call():
    llm = _Validating({"fields": [{"field_id": "b1", "draft": {"values": [{"value": "yes"}], "confidence": 0.7}}]})
    await extract_group("Acme", [_BOOL], [], llm)
    assert llm.calls == 1
