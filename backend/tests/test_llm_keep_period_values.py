"""Spec llm-keep-period-values: a bad citation drops that citation, never the period; every drop is counted and logged."""
import json
import logging
from types import SimpleNamespace

from arp.extraction.adjudicator import AdjudicatorOutput
from arp.extraction.extractor_agent import GroupDraft, draft_model_for
from arp.extraction.tnfd_extractor_agent import TNFDExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.llm.gemini_client import GeminiClient
from arp.schemas.datapoints import FieldDataType, FieldDefinition
from tests.test_langchain_client_retry import _client_with_responses, _message, _TargetWithItems

GOOD = {"doc_id": "d", "doc_type": "10-K", "quote": "q"}
BAD = {"doc_id": "d"}
Draft = draft_model_for(FieldDefinition(name="rev", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="i"))
LOGGER = "arp.llm.langchain_client"


def period(value, citations, **extra):
    return {"value": value, "citations": citations, **extra}


def draft(a, b):
    return {"values": [a, b], "confidence": 0.5}


VALID = draft(period(100, [GOOD]), period(90, [GOOD]))


def warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING and r.name == LOGGER]


async def run_anthropic(tmp_path, answers, model=Draft, **kw):
    client, fake = _client_with_responses(tmp_path, [_message(f"tu_{i}", a) for i, a in enumerate(answers)])
    client.cache.enabled = kw.get("cache_enabled", False)
    out, usage = await client.complete_structured(system="s", prompt="p", output_model=model)
    return out, usage, fake.messages.calls


class _Gemini(GeminiClient):
    def __init__(self, tmp_path, answers):
        super().__init__(api_key="k", model="gemini-3.8-flash", cache_dir=tmp_path, cache_enabled=False)
        self.answers, self.sent = list(answers), []

    async def _send(self, contents, config):
        self.sent.append(contents)
        usage = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0, cached_content_token_count=0)
        return SimpleNamespace(text=json.dumps(self.answers.pop(0)), usage_metadata=usage)


async def run_gemini(tmp_path, answers):
    client = _Gemini(tmp_path, answers)
    out, usage = await client.complete_structured(system="s", prompt="p", output_model=Draft)
    return out, usage, client.sent


def values(out):
    return [v.value for v in out.values]


async def test_ac1_bad_citation_next_to_good_one_is_dropped(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [draft(period(100, [GOOD, BAD]), period(90, [GOOD]))])
    assert (len(calls), usage.attempts, usage.dropped_items) == (1, 1, 1)
    assert values(out) == [100, 90] and [len(v.citations) for v in out.values] == [1, 1]


async def test_ac2_only_citation_bad_keeps_the_period_uncited(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [draft(period(100, [BAD]), period(90, [GOOD]))])
    assert (len(calls), usage.dropped_items) == (1, 1)
    assert values(out) == [100, 90] and [len(v.citations) for v in out.values] == [0, 1]


async def test_ac3_two_bad_citations_count_two(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [draft(period(100, [BAD, BAD]), period(90, [GOOD]))])
    assert (len(calls), usage.dropped_items) == (1, 2)
    assert values(out) == [100, 90] and [len(v.citations) for v in out.values] == [0, 1]


async def test_ac4_a_bad_item_is_dropped_counted_and_warned(tmp_path, caplog):
    out, usage, calls = await run_anthropic(tmp_path, [{"values": [period(100, [GOOD]), 5], "confidence": 0.5}])
    assert (len(calls), usage.attempts, usage.dropped_items) == (1, 1, 1)
    assert values(out) == [100] and len(out.values[0].citations) == 1
    [w] = warnings(caplog)
    assert "values.1" in w.getMessage()


async def test_ac5_a_list_value_is_retried(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [draft(period(100, [GOOD]), period([1], [GOOD])), VALID])
    assert (len(calls), usage.attempts, usage.dropped_items) == (2, 2, 0)
    assert values(out) == [100, 90]


def group(a, b):
    return {"fields": [{"field_id": "a", "draft": draft(*a)}, {"field_id": "b", "draft": {"values": [period(1, [GOOD])], "confidence": 0.5}}]}


async def test_ac6_ac7_group_draft_keeps_both_periods_and_the_other_field(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [group((period(100, [GOOD, BAD]), period(90, [GOOD])), None)], model=GroupDraft)
    assert (len(calls), usage.dropped_items) == (1, 1)
    a, b = out.fields
    assert [v.value for v in a.draft.values] == [100, 90] and len(a.draft.values[0].citations) == 1
    assert [v.value for v in b.draft.values] == [1] and len(b.draft.values[0].citations) == 1


async def test_ac8_gemini_drops_the_bad_citation_only(tmp_path):
    out, usage, sent = await run_gemini(tmp_path, [draft(period(100, [GOOD, BAD]), period(90, [GOOD]))])
    assert (len(sent), usage.attempts, usage.dropped_items) == (1, 1, 1)
    assert values(out) == [100, 90] and len(out.values[0].citations) == 1


