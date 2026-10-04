from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.holdings import load
from arp.holdings.intake import IntakeError, holder_status, ingest, isin_decisions, previous_month_end
from arp.holdings.validate import RowError, Validated, validate
from arp.orchestration.review_queue import append_decision
from arp.schemas.issuer import IdentifierMap
from arp.schemas.portfolio import HolderConfig
from arp.schemas.review import ReviewDecision
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from tests.conftest import PRINCIPAL

ISIN, ISIN2 = "US0378331005", "DE0007164600"
LEI = "5493001KJTIIGC8Y1R12"
ALICE = Principal(user_id="u_alice", name="Alice", role="analyst")
BOB = Principal(user_id="u_bob", name="Bob", role="analyst")


@pytest.fixture
def env(tmp_path):
    yield PortfolioStore(tmp_path / "pf"), RunStore(tmp_path / "runs"), IdentifierMapStore(tmp_path / "idmap.jsonl")
    app.dependency_overrides.pop(get_run_store, None)
    app.dependency_overrides.pop(current_user, None)


def rows(kind="index", as_of="2026-10-31", weights=(60, 40)):
    raw = [{"_row": 2, "isin": ISIN, "name": "Apple", "weight": weights[0], "market_value": 600, "currency": "EUR"},
           {"_row": 3, "isin": ISIN2, "name": "SAP", "weight": weights[1], "market_value": 400, "currency": "EUR"}]
    v = validate(raw, kind=kind, as_of=as_of, today=date(2027, 1, 31))
    assert not v.errors, v.errors
    return v


def run(env, v=None, *, kind="index", holder="IX1", as_of="2026-10-31", source="file", reason=None, principal=PRINCIPAL):
    store, rs, idmap = env
    return ingest(store, v or rows(kind, as_of), kind=kind, holder_id=holder, as_of=as_of, source=source,
                  source_ref="f.csv", principal=principal, override_reason=reason, run_store=rs, idmap=idmap)


def held(env, isin, kind="index", holder="IX1", as_of="2026-10-31"):
    return next(h for h in env[0].load_snapshot(holder, as_of, kind=kind) if h.isin == isin)


def client(who, rs):
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def decide(who, rs, run_id, body):
    c = client(who, rs)
    key = f"isin:{ISIN}"
    etag = c.get(f"/api/review/runs/{run_id}/items/{key}/context").json()["etag"]
    return c.post(f"/api/review/runs/{run_id}/items/{key}/decision", json={**body, "context_etag": etag})


def test_isin_resolves_to_lei_through_identifier_map(env):
    env[2].add(IdentifierMap(issuer_key=LEI, scheme="ISIN", value=ISIN))
    run(env)
    h = held(env, ISIN)
    assert (h.issuer_key, h.issuer_scheme) == (LEI, "LEI")


def test_unresolved_isin_appears_in_review_workbench(env):
    env[2].add(IdentifierMap(issuer_key=LEI, scheme="ISIN", value=ISIN2))
    result = run(env)
    assert result.unresolved == [ISIN] and result.review_run_id
    h = held(env, ISIN)
    assert h.issuer_scheme == "ARP_PROVISIONAL" and h.issuer_key.startswith("ARP:")
    r = client(PRINCIPAL, env[1]).get("/api/review/items")
    assert r.status_code == 200, r.text
    assert [(i["kind"], i["item_key"]) for i in r.json()["items"]] == [("security", f"isin:{ISIN}")]
    assert [x.security_id for x in env[0].list_resolutions_needing_review()] == [ISIN]


def test_resolved_isin_clears_needs_review(env):
    store, rs, _ = env
    result = run(env)
    append_decision(rs, result.review_run_id, ReviewDecision(
        item_key=f"isin:{ISIN}", decision="correct", reason_code="wrong_entity", reviewer="A", user_id="u_a",
        role="analyst", corrected_value={"value": LEI}, snapshot_id="s1", step="first",
    ))
    run(env, rows(weights=(50, 50)))
    assert ISIN not in [x.security_id for x in store.list_resolutions_needing_review()]
    assert ISIN2 in [x.security_id for x in store.list_resolutions_needing_review()]


