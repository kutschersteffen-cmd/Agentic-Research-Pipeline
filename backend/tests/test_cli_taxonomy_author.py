import json

import pytest
from typer.testing import CliRunner

from arp.cli import taxonomy as cli
from arp.research.authority_taxonomy import run
from arp.research.authority_taxonomy.discovery import Candidate
from arp.research.authority_taxonomy.extract import SourceExtraction
from arp.storage.run_store import LegacyRunStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.test_authority_taxonomy_consolidate import _act, _fake, _settings


@pytest.fixture
def env(monkeypatch, tmp_path):
    async def fake_discover(theme_name, theme_key, guidance, **kw):
        return [Candidate(url="https://a.org", title="A", source_type="agency_report", summary="sum", reason="r",
                          fetchable=True, covers=[], from_library=False)]

    async def fake_fetch(url, user_agent, timeout=20.0, max_chars=0):
        return "text"

    async def fake_extract(url, text, **kw):
        return SourceExtraction(url=url, activities=[_act("Stacks", url)])

    monkeypatch.setattr(run, "discover_candidates", fake_discover)
    monkeypatch.setattr(run, "fetch_source_text", fake_fetch)
    monkeypatch.setattr(run, "extract_source", fake_extract)
    store, tax = LegacyRunStore(tmp_path / "runs"), TaxonomyStore(tmp_path / "tax")
    monkeypatch.setattr(cli, "_run_store", lambda: store)
    monkeypatch.setattr(cli, "_taxonomy_store", lambda: tax)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "build_llm_client", lambda s: _fake(10))
    monkeypatch.setattr(cli, "build_web_search_client", lambda ua: None)
    return tmp_path


def _invoke(*args):
    return CliRunner().invoke(cli.taxonomy_app, ["author", *args])


def _last(res):
    return res.stdout.strip().splitlines()[-1]


def test_cli_flow(env):
    res = _invoke("start", "Hydrogen", "--scope", "x")
    assert res.exit_code == 0 and "https://a.org" in res.stdout and _last(res) == "stage: awaiting_sources"
    run_id = res.stdout.splitlines()[0].split()[-1]
    res = _invoke("select", run_id, "--url", "https://a.org")
    assert res.exit_code == 0 and _last(res) == "stage: awaiting_review"
    res = _invoke("review", run_id)
    draft = json.loads(res.stdout[: res.stdout.rindex("stage:")])
    assert _last(res) == "stage: awaiting_review"
    edited = env / "d.json"
    edited.write_text(json.dumps(draft))
    res = _invoke("review", run_id, "--edit", str(edited))
    assert res.exit_code == 0 and _last(res) == "stage: awaiting_review"
    res = _invoke("accept", run_id)
    assert res.exit_code == 0 and _last(res) == "stage: accepted" and "tax_" in res.stdout


def test_wrong_stage_exits_1(env):
    run_id = _invoke("start", "Hydrogen", "--scope", "x").stdout.splitlines()[0].split()[-1]
    res = _invoke("accept", run_id)
    assert res.exit_code == 1 and "awaiting_sources" in res.stderr


def test_unknown_run_exits_1(env):
    res = _invoke("review", "nope")
    assert res.exit_code == 1 and res.stderr.strip()
