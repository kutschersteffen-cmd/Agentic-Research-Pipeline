import asyncio
from datetime import date

from typer.testing import CliRunner

from arp.cli.authority_library import authority_library_app
from arp.discovery.site_finder import SearchResult
from arp.research.authority_taxonomy import discovery
from arp.research.authority_taxonomy.discovery import _CandidateDraft, propose
from arp.research.authority_taxonomy.library import THEME_KEYS, LibraryEntry, approve, load_library, reject, save_library
from tests.conftest import FakeLLMClient, FakeSearchClient


def _entry(url, status="proposed"):
    return LibraryEntry(url=url, title=url, source_type="agency_report", summary="s", covers=[], fetchable=True, status=status)


def test_propose_adds_proposed(monkeypatch, tmp_path):
    async def fake_fetch(url, user_agent, timeout=20.0, max_chars=0):
        return "text"

    monkeypatch.setattr(discovery, "fetch_source_text", fake_fetch)
    save_library("hydrogen", [_entry("https://iea.org/0", "approved")], tmp_path)
    urls = [f"https://iea.org/n{i}" for i in range(4)]
    search = FakeSearchClient({"": [SearchResult(title="T", url=u, snippet="s") for u in urls]})
    draft = _CandidateDraft(summary="x", reason="r", source_type="agency_report", covers=["a"])
    llm = FakeLLMClient({"_CandidateDraft": [draft] * 20})
    asyncio.run(propose("hydrogen", search_client=search, llm=llm, user_agent="t", root=tmp_path))
    entries = load_library("hydrogen", tmp_path)
    assert len(entries) == 5
    asyncio.run(propose("hydrogen", search_client=search, llm=llm, user_agent="t", root=tmp_path))  # idempotent
    assert len(load_library("hydrogen", tmp_path)) == 5
    assert entries[0] == _entry("https://iea.org/0", "approved")
    assert {e.status for e in entries[1:]} == {"proposed"} and all(e.checked_on is None for e in entries[1:])


def test_approve_sets_date(tmp_path):
    save_library("water", [_entry("https://a")], tmp_path)
    approve("water", "https://a", date(2026, 11, 10), tmp_path)
    [e] = load_library("water", tmp_path)
    assert (e.status, e.checked_on) == ("approved", "2026-11-10")


def test_reject_removes(tmp_path):
    save_library("water", [_entry("https://a"), _entry("https://b")], tmp_path)
    reject("water", "https://a", tmp_path)
    assert [e.url for e in load_library("water", tmp_path)] == ["https://b"]


def test_cli_approve_reject_and_errors(tmp_path):
    save_library("water", [_entry("https://a")], tmp_path)
    run = lambda *a: CliRunner().invoke(authority_library_app, [*a, "--root", str(tmp_path)])  # noqa: E731
    assert run("approve", "--theme", "water", "--url", "https://a").exit_code == 0
    assert load_library("water", tmp_path)[0].status == "approved"
    r = run("approve", "--theme", "water", "--url", "https://nope")
    assert r.exit_code == 1 and "https://nope" in r.output
    assert run("reject", "--theme", "water", "--url", "https://a").exit_code == 0
    assert load_library("water", tmp_path) == []


def test_unknown_theme_rejected(tmp_path):
    r = CliRunner().invoke(authority_library_app, ["approve", "--theme", "bogus", "--url", "u", "--root", str(tmp_path)])
    assert r.exit_code == 1 and all(k in r.output for k in THEME_KEYS)
