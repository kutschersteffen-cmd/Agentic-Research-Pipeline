"""Theme Radar signal store, slice a (spec theme-radar-signal-store): store, dedupe, embeddings, full scan reads it."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import text

from arp.config import Settings
from arp.emerging_themes.ingestion.base import MentionSource
from arp.emerging_themes.pipeline import create_emerging_themes_run, execute_emerging_themes_run
from arp.emerging_themes.signal_store import SignalStore
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import MentionSourceType, RawMention, SignalSourceType
from arp.storage.postgres import get_engine
from arp.storage.run_store import RunStore
from arp.storage.topic_store import TopicStateStore

T0 = datetime(2000, 1, 1, tzinfo=UTC)


def item(u, t, x, s=MentionSourceType.GDELT, **kw):
    return RawMention(source_type=s, title=t, text=x, url=u, **kw)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture
def embedded(monkeypatch):
    calls: list[list[str]] = []

    def fake(texts):
        calls.append(list(texts))
        return np.ones((len(texts), 384), dtype=np.float32)

    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", fake)
    return calls


@pytest.fixture
def store(pg, embedded):
    return SignalStore(pg)


def _signal_embeddings(dsn):
    with get_engine(dsn).connect() as conn:
        return conn.execute(text("SELECT chunk_id, embed_model FROM chunk_embeddings WHERE chunk_id LIKE 'signal:%'")).all()


def test_add_items_dedupes_by_hash_and_moves_last_seen(store):
    assert store.add_items([item("https://a.example/1", "T1", "X1"), item("https://a.example/2", "T2", "X2")]) == 2
    assert {i.content_hash for i in store.read_items(since=T0)} == {
        sha("https://a.example/1\nT1\nX1"), sha("https://a.example/2\nT2\nX2")
    }
    assert store.add_items([item("https://a.example/1", "T1", "X1")], seen_at=datetime(2026, 11, 2, tzinfo=UTC)) == 0
    first = next(i for i in store.read_items(since=T0) if i.url == "https://a.example/1")
    assert first.last_seen_at == "2026-11-02T00:00:00+00:00" and first.first_seen_at != first.last_seen_at


def test_whitespace_is_normalised_but_text_counts(store):
    assert store.add_items([item("u", "Solar  cell", "A\n b "), item("u", " Solar cell", "A b")]) == 1
    assert store.add_items([item("v", "T", "X1"), item("v", "T", "X2")]) == 2


def test_source_types_window_and_filter(store):
    store.add_items([
        item("a", "A", "x", published_at="2026-11-10T00:00:00+00:00"),
        item("c", "C", "x", MentionSourceType.REGULATORY_RSS, published_at="2026-11-14T00:00:00+00:00"),
        item("d", "D", "x", MentionSourceType.EDGAR_FTS, published_at="2026-11-10"),
    ])
    store.add_items([item("b", "B", "x")], seen_at=datetime(2026, 11, 12, tzinfo=UTC))
    got = store.read_items(since=datetime(2026, 11, 10, tzinfo=UTC), until=datetime(2026, 11, 14, tzinfo=UTC))
    assert [i.content_hash for i in got[:2]] == sorted([sha("a\nA\nx"), sha("d\nD\nx")]) and got[2].title == "B"
    assert got[-1].item_at == "2026-11-12T00:00:00+00:00"
    assert {i.title: i.source_type for i in got} == {"A": "news", "D": "filings", "B": "news"}
    assert next(i for i in got if i.title == "D").published_at == "2026-11-10T00:00:00+00:00"
    regs = store.read_items(since=T0, source_types=[SignalSourceType.REGULATORS])
    assert [(i.title, i.source_type) for i in regs] == [("C", SignalSourceType.REGULATORS)]


def test_unparseable_published_at_is_null_and_estimated(store):
    store.add_items([item("a", "A", "x", published_at="yesterday")])
    (got,) = store.read_items(since=T0)
    assert got.published_at is None and got.published_at_is_estimated is True


def test_only_new_items_are_embedded(store, embedded, pg):
    store.add_items([item("u", "T", "X")])
    store.add_items([item("u", "T", "X")])
    assert embedded == [["T\nX"]]
    assert _signal_embeddings(pg) == [("signal:" + sha("u\nT\nX"), "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")]


def test_embedding_failure_keeps_items(pg, monkeypatch):
    def boom(texts):
        raise RuntimeError("no model")

    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", boom)
    store = SignalStore(pg)
    assert store.add_items([item("a", "A", "x"), item("b", "B", "x")]) == 2
    assert len(store.read_items(since=T0)) == 2 and _signal_embeddings(pg) == []


class _Source(MentionSource):
    name = "fixed"

    def __init__(self, mentions):
        self.mentions, self.calls = mentions, 0

    async def fetch(self, since):
        self.calls += 1
        return self.mentions


async def _scan(tmp_path, pg, store, source, *, fetch=True, **settings_kw):
    settings = Settings(runs_dir=tmp_path / "runs", emerging_themes_state_dir=tmp_path / "et", **settings_kw)
    run_store = RunStore(pg, settings.runs_dir)
    companies = [CompanyRef(company_id="acme", name="Acme")]
    run_id = create_emerging_themes_run(run_store, companies, "manual")
    await execute_emerging_themes_run(
        run_id, companies, llm=None, sources=[source], settings=settings, run_store=run_store,
        topic_store=TopicStateStore(tmp_path / "topics"), signal_store=store, fetch=fetch,
    )
    return [r["mention_id"] for r in run_store.read_jsonl(run_store.run_dir(run_id) / "mentions.jsonl")]


async def test_full_scan_stores_fetched_items_and_reads_them_back(tmp_path, pg, store, monkeypatch):
    async def no_tags(mention, llm):
        return [], None

    monkeypatch.setattr("arp.emerging_themes.pipeline.tag_mention", no_tags)
    source = _Source([item(f"https://n.example/{i}", "T", "X") for i in range(5)])
    ids = await _scan(tmp_path, pg, store, source)
    assert sorted(ids) == sorted(i.content_hash for i in store.read_items(since=T0)) and len(ids) == 5


async def test_full_scan_without_fetch_reads_the_window_up_to_the_cap(tmp_path, pg, store, monkeypatch):
    async def no_tags(mention, llm):
        return [], None

    monkeypatch.setattr("arp.emerging_themes.pipeline.tag_mention", no_tags)
    now = datetime.now(UTC)
    store.add_items([item(f"r{i}", "R", "x") for i in range(3)], seen_at=now - timedelta(days=1))
    store.add_items([item("old", "O", "x")], seen_at=now - timedelta(days=20))
    source = _Source([item("extra", "E", "x")])
    ids = await _scan(tmp_path, pg, store, source, fetch=False)
    assert source.calls == 0 and sorted(ids) == sorted(sha(f"r{i}\nR\nx") for i in range(3))

    store.add_items([item(f"p{d}", "P", "x", published_at=(now - timedelta(days=d)).isoformat()) for d in (4, 5)])
    ids = await _scan(tmp_path, pg, store, source, fetch=False, emerging_themes_full_scan_max_items=2)
    assert ids == sorted(sha(f"r{i}\nR\nx") for i in range(3))[:2]


def test_post_run_without_fetch_calls_no_source(pg, store, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from arp.api.deps import get_llm_client, get_signal_store, get_xbrl_source
    from arp.api.main import app
    from arp.api.routers import emerging_themes as router

    monkeypatch.setenv("ARP_EMERGING_THEMES_STATE_DIR", str(tmp_path / "et"))
    source = _Source([item("x", "X", "x")])
    tasks = []
    monkeypatch.setattr(router, "default_sources", lambda settings: [source])
    monkeypatch.setattr(router, "keep_task", tasks.append)
    app.dependency_overrides.update({get_signal_store: lambda: store, get_llm_client: lambda: None, get_xbrl_source: lambda: None})
    try:
        r = TestClient(app).post("/api/emerging-themes/runs", json={"companies": [{"company_id": "a", "name": "A"}], "fetch": False})
    finally:
        for dep in (get_signal_store, get_llm_client, get_xbrl_source):
            app.dependency_overrides.pop(dep, None)
    assert r.status_code == 200 and r.json()["run_id"]
    asyncio.run(tasks[0])
    assert source.calls == 0
