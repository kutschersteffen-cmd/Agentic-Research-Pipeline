"""Typed answers per field type (spec 2026-10-31-extraction-quick-wins, AC-1 to AC-5e)."""

import pydantic
import pytest
from anthropic.types import Message, ToolUseBlock, Usage

from arp.extraction.extractor_agent import ExtractionDraft, draft_model_for, extract_field
from arp.extraction.verifier_agent import blind_verify
from arp.llm.langchain_client import LangChainAnthropicClient
from arp.schemas.datapoints import FieldDataType, FieldDefinition


def _field(dt, allowed=None):
    return FieldDefinition(field_id="f", name="f", description="d", data_type=dt, extraction_instructions="look",
                           allowed_values=allowed, high_risk=True)


def _msg(i, value, state="found"):
    tool_input = {"values": [{"value": value, "state": state}], "confidence": 0.9}
    return Message(id=f"m{i}", type="message", role="assistant", model="m", stop_reason="tool_use", stop_sequence=None,
                   content=[ToolUseBlock(type="tool_use", id=f"tu{i}", name="emit_result", input=tool_input)],
                   usage=Usage(input_tokens=1, output_tokens=1))


class _Messages:
    def __init__(self, values):
        self.values, self.calls = values, 0

    async def create(self, **kwargs):
        self.calls += 1
        return _msg(self.calls, *self.values[min(self.calls, len(self.values)) - 1])


def _client(tmp_path, *values):
    client = LangChainAnthropicClient(api_key="t", model="m", cache_dir=tmp_path, cache_enabled=False)
    msgs = _Messages([v if isinstance(v, tuple) else (v,) for v in values])
    client._client = type("C", (), {"messages": msgs})()
    return client, msgs


async def _run(tmp_path, dt, *values, allowed=None):
    client, msgs = _client(tmp_path, *values)
    draft, _ = await extract_field("Acme", _field(dt, allowed), [], client)
    return draft, msgs.calls


async def test_ac1_boolean_number_then_true(tmp_path):
    draft, _ = await _run(tmp_path, FieldDataType.BOOLEAN, 220221, True)
    assert draft.values[0].value is True


async def test_ac1b_two_calls(tmp_path):
    _, calls = await _run(tmp_path, FieldDataType.BOOLEAN, 220221, True)
    assert calls == 2


async def test_ac2_boolean_text_every_call_raises(tmp_path):
    client, msgs = _client(tmp_path, "Not disclosed")
    with pytest.raises(pydantic.ValidationError):
        await extract_field("Acme", _field(FieldDataType.BOOLEAN), [], client)
    assert msgs.calls == 3


async def test_ac3_enum_label_then_code(tmp_path):
    draft, _ = await _run(tmp_path, FieldDataType.ENUM, "EU Taxonomy", "eu_taxonomy", allowed=["eu_taxonomy", "other"])
    assert draft.values[0].value == "eu_taxonomy"


async def test_ac3b_enum_null(tmp_path):
    draft, _ = await _run(tmp_path, FieldDataType.ENUM, (None, "not_found"), allowed=["eu_taxonomy", "other"])
    assert draft.values[0].value is None


async def test_ac3c_enum_null_one_call(tmp_path):
    _, calls = await _run(tmp_path, FieldDataType.ENUM, (None, "not_found"), allowed=["eu_taxonomy", "other"])
    assert calls == 1


async def test_ac5_currency_int(tmp_path):
    draft, _ = await _run(tmp_path, FieldDataType.CURRENCY_AMOUNT, 11887)
    assert draft.values[0].value == 11887.0


async def test_ac5b_currency_one_call(tmp_path):
    _, calls = await _run(tmp_path, FieldDataType.CURRENCY_AMOUNT, 11887)
    assert calls == 1


async def test_ac5c_percentage_text_then_number(tmp_path):
    draft, _ = await _run(tmp_path, FieldDataType.PERCENTAGE, "39.6%", 39.6)
    assert draft.values[0].value == 39.6


async def test_ac5d_string_number_kept_as_text(tmp_path):
    draft, _ = await _run(tmp_path, FieldDataType.STRING, 11115)
    assert draft.values[0].value == "11115"


async def test_ac5e_date_text(tmp_path):
    draft, _ = await _run(tmp_path, FieldDataType.DATE, "2025-12-31")
    assert draft.values[0].value == "2025-12-31"


async def _blind(tmp_path):
    client, msgs = _client(tmp_path, "YES", False)
    draft = ExtractionDraft.model_validate({"values": [{"value": False}], "confidence": 0.9})
    out, _ = await blind_verify("Acme", _field(FieldDataType.BOOLEAN), [], draft, client)
    return out, msgs.calls


async def test_ac4_blind_verify_yes_then_false(tmp_path):
    out, _ = await _blind(tmp_path)
    assert out.agrees is True


async def test_ac4b_blind_verify_two_calls(tmp_path):
    _, calls = await _blind(tmp_path)
    assert calls == 2


def test_number_text_with_comma_rejected():  # Review Focus 1: rejected, so the client retries
    with pytest.raises(pydantic.ValidationError):
        draft_model_for(_field(FieldDataType.CURRENCY_AMOUNT)).model_validate({"values": [{"value": "1,234"}], "confidence": 1})


def test_boolean_string_true_rejected():  # Review Focus 2: strict, so the client retries
    with pytest.raises(pydantic.ValidationError):
        draft_model_for(_field(FieldDataType.BOOLEAN)).model_validate({"values": [{"value": "true"}], "confidence": 1})


def test_enum_without_allowed_values_is_text():  # Review Focus 3
    d = draft_model_for(_field(FieldDataType.ENUM)).model_validate({"values": [{"value": "x"}], "confidence": 1})
    assert d.values[0].value == "x"


def test_typed_model_keeps_class_name():  # FakeLLMClient scripts key on it
    assert draft_model_for(_field(FieldDataType.BOOLEAN)).__name__ == "ExtractionDraft"
