"""Indirect exposure from the NACE set (spec 2026-11-02-nace-exiobase-link-design, AC-11, AC-12*, AC-23)."""

import asyncio
import csv

import pytest

from arp.cli import app
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMUsage
from arp.research.indirect_exposure import nace
from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.pipeline import _match_company
from arp.research.value_chain.links import classify_unlinked, company_nace
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.portfolio_store import PortfolioStore
from tests.io_tier_fixture import write_fixture_v
from tests.test_io_tier import _round, runner
from tests.test_research_pipeline import _FixedDocSource, _settings
from tests.test_value_chain_links_nace import N


@pytest.fixture
def built(tmp_path, monkeypatch):
    def build():
        out = tmp_path / "vc"
        assert runner.invoke(app, ["io", "build-full", str(write_fixture_v(tmp_path / "src")), "--out", str(out)]).exit_code == 0
        monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(out))

    return build


def _ref(cid):
    return CompanyRef(company_id=cid, name=cid.upper(), **N[cid])


def X(cid, core, country):
    company = _ref(cid)
    return compute_indirect_exposure(
        cid, company.isic_code or "", resolve_indirect_exposure_model(Settings()), core, "e", country=country, nace=company_nace(company)
    )


class _Counting:
    def __init__(self):
        self.calls = 0

    async def complete_structured(self, *, system, prompt, output_model, **kwargs):
        self.calls += 1
        return output_model(isic_code=None, rationale="stub"), LLMUsage()


NACE_IDS = ["nc", "nw", "nr", "nf", "ni", "nm", "nd", "nu"]


def test_no_llm_call_on_the_nace_path(built, tmp_path):  # AC-11
    built()
    model = resolve_indirect_exposure_model(Settings())
    activity = ActivityDefinition(name="Copper mining", in_scope_description="x", out_of_scope_description="y",
                                  seed_keywords=["copper"], core_isic_codes=["B07"])
    theme = ThemeDefinition(name="T", description="t", activities=[activity])
    stub = _Counting()
    for cid in NACE_IDS:
        result = asyncio.run(_match_company(
            _ref(cid), theme, registry=DocumentSourceRegistry([_FixedDocSource([])]), llm=stub,
            settings=_settings(tmp_path), indirect_model=model,
        ))
        assert result.matches[0].indirect_exposure is None or result.matches[0].indirect_exposure.code_scheme != "icio"
    store = PortfolioStore(tmp_path / "pf")
    store.save_portfolio(Portfolio(portfolio_id="P", name="P"))
    for cid in NACE_IDS:
        store.save_company(_ref(cid))
        store.save_security(SecurityRef(security_id=f"s_{cid}", name=cid, asset_class="equity", currency="EUR", company_id=cid))
    store.save_snapshot("P", "2026-09-30", [
        Holding(holder_id="P", security_id=f"s_{c}", as_of_date="2026-09-30", market_value=1, market_value_eur=1) for c in NACE_IDS])
    asyncio.run(classify_unlinked(store, "P", "2026-09-30", model, stub))
    assert stub.calls == 0


def test_nace_exposure(built):  # AC-12, AC-12b, AC-12c, AC-12d, AC-12f
    built()
    nm = X("nm", {"B07"}, "CN")
    assert (_round(nm.upstream_exposure), _round(nm.downstream_exposure)) == (0.1549, 0.015)
    assert (nm.code_scheme, nm.isic_code) == ("nace2", "27.11")
    assert (X("nr", {"B07"}, "DE").code_scheme, X("nr", {"B07"}, "DE").isic_code) == ("nace21", "35.12")
    ni = X("ni", {"B07"}, "CN")
    assert (ni.code_scheme, ni.isic_code) == ("isic4", "2710")
    with nace._NACE_REVS.open(newline="", encoding="utf-8") as f:
        heading = next(r["NACE_Rev_2_Heading"] for r in csv.DictReader(f) if r["NACE_Rev_2_Code"] == "27.11")
    assert nm.isic_label == heading


def test_nace_core_and_critical(built):  # AC-12e, AC-12g, AC-12h
    built()
    assert X("nc", {"C27"}, "CN").critical_input is True
    nm = X("nm", {"C27"}, "CN")
    assert (nm.critical_input, nm.core_sector) == (False, True)


@pytest.mark.parametrize(("code", "core", "country"), [
    ("C27", {"B07"}, "CN"), ("C27", {"B07"}, None), ("B07", {"C27"}, "CN"), ("B07", {"C27"}, "DE"),
    ("C27", {"D_GEN_REN"}, "CN"), ("C27", {"D"}, "CN"), ("C27", {"B07"}, "THA"), ("C27", {"B07"}, "th"),
])
def test_icio_results_say_icio(built, code, core, country):  # AC-23 (values pinned in test_io_tier)
    built()
    r = compute_indirect_exposure("x", code, resolve_indirect_exposure_model(Settings()), core, "e", country=country)
    assert (r.code_scheme, r.isic_code) == ("icio", code)
