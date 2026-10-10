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


def test_reject_leaves_fact_and_edit_waits_for_cosign(run_store, pg):
    cid, key = _write_extraction(run_store, pg, 100.0)
    record_review_decision(run_store, "r1", key, "reject", "bob", None)
    assert _current(pg, cid) == [(FY24, 100.0, m.FactStatus.PENDING_REVIEW)]
    record_review_decision(run_store, "r1", key, "edit", "bob", {"value": 110.0})
    assert _current(pg, cid) == [(FY24, 100.0, m.FactStatus.PENDING_REVIEW)]  # extraction edits need a cosign
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
