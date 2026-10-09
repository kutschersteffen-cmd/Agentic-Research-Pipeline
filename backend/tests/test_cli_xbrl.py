from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from arp.xbrl_pipeline.models import CatalogEntry, ReportMeta
from arp.xbrl_pipeline.store import XbrlStore

CIK = "0001234567"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARP_XBRL_DIR", str(tmp_path / "xbrl"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _invoke(*args):
    return CliRunner().invoke(app, ["xbrl", *args])


def _seed(tmp_path):
    store = XbrlStore(tmp_path / "xbrl")
    store.write_catalog(CIK, [CatalogEntry(taxonomy="us-gaap", concept="Revenues", label="Revenues", fact_count=3,
                                           first_year=2020, last_year=2025, units=["USD"])])
    store.set_meta(CIK, source_sha="abc", tags=None, company_id="ex", company_name="Example Inc", fact_count=7)
    return store


def test_tags_lists_registry_with_seen_counts(env):
    _seed(env)
    result = _invoke("tags", "--search", "revenues")
    assert result.exit_code == 0, result.output
    assert "us-gaap:Revenues" in result.stdout and "seen=1" in result.stdout
    assert "1 tag(s)" in result.stdout


def test_select_writes_selection_and_prints_count(env):
    result = _invoke("select", "--name", "mine", "--tags", "us-gaap:Revenues, us-gaap:Assets")
    assert result.exit_code == 0, result.output
    assert "Selection 'mine': 0 fact(s)" in result.stdout
    meta = json.loads((env / "xbrl" / "selections" / "mine.json").read_text())
    assert meta["tags"] == ["us-gaap:Assets", "us-gaap:Revenues"]


def test_files_lists_companies_with_report_info(env):
    store = _seed(env)
    store.save_report(CIK, b"<html/>", ReportMeta(
        accession="0001-26-000001", form="10-K", filing_date="2026-02-01", source_url="http://x",
        primary_document="r.htm", filename="r.htm", sha256="s", size=7, inline_xbrl=True))
    result = _invoke("files")
    assert result.exit_code == 0, result.output
    assert f"{CIK}  ex  Example Inc  facts=7  report=10-K 2026-02-01" in result.stdout


def _verify_setup(env, **settings):
    run_dir = env / "runs" / "r1"
    run_dir.mkdir(parents=True)
    if settings is not None:
        (run_dir / "step_settings.json").write_text(json.dumps(settings))
    (run_dir / "results.jsonl").write_text("")


def test_verify_prints_summary_and_exits_nonzero_on_circular_run(env):
    _verify_setup(env, xbrl_facts_enabled=True)
    result = _invoke("verify", "r1", "--map", "revenue=rev_f")
    assert result.exit_code == 1
    assert "r1: ran with xbrl_facts_enabled, its values are copied from XBRL" in result.stderr


def test_verify_prints_summary_for_clean_run(env):
    _verify_setup(env, xbrl_facts_enabled=False)
    result = _invoke("verify", "r1", "--map", "revenue=rev_f")
    assert result.exit_code == 0, result.output
    assert "0 comparison(s)" in result.stdout


def test_verify_reports_malformed_step_settings(env):
    _verify_setup(env)
    (env / "runs" / "r1" / "step_settings.json").write_text("{not json")
    result = _invoke("verify", "r1", "--map", "revenue=rev_f")
    assert result.exit_code == 1 and "r1" in result.stderr and "Traceback" not in result.output


def test_verify_circular_run_without_map_reports_guard_first(env):
    _verify_setup(env, xbrl_facts_enabled=True)
    result = _invoke("verify", "r1")
    assert result.exit_code == 1
    assert "r1: ran with xbrl_facts_enabled, its values are copied from XBRL" in result.stderr


def test_verify_clean_run_requires_a_map(env):
    _verify_setup(env, xbrl_facts_enabled=False)
    result = _invoke("verify", "r1")
    assert result.exit_code == 2
    assert "pass at least one --map metric=field" in result.output


def test_verify_rejects_malformed_map(env):
    _verify_setup(env, xbrl_facts_enabled=False)
    result = _invoke("verify", "r1", "--map", "revenue")
    assert result.exit_code == 2
    assert "--map must look like metric=field" in result.output


def test_fetch_runs_with_patched_source(env, monkeypatch):
    class Source:
        async def resolve_cik(self, cik, ticker):
            return None

    monkeypatch.setattr("arp.cli.xbrl.build_source", lambda settings, refresh=False: Source())
    universe = env / "u.json"
    universe.write_text(json.dumps([{"company_id": "ex", "name": "Example Inc"}]))
    result = _invoke("fetch", "--universe", str(universe), "--tags", "")
    assert result.exit_code == 0, result.output
    assert "no_cik=1" in result.stdout
    run_id = result.stdout.split("Run: ")[1].split()[0]
    rows = [json.loads(line) for line in (env / "runs" / run_id / "results.jsonl").read_text().splitlines()]
    assert [(r["company_id"], r["status"]) for r in rows] == [("ex", "no_cik")]
    assert json.loads((env / "runs" / run_id / "manifest.json").read_text())["params"]["tags"] is None


def test_taxonomy_update_uses_http_fetch_with_user_agent(env, monkeypatch):
    calls = {}

    async def fake_update(store, *, fetch, taxonomies=None):
        calls["fetch"] = fetch
        return {"us-gaap": 4}

    monkeypatch.setattr("arp.cli.xbrl.update_taxonomies", fake_update)
    result = _invoke("taxonomy", "update")
    assert result.exit_code == 0, result.output
    assert "us-gaap: 4 tag(s)" in result.stdout
    assert callable(calls["fetch"])


@pytest.mark.parametrize("exc, fragment", [
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "http://sec/x.xsd"), response=httpx.Response(403)),
     "HTTP 403 for http://sec/x.xsd"),
    (httpx.ConnectError("no route"), "taxonomy update failed: no route"),
])
def test_taxonomy_update_reports_http_errors_without_traceback(env, monkeypatch, exc, fragment):
    async def failing(store, *, fetch, taxonomies=None):
        raise exc

    monkeypatch.setattr("arp.cli.xbrl.update_taxonomies", failing)
    result = _invoke("taxonomy", "update")
    assert result.exit_code == 1
    assert fragment in result.stderr and "Traceback" not in result.output


def test_select_rejects_malformed_tag(env):
    result = _invoke("select", "--name", "mine", "--tags", "us-gaap:Revenues,Revenues")
    assert result.exit_code == 2 and "Revenues" in result.stderr and not (env / "xbrl" / "selections").exists()


def test_fetch_rejects_malformed_tag_before_running(env, tmp_path):
    uni = tmp_path / "u.csv"
    uni.write_text("company_id,name,cik\nex,Ex,1\n")
    result = _invoke("fetch", "--universe", str(uni), "--tags", "us-gaap:Revenues,Bad Tag")
    assert result.exit_code == 2 and "Bad Tag" in result.stderr and not list((env / "runs").glob("*"))


def test_verify_non_generic_run_exits_1_with_message(env):
    _verify_setup(env, xbrl_facts_enabled=False)
    (env / "runs" / "r1" / "results.jsonl").write_text(json.dumps({"company_id": "ex", "financials": {}}) + "\n")
    result = _invoke("verify", "r1", "--map", "revenue=rev_f")
    assert result.exit_code == 1 and "generic extraction records" in result.stderr
    assert "Traceback" not in result.output
