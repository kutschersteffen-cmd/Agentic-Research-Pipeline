from __future__ import annotations

import json

import pytest

from arp.portfolio.news.text_pull import _story_body, pull_news_text
from arp.schemas.issuer import IdentifierMap
from arp.signal_lab.text_store import TextStore
from arp.storage.identifier_map import IdentifierMapStore
from tests.test_news_api_source import PERMID_A, PERMID_B, PERMID_C, SETTINGS, TOKEN, page, story

T1, T2 = "2026-10-06T00:00:00Z", "2026-10-08T00:00:00Z"


def headline(sid, title, revised, *qcodes):
    s = story(sid, title, revised, *qcodes)
    s["newsItem"]["itemMeta"]["firstCreated"] = {"$": "2026-10-01T09:00:00Z"}
    return s


def body(html: str) -> bytes:
    return json.dumps({"newsItem": {"contentSet": {"inlineXML": [{"$": html}]}}}).encode()


def rdp(headlines: bytes, bodies: dict, stories_calls: list):
    def fetch(url, headers, form):
        if form is not None:
            return TOKEN
        if "/stories/" in url:
            stories_calls.append(url)
            return bodies[url.rsplit("/", 1)[1]]
        return headlines
    return fetch


@pytest.fixture
def idmap(tmp_path):
    m = IdentifierMapStore(tmp_path / "idmap.jsonl")
    m.add(IdentifierMap(issuer_key="ISS-1", scheme="PERMID", value=PERMID_A))
    m.add(IdentifierMap(issuer_key="ISS-2", scheme="PERMID", value=PERMID_B))
    return m


def test_story_with_two_issuers_gives_two_records(pg, idmap):
    store, calls = TextStore(pg), []
    f = rdp(page(headline("s1", "Merger", "2026-10-01T09:00:00Z", f"P:{PERMID_A}", f"P:{PERMID_B}")), {"s1": body("<p>Deal.</p>")}, calls)
    out = pull_news_text(store, SETTINGS, idmap, fetcher=f, now=T1)
    assert out == {"stories": 1, "records": 2, "unmatched": 0}
    recs = store.items()
    assert {(r.source, r.source_item_id, r.company_id) for r in recs} == {
        ("tr_news", "s1:ISS-1", "ISS-1"), ("tr_news", "s1:ISS-2", "ISS-2")}
    assert all(r.event_time == "2026-10-01T09:00:00Z" and r.knowledge_time == T1 and r.title == "Merger" for r in recs)
    assert len(calls) == 1 and calls[0] == "https://rdp.example/data/news/v1/stories/s1"


def test_story_with_no_issuer_gives_one_unlinked_record(pg, idmap):
    store = TextStore(pg)
    f = rdp(page(headline("s3", "Unknown", "2026-10-01T09:00:00Z", f"P:{PERMID_C}")), {"s3": body("<p>x</p>")}, [])
    assert pull_news_text(store, SETTINGS, idmap, fetcher=f, now=T1) == {"stories": 1, "records": 1, "unmatched": 1}
    [r] = store.items()
    assert r.company_id is None and r.source_item_id == "s3"


def test_rerun_adds_nothing_and_fetches_no_body(pg, idmap):
    store, calls = TextStore(pg), []
    f = rdp(page(headline("s1", "Fined", "2026-10-01T09:00:00Z", f"P:{PERMID_A}")), {"s1": body("<p>x</p>")}, calls)
    pull_news_text(store, SETTINGS, idmap, fetcher=f, now=T1)
    calls.clear()
    out = pull_news_text(store, SETTINGS, idmap, fetcher=f, now=T2)
    assert calls == [] and out["records"] == 0 and len(store.items()) == 1


def test_revised_story_is_a_new_version(pg, idmap):
    store = TextStore(pg)
    h = lambda v: page(headline("s1", "Fined", v, f"P:{PERMID_A}"))  # noqa: E731
    pull_news_text(store, SETTINGS, idmap, fetcher=rdp(h("2026-10-01T09:00:00Z"), {"s1": body("<p>old text</p>")}, []), now=T1)
    out = pull_news_text(store, SETTINGS, idmap, fetcher=rdp(h("2026-10-07T09:00:00Z"), {"s1": body("<p>new text</p>")}, []), now=T2)
    assert out["records"] == 1
    new, old = store.items(), store.items(known_by="2026-10-07T00:00:00Z")
    assert "new text" in new[0].body and "old text" in old[0].body
    assert new[0].event_time == old[0].event_time and new[0].revision_time == "2026-10-07T09:00:00Z"


def test_html_body_becomes_text():
    text = _story_body(body("<html><body><p>Hello <b>world</b>.</p><p>Second paragraph here.</p></body></html>"))
    assert "Second paragraph here." in text and "Hello" in text and "<" not in text


@pytest.mark.parametrize("data", [b"not json", b"{}", json.dumps({"newsItem": {"contentSet": {"inlineXML": []}}}).encode()])
def test_unexpected_story_shape_raises_value_error(data):
    with pytest.raises(ValueError, match="unexpected Refinitiv story response"):
        _story_body(data)


def test_missing_credentials_raises_without_leaking(pg, idmap):
    from arp.config import Settings

    with pytest.raises(ValueError, match="not configured") as e:
        pull_news_text(TextStore(pg), Settings(news_api_client_id="cid-123"), idmap, fetcher=rdp(b"", {}, []))
    assert "cid-123" not in str(e.value)
    with pytest.raises(ValueError, match="no PermIDs"):
        pull_news_text(TextStore(pg), SETTINGS, IdentifierMapStore(idmap.path.with_name("e.jsonl")), fetcher=rdp(b"", {}, []))
