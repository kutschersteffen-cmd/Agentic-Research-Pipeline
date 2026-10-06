from __future__ import annotations

from datetime import date

import pytest

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.holdings import load
from arp.holdings.intake import IntakeError, holder_status, ingest, previous_month_end
from arp.holdings.validate import RowError, Validated, validate
from arp.schemas.issuer import IdentifierMap
from arp.schemas.portfolio import HolderConfig
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


def run(env, v=None, *, kind="index", holder="IX1", as_of="2026-10-31", source="file", reason=None, principal=PRINCIPAL,
        ref="f.csv"):
    store, rs, idmap = env
    return ingest(store, v or rows(kind, as_of), kind=kind, holder_id=holder, as_of=as_of, source=source,
                  source_ref=ref, principal=principal, override_reason=reason, idmap=idmap)


def held(env, isin, kind="index", holder="IX1", as_of="2026-10-31"):
    return next(h for h in env[0].load_snapshot(holder, as_of, kind=kind) if h.isin == isin)


def test_isin_resolves_to_internal_issuer_through_security_master(env):
    env[2].add(IdentifierMap(issuer_key="ISS-1", scheme="ISIN", value=ISIN))
    run(env)
    assert (held(env, ISIN).issuer_key, held(env, ISIN).issuer_scheme) == ("ISS-1", "INTERNAL")


def test_row_lei_counts_only_through_the_security_master(env):
    lei_rows = Validated([{**r, "lei": LEI} for r in rows().rows], [])
    run(env, lei_rows)
    assert held(env, ISIN).issuer_scheme == "ARP_PROVISIONAL", "a valid LEI the master does not know is not an issuer"
    env[2].add(IdentifierMap(issuer_key="ISS-1", scheme="LEI", value=LEI))
    run(env, Validated([{**r, "lei": LEI, "weight": 50} for r in rows().rows], []))
    assert (held(env, ISIN).issuer_key, held(env, ISIN).issuer_scheme) == ("ISS-1", "INTERNAL")


def test_unmatched_isin_is_provisional_and_never_queued_for_a_manual_issuer(env):
    env[2].add(IdentifierMap(issuer_key="ISS-2", scheme="ISIN", value=ISIN2))
    result = run(env)
    assert result.unresolved == [ISIN]
    h = held(env, ISIN)
    assert h.issuer_scheme == "ARP_PROVISIONAL" and h.issuer_key.startswith("ARP:")
    assert env[1].list_runs("holdings") == [], "the fix is the security master, not a review item"
    assert [x.security_id for x in env[0].list_resolutions_needing_review()] == [ISIN]


def test_ambiguous_isin_stays_unmatched(env):
    env[2].add(IdentifierMap(issuer_key="ISS-1", scheme="ISIN", value=ISIN))
    env[2].add(IdentifierMap(issuer_key="ISS-9", scheme="ISIN", value=ISIN))
    assert ISIN in run(env).unresolved


def test_master_fix_clears_needs_review_on_the_next_load(env):
    store = env[0]
    run(env)
    env[2].add(IdentifierMap(issuer_key="ISS-1", scheme="ISIN", value=ISIN))
    run(env, rows(weights=(50, 50)))
    assert ISIN not in [x.security_id for x in store.list_resolutions_needing_review()]
    assert ISIN2 in [x.security_id for x in store.list_resolutions_needing_review()]


def test_override_without_reason_refused(env):
    store = env[0]
    store.save_holder(HolderConfig(holder_id="IX1", kind="index", source="api"))
    assert run(env, source="api").revision == 1
    with pytest.raises(IntakeError) as e:
        run(env, rows(weights=(50, 50)))
    assert e.value.status == 409
    assert store.list_revisions("index", "IX1", "2026-10-31") == [1]
    assert [h.weight_pct for h in store.load_snapshot("IX1", "2026-10-31", kind="index")] == [60, 40]
    assert len(store._read_jsonl(store.holdings_audit_path())) == 1
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
    assert run(env, ref="renamed.csv").status == "unchanged"
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


@pytest.mark.parametrize("as_of", ["../x", "20261031", "2026-W44-6"])
def test_non_iso_as_of_refused(env, as_of):
    with pytest.raises(IntakeError) as e:
        run(env, rows(), as_of=as_of)
    assert e.value.status == 422
    assert env[0].list_holders() == []
    with pytest.raises(ValueError):
        validate([], kind="index", as_of=as_of)


@pytest.mark.parametrize("as_of", ["2026-10-30", "20261030", "2026-W44-5"])
def test_api_month_override_holds_for_any_spelling(env, as_of):
    env[0].save_holder(HolderConfig(holder_id="IX1", kind="index", source="api"))
    run(env, source="api")
    with pytest.raises(IntakeError) as e:
        run(env, rows(), as_of=as_of)
    assert e.value.status in (409, 422)  # a compact spelling is refused outright, never written past the rule
    assert env[0].list_snapshot_dates("IX1", kind="index") == ["2026-10-31"]


def test_unsafe_holder_id_refused(env):
    with pytest.raises(IntakeError) as e:
        run(env, holder="../evil")
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
