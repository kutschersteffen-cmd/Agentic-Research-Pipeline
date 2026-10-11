from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from arp.db import models as m
from arp.db.companies import lookup, resolve
from arp.db.providers import ProviderRow, ensure_source, ingest_rows, record_load, reingest
from arp.db.session import transaction
from arp.publish.facts import FactCandidate, LicenceRefused, PublishStore, Release, fact_key, plan_version, ts_now
from arp.schemas.common import Citation

FY24 = date(2024, 12, 31)
MSCI = "MSCI_ISSUER_ID"
LEI = "529900T8BM49AURSDO55"


def _source(s, slug="msci", licence=m.Licence.INTERNAL_ONLY):
    return ensure_source(s, slug, name=slug.upper(), kind="api", licence=licence, id_scheme=MSCI)


def _company(s, lei=LEI, uid="acme"):
    return resolve(s, [(m.IdScheme.LEI, lei), (m.IdScheme.UNIVERSE, uid)], name=uid, allow_create=True).company_id


def _row(ids, code="CARBON_EMISSIONS_SCOPE_1", value=12.5):
    return ProviderRow(issuer_ids=ids, metric_code=code, metric_name=code.title(), unit="tCO2e",
                       data_type="number", period_end=FY24, value=value)


def _n(s, model):
    return s.scalar(select(func.count()).select_from(model))


def test_identical_payload_is_unchanged(pg):
    with transaction(pg) as s:
        cid, sid = _company(s), _source(s)
        first = record_load(s, sid, b"payload", request={"q": 1}, as_of=FY24)
        ingest_rows(s, first.load_id, [_row([(MSCI, "M1"), (m.IdScheme.LEI, LEI)])])
    with transaction(pg) as s:
        again = record_load(s, sid, b"payload", request={"q": 1}, as_of=FY24)
        assert (again.load_id, again.unchanged, first.unchanged) == (first.load_id, True, False)
        assert (_n(s, m.SourceLoad), _n(s, m.FieldObservation)) == (1, 1)
        load = s.get(m.SourceLoad, first.load_id)
        assert load.payload_uri and load.payload_uri.endswith(f"provider-loads/msci/{load.payload_sha}")
    assert cid


def test_unknown_issuer_is_reported_not_created(pg):
    with transaction(pg) as s:
        sid = _source(s)
        load = record_load(s, sid, b"p", request={}, as_of=FY24)
        report = ingest_rows(s, load.load_id, [_row([(MSCI, "M9"), (m.IdScheme.LEI, "NOPE")])])
        assert report.observations == 0
        assert report.unmatched_issuers == [[(MSCI, "M9"), ("LEI", "NOPE")]]
        assert _n(s, m.Company) == 0


def test_first_match_by_lei_stores_provider_alias(pg):
    with transaction(pg) as s:
        cid, sid = _company(s), _source(s)
        load = record_load(s, sid, b"one", request={}, as_of=FY24)
        assert ingest_rows(s, load.load_id, [_row([(MSCI, "M1"), (m.IdScheme.LEI, LEI), (m.IdScheme.ISIN, "US0000000001")])]).observations == 1
        assert lookup(s, MSCI, "M1") == cid
        assert lookup(s, m.IdScheme.ISIN, "US0000000001") is None  # only the provider's own id becomes an alias
        load2 = record_load(s, sid, b"two", request={}, as_of=FY24)
        report = ingest_rows(s, load2.load_id, [_row([(MSCI, "M1")], value=13)])
        assert (report.observations, report.unmatched_issuers) == (1, [])


def test_new_metric_registers_own_field(pg):
    with transaction(pg) as s:
        _company(s)
        sid = _source(s)
        load = record_load(s, sid, b"p", request={}, as_of=FY24)
        ingest_rows(s, load.load_id, [_row([(m.IdScheme.LEI, LEI)], code="Carbon Emissions Scope 1")])
        obs = s.scalar(select(m.FieldObservation))
        assert obs.field_id == "prov:msci:carbon_emissions_scope_1"
        assert (obs.source_kind, obs.source_id, obs.load_id) == (m.SourceKind.PROVIDER, sid, load.load_id)
        assert not s.scalar(select(func.count()).where(m.Field.field_id.like("fld_%")))


def test_colliding_codes_reported(pg):
    with transaction(pg) as s:
        _company(s)
        load = record_load(s, _source(s), b"p", request={}, as_of=FY24)
        ids = [(m.IdScheme.LEI, LEI)]
        report = ingest_rows(s, load.load_id, [_row(ids, code="CO2-Total"), _row(ids, code="co2 total"), _row(ids, code="water")])
        assert report.observations == 1
        assert sorted(report.collisions) == ["CO2-Total", "co2 total"]
        assert s.get(m.Field, "prov:msci:co2_total") is None


def test_failed_ingest_reingests_from_stored_payload(pg):
    fetched = []

    def fetch():
        fetched.append(1)
        return b"M1,7"

    def parse(payload: bytes):
        issuer, value = payload.decode().split(",")
        return [_row([(MSCI, issuer)], value=float(value))]

    def boom(payload: bytes):
        raise ValueError("bad format")

    with transaction(pg) as s:
        _company(s)
        s.add(m.CompanyIdentifier(company_id=lookup(s, m.IdScheme.LEI, LEI), scheme=MSCI, value="M1"))
        load = record_load(s, _source(s), fetch(), request={}, as_of=FY24)
        with pytest.raises(ValueError):
            reingest(s, load.load_id, boom)
    with transaction(pg) as s:
        failed = s.get(m.SourceLoad, load.load_id)
        assert (failed.status, failed.error) == (m.LoadStatus.FAILED, "bad format")
        assert reingest(s, load.load_id, parse).observations == 1
        assert s.get(m.SourceLoad, load.load_id).status == m.LoadStatus.INGESTED
    assert fetched == [1]


def test_internal_only_fact_refused_by_publish(pg):
    with transaction(pg) as s:
        cid = _company(s)
        load = record_load(s, _source(s), b"p", request={}, as_of=FY24)
        ingest_rows(s, load.load_id, [_row([(m.IdScheme.LEI, LEI)])])
    store = PublishStore(pg)

    def cand(field_id):
        return FactCandidate(
            issuer_key=str(cid), issuer_scheme="INTERNAL", field_id=field_id, period_end=FY24.isoformat(),
            value=12.5, state="auto_accepted", citation=None, source_run_id="r1", observed_at=ts_now(), item_key="k",
        )

    blocked, other = cand("prov:msci:carbon_emissions_scope_1"), cand("revenue")
    assert store.internal_only([blocked, other]) == {fact_key(blocked)}
    release = Release(doc_id="d", content_key="c", storage_uri="u", issuer_key=str(cid), issuer_scheme="INTERNAL",
                      run_id="r1", published_at=ts_now(), published_by="u", published_by_role="approver")
    plan = plan_version(None, blocked.model_copy(update={"citation": Citation(doc_id="d", doc_type="10-K", quote="q")}), release_id=release.release_id, now=ts_now())
    with pytest.raises(LicenceRefused):
        store.save_release(release, [plan], [])
    assert store.get_release(release.release_id) is None


def test_slug_is_immutable(pg):
    with transaction(pg) as s:
        sid = _source(s)
        again = ensure_source(s, "msci", name="Renamed", kind="file", licence=m.Licence.REDISTRIBUTABLE, id_scheme="OTHER")
        src = s.get(m.DataSource, sid)
        assert again == sid and (src.slug, src.name, src.licence) == ("msci", "MSCI", m.Licence.INTERNAL_ONLY)
