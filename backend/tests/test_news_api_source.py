from __future__ import annotations

import json
from datetime import date

import pytest

from arp.config import Settings
from arp.portfolio import feeds
from arp.portfolio.news.api_source import pull_news
from arp.schemas.issuer import IdentifierMap
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore

ISIN, LEI = "US0378331005", "5493001KJTIIGC8Y1R12"
SETTINGS = Settings(news_api_url="https://news.example/api/", news_api_token="secret-token")


def articles(*rows: dict) -> bytes:
    return json.dumps({"articles": list(rows)}).encode()


@pytest.fixture
def env(tmp_path):
    idmap = IdentifierMapStore(tmp_path / "idmap.jsonl")
    idmap.add(IdentifierMap(issuer_key="ISS-1", scheme="ISIN", value=ISIN))
    idmap.add(IdentifierMap(issuer_key="ISS-2", scheme="LEI", value=LEI))
    return PortfolioStore(tmp_path / "pf"), idmap


def test_articles_are_tied_to_issuers_by_exact_identifier_only(env):
    store, idmap = env
    calls = []

    def fetch(url, headers):
        calls.append((url, headers))
        return articles(
            {"id": "a1", "headline": "Apple fined", "excerpt": "...", "published_at": "2026-10-01", "isin": ISIN},
            {"id": "a2", "headline": "Lender news", "published_at": "2026-10-02", "lei": LEI.lower()},
            {"id": "a3", "headline": "Apple Inc mentioned by name only", "published_at": "2026-10-03"},
            {"id": "", "headline": "no id: skipped", "published_at": "2026-10-03"},
        )

    out = pull_news(store, SETTINGS, idmap, fetcher=fetch, today=date(2026, 10, 6))
    assert out == {"added": 3, "unmatched": 1, "received": 4}
    assert {n.news_id: n.company_id for n in store.list_news()} == {"news:a1": "ISS-1", "news:a2": "ISS-2", "news:a3": None}
    assert calls[0][0] == "https://news.example/api/articles" and calls[0][1]["Authorization"] == "Bearer secret-token"
    # The next pull asks only for what is new and never stores an article twice.
    out = pull_news(store, SETTINGS, idmap, fetcher=fetch, today=date(2026, 10, 6))
    assert out["added"] == 0 and calls[1][0].endswith("?since=2026-10-03")
    row = next(r for r in feeds.overview(store, idmap, date(2026, 10, 6)) if r["feed"] == "news")
    assert row["last_load"]["status"] == "ok" and row["as_of"] == "2026-10-03"


def test_a_bad_response_records_a_failed_load_without_the_token(env):
    store, idmap = env
    with pytest.raises(ValueError):
        pull_news(store, SETTINGS, idmap, fetcher=lambda url, h: b"<html>", today=date(2026, 10, 6))
    row = next(r for r in feeds.overview(store, idmap, date(2026, 10, 6)) if r["feed"] == "news")
    assert row["last_load"]["status"] == "failed" and "secret" not in row["last_load"]["detail"]
    assert store.list_news() == []


def test_unconfigured_pull_is_refused(env):
    store, idmap = env
    with pytest.raises(ValueError, match="not configured"):
        pull_news(store, Settings(), idmap, fetcher=lambda u, h: b"")


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
        monkeypatch.setattr(api_source, "_http_fetch", lambda url, h: articles(
            {"id": "a1", "headline": "Apple fined", "published_at": "2026-10-01", "isin": ISIN}))
        r = c.post("/api/feeds/news/pull")
        assert r.status_code == 200 and r.json()["added"] == 1, r.text
        monkeypatch.setattr(api_source, "_http_fetch", lambda url, h: b"not json")
        assert c.post("/api/feeds/news/pull").status_code == 502
    finally:
        app.dependency_overrides.clear()
