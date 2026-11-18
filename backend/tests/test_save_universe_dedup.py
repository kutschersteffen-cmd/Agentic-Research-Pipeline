"""Saving the same company list under the same name twice reuses the first file instead of adding a copy."""

from arp.api.routers.universe import save_universe
from arp.config import Settings
from arp.schemas.common import CompanyRef


def _settings(tmp_path) -> Settings:
    return Settings(runs_dir=tmp_path / "runs")


def test_same_list_and_name_reuses_the_file(tmp_path):
    s = _settings(tmp_path)
    companies = [CompanyRef(company_id="c1", name="Acme"), CompanyRef(company_id="c2", name="Beta")]
    first = save_universe(s, companies, "holdings all 2026-08-12")
    second = save_universe(s, companies, "holdings all 2026-08-12")
    assert second["path"] == first["path"]
    assert len(list((s.runs_dir / "_universes").glob("*.json"))) == 1


def test_a_different_list_or_name_is_saved_separately(tmp_path):
    s = _settings(tmp_path)
    a = save_universe(s, [CompanyRef(company_id="c1", name="Acme")], "holdings")
    b = save_universe(s, [CompanyRef(company_id="c2", name="Beta")], "holdings")
    c = save_universe(s, [CompanyRef(company_id="c1", name="Acme")], "other")
    assert len({a["path"], b["path"], c["path"]}) == 3
