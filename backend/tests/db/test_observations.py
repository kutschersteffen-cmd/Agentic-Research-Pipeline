from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime

from sqlalchemy import select

from arp.db import models as m
from arp.db.companies import ensure_universe_company
from arp.db.documents import DocumentRegistry
from arp.db.observations import CitationIn, ObservationIn, record
from arp.db.session import transaction
from arp.db.to_observations import to_observations
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import record_cosign, record_review_decision
from arp.schemas.common import CompanyRef, RunManifest
from tests.conftest import PRINCIPAL

FY24, FY23 = date(2024, 12, 31), date(2023, 12, 31)


def _company(pg, uid="acme"):
    with transaction(pg) as s:
        return ensure_universe_company(s, uid)


def _obs(cid, value, period=FY24, *, field_id="revenue", route=m.Route.AUTO_ACCEPT, **kw):
    return ObservationIn(
        company_id=cid, field_id=field_id, field_version=1, source_kind=m.SourceKind.EXTRACTION,
        period_end=period, value=value, value_state=m.ValueState.FOUND, route=route, **kw,
    )


def _record(pg, *obs):
    with transaction(pg) as s:
        return record(s, list(obs))


def _current(pg, cid, field_id="revenue"):
    with transaction(pg) as s:
        rows = s.scalars(
            select(m.CompanyFact).where(m.CompanyFact.company_id == cid, m.CompanyFact.field_id == field_id,
                                        m.CompanyFact.valid_to.is_(None)).order_by(m.CompanyFact.period_end)
        ).all()
        return [(f.period_end, f.value, f.status) for f in rows]


def _as_of(pg, cid, t):
    with transaction(pg) as s:
        return s.scalar(select(m.CompanyFact.value).where(
            m.CompanyFact.company_id == cid, m.CompanyFact.valid_from <= t,
            (m.CompanyFact.valid_to.is_(None)) | (m.CompanyFact.valid_to > t),
        ))


def test_new_period_adds_fact_and_keeps_old_period(pg):
    cid = _company(pg)
    _record(pg, _obs(cid, 90, FY23))
    _record(pg, _obs(cid, 100, FY24))
    assert _current(pg, cid) == [(FY23, 90, m.FactStatus.AUTO_ACCEPTED), (FY24, 100, m.FactStatus.AUTO_ACCEPTED)]


def test_restated_value_supersedes_and_history_is_queryable(pg):
    cid = _company(pg)
    _record(pg, _obs(cid, 100))
    time.sleep(0.01)
    between = datetime.now(UTC)
    time.sleep(0.01)
    _record(pg, _obs(cid, 1000.0))
    _record(pg, _obs(cid, 1000))  # same value again: no new version
    assert _current(pg, cid) == [(FY24, 1000.0, m.FactStatus.AUTO_ACCEPTED)]
    assert _as_of(pg, cid, between) == 100
    assert _as_of(pg, cid, datetime.now(UTC)) == 1000.0
    with transaction(pg) as s:
        old, new = s.scalars(select(m.CompanyFact).order_by(m.CompanyFact.id)).all()
        assert old.superseded_by == new.id and old.valid_to is not None
        assert s.scalar(select(m.func.count()).select_from(m.FieldObservation)) == 3


def test_pending_and_missing_values_keep_the_current_fact(pg):
    cid = _company(pg)
    _record(pg, _obs(cid, 100))
    _record(pg, _obs(cid, 120, route=m.Route.REVIEW))
    _record(pg, ObservationIn(company_id=cid, field_id="revenue", field_version=1, source_kind=m.SourceKind.EXTRACTION,
                              period_end=FY24, value=None, value_state=m.ValueState.NOT_FOUND))
    assert _current(pg, cid) == [(FY24, 100, m.FactStatus.AUTO_ACCEPTED)]


