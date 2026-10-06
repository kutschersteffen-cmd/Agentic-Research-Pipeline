from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from arp.config import Settings
from arp.portfolio import feeds
from arp.portfolio.news.api_source import pull_news
from arp.schemas.issuer import IdentifierMap
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore

PERMID_A, PERMID_B, PERMID_C = "4295905573", "4295907168", "5000000001"
SETTINGS = Settings(news_api_url="https://rdp.example/", news_api_client_id="cid", news_api_client_secret="secret-key")
TOKEN = json.dumps({"access_token": "tok", "expires_in": 600}).encode()


def story(sid: str, title: str, when: str, *qcodes: str) -> dict:
    return {"storyId": sid, "newsItem": {"itemMeta": {"title": [{"$": title}], "versionCreated": {"$": when}},
                                         "contentMeta": {"subject": [{"_qcode": q} for q in ("G:1", *qcodes)]}}}


def page(*stories: dict, next_cursor: str | None = None) -> bytes:
    return json.dumps({"data": list(stories), "meta": {"count": len(stories), **({"next": next_cursor} if next_cursor else {})}}).encode()


@pytest.fixture
def env(tmp_path):
    idmap = IdentifierMapStore(tmp_path / "idmap.jsonl")
    idmap.add(IdentifierMap(issuer_key="ISS-1", scheme="PERMID", value=PERMID_A))
    idmap.add(IdentifierMap(issuer_key="ISS-2", scheme="PERMID", value=PERMID_B))
    idmap.add(IdentifierMap(issuer_key="ISS-3", scheme="ISIN", value="US0378331005"))
    return PortfolioStore(tmp_path / "pf"), idmap


def rdp(pages: list[bytes], calls: list):
    def fetch(url, headers, form):
        calls.append((url, headers, form))
        return TOKEN if form is not None else pages.pop(0)
    return fetch


def test_stories_are_tied_to_issuers_by_permid_only(env):
    store, idmap = env
    calls: list = []
    pages = [
        page(story("s1", "Vodafone fined", "2026-10-01T09:00:00Z", f"P:{PERMID_A}", "R:VOD.L"),
             story("s2", "Two holdings merge", "2026-10-02T09:00:00Z", f"P:{PERMID_A}", f"P:{PERMID_B}"), next_cursor="c2"),
        page(story("s3", "Unknown PermID only", "2026-10-03T09:00:00Z", f"P:{PERMID_C}")),
    ]
    out = pull_news(store, SETTINGS, idmap, fetcher=rdp(pages, calls), today=date(2026, 10, 6))
    assert out == {"added": 3, "unmatched": 1, "received": 3}
    assert {n.news_id: n.company_id for n in store.list_news()} == {
        "news:s1:ISS-1": "ISS-1", "news:s2:ISS-1": "ISS-1", "news:s2:ISS-2": "ISS-2", "news:s3": None}
    token_url, _, form = calls[0]
    assert token_url == "https://rdp.example/auth/oauth2/v2/token" and form["client_secret"] == "secret-key"
    first = urlparse(calls[1][0])
    assert first.path == "/data/news/v1/headlines" and calls[1][1]["Authorization"] == "Bearer tok"
    assert parse_qs(first.query)["query"] == [f"P:{PERMID_A} OR P:{PERMID_B}"]  # only master PermIDs are asked for
    assert parse_qs(urlparse(calls[2][0]).query) == {"cursor": ["c2"]}
    # The next pull asks only for what is new and never stores a story twice.
    calls.clear()
    pages = [page(story("s3", "Unknown PermID only", "2026-10-03T09:00:00Z", f"P:{PERMID_C}"))]
    out = pull_news(store, SETTINGS, idmap, fetcher=rdp(pages, calls), today=date(2026, 10, 6))
    assert out["added"] == 0 and parse_qs(urlparse(calls[1][0]).query)["dateFrom"] == ["2026-10-03T00:00:00Z"]
    row = next(r for r in feeds.overview(store, idmap, date(2026, 10, 6)) if r["feed"] == "news")
    assert row["last_load"]["status"] == "ok" and row["as_of"] == "2026-10-03"


def test_a_bad_response_records_a_failed_load_without_the_secret(env):
    store, idmap = env
    with pytest.raises(ValueError):
        pull_news(store, SETTINGS, idmap, fetcher=rdp([b"<html>"], []), today=date(2026, 10, 6))
    row = next(r for r in feeds.overview(store, idmap, date(2026, 10, 6)) if r["feed"] == "news")
    assert row["last_load"]["status"] == "failed" and "secret" not in row["last_load"]["detail"]
    assert store.list_news() == []


def test_unconfigured_or_no_permids_is_refused(env, tmp_path):
    store, idmap = env
    with pytest.raises(ValueError, match="not configured"):
        pull_news(store, Settings(), idmap, fetcher=rdp([], []))
    with pytest.raises(ValueError, match="no PermIDs"):
        pull_news(store, SETTINGS, IdentifierMapStore(tmp_path / "empty.jsonl"), fetcher=rdp([], []))


def test_feeds_pull_routes(env, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from arp.api.auth import current_user
    from arp.api.deps import get_portfolio_store, settings_dep
    from arp.api.main import app
    from arp.portfolio.news import api_source
    from tests.conftest import PRINCIPAL

    store, idmap = env
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    try:
        app.dependency_overrides[settings_dep] = lambda: Settings(identifier_map_path=idmap.path)
        c = TestClient(app)
        assert c.post("/api/feeds/news/pull").status_code == 503
        assert c.post("/api/feeds/esg/pull").status_code == 503
        app.dependency_overrides[settings_dep] = lambda: SETTINGS.model_copy(update={"identifier_map_path": idmap.path})
        monkeypatch.setattr(api_source, "_http_fetch", rdp([page(story("s1", "Fined", "2026-10-01T09:00:00Z", f"P:{PERMID_A}"))], []))
        r = c.post("/api/feeds/news/pull")
        assert r.status_code == 200 and r.json()["added"] == 1, r.text
        monkeypatch.setattr(api_source, "_http_fetch", rdp([b"not json"], []))
        assert c.post("/api/feeds/news/pull").status_code == 502
    finally:
        app.dependency_overrides.clear()
