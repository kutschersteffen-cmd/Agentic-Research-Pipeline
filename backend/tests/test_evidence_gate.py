"""Evidence gate (evidence-gate spec): what it keeps, how it fails open, the breaker, and what the trace records."""

import asyncio
import logging

import pytest

from arp.config import Settings
from arp.extraction.evidence_gate import EvidenceGate, GateAnswer, gate_run
from arp.extraction.pipeline import input_settings
from arp.llm.base import LLMUsage
from arp.orchestration.cost_tracker import estimate_cost_usd
from arp.schemas.common import DocType, DocumentChunk
from arp.schemas.datapoints import FieldDataType, FieldDefinition

USAGE = LLMUsage(input_tokens=1000, output_tokens=50, model="claude-haiku-5-5")
PASSAGES = [DocumentChunk(chunk_id=f"c{i}", doc_id="d", company_id="c", doc_type=DocType.ANNUAL_REPORT_10K,
                          text=f"passage text {i}", char_start=i * 100, char_end=i * 100 + 50) for i in range(1, 11)]


def _field(**kw):
    return FieldDefinition(**{"field_id": "capex", "name": "green capex", "description": "Green capital expenditure",
                              "data_type": FieldDataType.NUMBER, "extraction_instructions": "Report the total.",
                              "seed_keywords": ["capex"], **kw})


class Stub:
    def __init__(self, answer=None, error=None, sleep=0.0):
        self.answer, self.error, self.sleep, self.calls, self.prompts = answer, error, sleep, 0, []

    async def complete_structured(self, *, system, prompt, output_model, **kw):
        self.calls += 1
        self.prompts.append(prompt)
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.error:
            raise self.error
        return self.answer, USAGE


def _gate(stub, **kw):
    return EvidenceGate(stub, **{"min_keep": 3, "breaker": 3, "timeout_s": 5, **kw})


def _ranks(result):
    return [PASSAGES.index(c) + 1 for c in result.kept]


async def test_default_settings_open_no_gate():  # AC-1
    with gate_run(Settings(anthropic_api_key="x")) as gate:
        assert gate is None


async def test_keeps_named_and_top_three():  # AC-2, AC-19
    r = await _gate(Stub(GateAnswer(keep=[2, 5, 9]))).apply(_field(), PASSAGES)
    assert _ranks(r) == [1, 2, 3, 5, 9]
    assert r.info == {"kept": 5, "of": 10, "failed": False, "skipped": None}


async def test_out_of_range_ids_ignored():  # AC-3
    assert _ranks(await _gate(Stub(GateAnswer(keep=[0, 11, 4]))).apply(_field(), PASSAGES)) == [1, 2, 3, 4]


@pytest.mark.parametrize("stub", [
    Stub(GateAnswer(keep=[0, 11])),  # AC-4
    Stub(error=RuntimeError("down")),  # AC-5
    Stub(GateAnswer(keep=[])),  # AC-6
    Stub(error=ValueError("output does not fit GateAnswer")),  # AC-7: the client raises on invalid output
])
async def test_failures_keep_everything(stub):  # AC-4 to AC-7, AC-9
    r = await _gate(stub).apply(_field(), PASSAGES)
    assert r.kept == PASSAGES
    assert r.info == {"kept": 10, "of": 10, "failed": True, "skipped": None}


async def test_timeout_keeps_everything():  # AC-8
    r = await _gate(Stub(GateAnswer(keep=[1]), sleep=1), timeout_s=0.05).apply(_field(), PASSAGES)
    assert r.kept == PASSAGES and r.info["failed"] is True


async def test_breaker_opens_after_three(caplog):  # AC-10, AC-11, AC-12
    stub = Stub(error=RuntimeError("down"))
    gate = _gate(stub, run_id="run_1")
    with caplog.at_level(logging.WARNING):
        results = [await gate.apply(_field(), PASSAGES) for _ in range(5)]
    assert stub.calls == 3
    assert [r.info["skipped"] for r in results[3:]] == ["breaker open", "breaker open"]
    assert len([r for r in caplog.records if "evidence gate breaker open" in r.getMessage()]) == 1


async def test_a_success_resets_the_count():  # AC-13
    stub = Stub(error=RuntimeError("down"))
    gate = _gate(stub)
    for i in range(5):
        stub.error = None if i == 1 else RuntimeError("down")
        stub.answer = GateAnswer(keep=[4])
        await gate.apply(_field(), PASSAGES)
    assert stub.calls == 5


@pytest.mark.parametrize(("kw", "evidence", "reason"), [
    ({"field": _field(high_risk=True)}, PASSAGES, "high risk"),  # AC-14
    ({}, PASSAGES[:3], "too few passages"),  # AC-15
    ({"grouped": True}, PASSAGES, "grouped"),  # AC-16
    ({"unranked": True}, PASSAGES, "unranked"),  # AC-17
])
async def test_skips(kw, evidence, reason):
    stub = Stub(GateAnswer(keep=[1]))
    kw = dict(kw)  # parametrize shares this dict between runs: never change it
    f = kw.pop("field", _field())
    r = await _gate(stub).apply(f, evidence, **kw)
    assert stub.calls == 0
    assert r.info == {"kept": len(evidence), "of": len(evidence), "failed": False, "skipped": reason}


