"""AC-13, AC-16, AC-22..AC-29: publishing authoritative values and reading them as of a date."""

from __future__ import annotations

import hashlib
import os
import threading

import pytest

from arp.schemas.decision import AuthoritativeOutput, MechanismConfig
from tests.authoritative_fixtures import add_fact, build, seed
from tests.test_authoritative_evaluate import F_PERIOD, F_VALUE, _graph

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")


@pytest.fixture(autouse=True)
def _db():
    from arp.storage.postgres import ensure_schema
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    yield
    reset_postgres_tables(DSN)


@pytest.fixture
def fx():
    return seed(DSN)


@pytest.fixture
def store():
    from arp.authoritative.store import AuthoritativeStore

    return AuthoritativeStore(DSN)


def f_config(version=1, statuses=("approved",)) -> MechanismConfig:
    cond = "scope1_tco2e__status == 'approved'" if statuses == ("approved",) else \
        f"scope1_tco2e__status in [{', '.join(repr(s) for s in statuses)}]"
    return MechanismConfig(
        framework_id="fw_f", version=version, purpose="authoritative", ratified=True,
        rule_graph=_graph(auth_scope1=F_VALUE.replace("scope1_tco2e__status == 'approved'", cond),
                          auth_scope1__period_end=F_PERIOD.replace("scope1_tco2e__status == 'approved'", cond)),
        outputs=[AuthoritativeOutput(column="auth_scope1", name="Scope 1", unit="tCO2e")],
    )


def current(store, company_id):
    return store.values(framework_id="fw_f", output="auth_scope1", company_id=company_id, as_of=None)


def all_rows(store, company_id):
    return store.history(framework_id="fw_f", output="auth_scope1", company_id=company_id)


def publish_d1(store, fx, as_of="2026-10-15", config=None, company_ids=None):
    return store.publish(build(DSN, fx, as_of=as_of, company_ids=company_ids), config or f_config(), published_by="Bob")


def test_ac_13_publish_writes_current_rows(store, fx):
    publish_d1(store, fx)
    [a], [b] = current(store, fx["A"]), current(store, fx["B"])
    assert (a["value"], a["status"], a["period_end"]) == (90, "value", "2025-12-31")
    assert (b["value"], b["status"], b["period_end"]) == (50, "value", "2026-09-30")
    assert len(store.values(framework_id="fw_f", output="auth_scope1", company_id=None, as_of=None)) == 2


def test_ac_14_get_returns_derivation(store, fx):
    publish_d1(store, fx)
    [a] = current(store, fx["A"])
    got = store.get(a["id"])
    assert got["derivation"]["inputs"]["scope1_tco2e"]["observation_id"] == fx["a_ext"]
    assert got["derivation"]["snapshot_id"] == current(store, fx["B"])[0]["snapshot_id"]


def test_ac_16_published_fact_is_linked(store, fx):
    from arp.db.session import transaction
    from arp.storage.postgres_models import PublishedFactModel, ReleaseModel

    with transaction(DSN) as s:
        s.add(ReleaseModel(release_id="rel_1", doc_id="d1", content_key="k", storage_uri="u", issuer_key=fx["A"],
                           issuer_scheme="internal", run_id="r1", published_at="2026-04-01T00:00:00Z", published_by="x",
                           published_by_role="approver", company_id=fx["A"]))
        s.flush()
        s.add(PublishedFactModel(fact_id="pf_1", issuer_key=fx["A"], issuer_scheme="internal", field_id="scope1_tco2e",
                                 period_end="2025-12-31", basis="", value=90, state="approved", citation={},
                                 source_run_id="r1", observed_at="2026-03-01", item_key="k", version=1,
                                 valid_from="2026-04-01T00:00:00Z", release_id="rel_1", company_id=fx["A"]))
    publish_d1(store, fx)
    [a] = current(store, fx["A"])
    assert store.get(a["id"])["derivation"]["inputs"]["scope1_tco2e"]["published_fact_id"] == "pf_1"


def test_ac_22_unchanged_publish_reconfirms(store, fx):
    first = publish_d1(store, fx)
    before = {r["company_id"]: r for c in (fx["A"], fx["B"]) for r in current(store, c)}
    second = publish_d1(store, fx, as_of="2026-10-20")
    published = {p["snapshot_id"]: p for p in store.publishes("fw_f")}
    assert len(published) == 2
    for c in (fx["A"], fx["B"]):
        [now] = current(store, c)
        assert now["id"] == before[c]["id"]
        assert now["snapshot_id"] == first
        assert now["reconfirmed_at"] == published[second]["published_at"]


