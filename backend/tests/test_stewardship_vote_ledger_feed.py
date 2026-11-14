from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import update

pytest.importorskip("zen")

from arp.api.routers.stewardship import monitoring_triggers  # noqa: E402
from arp.config import Settings  # noqa: E402
from arp.db.session import transaction  # noqa: E402
from arp.stewardship import process, voting_feed  # noqa: E402
from arp.stewardship.npx_load import load_npx  # noqa: E402
from arp.stewardship.process import SAMPLE_PATH, StreamStore  # noqa: E402
from arp.stewardship.vote_ledger_feed import ledger_rows  # noqa: E402
from arp.storage.engagement_store import EngagementStore  # noqa: E402
from arp.storage.postgres_models import VoteDecisionModel  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "npx" / "fixture.csv"
SOCGEN = "isin_FR0000130809"  # in the house universe, no stw_companies row


@pytest.fixture(autouse=True)
def universe(pg, sample_house_universe, monkeypatch):
    issuer = copy.deepcopy(json.loads(SAMPLE_PATH.read_text())["issuers"][0])
    issuer.update(issuer_id=SOCGEN, name="Societe Generale", fields={})
    monkeypatch.setattr(process, "house_universe", lambda: {"issuers": [copy.deepcopy(issuer)]})
    monkeypatch.setattr(process, "house_isins", lambda: {})  # the sample-like universe above holds no securities


def _load(tmp_path, pg, dates=None, lines=None):
    text = FIXTURE.read_text().splitlines()
    rows = text[1:] if lines is None else [text[i] for i in lines]
    dates = dates or {}
    rows = [r.replace("/2024,", f"/{dates.get(r.split(',')[2], 2026)},") for r in rows]
    d = tmp_path / "npx"
    d.mkdir(exist_ok=True)
    (d / "f.csv").write_text("\n".join([text[0], *rows]) + "\n")
    load_npx(d, pg)


def _vote_triggers(tmp_path):
    out = monitoring_triggers(Settings(), StreamStore(tmp_path / "s"), EngagementStore(tmp_path / "e"))["triggers"]
    return [t for t in out if t["issuer_id"] == SOCGEN and t["type"] == "vote_outcome"]


def test_ac38_against_vote_in_newest_year_raises_one_trigger(tmp_path, pg):
    _load(tmp_path, pg)
    [t] = _vote_triggers(tmp_path)
    assert t["rule"] == "vote_against_management"


def test_ac39_old_against_vote_raises_none(tmp_path, pg):
    _load(tmp_path, pg, dates={"Société Générale": 2024, "トヨタ自動車": 2026, "Apple Inc.": 2026})
    assert _vote_triggers(tmp_path) == []


def test_rows_carry_every_voting_feed_key(tmp_path, pg):
    _load(tmp_path, pg)
    keys = {"run_id", "company_id", "company", "meeting_date", "item", "type", "management", "policy", "vote", "status",
            "decided_by", "co_signed_by", "note", "overrode_policy", "against_management"}  # fmt: skip
    rows = ledger_rows(pg, 365)
    assert len(rows) == 10 and all(set(r) == keys for r in rows)
    assert {r["meeting_date"] for r in rows if r["company_id"] == SOCGEN} == {"2026-05-23"}


def test_ac40_run_row_with_same_key_is_not_counted_twice(tmp_path, pg, monkeypatch):
    _load(tmp_path, pg, lines=[1])
    with transaction(pg) as s:
        s.execute(update(VoteDecisionModel).values(run_id="run_1"))
    [ledger] = ledger_rows(pg, 365)
    run = {**ledger, "decided_by": "pm", "policy": "for", "type": "routine"}
    monkeypatch.setattr(voting_feed, "items", lambda _store: [run])
    assert len(process.vote_items()) == 1
    assert process.load_sample()["issuers"][0]["fields"]["vote.decided"] == 1


def test_null_against_counts_decided_only(tmp_path, pg):
    _load(tmp_path, pg, lines=[10])  # Apple, "ONE YEAR": against_management is null
    [row] = ledger_rows(pg, 365)
    assert row["against_management"] is False
    fields = voting_feed.issuer_fields([row])[row["company_id"]]
    assert (fields["vote.decided"], fields["vote.against_management"]) == (1, 0)


def test_isin_registered_under_a_universe_id_gives_that_id(tmp_path, pg, monkeypatch):
    from arp.db.companies import resolve_company
    from arp.schemas.common import CompanyRef

    issuer = {**process.house_universe()["issuers"][0], "issuer_id": "SgFr01"}
    monkeypatch.setattr(process, "house_universe", lambda: {"issuers": [issuer]})
    with transaction(pg) as s:
        resolve_company(s, CompanyRef(company_id="SgFr01", name="Societe Generale", isin="FR0000130809"))
    _load(tmp_path, pg, lines=[1])  # stw_companies is empty: the meeting has no company_id
    [row] = ledger_rows(pg, 365)
    assert row["company_id"] == "SgFr01"


def test_isin_of_a_company_outside_the_house_universe_keeps_isin_key(tmp_path, pg):
    from arp.db.companies import resolve_company
    from arp.schemas.common import CompanyRef

    with transaction(pg) as s:
        resolve_company(s, CompanyRef(company_id="Other99", name="Societe Generale", isin="FR0000130809"))
    _load(tmp_path, pg, lines=[1])
    [row] = ledger_rows(pg, 365)
    assert row["company_id"] == SOCGEN


def test_ac38_house_issuer_holding_the_isin_gets_the_trigger(tmp_path, pg, monkeypatch):
    """A portfolio universe names issuers by portfolio company id (here `bmw`), not `isin_<ISIN>`: the vote on the
    ISIN the portfolio holds must reach that issuer, with stw_* empty."""
    import asyncio

    from arp.portfolio.mock_data import generate_demo_dataset
    from arp.stewardship.universe import from_portfolio, held_isins
    from arp.storage.portfolio_store import PortfolioStore

    store = PortfolioStore(tmp_path / "pf")
    asyncio.run(generate_demo_dataset(store))
    monkeypatch.setattr(process, "house_universe", lambda: from_portfolio(store))
    monkeypatch.setattr(process, "house_isins", lambda: held_isins(store))
    isin = next(i for i, c in held_isins(store).items() if c == "bmw")
    d = tmp_path / "npx"
    d.mkdir()
    (d / "f.csv").write_text(FIXTURE.read_text().replace("FR0000130809", isin).replace("/2024,", "/2026,"))
    load_npx(d, pg)
    out = monitoring_triggers(Settings(), StreamStore(tmp_path / "s"), EngagementStore(tmp_path / "e"))["triggers"]
    assert [t["rule"] for t in out if t["issuer_id"] == "bmw" and t["type"] == "vote_outcome"] == ["vote_against_management"]