async def test_prompt_holds_the_field_and_numbered_passages():  # AC-18
    stub = Stub(GateAnswer(keep=[2]))
    await _gate(stub).apply(_field(), PASSAGES)
    prompt = stub.prompts[0]
    assert all(s in prompt for s in ("green capex", "Green capital expenditure", "Report the total."))
    positions = [prompt.index(f"[{i}] passage text {i}") for i in range(1, 11)]
    assert positions == sorted(positions)


async def test_dropped_and_usage():  # AC-20, AC-21 (the gate's part; the trace copies them)
    r = await _gate(Stub(GateAnswer(keep=[2, 5, 9]))).apply(_field(), PASSAGES)
    assert [PASSAGES.index(c) + 1 for c in r.dropped] == [4, 6, 7, 8, 10]
    assert r.usage == USAGE
    from arp.walkthrough import trace
    call = trace.call(r.usage, r.answer)
    assert (call["model"], call["input_tokens"], call["output_tokens"]) == ("claude-haiku-5-5", 1000, 50)
    assert call["cost_usd"] == round(estimate_cost_usd("claude-haiku-5-5", USAGE), 6)


def test_gate_settings_change_the_input_hash():  # AC-23, AC-24
    off = Settings(anthropic_api_key="x")
    on = Settings(anthropic_api_key="x", evidence_gate_enabled=True)
    other = Settings(anthropic_api_key="x", evidence_gate_enabled=True, evidence_gate_model="gemini-3.8-flash")
    assert input_settings(off) != input_settings(on) != input_settings(other)
    assert input_settings(off) == input_settings(Settings(anthropic_api_key="x"))


# --- through the field graph ---

async def test_extractor_sees_only_kept_passages_and_trace_records_the_gate(fake_llm):  # AC-2, AC-19 to AC-22 end to end
    from arp.extraction import evidence_gate
    from arp.extraction.field_graph import extract_one_field
    from tests.test_walkthrough_field_graph import _LONG_DOC, _agreeing_llm
    from tests.test_walkthrough_field_graph import _field as wt_field

    llm, sink = _agreeing_llm(fake_llm), {}
    gate = _gate(Stub(GateAnswer(keep=[5])))
    token = evidence_gate._current.set(gate)
    try:
        _, _, usages = await extract_one_field(
            "Acme", wt_field(), documents=[_LONG_DOC], documents_by_id={_LONG_DOC.doc_id: _LONG_DOC}, llm=llm,
            verifier_llm=llm, fuzzy_threshold=0.9, confidence_review_threshold=0.6, trace_sink=sink)
    finally:
        evidence_gate._current.reset(token)
    e = sink["scope1"]
    assert e["retrieval"]["gate"]["kept"] == 4 and e["retrieval"]["gate"]["failed"] is False
    assert len(e["passages"]) == 4 and len(e["gate_dropped"]) == e["retrieval"]["gate"]["of"] - 4
    dropped_text = [_LONG_DOC.full_text[p["char_start"]:p["char_end"]] for p in e["gate_dropped"]]
    assert not any(t in llm.prompts[0] for t in dropped_text)
    assert e["gate"]["model"] == "claude-haiku-5-5"
    assert USAGE in usages  # the run's cost is summed from these usages


def test_golden_set_gate_output(monkeypatch, pg):  # AC-34; pg: the CLI callback needs a DSN
    from typer.testing import CliRunner

    from arp.cli import app as cli_app
    from arp.cli import golden_set as cli
    from arp.golden_set.schema import GoldenSetCaseResult, GoldenSetReport

    def case(cid, ok):
        return GoldenSetCaseResult(case_id=cid, description="d", passed=ok, expected_value=1.0, actual_value=1.0 if ok else 2.0,
                                   confidence=0.9, grounded=True, needs_review=False)

    async def fake_run(cases, **kw):
        return GoldenSetReport(total=2, passed=1, failed_case_ids=["c2"], results=[case("c1", True), case("c2", False)],
                               extractor_input_tokens=4321)

    monkeypatch.setattr(cli, "build_llm_client", lambda *a, **k: None)
    monkeypatch.setattr(cli, "build_verifier_llm_client", lambda *a, **k: None)
    monkeypatch.setattr(cli, "load_golden_set_cases", lambda f, **kw: [])
    monkeypatch.setattr(cli, "run_golden_set", fake_run)
    monkeypatch.setattr(cli, "gate_run", lambda *a, **k: __import__("contextlib").nullcontext())
    result = CliRunner().invoke(cli_app, ["golden-set", "run", "--gate", "on"])
    lines = result.output.strip().splitlines()
    assert lines[-3:] == ["c1: pass", "c2: fail", "extractor input tokens: 4321"]
    assert result.exit_code == 1