async def test_ac9_gemini_keeps_the_uncited_period(tmp_path):
    out, usage, sent = await run_gemini(tmp_path, [draft(period(100, [BAD]), period(90, [GOOD]))])
    assert (len(sent), usage.dropped_items) == (1, 1)
    assert values(out) == [100, 90] and out.values[0].citations == []


async def test_ac10_a_bad_period_field_is_retried(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [draft(period(100, [GOOD], period_text=["x"]), period(90, [GOOD])), VALID])
    assert (len(calls), usage.attempts, usage.dropped_items) == (2, 2, 0)
    assert values(out) == [100, 90]


async def test_ac11_warning_names_the_model_and_the_path(tmp_path, caplog):
    await run_anthropic(tmp_path, [draft(period(100, [GOOD, BAD]), period(90, [GOOD]))])
    [w] = warnings(caplog)
    assert "ExtractionDraft" in w.getMessage() and "values.0.citations.1" in w.getMessage()


async def test_ac12_top_level_item_drop_is_counted_and_warned(tmp_path, caplog):
    out, usage, calls = await run_anthropic(tmp_path, [{"value": 1, "items": [{"kind": "a"}, {"not_kind": "b"}]}], model=_TargetWithItems)
    assert len(calls) == 1 and [i.kind for i in out.items] == ["a"] and usage.dropped_items == 1
    [w] = warnings(caplog)
    assert "items.1" in w.getMessage()


async def test_ac13_tnfd_bad_item_is_dropped_and_counted(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [{"core_global_metrics": [{"value": "Not disclosed"}], "confidence": 0.5}], model=TNFDExtractionDraft)
    assert len(calls) == 1 and out.core_global_metrics == [] and usage.dropped_items == 1


async def test_ac14_valid_draft_is_untouched(tmp_path, caplog):
    out, usage, calls = await run_anthropic(tmp_path, [VALID])
    assert (len(calls), usage.dropped_items) == (1, 0) and not warnings(caplog)


async def test_ac15_ac16_cache_hit_keeps_the_count_and_does_not_warn(tmp_path, caplog):
    client, fake = _client_with_responses(tmp_path, [_message("tu_0", draft(period(100, [GOOD, BAD]), period(90, [GOOD])))])
    client.cache.enabled = True
    await client.complete_structured(system="s", prompt="p", output_model=Draft)
    caplog.clear()
    _, usage = await client.complete_structured(system="s", prompt="p", output_model=Draft)
    assert len(fake.messages.calls) == 1 and usage.cached is True and usage.dropped_items == 1
    assert not warnings(caplog)


async def test_ac17_citations_that_are_not_a_list_are_retried(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [draft(period(100, "x"), period(90, [GOOD])), VALID])
    assert (len(calls), usage.attempts, usage.dropped_items) == (2, 2, 0)
    assert values(out) == [100, 90]


async def test_ac18_a_retry_discards_the_first_answers_drops(tmp_path, caplog):
    first = draft(period(100, [GOOD, BAD]), period([1], [GOOD]))
    second = draft(period(100, [GOOD, GOOD]), period(90, [GOOD]))
    out, usage, calls = await run_anthropic(tmp_path, [first, second])
    assert (len(calls), usage.attempts, usage.dropped_items) == (2, 2, 0)
    assert len(out.values[0].citations) == 2 and not warnings(caplog)


async def test_ac19_tnfd_metric_keeps_its_value(tmp_path):
    metric = {"category": "c", "metric_kind": "k", "metric_name": "n", "value": 5.0, "citations": [GOOD, BAD]}
    out, usage, calls = await run_anthropic(tmp_path, [{"core_global_metrics": [metric], "confidence": 0.5}], model=TNFDExtractionDraft)
    assert (len(calls), usage.dropped_items) == (1, 1)
    [m] = out.core_global_metrics
    assert m.value == 5.0 and len(m.citations) == 1


async def test_ac20_verifier_top_level_citation_is_dropped(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [{"agrees": True, "confidence": 0.5, "notes": "n", "citations": [GOOD, BAD]}], model=VerifierOutput)
    assert (len(calls), usage.dropped_items, len(out.citations)) == (1, 1, 1)


async def test_ac21_adjudicator_top_level_citation_is_dropped(tmp_path):
    out, usage, calls = await run_anthropic(tmp_path, [{"settled": True, "notes": "n", "citations": [GOOD, BAD]}], model=AdjudicatorOutput)
    assert (len(calls), usage.dropped_items, len(out.citations)) == (1, 1, 1)


async def test_ac22_gemini_retries_a_list_value(tmp_path):
    out, usage, sent = await run_gemini(tmp_path, [draft(period(100, [GOOD]), period([1], [GOOD])), VALID])
    assert (len(sent), usage.attempts, usage.dropped_items) == (2, 2, 0) and values(out) == [100, 90]


async def test_ac23_gemini_retries_a_bad_period_field(tmp_path):
    _, usage, sent = await run_gemini(tmp_path, [draft(period(100, [GOOD], period_text=["x"]), period(90, [GOOD])), VALID])
    assert (len(sent), usage.attempts, usage.dropped_items) == (2, 2, 0)