def test_security_correction_needs_valid_lei(env):
    store, rs, _ = env
    result = run(env)
    body = {"decision": "correct", "reason_code": "wrong_entity", "corrected_value": {"value": "BAD"}, "comment": "GLEIF"}
    r = decide(ALICE, rs, result.review_run_id, body)
    assert r.status_code == 422 and "valid LEI" in r.text
    no_comment = {**body, "corrected_value": {"value": LEI.lower()}, "comment": ""}
    assert decide(ALICE, rs, result.review_run_id, no_comment).status_code == 422
    r = decide(ALICE, rs, result.review_run_id, {**body, "corrected_value": {"value": LEI}})
    assert (r.json()["state"], r.json()["second_reasons"]) == ("first_done", ["correction"])
    assert decide(ALICE, rs, result.review_run_id, {**body, "corrected_value": {"value": LEI}}).status_code == 409
    assert isin_decisions(rs) == {}
    r = decide(BOB, rs, result.review_run_id, {**body, "corrected_value": {"value": LEI}})
    assert r.json()["state"] == "second_done", r.text
    assert isin_decisions(rs) == {ISIN: LEI}
    run(env, rows(weights=(50, 50)))
    assert (held(env, ISIN).issuer_key, held(env, ISIN).issuer_scheme) == (LEI, "LEI")


def test_override_without_reason_refused(env):
    store = env[0]
    store.save_holder(HolderConfig(holder_id="IX1", kind="index", source="api"))
    assert run(env, source="api").revision == 1
    with pytest.raises(IntakeError) as e:
        run(env, rows(weights=(50, 50)))
    assert e.value.status == 409
    result = run(env, rows(weights=(50, 50)), reason="provider correction")
    assert result.revision == 2
    audit = store._read_jsonl(store.holdings_audit_path())[-1]
    assert audit["user_id"] == "u_test" and audit["override_reason"] == "provider correction"
    assert [h.weight_pct for h in store.load_revision("index", "IX1", "2026-10-31", 1)] == [60, 40]


def test_override_needed_for_other_date_in_api_month(env):
    env[0].save_holder(HolderConfig(holder_id="IX1", kind="index", source="api"))
    run(env, source="api")
    with pytest.raises(IntakeError) as e:
        run(env, as_of="2026-10-30")
    assert e.value.status == 409


def test_api_pull_for_file_holder_refused(env):
    run(env)
    with pytest.raises(IntakeError) as e:
        run(env, source="api")
    assert e.value.status == 409


def test_same_rows_twice_unchanged(env):
    run(env)
    assert run(env).status == "unchanged"
    assert env[0].list_revisions("index", "IX1", "2026-10-31") == [1]


def test_missing_month_reads_previous(env):
    run(env, kind="portfolio", holder="P1")
    assert [h.isin for h in load(env[0], "portfolio", "P1", "2026-11-30")] == [ISIN, ISIN2]
    assert load(env[0], "portfolio", "P1", "2026-09-30") == []


def test_intake_portfolio_visible_to_analytics(env):
    run(env, kind="portfolio", holder="P1")
    got = env[0].load_holdings_as_of("2026-10-31")
    assert [(h.holder_id, h.market_value_eur, h.fx_rate_to_eur) for h in got] == [("P1", 600, 1.0), ("P1", 400, 1.0)]


def test_holder_status_flags_stale(env):
    env[0].save_holder(HolderConfig(holder_id="IX1", kind="index", as_of="2026-09-30"))
    [s] = holder_status(env[0], date(2026, 11, 5))
    assert (s["stale"], s["age_days"], s["expected_as_of"]) == (True, 36, "2026-10-31")
    assert previous_month_end(date(2026, 3, 1)) == "2026-02-28"


def test_non_iso_as_of_refused(env):
    with pytest.raises(IntakeError) as e:
        run(env, rows(), as_of="../x")
    assert e.value.status == 422
    assert env[0].list_holders() == []


def test_rejected_file_writes_nothing(env):
    store = env[0]
    with pytest.raises(IntakeError) as e:
        run(env, Validated([], [RowError(2, "isin", "ISIN check digit fails")]))
    assert e.value.status == 422 and e.value.errors[0].column == "isin"
    assert store.list_revisions("index", "IX1", "2026-10-31") == []
    assert store.list_snapshot_dates("IX1", kind="index") == []
    assert store._read_jsonl(store.holdings_audit_path()) == []
