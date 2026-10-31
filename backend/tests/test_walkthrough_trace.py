import pytest

from arp.extraction.verifier_agent import VerifierOutput
from arp.llm.base import LLMUsage
from arp.schemas.common import DocType, DocumentChunk
from arp.walkthrough.trace import call, field_entry, passage, read_trace, trace_path, write_trace

RUN = "r1"


def test_field_entry_has_every_key():
    entry = field_entry("f1")
    assert set(entry) == {"field_id", "grouped", "skipped", "passages", "extractor", "verifier", "adjudicator", "vision", "routing"}
    assert entry == {
        "field_id": "f1",
        "grouped": False,
        "skipped": None,
        "passages": [],
        "extractor": None,
        "verifier": None,
        "adjudicator": None,
        "vision": None,
        "routing": None,
    }


def test_passage_keys_are_exact():
    chunk = DocumentChunk(
        doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, section="Risks", text="t", char_start=3, char_end=9
    )
    assert passage(chunk) == {"doc_id": "d1", "char_start": 3, "char_end": 9, "section": "Risks"}


def test_call_records_usage_and_answer():
    usage = LLMUsage(model="m", prompt_version="p")
    out = call(usage, VerifierOutput(agrees=True, confidence=0.9, notes="ok"))
    assert out["answer"]["agrees"] is True
    assert out["model"] == "m"
    assert out["prompt_version"] == "p"
    assert call(usage, None) is None


def test_write_then_read_round_trip(run_store):
    trace = {"fields": [field_entry("f1")]}
    write_trace(run_store, RUN, "c1", trace)
    assert read_trace(run_store, RUN, "c1") == trace
    assert (run_store.run_dir(RUN) / "traces" / "c1.json").is_file()


def test_empty_trace_is_not_written(run_store):
    write_trace(run_store, RUN, "c1", {})
    assert read_trace(run_store, RUN, "c1") is None
    assert not (run_store.run_dir(RUN) / "traces").exists()


def test_write_failure_records_event_and_does_not_raise(run_store):
    (run_store.run_dir(RUN) / "traces").write_text("in the way")
    write_trace(run_store, RUN, "c1", {"fields": [field_entry("f1")]})
    events = run_store.read_events(RUN)
    assert [(e["type"], e["company_id"]) for e in events] == [("trace_write_failed", "c1")]
    assert "at" in events[0]


def test_corrupt_trace_reads_as_none(run_store):
    path = trace_path(run_store, RUN, "c1")
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert read_trace(run_store, RUN, "c1") is None


def test_company_id_with_path_parts_is_refused(run_store):
    with pytest.raises(ValueError):
        trace_path(run_store, RUN, "../x")
    write_trace(run_store, RUN, "../x", {"fields": [field_entry("f1")]})
    assert [e["type"] for e in run_store.read_events(RUN)] == ["trace_write_failed"]
    assert not list(run_store.run_dir(RUN).rglob("x.json"))
    assert not (run_store.run_dir(RUN).parent / "x.json").exists()
