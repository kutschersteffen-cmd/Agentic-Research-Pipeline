"""Seeded known-answer items carry a walkthrough trace built like a real run's (argus-walkthrough spec)."""

from __future__ import annotations

import asyncio
import json
import random
import re

import pytest

from arp.extraction.field_graph import field_evidence, merge_evidence
from arp.golden_set.runner import load_cases
from arp.ingestion.local_files import parser_version
from arp.review.quality import _record, seed_known_answers
from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import DataPointSchema
from arp.walkthrough import trace
from tests.test_review_quality import qenv  # noqa: F401, F811 - fixture

pytestmark = pytest.mark.usefixtures("pg")


def _seeded_record(settings, high_risk=False):
    case = next(c for c in load_cases() if c.expected_value is not None)
    spec = case.field.model_copy(update={"high_risk": high_risk})
    sink: dict = {}
    record = asyncio.run(_record(
        CompanyRef(company_id="c1", name="Co"), case, case.expected_value,
        DataPointSchema(name="s", fields=[spec]), spec, settings, random.Random(1), trace_sink=sink,
    ))
    return case, spec, record, sink["fields"][spec.field_id]


def test_seeded_trace_written(qenv):  # noqa: F811
    rs, _, settings = qenv
    run_id = seed_known_answers(rs, settings, count=3, seed=3)
    companies = rs.load_companies(run_id)
    assert companies
    for c in companies:
        data = json.loads((rs.run_dir(run_id) / "traces" / f"{c.company_id}.json").read_text())
        assert list(data) == ["fields"]
        [entry] = data["fields"].values()
        assert entry["passages"] and entry["extractor"]["answer"] and entry["verifier"]


def test_seeded_passages_match_real_selection(qenv):  # noqa: F811  # AC-21
    _, store, settings = qenv
    case, spec, record, entry = _seeded_record(settings)
    [d] = record.documents
    doc = SourceDocument(
        doc_id=d["doc_id"], company_id=d["company_id"], doc_type=case.doc_type, title=d["title"],
        full_text=case.document_text, content_key=d["content_key"], parser_version=parser_version(),
    )
    want = [(c.doc_id, c.char_start, c.char_end, c.section) for c in field_evidence(spec, [doc], settings)]
    assert want
    assert [(p["doc_id"], p["char_start"], p["char_end"], p["section"]) for p in entry["passages"]] == want


def test_seeded_grouped_field_passages(qenv):  # noqa: F811  # AC-72
    # A seeded company holds one field, and a real run groups only when more than one field has evidence;
    # merge_evidence of a single ranking is that ranking, so the seeded passages are the group's selection.
    _, _, settings = qenv
    settings = settings.model_copy(update={"extraction_group_size": 4})
    case, spec, record, entry = _seeded_record(settings)
    assert not spec.high_risk and not spec.xbrl_tags
    [d] = record.documents
    doc = SourceDocument(
        doc_id=d["doc_id"], company_id=d["company_id"], doc_type=case.doc_type, title=d["title"],
        full_text=case.document_text, content_key=d["content_key"], parser_version=parser_version(),
    )
    want = [(c.doc_id, c.char_start, c.char_end, c.section)
            for c in merge_evidence([field_evidence(spec, [doc], settings)], settings.evidence_max_chunks * 2)]
    assert want
    assert [(p["doc_id"], p["char_start"], p["char_end"], p["section"]) for p in entry["passages"]] == want


@pytest.mark.parametrize("high_risk", [True, False])
def test_seeded_high_risk_is_blind(qenv, high_risk):  # noqa: F811  # AC-22
    _, _, settings = qenv
    _, _, record, entry = _seeded_record(settings, high_risk)
    f = record.fields[0]
    assert entry["extractor"]["model"] == f.provenance.extractor_model
    assert entry["extractor"]["prompt_version"] == f.provenance.extractor_prompt_version
    v = entry["verifier"]
    assert (v["model"], v["prompt_version"]) == (f.provenance.verifier_model, f.provenance.verifier_prompt_version)
    assert v["blind"] is high_risk
    if high_risk:
        assert v["answer"] == entry["extractor"]["answer"] and v["verdict"]["agrees"] is True
    else:
        assert v["answer"]["agrees"] is True and v["verdict"] is None


def test_seeded_items_unchanged(qenv, monkeypatch):  # noqa: F811  # AC-62 stand-in
    rs, _, settings = qenv
    with_trace = seed_known_answers(rs, settings, count=4, seed=5)
    monkeypatch.setattr(trace, "write_trace", lambda *a, **k: None)
    without = seed_known_answers(rs, settings, count=4, seed=5)

    def bodies(run_id):
        # sorted: the batch commits each company in a thread, so queue order is a race, not part of the item
        text = [re.sub(r"[a-z]+_[0-9a-f]{12}|[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", "ID", json.dumps(r, sort_keys=True))
                for r in rs.read_review_queue(run_id)]
        return sorted(re.sub(r"\d{4}-\d\d-\d\dT[\d:.+Z-]+", "TS", t) for t in text)

    assert bodies(with_trace) == bodies(without)
    assert not (rs.run_dir(without) / "traces").exists()


def test_seeding_survives_a_trace_error(qenv, monkeypatch):  # noqa: F811
    rs, _, settings = qenv

    def boom(*a, **k):
        raise RuntimeError("no embedding model")

    monkeypatch.setattr("arp.review.quality.field_evidence", boom)
    run_id = seed_known_answers(rs, settings, count=3, seed=3)
    assert len(rs.read_review_queue(run_id)) >= 3
    assert not (rs.run_dir(run_id) / "traces").exists()