def test_ac_23_older_as_of_is_refused(store, fx):
    from arp.authoritative.store import StalePublish

    publish_d1(store, fx)
    publish_d1(store, fx, as_of="2026-10-20")
    rows_before = [all_rows(store, c) for c in (fx["A"], fx["B"])]
    with pytest.raises(StalePublish):
        publish_d1(store, fx, as_of="2026-10-17")
    assert [all_rows(store, c) for c in (fx["A"], fx["B"])] == rows_before
    assert len(store.publishes("fw_f")) == 2


def _edit_a_to_95(fx):
    from arp.db.session import transaction

    with transaction(DSN) as s:
        add_fact(s, fx["A"], "scope1_tco2e", 95, "2025-12-31", valid_from="2026-10-16", status="edited")


def test_ac_24_source_edit_without_publish_changes_nothing(store, fx):
    publish_d1(store, fx)
    _edit_a_to_95(fx)
    [a] = current(store, fx["A"])
    assert a["value"] == 90


def _publish_v2(store, fx):
    publish_d1(store, fx)
    _edit_a_to_95(fx)
    publish_d1(store, fx, as_of="2026-10-25", config=f_config(version=2, statuses=("approved", "edited")))


def test_ac_25_new_value_closes_old_version(store, fx):
    _publish_v2(store, fx)
    v1, v2 = all_rows(store, fx["A"])
    assert (v1["value"], v2["value"]) == (90, 95)
    assert v1["valid_to"] == v2["valid_from"]
    assert v1["superseded_by"] == v2["id"]
    assert v2["valid_to"] is None


def test_ac_25b_new_framework_version_writes_new_row(store, fx):
    _publish_v2(store, fx)
    old, new = all_rows(store, fx["B"])
    assert (new["value"], new["framework_version"]) == (50, 2)
    assert old["valid_to"] is not None


def test_ac_26_27_as_of_reads(store, fx):
    _publish_v2(store, fx)
    first, second = sorted(store.publishes("fw_f"), key=lambda p: p["published_at"])
    v1, v2 = all_rows(store, fx["A"])
    between = v2["valid_from"]  # strictly after v1 opened: read just before v2 opened
    from datetime import datetime, timedelta

    just_before = (datetime.fromisoformat(between) - timedelta(microseconds=1)).isoformat()
    [mid] = store.values(framework_id="fw_f", output="auth_scope1", company_id=fx["A"], as_of=just_before)
    assert mid["value"] == 90
    early = (datetime.fromisoformat(first["published_at"]) - timedelta(seconds=1)).isoformat()
    assert store.values(framework_id="fw_f", output="auth_scope1", company_id=fx["A"], as_of=early) == []


def test_ac_28_company_dropped_from_dataset(store, fx):
    publish_d1(store, fx)
    publish_d1(store, fx, as_of="2026-10-26", company_ids=[fx["A"]])
    [b] = current(store, fx["B"])
    assert (b["status"], b["reason"], b["value"]) == ("no_value", "not_in_dataset", None)
    old = all_rows(store, fx["B"])[0]
    assert old["value"] == 50 and old["valid_to"] is not None


def _source_digest():
    from sqlalchemy import text

    from arp.storage.postgres import get_engine

    with get_engine(DSN).connect() as conn:
        return {t: hashlib.sha256(repr(conn.execute(text(f"SELECT * FROM {t} ORDER BY 1")).all()).encode()).hexdigest()
                for t in ("company_facts", "field_observations", "published_facts")}


def test_ac_29_sources_untouched(store, fx):
    before = _source_digest()
    publish_d1(store, fx)
    assert _source_digest() == before


def test_concurrent_publishes_leave_one_current_row_each(store, fx):
    dataset = build(DSN, fx)
    errors = []

    def go():
        try:
            store.publish(dataset, f_config(), published_by="Bob")
        except Exception as exc:  # noqa: BLE001 -- surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(store.values(framework_id="fw_f", output="auth_scope1", company_id=None, as_of=None)) == 2
