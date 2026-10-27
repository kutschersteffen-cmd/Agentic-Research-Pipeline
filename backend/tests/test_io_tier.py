"""The indirect-exposure tier on `arp io build-full` output (spec 2026-10-26-io-full-resolution-tier-design)."""

import asyncio
import csv
import re

import numpy as np
import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import Settings
from arp.llm.base import LLMUsage
from arp.research.indirect_exposure.company_mapper import resolve_company_isic
from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.indirect_exposure.io_import import REFERENCE_DIR, country_regions
from arp.schemas.common import CompanyRef
from tests.io_tier_fixture import write_fixture_v

runner = CliRunner()


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Builds Fixture V (kwargs to write_fixture_v) and points ARP_VALUE_CHAIN_DIR at it."""

    def build(**kwargs):
        out = tmp_path / "vc"
        result = runner.invoke(app, ["io", "build-full", str(write_fixture_v(tmp_path / "src", **kwargs)), "--out", str(out)])
        monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(out))
        return result, out

    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR", raising=False)
    return build


def _exposure(code, core, country=None):
    model = resolve_indirect_exposure_model(Settings())
    return compute_indirect_exposure("x", code, model, core, "e", country=country)


def _round(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def test_reference_files():
    rows = list(csv.DictReader((REFERENCE_DIR / "exiobase_ixi_to_icio2025.csv").open()))
    assert len(rows) == 163
    assert [rows[k - 1]["icio_code"] for k in (87, 88, 89, 100, 108, 133, 55, 163)] == ["C26", "C27", "C26", "D", "D", "J62_63", "C17_18", "O"]
    assert len(list(csv.DictReader((REFERENCE_DIR / "ghg_gwp100.csv").open()))) == 23
    regions = country_regions()
    assert (regions["THA"], regions["TH"], regions["GBR"], regions["GR"], regions["USA"]) == ("WA", "WA", "GB", "GR", "US")
    assert len(set(regions.values())) == 49


def test_build_writes_final_demand(built):
    result, out = built()
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == f"12 nodes (4 sectors × 3 regions) -> {out}"
    columns = list(csv.reader((out / "y_columns.csv").open()))
    assert columns[0] == ["region", "category"] and len(columns) == 22
    assert [c[0] for c in columns[1:]] == ["DE"] * 7 + ["CN"] * 7 + ["WA"] * 7
    assert columns[4] == ["DE", "Gross fixed capital formation"] and columns[7] == ["DE", "Exports: Total (fob)"]
    y = np.load(out / "Y.npy")
    assert y.shape == (12, 21) and y.dtype == np.float64
    assert (y[7, 7 + 3], y[7, 7 + 6], y[7, 0]) == (200, 999, 30)


def test_build_without_y_writes_no_final_demand(built):
    result, out = built(with_y=False)
    assert result.exit_code == 0, result.output
    assert not (out / "Y.npy").exists() and not (out / "y_columns.csv").exists()


def test_build_rejects_unknown_category(built):
    result, out = built(y_categories={("CN", "Changes in valuables"): "Made-up demand"})
    assert result.exit_code == 1
    assert "Y.txt: unknown final-demand category: Made-up demand" in result.stderr
    assert not out.exists()


def test_model(built):
    built()
    model = resolve_indirect_exposure_model(Settings())
    assert model.edition_label == "exiobase-IOT_2022_ixi"
    assert len(model.codes) == 55 and model.codes[-5:] == ["D_GEN_FOS", "D_GEN_NUC", "D_GEN_REN", "D_TD", "D_GAS"]
    prompt = model.industry_prompt_list().splitlines()
    assert len(prompt) == 50 and not any("D_GEN" in line for line in prompt)


def test_model_off_or_not_built(tmp_path, monkeypatch):
    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR", raising=False)
    assert resolve_indirect_exposure_model(Settings()) is None
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="^value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR$"):
        resolve_indirect_exposure_model(Settings())


def test_exposure_in_company_region(built):
    built()
    r = _exposure("C27", {"B07"}, "CN")
    assert _round(r.upstream_exposure) == 0.1549 and _round(r.downstream_exposure) == 0.015
    assert (r.isic_code, r.isic_label, r.core_sector, r.icio_edition, r.company_id) == (
        "C27", "Manufacture of electrical equipment", False, "e", "x")
    assert _round(r.end_market) == {"households": 0.4116, "government": 0.0023, "investment": 0.5855, "inventories": 0.0006}
    assert list(r.end_market) == ["households", "government", "investment", "inventories"]
    assert _round(r.theme_demand_share) == 0.0006
    assert _round(r.ghg_direct_t_per_meur) == 5 and _round(r.ghg_supply_chain_t_per_meur) == 5.2949
    assert r.regional.region == "CN" and _round(r.regional.upstream) == 0.1549
    assert _round(r.regional.upstream_by_region) == {"CN": 0.1149, "EU": 0.0019, "ASIA_OTH": 0.038}
    assert list(r.regional.upstream_by_region) == ["CN", "EU", "ASIA_OTH"]
    assert _round(r.regional.downstream_by_region) == {"CN": 0.015, "EU": 0, "ASIA_OTH": 0}


@pytest.mark.parametrize("country", [None, "US"])  # US has no nodes in V: every region
def test_exposure_all_regions(built, country):
    built()
    r = _exposure("C27", {"B07"}, country)
    assert [_round(v) for v in (r.upstream_exposure, r.downstream_exposure, r.ghg_direct_t_per_meur, r.ghg_supply_chain_t_per_meur)] == [
        0.1295, 0.0152, 3.6923, 3.9307]
    assert r.regional is None


@pytest.mark.parametrize(("code", "core", "country", "expected"), [
    ("B07", {"C27"}, "CN", {"upstream_exposure": 0.014, "downstream_exposure": 0.1085, "ghg_direct_t_per_meur": 0.7143, "theme_demand_share": 0.7939}),
    ("B07", {"C27"}, "DE", {"upstream_exposure": 0, "downstream_exposure": 0.0506}),  # DE.2 has no output
    ("C27", {"D_GEN_REN"}, "CN", {"upstream_exposure": 0.0493, "downstream_exposure": 0.2273, "theme_demand_share": 0.0348}),
    ("C27", {"D"}, "CN", {"upstream_exposure": 0.0493, "downstream_exposure": 0.2273, "theme_demand_share": 0.0348}),
    ("C27", {"B07"}, "THA", {"upstream_exposure": 0.0909, "downstream_exposure": 0.0904}),
    ("C27", {"B07"}, "th", {"upstream_exposure": 0.0909, "downstream_exposure": 0.0904}),
    ("C27", {"B07", "D"}, "DE", {"upstream_exposure": 0.1705, "downstream_exposure": 0.2313, "theme_demand_share": 0.1025, "ghg_direct_t_per_meur": 2}),
])
def test_exposure_values(built, code, core, country, expected):
    built()
    r = _exposure(code, core, country)
    assert {k: _round(getattr(r, k)) for k in expected} == expected


def test_exposure_region_groups(built):
    built()
    assert _exposure("B07", {"C27"}, "DE").regional.region == "EU"
    assert _exposure("C27", {"B07"}, "THA").regional.region == "ASIA_OTH"


def test_exposure_none(built):
    built()
    assert _exposure("B07", {"A01"}, "CN") is None  # no A01 nodes
    assert _exposure("ZZ", {"B07"}, "CN") is None


def test_exposure_without_final_demand(built):
    built(with_y=False)
    r = _exposure("C27", {"B07"}, "CN")
    assert (r.end_market, r.theme_demand_share) == (None, None)
    assert _round(r.upstream_exposure) == 0.1549


class _Stub:
    def __init__(self):
        self.calls = 0

    async def complete_structured(self, *, system, prompt, output_model):
        self.calls += 1
        return output_model(isic_code=None, rationale="stub"), LLMUsage()


@pytest.mark.parametrize(("code", "expected", "calls"), [
    ("27", "C27", 0), ("35", "D", 0), ("35.12", "D_TD", 0), ("D_GEN_REN", "D_GEN_REN", 0), ("35.11", None, 1), ("24", None, 1),
    ("62", "J62_63", 0), ("2610", None, 1), ("C27", "C27", 0),
])
def test_company_lookup(built, code, expected, calls):
    built()
    stub = _Stub()
    company = CompanyRef(company_id="x", name="X", isic_code=code)
    assert asyncio.run(resolve_company_isic(company, resolve_indirect_exposure_model(Settings()), stub))[0] == expected
    assert stub.calls == calls


def test_rebuild_into_same_directory_reloads(built):
    built()
    assert resolve_indirect_exposure_model(Settings()).final_demand is not None
    result, _ = built(with_y=False)  # same --out, different archive: a new manifest
    assert result.exit_code == 0, result.output
    assert resolve_indirect_exposure_model(Settings()).final_demand is None


def test_sample():
    model = resolve_indirect_exposure_model(Settings(), use_sample=True)
    assert model.edition_label == "sample"
    r = compute_indirect_exposure("x", "C27", model, {"B07"}, "e", country="CN")
    assert r.upstream_exposure > 0 and r.downstream_exposure > 0 and r.end_market is not None


def test_status(built, monkeypatch):
    assert runner.invoke(app, ["io", "status"]).stdout == "source: none\n"
    built()
    result = runner.invoke(app, ["io", "status"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["source: exiobase", "edition: exiobase-IOT_2022_ixi", "nodes: 12", "final demand: yes"]


def test_status_without_final_demand(built):
    built(with_y=False)
    assert runner.invoke(app, ["io", "status"]).stdout.splitlines()[3] == "final demand: no"


def test_status_reports_retired_settings(monkeypatch):
    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR", raising=False)
    monkeypatch.setenv("ARP_IO_SOURCE", "icio")
    monkeypatch.setenv("ARP_ICIO_MATRIX_PATH", "/x")
    result = runner.invoke(app, ["io", "status"])
    assert result.exit_code == 0 and result.stdout == "source: none\n"
    assert result.stderr.splitlines() == ["ignored (retired): ARP_ICIO_MATRIX_PATH", "ignored (retired): ARP_IO_SOURCE"]


@pytest.mark.parametrize("args", [
    ["io", "import-exiobase", "x.zip", "--out", "d"],
    ["io", "import-icio", "x.csv", "--out", "d"],
])
def test_retired_commands(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2 and "No such command" in result.stderr


@pytest.mark.parametrize("args", [
    ["theme", "classify-sectors", "--use-sample-icio"],
    ["taxonomy", "create", "t", "--use-sample-exiobase"],
])
def test_retired_options(args, pg):
    result = runner.invoke(app, args)
    # CI forces colour: Rich wraps the message in ANSI codes and a box
    stderr = " ".join(re.sub(r"[│╭╮╰╯─]", " ", re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)).split())
    assert result.exit_code == 2 and f"No such option: {args[-1]}" in stderr


def test_classify_sectors_without_model(tmp_path, monkeypatch, pg):
    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR", raising=False)
    theme = tmp_path / "theme.json"
    theme.write_text('{"name": "t", "description": "", "activities": []}')
    result = runner.invoke(app, ["theme", "classify-sectors", "--theme", str(theme), "--out", str(tmp_path / "o.json")])
    assert result.exit_code == 1
    assert result.stderr == (
        "No input-output data available: run arp io build-full and set ARP_VALUE_CHAIN_DIR, or pass --use-sample-io.\n")