def test_two_concurrent_writers_leave_one_current_fact(pg):
    cid = _company(pg)
    failures = []
    for round_ in range(5):
        barrier = threading.Barrier(2)

        def write(v, barrier=barrier, field_id=f"f{round_}"):
            try:
                with transaction(pg) as s:
                    barrier.wait()
                    record(s, [_obs(cid, v, field_id=field_id)])
            except Exception as exc:  # noqa: BLE001
                failures.append(exc)

        threads = [threading.Thread(target=write, args=(v,)) for v in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        current = _current(pg, cid, f"f{round_}")
        assert failures == []
        assert len(current) == 1 and current[0][1] in (1, 2)


def test_trial_run_writes_no_facts(pg):
    cid = _company(pg)
    ids = _record(pg, _obs(cid, 100, trial=True))
    assert len(ids) == 1
    assert _current(pg, cid) == []


def test_citation_links_to_document_and_chunk(pg):
    cid = _company(pg)
    DocumentRegistry(pg).register_document(doc_id="doc_a", company_id="acme", doc_type="10-K", content_key="ck1",
                                           title="AR", local_path=None, source_url=None)
    (oid,) = _record(pg, _obs(cid, 100, citations=[
        CitationIn(doc_id="doc_a", content_key="ck1", page=4, quote="revenue 100", passage_id="p7", grounded=True),
        CitationIn(doc_id="doc_unknown", role=m.CitationRole.CORROBORATING),  # not registered: dropped
    ]))
    with transaction(pg) as s:
        (c,) = s.scalars(select(m.ValueCitation)).all()
        assert (c.observation_id, c.doc_id, c.content_key, c.page, c.passage_id, c.role) == (
            oid, "doc_a", "ck1", 4, "p7", m.CitationRole.PRIMARY)
        fact = s.scalar(select(m.CompanyFact))
        assert fact.observation_id == oid


def _extraction_row(value, *, period="2024-12-31", route="review"):
    return {"company_id": "acme", "name": "Acme", "schema_id": "s", "run_id": "r1", "issuer_key": "LEI:X",
            "_key": "acme", "fields": [{"field_id": "revenue", "field_name": "Revenue", "value": value,
                                        "confidence": 0.5, "period_end": period, "route": route}]}


def _write_extraction(run_store, pg, value, *, route="review", run_id="r1"):
    cid = _company(pg)
    if run_store.load_manifest(run_id) is None:
        run_store.save_manifest(RunManifest(run_id=run_id, run_type="extraction"))
    row = _extraction_row(value, route=route)
    key = "LEI:X:revenue:2024-12-31"
    items = [(key, {"item_key": key, "company_id": "acme", "field_id": "revenue", "period_end": "2024-12-31"})]
    run_store.record_company_result(
        run_id, row, observations=to_observations("extraction", cid, run_id, row, trial=False),
        review_items=items if route == "review" else [], company=CompanyRef(company_id="acme", name="Acme", entity_id=cid),
    )
    return cid, key


def test_review_approve_turns_pending_into_approved(run_store, pg):
    cid, key = _write_extraction(run_store, pg, 100.0)
    assert _current(pg, cid) == [(FY24, 100.0, m.FactStatus.PENDING_REVIEW)]
    (item,) = run_store.read_review_queue("r1")
    record_review_decision(run_store, "r1", key, "approve", "bob", None)
    assert _current(pg, cid) == [(FY24, 100.0, m.FactStatus.APPROVED)]
    with transaction(pg) as s:
        fact = s.scalar(select(m.CompanyFact).where(m.CompanyFact.valid_to.is_(None)))
        assert fact.decision_id is not None
        assert s.scalar(select(m.ReviewItem.observation_id)) == fact.observation_id


def test_reject_retires_pending_fact_and_edit_waits_for_cosign(run_store, pg):
    cid, key = _write_extraction(run_store, pg, 100.0)
    record_review_decision(run_store, "r1", key, "reject", "bob", None)
    assert _current(pg, cid) == []  # the rejected first value is no longer current; nothing replaces it
    record_review_decision(run_store, "r1", key, "edit", "bob", {"value": 110.0})
    assert _current(pg, cid) == []  # extraction edits need a cosign
    record_cosign(run_store, "r1", key, PRINCIPAL)
    assert _current(pg, cid) == [(FY24, 110.0, m.FactStatus.EDITED)]


def test_trial_run_review_writes_no_facts(run_store, pg):
    run_store.save_manifest(RunManifest(run_id="t1", run_type="extraction", params={"trial": True}))
    cid = _company(pg)
    row = _extraction_row(100.0)
    run_store.record_company_result(
        "t1", row, observations=to_observations("extraction", cid, "t1", row, trial=True),
        review_items=[("k", {"item_key": "k", "field_id": "revenue", "period_end": "2024-12-31"})],
        company=CompanyRef(company_id="acme", name="Acme", entity_id=cid),
    )
    record_review_decision(run_store, "t1", "k", "approve", "bob", None)
    assert _current(pg, cid) == []


def test_run_type_facts_do_not_overwrite_each_other(run_store, pg):
    cid, _ = _write_extraction(run_store, pg, 100.0, route="auto_accept")
    run_store.save_manifest(RunManifest(run_id="f1", run_type="financials"))
    fin = {"company_id": "acme", "name": "Acme", "run_id": "f1", "currency": "USD", "fiscal_period": "2024-12-31",
           "capex": {"total": {"value": 7.0}}, "rnd": {"total": {"value": 3.0}}, "_key": "acme"}
    run_store.record_company_result(
        "f1", fin, observations=to_observations("financials", cid, "f1", fin, trial=False), review_items=[],
        company=CompanyRef(company_id="acme", name="Acme", entity_id=cid),
    )
    with transaction(pg) as s:
        current = {f.field_id: f.value for f in s.scalars(select(m.CompanyFact).where(m.CompanyFact.valid_to.is_(None)))}
    assert current == {"revenue": 100.0, "capex_total": 7.0, "rnd_total": 3.0}
    assert [r["_key"] for r in run_store.read_results("f1")] == ["acme"]


def test_invalid_period_goes_to_run_errors(run_store, pg):
    cid = _company(pg)
    run_store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    row = _extraction_row(1.0, period="31/12/2024")
    errors = []
    obs = to_observations("extraction", cid, "r1", row, trial=False, errors=errors)
    run_store.record_company_result("r1", row, observations=obs, review_items=[], company=None, errors=errors)
    assert run_store.read_errors("r1") == [{"kind": "invalid_value", "field_id": "revenue", "raw": "31/12/2024"}]


async def test_company_batch_writes_observations_and_facts(run_store, pg):
    from arp.orchestration.batch_runner import run_company_batch

    universe = [CompanyRef(company_id="acme", name="Acme")]
    run_id = JobManager(run_store).create_run("extraction", {}, 1, companies=universe).run_id

    async def worker(company):
        return _extraction_row(5.0, route="auto_accept")

    await run_company_batch(run_id, universe, run_store=run_store, worker=worker, result_to_json=dict, concurrency=1)
    (company,) = run_store.load_companies(run_id)
    assert _current(pg, company.entity_id) == [(FY24, 5.0, m.FactStatus.AUTO_ACCEPTED)]
    assert run_store.load_manifest(run_id).completed_count == 1


def test_reject_keeps_an_accepted_fact(run_store, pg):
    cid, _ = _write_extraction(run_store, pg, 100.0, route="auto_accept")
    _, key = _write_extraction(run_store, pg, 120.0, run_id="r2")
    record_review_decision(run_store, "r2", key, "reject", "bob", None)
    assert _current(pg, cid) == [(FY24, 100.0, m.FactStatus.AUTO_ACCEPTED)]


def test_requeue_keeps_observation_link(run_store, pg):
    from arp.orchestration.review_queue import queue_for_review

    _, key = _write_extraction(run_store, pg, 100.0)
    with transaction(pg) as s:
        linked = s.scalar(select(m.ReviewItem.observation_id))
    assert linked is not None
    queue_for_review(run_store, "r1", key, {"field_id": "revenue", "period_end": "2024-12-31", "review_reasons": ["span_moved"]})
    with transaction(pg) as s:
        assert s.scalar(select(m.ReviewItem.observation_id)) == linked


def _financials(run_store, pg, *, needs_review):
    cid = _company(pg)
    run_store.save_manifest(RunManifest(run_id="f1", run_type="financials"))
    fin = {"company_id": "acme", "name": "Acme", "run_id": "f1", "currency": "USD", "fiscal_period": "2024-12-31",
           "capex": {"total": {"value": 7.0}}, "rnd": {"total": {"value": 3.0}}, "needs_review": needs_review,
           "_key": "acme"}
    run_store.record_company_result(
        "f1", fin, observations=to_observations("financials", cid, "f1", fin, trial=False),
        review_items=[("acme", fin)] if needs_review else [],
        company=CompanyRef(company_id="acme", name="Acme", entity_id=cid),
    )
    return cid


def _facts(pg):
    with transaction(pg) as s:
        return {f.field_id: (f.value, f.status) for f in s.scalars(select(m.CompanyFact).where(m.CompanyFact.valid_to.is_(None)))}


def test_whole_record_review_resolves_its_facts(run_store, pg):
    _financials(run_store, pg, needs_review=True)
    assert {v[1] for v in _facts(pg).values()} == {m.FactStatus.PENDING_REVIEW}
    record_review_decision(run_store, "f1", "acme", "approve", "bob", None)
    assert _facts(pg) == {"capex_total": (7.0, m.FactStatus.APPROVED), "rnd_total": (3.0, m.FactStatus.APPROVED)}


def test_whole_record_edit_sets_only_named_fields(run_store, pg):
    _financials(run_store, pg, needs_review=True)
    record_review_decision(run_store, "f1", "acme", "edit", "bob", {"capex_total": 8.0})
    assert _facts(pg) == {"capex_total": (8.0, m.FactStatus.EDITED), "rnd_total": (3.0, m.FactStatus.PENDING_REVIEW)}


def _ballot_and_theme(run_store, pg):
    cid = _company(pg)
    company = CompanyRef(company_id="acme", name="Acme", entity_id=cid)
    run_store.save_manifest(RunManifest(run_id="v1", run_type="proxy_voting"))
    vote = {"proposal": {"company_id": "acme", "meeting_id": "M1", "proposal_number": "3", "type": "other",
                         "sponsor": "Management", "resolution_text": "t"},
            "policy_recommendation": {"vote": "for", "rationale": "r"}}
    ballot = {"company_id": "acme", "name": "Acme", "meeting_id": "M1", "votes": [vote], "_key": "acme"}
    run_store.record_company_result("v1", ballot, observations=to_observations("proxy_voting", cid, "v1", ballot, trial=False),
                                    review_items=[("acme:3", vote)], company=company)
    run_store.save_manifest(RunManifest(run_id="t1", run_type="theme"))
    match = {"company_id": "acme", "name": "Acme", "activity_id": "A1", "activity_name": "a", "verdict": "uncertain",
             "exposure_estimate": "low", "confidence": 0.4, "adjudicator_rationale": "x", "flagged_for_review": True}
    themed = {"company_matches": [match], "_key": "acme"}
    run_store.record_company_result("t1", themed, observations=to_observations("theme", cid, "t1", themed, trial=False),
                                    review_items=[("acme:A1", match)], company=company)


def test_vote_and_theme_decisions_reach_facts(run_store, pg):
    _ballot_and_theme(run_store, pg)
    assert _facts(pg) == {
        "vote:M1:3": ("for", m.FactStatus.PENDING_REVIEW),
        "theme:A1": ({"verdict": "uncertain", "exposure_estimate": "low"}, m.FactStatus.PENDING_REVIEW),
    }
    record_review_decision(run_store, "v1", "acme:3", "edit", "bob", {"vote": "against", "co_signed_by": "ann"})
    record_review_decision(run_store, "t1", "acme:A1", "edit", "bob", {"value": "include"})
    assert _facts(pg) == {
        "vote:M1:3": ("against", m.FactStatus.EDITED),
        "theme:A1": ({"verdict": "include", "exposure_estimate": "low"}, m.FactStatus.EDITED),
    }


def test_theme_approve_reaches_fact(run_store, pg):
    _ballot_and_theme(run_store, pg)
    record_review_decision(run_store, "t1", "acme:A1", "approve", "bob", None)
    assert _facts(pg)["theme:A1"][1] == m.FactStatus.APPROVED


def test_held_documents_make_held_facts(run_store, pg):
    cid = _company(pg)
    DocumentRegistry(pg).register_document(doc_id="doc_x", company_id="acme", doc_type="10-K", content_key="ck",
                                           title="Other entity", local_path=None, source_url=None)
    run_store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    row = {**_extraction_row(5.0, route="hold"), "held_documents": [{"doc_id": "doc_x", "reason": "entity_mismatch"}]}
    run_store.record_company_result("r1", row, observations=to_observations("extraction", cid, "r1", row, trial=False),
                                    review_items=[], company=CompanyRef(company_id="acme", name="Acme", entity_id=cid))
    assert _current(pg, cid) == [(FY24, 5.0, m.FactStatus.HELD)]
    with transaction(pg) as s:
        held = s.scalars(select(m.RunHeldDocument)).all()
        assert [(h.run_id, h.company_id, h.doc_id, h.reason) for h in held] == [("r1", cid, "doc_x", "entity_mismatch")]


def test_held_value_does_not_displace_accepted_fact(run_store, pg):
    cid, _ = _write_extraction(run_store, pg, 100.0, route="auto_accept")
    _write_extraction(run_store, pg, 5.0, route="hold", run_id="r2")
    assert _current(pg, cid) == [(FY24, 100.0, m.FactStatus.AUTO_ACCEPTED)]


def test_value_not_fitting_data_type_goes_to_run_errors(run_store, pg):
    from arp.db.fields import ensure_extracted_field

    with transaction(pg) as s:
        ensure_extracted_field(s, "revenue", m.FieldDefinition(version=1, name="Revenue", data_type="number", definition={}))
        ensure_extracted_field(s, "listed", m.FieldDefinition(version=1, name="Listed", data_type="boolean", definition={}))
    cid = _company(pg)
    run_store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    row = _extraction_row("lots")
    row["fields"] += [
        {**row["fields"][0], "value": "1,234", "period_end": "2023-12-31"},
        {"field_id": "listed", "field_name": "Listed", "value": "yes", "confidence": 0.9, "route": "auto_accept"},
    ]
    run_store.record_company_result("r1", row, observations=to_observations("extraction", cid, "r1", row, trial=False),
                                    review_items=[], company=CompanyRef(company_id="acme", name="Acme", entity_id=cid))
    assert run_store.read_errors("r1") == [
        {"kind": "invalid_value", "field_id": "revenue", "raw": "lots"},
        {"kind": "invalid_value", "field_id": "listed", "raw": "yes"},
    ]
    with transaction(pg) as s:
        assert s.scalars(select(m.FieldObservation.value)).all() == ["1,234"]


def test_unregistered_citation_goes_to_run_errors(run_store, pg):
    cid = _company(pg)
    run_store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    row = _extraction_row(5.0, route="auto_accept")
    row["fields"][0]["citations"] = [{"doc_id": "doc_gone", "doc_type": "10-K", "quote": "q"}]
    run_store.record_company_result("r1", row, observations=to_observations("extraction", cid, "r1", row, trial=False),
                                    review_items=[], company=CompanyRef(company_id="acme", name="Acme", entity_id=cid))
    assert run_store.read_errors("r1") == [{"kind": "unregistered_citation", "doc_id": "doc_gone"}]
