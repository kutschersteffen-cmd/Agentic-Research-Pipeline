"""Showcase defect 4: a failed load for a holder that does not exist (a rejected upload for a mistyped id) shows
neither as a feed row nor as an issue; one for a holder or portfolio that exists is still shown. Stored events stay."""
from datetime import date

import pytest

from arp.holdings.intake import IntakeError, ingest
from arp.holdings.validate import RowError, Validated
from arp.portfolio import feeds, issues
from arp.portfolio.loads import LoadRecord, record_load
from arp.schemas.portfolio import HolderConfig, Portfolio
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore

TODAY = date(2026, 11, 12)
REJECTED = Validated([], [RowError(None, "currency", "missing required column")])


@pytest.fixture
def env(tmp_path, pg):
    return PortfolioStore(tmp_path / "pf"), IdentifierMapStore(tmp_path / "idmap.jsonl"), RunStore(pg, tmp_path / "runs")


def _upload_rejected(store, idmap, holder_id, kind="portfolio"):
    with pytest.raises(IntakeError) as e:
        ingest(store, REJECTED, kind=kind, holder_id=holder_id, as_of="2026-10-31", source="file", source_ref="f.csv",
               principal=None, override_reason=None, idmap=idmap)
    assert (e.value.status, e.value.message) == (422, "file rejected")


def _loads(store):
    return [(e["source_id"], e["status"]) for e in store.list_governance_events() if e["event_type"] == "load_recorded"]


def _shown(store, idmap, rs):
    rows = feeds.overview(store, idmap, TODAY)
    found = issues.open_issues(store, idmap, rs, TODAY)
    return {r["source_id"] for r in rows if r["feed"] == "holdings"}, {i["subject"] for i in found if i["source"] == "feed"}


def test_stored_orphan_and_new_rejected_upload_show_nowhere(env):  # AC-106, without its last clause (spec question)
    store, idmap, rs = env
    record_load(store, LoadRecord(kind="holdings", source_id="ghost_fund", month="2026-10", status="failed", content_hash="",
                                  detail="4 row errors"))
    before = store.list_governance_events()
    _upload_rejected(store, idmap, "typo_fund")
    assert store.list_governance_events()[: len(before)] == before  # the stored orphan event is kept as it is
    feed_rows, issue_subjects = _shown(store, idmap, rs)
    assert not {"ghost_fund", "typo_fund"} & feed_rows and not {"ghost_fund", "typo_fund"} & issue_subjects


def test_failed_load_is_still_recorded_and_shown_for_a_holder_and_for_a_portfolio(env):
    store, idmap, rs = env
    store.save_holder(HolderConfig(holder_id="good_fund", kind="portfolio", source="file"))
    store.save_portfolio(Portfolio(portfolio_id="seeded", name="Seeded"))
    record_load(store, LoadRecord(kind="holdings", source_id="seeded", month="2026-10", status="ok", content_hash="h"))
    _upload_rejected(store, idmap, "good_fund")
    _upload_rejected(store, idmap, "seeded")
    assert _loads(store)[-2:] == [("good_fund", "failed"), ("seeded", "failed")]
    feed_rows, issue_subjects = _shown(store, idmap, rs)
    assert {"good_fund", "seeded"} <= feed_rows and {"good_fund", "seeded"} <= issue_subjects
    rows = {r["source_id"]: r for r in feeds.overview(store, idmap, TODAY)}
    assert rows["seeded"]["last_load"]["status"] == "failed"

