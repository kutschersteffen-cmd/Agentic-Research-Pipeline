import asyncio

import pytest

from arp.discovery.site_finder import SearchResult
from arp.research.authority_taxonomy import discovery
from arp.research.authority_taxonomy.discovery import _CandidateDraft, _GuidanceDraft, discover_candidates
from arp.research.authority_taxonomy.library import LibraryEntry, save_library
from tests.conftest import FakeLLMClient, FakeSearchClient


def _draft(reason="Official source."):
    return _CandidateDraft(summary="Fetched summary.", reason=reason, source_type="agency_report", covers=["electrolysers"])


def _patch_fetch(monkeypatch, texts):
    async def fake_fetch(url, user_agent, timeout=20.0, max_chars=0):
        return texts.get(url)

    monkeypatch.setattr(discovery, "fetch_source_text", fake_fetch)


def _run(**kw):
    kw.setdefault("theme_key", None)
    kw.setdefault("guidance", "")
    return asyncio.run(discover_candidates("Hydrogen", user_agent="t", **kw))


def test_unfetchable_candidate(monkeypatch):
    _patch_fetch(monkeypatch, {})
    search = FakeSearchClient({"taxonomy": [SearchResult(title="T", url="https://iea.org/u", snippet="Snippet S")]})
    llm = FakeLLMClient({"_CandidateDraft": [_draft()]})
    [c] = _run(search_client=search, llm=llm)
    assert (c.url, c.fetchable, c.summary, c.from_library) == ("https://iea.org/u", False, "Snippet S", False)
    assert c.reason


def _entry(url, status):
    return LibraryEntry(url=url, title=url, source_type="agency_report", summary="s", covers=[], fetchable=True, status=status)


def test_library_first(monkeypatch, tmp_path):
    save_library("hydrogen", [_entry("https://a.org/A", "approved"), _entry("https://p.org/P", "proposed")], root=tmp_path)
    _patch_fetch(monkeypatch, {"https://web.org/w": "text"})
    search = FakeSearchClient({"taxonomy": [SearchResult(title="W", url="https://web.org/w", snippet="")]})
    llm = FakeLLMClient({"_CandidateDraft": [_draft()]})
    cands = _run(theme_key="hydrogen", search_client=search, llm=llm, library_root=tmp_path)
    assert cands[0].url == "https://a.org/A" and cands[0].from_library
    assert [c.url for c in cands] == ["https://a.org/A", "https://web.org/w"]


def test_proposed_not_listed(monkeypatch, tmp_path):
    save_library("hydrogen", [_entry("https://a.org/A", "approved"), _entry("https://p.org/P", "proposed")], root=tmp_path)
    _patch_fetch(monkeypatch, {})
    cands = _run(theme_key="hydrogen", search_client=FakeSearchClient({}), llm=FakeLLMClient({}), library_root=tmp_path)
    assert "https://p.org/P" not in [c.url for c in cands]


def test_guidance_filters_hosts(monkeypatch):
    _patch_fetch(monkeypatch, {})
    search = FakeSearchClient(
        {
            "taxonomy": [
                SearchResult(title="EU", url="https://ec.europa.eu/x", snippet="eu"),
                SearchResult(title="IEA", url="https://www.iea.org/y", snippet="iea"),
            ]
        }
    )
    llm = FakeLLMClient({"_GuidanceDraft": [_GuidanceDraft(allowed_hosts=["europa.eu"])], "_CandidateDraft": [_draft()]})
    cands = _run(guidance="EU Taxonomy only", search_client=search, llm=llm)
    assert [c.url for c in cands] == ["https://ec.europa.eu/x"]


def test_pdf_without_text_is_unfetchable(monkeypatch):
    # fetch_source_text returns None for a PDF with no extractable text
    _patch_fetch(monkeypatch, {"https://iea.org/r.pdf": None})
    search = FakeSearchClient({"taxonomy": [SearchResult(title="PDF", url="https://iea.org/r.pdf", snippet="pdf snip")]})
    llm = FakeLLMClient({"_CandidateDraft": [_draft()]})
    [c] = _run(search_client=search, llm=llm)
    assert not c.fetchable and c.summary == "pdf snip"


@pytest.mark.parametrize("theme_key", ["nonsense", None])
def test_unknown_theme_key_web_only(monkeypatch, tmp_path, theme_key):
    _patch_fetch(monkeypatch, {"https://web.org/w": "text"})
    search = FakeSearchClient({"taxonomy": [SearchResult(title="W", url="https://web.org/w", snippet="")]})
    llm = FakeLLMClient({"_CandidateDraft": [_draft()]})
    cands = _run(theme_key=theme_key, search_client=search, llm=llm, library_root=tmp_path)
    assert [(c.url, c.from_library, c.fetchable) for c in cands] == [("https://web.org/w", False, True)]


def test_library_rejects_unknown_theme_key(tmp_path):
    from arp.research.authority_taxonomy.library import load_library

    assert load_library("../x", root=tmp_path) == []
    with pytest.raises(ValueError):
        save_library("../x", [], root=tmp_path)
    assert not list(tmp_path.parent.glob("x.json"))


def test_library_summary_truncated(monkeypatch, tmp_path):
    e = _entry("https://a.org/A", "approved").model_copy(update={"summary": "w " * 100})
    save_library("hydrogen", [e], root=tmp_path)
    [c] = _run(theme_key="hydrogen", search_client=FakeSearchClient({}), llm=FakeLLMClient({}), library_root=tmp_path)
    assert len(c.summary.split()) == 80


def test_fetch_max_chars(monkeypatch):
    seen = []

    async def fake_fetch(url, user_agent, timeout=20.0, max_chars=0):
        seen.append(max_chars)
        return "text"

    monkeypatch.setattr(discovery, "fetch_source_text", fake_fetch)
    search = FakeSearchClient({"taxonomy": [SearchResult(title="W", url="https://web.org/w", snippet="")]})
    _run(search_client=search, llm=FakeLLMClient({"_CandidateDraft": [_draft()]}))
    assert seen == [400_000]


def test_failures_do_not_abort(monkeypatch):
    async def fake_fetch(url, user_agent, timeout=20.0, max_chars=0):
        raise RuntimeError("boom")

    monkeypatch.setattr(discovery, "fetch_source_text", fake_fetch)
    urls = ["https://a.org/1", "https://b.org/2"]
    search = FakeSearchClient({"taxonomy": [SearchResult(title=u, url=u, snippet="s") for u in urls]})
    llm = FakeLLMClient({"_CandidateDraft": [_draft()]})  # second call raises: no response left
    cands = _run(search_client=search, llm=llm)
    assert [(c.url, c.fetchable) for c in cands] == [("https://a.org/1", False)]


@pytest.mark.parametrize("host", ["*.europa.eu", "https://europa.eu/", "EUROPA.EU"])
def test_allowed_host_normalised(monkeypatch, host):
    _patch_fetch(monkeypatch, {})
    search = FakeSearchClient({"taxonomy": [SearchResult(title="EU", url="https://ec.europa.eu/x", snippet="eu")]})
    llm = FakeLLMClient({"_GuidanceDraft": [_GuidanceDraft(allowed_hosts=[host])], "_CandidateDraft": [_draft()]})
    assert [c.url for c in _run(guidance="EU only", search_client=search, llm=llm)] == ["https://ec.europa.eu/x"]
