"""Argus step 1 rows: per company, its identifiers, what the newest Argus run extracted, and its documents."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from arp.argus.companies import CONFLICT, NO_IDENTIFIER
from arp.argus.flows import ArgusFlow
from arp.argus.rows import PriorRun, flow_rows
from arp.db.models import Company, CompanyIdentifier
from arp.db.session import engine
from arp.schemas.common import CompanyRef, RunManifest
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.store import XbrlStore
from tests.conftest import PRINCIPAL

IK = "lei:K1"


class _Docs:
    def __init__(self, stored):
        self.stored = stored

    def readiness_by_company(self, ids):
        return {i: self.stored[i] for i in ids if i in self.stored}


def _field(field_id, route):
    return {"field_id": field_id, "field_name": field_id, "value": 1, "confidence": 0.9, "value_state": "found",
            "period_end": "2025-12-31", "route": route}


@pytest.fixture
def store(pg, tmp_path):
    return RunStore(pg, tmp_path)


@pytest.fixture
def rows_for(store, pg, tmp_path):
    def rows(*companies, docs=None):
        flow = ArgusFlow(flow_id="f", created_at="t", updated_at="t", started_by="u", started_by_name="U", companies=list(companies))
        with Session(engine(pg)) as session:
            return flow_rows(flow, session=session, run_store=store, content_store=_Docs(docs or {}),
                             xbrl_store=XbrlStore(tmp_path / "xbrl"), idmap=IdentifierMapStore(tmp_path / "idmap.jsonl"),
                             principal=PRINCIPAL, documents_dir=tmp_path / "docs")
    return rows


def _seed_run(store, run_id, created, company_id="c1"):
    store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", created_at=created, company_count=1,
                                    params={"schema_name": "S", "schema_version": "s:v2"}))
    fields = [_field("a", "auto_accept"), _field("b", "auto_accept"), _field("c", "review"), _field("d", "review")]
    store.append_result(run_id, {"company_id": company_id, "name": "C1", "issuer_key": IK, "fields": fields})
    for f in fields[2:]:
        key = f"{IK}:{f['field_id']}:2025-12-31"
        store.append_review_item(run_id, {"item_key": key, "issuer_key": IK, "company_id": company_id, "name": "C1",
                                          "run_id": run_id, "field_id": f["field_id"], "period_end": "2025-12-31", "field": f})
    store.append_decision_row(run_id, {"item_key": f"{IK}:c:2025-12-31", "decision": "approve", "decided_at": "t", "user_id": "x"})


def test_prior_run_and_documents(rows_for, store):
    _seed_run(store, "old", "2026-09-01T00:00:00+00:00")
    _seed_run(store, "new", "2026-10-01T09:00:00+00:00")
    [row] = rows_for(CompanyRef(company_id="c1", name="C1"),
                     docs={"c1": {"registered": 2, "parsed": 2, "doc_types": ["sustainability_report", "10-K"]}})
    assert row.extracted_before == PriorRun(label="S v2", date="2026-10-01", approved=3, waiting=1)
    assert (row.documents, row.document_types) == (2, ["annual", "sustainability"])


def test_a_corrected_value_counts_as_approved(rows_for, store):
    _seed_run(store, "r", "2026-10-01T09:00:00+00:00")
    store.append_decision_row("r", {"item_key": f"{IK}:d:2025-12-31", "decision": "correct", "decided_at": "t2", "user_id": "x"})
    [row] = rows_for(CompanyRef(company_id="c1", name="C1"))
    assert (row.extracted_before.approved, row.extracted_before.waiting) == (4, 0)


def test_identifiers_show_the_values_given(rows_for, pg):
    with Session(engine(pg)) as s, s.begin():
        c = Company(name="Apple")
        s.add(c)
        s.flush()
        s.add(CompanyIdentifier(company_id=c.id, scheme="CIK", value="320193"))
        cid = c.id
    [row] = rows_for(CompanyRef(company_id="x", name="Apple", entity_id=cid, cik="0000320193"))
    assert row.identifiers == {"CIK": ["0000320193"]}


def test_never_and_none(rows_for):
    [row] = rows_for(CompanyRef(company_id="fresh", name="Fresh"))
    assert (row.extracted_before, row.documents, row.document_types) == (None, 0, [])


def test_identifiers_sector_country_and_problem(rows_for, pg):
    with Session(engine(pg)) as s, s.begin():
        apple = Company(name="Apple", sector="Information Technology", country="US")
        s.add(apple)
        s.flush()
        for scheme, value in (("LEI", "HWUPKR0MPOU8FGXBT394"), ("CIK", "320193"), ("USER", "AAPL-X"), ("UNIVERSE", "AAPL-X")):
            s.add(CompanyIdentifier(company_id=apple.id, scheme=scheme, value=value))
        apple_id = apple.id
    a, acme, mixed = rows_for(
        CompanyRef(company_id="AAPL-X", name="Apple", entity_id=apple_id, ticker="AAPL"),
        CompanyRef(company_id="Acme", name="Acme"),
        CompanyRef(company_id="Mixed", name="Mixed", lei="529900D6BF99LW9R2E68"),
    )
    assert (a.central_id, a.sector, a.country, a.problem) == (apple_id, "Information Technology", "US", None)
    assert a.identifiers == {"TICKER": ["AAPL"], "LEI": ["HWUPKR0MPOU8FGXBT394"], "CIK": ["320193"], "USER": ["AAPL-X"]}
    assert (acme.central_id, acme.problem, acme.identifiers) == (None, NO_IDENTIFIER, {})
    assert (mixed.problem, mixed.identifiers) == (CONFLICT, {"LEI": ["529900D6BF99LW9R2E68"]})


def test_unknown_central_id_does_not_raise(rows_for):
    [row] = rows_for(CompanyRef(company_id="x", name="Gone", entity_id=uuid4(), sector="S"))
    assert (row.sector, row.identifiers) == ("S", {})
