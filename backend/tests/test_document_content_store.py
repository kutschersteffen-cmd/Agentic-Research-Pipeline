import json
import sqlite3
import threading
import time

import numpy as np
import pytest

from arp.storage.document_store import DocumentContentStore, derive_doc_id
from arp.storage.parsed_content_cache import ParsedContentCache
from arp.storage.safe_path import UnsafeIdentifierError


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_get_or_parse_calls_parse_once_on_repeat(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_path = _write(tmp_path, "a.pdf", b"hello world")
    calls = []

    def parse(path):
        calls.append(path)
        return "extracted text", [0]

    a = store.get_or_parse(doc_path, parser_version="v1", parse=parse)
    b = store.get_or_parse(doc_path, parser_version="v1", parse=parse)

    assert len(calls) == 1
    assert a.full_text == b.full_text == "extracted text"
    assert a.page_breaks == b.page_breaks == [0]
    assert a.content_key == b.content_key


def test_changed_file_bytes_reparse(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_path = _write(tmp_path, "a.pdf", b"version one")
    calls = []

    def parse(path):
        calls.append(1)
        return path.read_bytes().decode(), []

    store.get_or_parse(doc_path, parser_version="v1", parse=parse)
    doc_path.write_bytes(b"version two, different content")
    import os
    import time

    time.sleep(0.01)
    os.utime(doc_path, None)  # bump mtime past the stat fast path too
    store.get_or_parse(doc_path, parser_version="v1", parse=parse)

    assert len(calls) == 2


def test_changed_parser_version_orphans_and_reparses(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_path = _write(tmp_path, "a.pdf", b"hello world")
    calls = []

    def parse(path):
        calls.append(1)
        return "text", []

    store.get_or_parse(doc_path, parser_version="v1", parse=parse)
    store.get_or_parse(doc_path, parser_version="v2", parse=parse)

    assert len(calls) == 2
    assert store.stats()["cached_documents"] == 2
    assert store.stats()["distinct_parser_versions"] == 2


def test_page_breaks_round_trip_exactly(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_path = _write(tmp_path, "a.pdf", b"hello")

    result = store.get_or_parse(doc_path, parser_version="v1", parse=lambda p: ("page one\n\npage two", [0, 10]))
    again = store.get_or_parse(doc_path, parser_version="v1", parse=lambda p: (_ for _ in ()).throw(AssertionError("should not reparse")))

    assert result.page_breaks == [0, 10]
    assert again.page_breaks == [0, 10]


def test_empty_page_breaks_round_trip(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_path = _write(tmp_path, "a.html", b"hello")

    result = store.get_or_parse(doc_path, parser_version="v1", parse=lambda p: ("some html text", []))
    assert result.page_breaks == []


def test_corrupt_row_is_a_miss_not_an_error(tmp_path):
    store_dir = tmp_path / "store"
    store = DocumentContentStore(store_dir)
    doc_path = _write(tmp_path, "a.pdf", b"hello world")
    content_key = store.content_key_for_file(doc_path)

    # Inject a corrupt row directly, bypassing the store's own writer.
    conn = sqlite3.connect(store_dir / "content.db")
    conn.execute(
        "INSERT INTO parsed_content (content_key, key_kind, parser_version, source_suffix, full_text, "
        "page_breaks, text_sha256, char_len, byte_size, created_at) VALUES (?, 'file_bytes', 'v1', '.pdf', "
        "'stale text', 'not valid json', 'x', 4, 4, 'now')",
        (content_key,),
    )
    conn.commit()
    conn.close()

    calls = []

    def parse(path):
        calls.append(1)
        return "fresh text", [0]

    result = store.get_or_parse(doc_path, parser_version="v1", parse=parse)

    assert len(calls) == 1
    assert result.full_text == "fresh text"


def test_identical_bytes_at_two_paths_share_one_parse(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    path_a = _write(tmp_path, "a.pdf", b"identical content")
    path_b = _write(tmp_path, "b.pdf", b"identical content")
    calls = []

    def parse(path):
        calls.append(path)
        return "shared text", []

    a = store.get_or_parse(path_a, parser_version="v1", parse=parse)
    b = store.get_or_parse(path_b, parser_version="v1", parse=parse)

    assert len(calls) == 1
    assert a.content_key == b.content_key
    assert a.full_text == b.full_text


def test_stat_fast_path_avoids_rehashing(tmp_path, monkeypatch):
    store = DocumentContentStore(tmp_path / "store")
    doc_path = _write(tmp_path, "a.pdf", b"hello world")

    store.content_key_for_file(doc_path)  # first call: hashes and caches the stat triple

    hash_calls = []
    original = ParsedContentCache._hash_file_bytes

    def counting_hash(path):
        hash_calls.append(1)
        return original(path)

    monkeypatch.setattr(ParsedContentCache, "_hash_file_bytes", staticmethod(counting_hash))
    store.content_key_for_file(doc_path)  # second call: same stat triple, should skip hashing

    assert hash_calls == []


def test_register_document_traversal_rejected(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    with pytest.raises(UnsafeIdentifierError):
        store.register_document(
            doc_id="doc_x",
            company_id="../../../../etc/cron.d",
            doc_type="10-K",
            content_key="abc",
            title="t",
            local_path=None,
            source_url=None,
        )
    # nothing outside the store's own dir was created or written
    assert not (tmp_path / "etc").exists()


def test_register_document_collision_falls_back_to_a_fresh_id(tmp_path, caplog):
    store = DocumentContentStore(tmp_path / "store")
    doc_id = derive_doc_id("acme", "10-K", "content_a")

    first = store.register_document(
        doc_id=doc_id, company_id="acme", doc_type="10-K", content_key="content_a",
        title="Report A", local_path=None, source_url=None,
    )
    # Force a collision: same doc_id, but a different (company_id, content_key).
    second = store.register_document(
        doc_id=doc_id, company_id="other_co", doc_type="10-K", content_key="content_b",
        title="Report B", local_path=None, source_url=None,
    )

    assert first == doc_id
    assert second != doc_id
    assert store.resolve_document(doc_id).company_id == "acme"
    assert store.resolve_document(second).company_id == "other_co"


def test_resolve_document_round_trip(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_id = derive_doc_id("acme", "10-K", "abc")
    store.register_document(
        doc_id=doc_id, company_id="acme", doc_type="10-K", content_key="abc",
        title="Annual Report", local_path="/x/y.pdf", source_url=None,
    )

    ref = store.resolve_document(doc_id)
    assert ref is not None
    assert ref.company_id == "acme"
    assert ref.title == "Annual Report"
    assert store.resolve_document("doc_nonexistent") is None


def test_disabled_store_never_persists(tmp_path):
    store_dir = tmp_path / "store"
    store = DocumentContentStore(store_dir, enabled=False)
    doc_path = _write(tmp_path, "a.pdf", b"hello world")

    assert not store_dir.exists()

    calls = []

    def parse(path):
        calls.append(1)
        return "text", []

    store.get_or_parse(doc_path, parser_version="v1", parse=parse)
    store.get_or_parse(doc_path, parser_version="v1", parse=parse)

    assert len(calls) == 2  # no caching -- reparses every time
    assert not store_dir.exists()


def test_concurrent_get_or_parse_agree_and_do_not_corrupt_the_row(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_path = _write(tmp_path, "a.pdf", b"hello world")

    def slow_parse(path):
        time.sleep(0.02)
        return "the parsed text", [0]

    results: list = []
    errors: list[Exception] = []

    def worker():
        try:
            results.append(store.get_or_parse(doc_path, parser_version="v1", parse=slow_parse))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 10
    assert all(r.full_text == "the parsed text" for r in results)
    assert all(r.content_key == results[0].content_key for r in results)
    assert store.stats()["cached_documents"] == 1  # exactly one row, no duplicate/corrupt insert


def test_prune_removes_only_stale_parser_versions(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    doc_a = _write(tmp_path, "a.pdf", b"aaa")
    doc_b = _write(tmp_path, "b.pdf", b"bbb")
    store.get_or_parse(doc_a, parser_version="v1", parse=lambda p: ("old", []))
    store.get_or_parse(doc_b, parser_version="v2", parse=lambda p: ("new", []))
    id_a = derive_doc_id("acme", "10-K", store.content_key_for_file(doc_a))
    store.register_document(doc_id=id_a, company_id="acme", doc_type="10-K", content_key=store.content_key_for_file(doc_a), title="t", local_path=None, source_url=None)

    deleted = store.prune(keep_parser_version="v2")

    assert deleted == 1
    stats = store.stats()
    assert stats["cached_documents"] == 1
    assert stats["distinct_parser_versions"] == 1
    # documents directory rows are untouched by prune -- citations must
    # keep resolving even after a parser upgrade prunes the old text.
    assert stats["registered_documents"] == 1


def test_prune_accepts_a_list_and_keeps_every_version_in_it(tmp_path):
    """The table holds rows from more than one producer once EDGAR shares
    it (key_kind='edgar_accession') -- pruning after only the local
    parser upgrades must not delete EDGAR's still-current rows just
    because their version string differs."""
    store = DocumentContentStore(tmp_path / "store")
    doc_a = _write(tmp_path, "a.pdf", b"aaa")
    doc_b = _write(tmp_path, "b.pdf", b"bbb")
    doc_c = _write(tmp_path, "c.pdf", b"ccc")
    store.get_or_parse(doc_a, parser_version="local-v1", parse=lambda p: ("old", []))
    store.get_or_parse(doc_b, parser_version="local-v2", parse=lambda p: ("new", []))
    store.get_or_parse(doc_c, parser_version="edgar-v1", parse=lambda p: ("edgar text", []))

    deleted = store.prune(keep_parser_version=["local-v2", "edgar-v1"])

    assert deleted == 1
    assert store.stats()["distinct_parser_versions"] == 2


def test_embeddings_round_trip(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    assert store.lookup_embeddings(["chk_a"], "model-x") == {}

    store.store_embeddings({"chk_a": vec}, "model-x")
    found = store.lookup_embeddings(["chk_a", "chk_b"], "model-x")

    assert set(found) == {"chk_a"}
    assert np.allclose(found["chk_a"], vec)


def test_embeddings_are_scoped_by_embed_model(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    store.store_embeddings({"chk_a": np.array([1.0, 2.0], dtype=np.float32)}, "model-x")

    assert store.lookup_embeddings(["chk_a"], "model-y") == {}


def test_embeddings_batch_lookup_returns_only_the_hit_subset(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    store.store_embeddings(
        {"chk_a": np.array([1.0], dtype=np.float32), "chk_b": np.array([2.0], dtype=np.float32)}, "model-x"
    )
    found = store.lookup_embeddings(["chk_a", "chk_b", "chk_c"], "model-x")
    assert set(found) == {"chk_a", "chk_b"}


def test_disabled_store_never_persists_embeddings(tmp_path):
    store = DocumentContentStore(tmp_path / "store", enabled=False)
    store.store_embeddings({"chk_a": np.array([1.0], dtype=np.float32)}, "model-x")
    assert store.lookup_embeddings(["chk_a"], "model-x") == {}


def test_list_cached_content_paginates_newest_first(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    for i in range(3):
        store.store(f"key{i}", key_kind="file_bytes", parser_version="v1", source_suffix=".pdf", byte_size=10, text=f"text{i}", page_breaks=[])
        time.sleep(0.01)  # created_at has second resolution in some environments; keep insert order distinguishable

    page1, total = store.list_cached_content(0, 2)
    page2, total2 = store.list_cached_content(2, 2)

    assert total == total2 == 3
    assert len(page1) == 2
    assert len(page2) == 1
    # newest-first: key2 (inserted last) should appear before key0 (inserted first)
    all_keys = [row["content_key"] for row in page1 + page2]
    assert all_keys.index("key2") < all_keys.index("key0")


def test_list_cached_content_excludes_full_text(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    store.store("key1", key_kind="file_bytes", parser_version="v1", source_suffix=".pdf", byte_size=10, text="the full text", page_breaks=[])

    rows, _ = store.list_cached_content(0, 10)

    assert "full_text" not in rows[0]
    assert rows[0]["char_len"] == len("the full text")


def test_get_cached_text_round_trips_by_row_id(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    store.store("key1", key_kind="file_bytes", parser_version="v1", source_suffix=".pdf", byte_size=10, text="hello", page_breaks=[0])
    rows, _ = store.list_cached_content(0, 10)
    row_id = rows[0]["id"]

    content = store.get_cached_text(row_id)

    assert content is not None
    assert content.full_text == "hello"
    assert content.page_breaks == [0]
    assert content.content_key == "key1"


def test_get_cached_text_missing_row_returns_none(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    assert store.get_cached_text(999) is None


def test_list_documents_by_content_keys_batch_lookup(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    store.register_document(
        doc_id=derive_doc_id("acme", "10-K", "key_a"), company_id="acme", doc_type="10-K",
        content_key="key_a", title="Acme 10-K", local_path="/docs/acme/10-K/acme.pdf", source_url=None,
    )
    store.register_document(
        doc_id=derive_doc_id("beta", "10-K", "key_b"), company_id="beta", doc_type="10-K",
        content_key="key_b", title="Beta 10-K", local_path=None, source_url=None,
    )

    refs = store.list_documents_by_content_keys(["key_a", "key_b", "key_missing"])

    assert set(refs) == {"key_a", "key_b"}
    assert refs["key_a"].company_id == "acme"
    assert refs["key_b"].local_path is None


def test_list_documents_by_content_keys_empty_input(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    assert store.list_documents_by_content_keys([]) == {}


def test_lookup_and_store_agree_with_get_or_compute(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    assert store.lookup("key1", "v1") is None

    stored = store.store(
        "key1", key_kind="file_bytes", parser_version="v1", source_suffix=".pdf", byte_size=10,
        text="hello", page_breaks=[0],
    )
    found = store.lookup("key1", "v1")

    assert found is not None
    assert found.full_text == stored.full_text == "hello"
    assert found.page_breaks == [0]
