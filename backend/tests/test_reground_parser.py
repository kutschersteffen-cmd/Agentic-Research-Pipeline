from __future__ import annotations

import hashlib

import pytest

import arp.orchestration.reground as R
from arp.config import Settings
from arp.orchestration.reground import RegroundReport, reground_if_parser_changed, reground_runs
from arp.publish.gate import reground_citation
from arp.schemas.common import Citation, RunManifest
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore

ORIGINAL = b"original report bytes"
KEY = hashlib.sha256(ORIGINAL).hexdigest()
QUOTE = "Scope 1 emissions were 1,234 tonnes"
OLD_TEXT = "Header 01\n" + QUOTE + ".\nScope 2 emissions were 500 tonnes.\n"
START = OLD_TEXT.index(QUOTE)
ITEM = "ISS1:f1:2024-12-31"


def _citation(**kw) -> Citation:
    return Citation(**{
        "doc_id": "d1", "doc_type": "sustainability_report", "quote": QUOTE, "grounded": True,
        "content_key": KEY, "parser_version": "old", "span_text": QUOTE, "char_start": START,
        "char_end": START + len(QUOTE), "match_method": "exact", "source_filename": "report.txt", **kw,
    })


@pytest.fixture
def world(tmp_path, monkeypatch):
    run_store = RunStore(tmp_path / "runs")
    run_store.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    row = {
        "company_id": "c1", "name": "Co", "schema_id": "s1", "run_id": "ext1", "issuer_key": "ISS1",
        "issuer_scheme": "LEI",
        "fields": [{
            "field_id": "f1", "field_name": "Scope 1", "value": 1234.0, "confidence": 0.9, "grounded": True,
            "period_end": "2024-12-31", "citations": [_citation().model_dump(mode="json")],
        }],
        "documents": [{"doc_id": "d1", "content_key": KEY, "parser_version": "old"}],
    }
    run_store.append_jsonl(run_store.results_path("ext1"), row)
    blobs = LocalBlobStore(tmp_path / "blobs")
    blobs.put(KEY, ORIGINAL)
    texts = DocumentContentStore(tmp_path / "docs")
    texts.store(KEY, key_kind="file_bytes", parser_version="old", source_suffix=".txt", byte_size=1,
                text=OLD_TEXT, page_breaks=[])
    settings = Settings(publish_state_dir=tmp_path / "state")
    monkeypatch.setattr(R, "parser_version", lambda: "new")

    def new_parser(text):
        monkeypatch.setattr(R, "parse_file_to_text_with_pages", lambda path: (text, [], []))

    def run(**kw):
        return reground_runs(run_store, settings=settings, blob_store=blobs, content_store=texts, **kw)

    return run_store, run, new_parser, settings, blobs, texts


def _rows(run_store, name):
    return run_store.read_jsonl(run_store.run_dir("ext1") / name)


def test_parser_bump_moves_span_and_flags_it(world):
    run_store, run, new_parser, *_ = world
    before = run_store.results_path("ext1").read_bytes()
    new_parser("A new preface the upgraded parser now extracts.\n" + OLD_TEXT)
    report = run()
    assert report == RegroundReport(checked=1, unchanged=0, moved=1, lost=0, queued=1)
    [row] = _rows(run_store, "regrounds.jsonl")
    shift = len("A new preface the upgraded parser now extracts.\n")
    assert row["item_key"] == ITEM and row["doc_id"] == "d1" and row["outcome"] == "offset_moved"
    assert row["old"] == {"char_start": START, "char_end": START + len(QUOTE), "page": None, "parser_version": "old"}
    assert row["new"] == {"char_start": START + shift, "char_end": START + shift + len(QUOTE), "page": None,
                          "parser_version": "new"}
    [q] = _rows(run_store, "review_queue.jsonl")
    assert q["item_key"] == ITEM and "span_moved" in q["review_reasons"] and q["field_id"] == "f1"
    assert run_store.results_path("ext1").read_bytes() == before


def test_unchanged_span_not_queued(world):
    run_store, run, new_parser, *_ = world
    new_parser(OLD_TEXT)
    assert run() == RegroundReport(checked=1, unchanged=1, moved=0, lost=0, queued=0)
    assert [r["outcome"] for r in _rows(run_store, "regrounds.jsonl")] == ["ok"]
    assert _rows(run_store, "review_queue.jsonl") == []


def test_lost_quote_flagged_not_grounded(world):
    run_store, run, new_parser, *_ = world
    new_parser("Completely different text with nothing about it.\n")
    assert run() == RegroundReport(checked=1, unchanged=0, moved=0, lost=1, queued=1)
    [row] = _rows(run_store, "regrounds.jsonl")
    assert row["outcome"] == "not_grounded" and row["new"]["char_start"] is None
    [q] = _rows(run_store, "review_queue.jsonl")
    assert "span_moved" in q["review_reasons"]


def test_second_run_same_version_does_nothing(world):
    run_store, run, new_parser, *_ = world
    new_parser("Preface.\n" + OLD_TEXT)
    run()
    assert run() == RegroundReport(checked=0, unchanged=0, moved=0, lost=0, queued=0)
    assert len(_rows(run_store, "regrounds.jsonl")) == 1
    assert len(_rows(run_store, "review_queue.jsonl")) == 1


def test_current_version_citation_skipped(world, monkeypatch):
    _, run, *_ = world
    monkeypatch.setattr(R, "parser_version", lambda: "old")
    assert run().checked == 0


def test_unparseable_original_is_text_unavailable(world):
    run_store, run, *_ = world
    run_store.results_path("ext1").write_text(
        run_store.results_path("ext1").read_text().replace("report.txt", "filing.bin")
    )
    assert run() == RegroundReport(checked=1, unchanged=0, moved=0, lost=0, queued=0)
    assert [r["outcome"] for r in _rows(run_store, "regrounds.jsonl")] == ["text_unavailable"]


def test_reground_if_parser_changed_first_run_records_only(world):
    run_store, _, new_parser, settings, blobs, texts = world
    new_parser("Preface.\n" + OLD_TEXT)
    kw = {"settings": settings, "blob_store": blobs, "content_store": texts}
    assert reground_if_parser_changed(run_store, **kw) is None
    assert (settings.publish_state_dir / "parser_version.txt").read_text() == "new"
    assert _rows(run_store, "regrounds.jsonl") == []
    assert reground_if_parser_changed(run_store, **kw) is None  # unchanged
    (settings.publish_state_dir / "parser_version.txt").write_text("old")
    assert reground_if_parser_changed(run_store, **kw).moved == 1
    assert (settings.publish_state_dir / "parser_version.txt").read_text() == "new"


def test_gate_reground_still_works(world):
    *_, blobs, texts = world
    assert reground_citation(_citation(), blob_store=blobs, content_store=texts, fuzzy_threshold=0.92) == "ok"
    moved = _citation(char_start=0, char_end=len(QUOTE))
    assert reground_citation(moved, blob_store=blobs, content_store=texts, fuzzy_threshold=0.92) == "offset_moved"


def test_daily_job_records_parser_version(world, tmp_path, monkeypatch):
    import asyncio

    import arp.publish.scheduler as S
    from arp.publish.scheduler import PublishingScheduleConfig, PublishingScheduler
    from arp.storage.portfolio_store import PortfolioStore

    run_store, *_, settings, _, _ = world
    monkeypatch.setattr(S, "due_jobs", lambda *a, **k: [])
    sched = PublishingScheduler(settings.model_copy(update={"snapshot_store_dir": tmp_path / "snaps"}),
                                PortfolioStore(tmp_path / "pf"), run_store)
    asyncio.run(sched._run(PublishingScheduleConfig(enabled=True)))
    assert (settings.publish_state_dir / "parser_version.txt").read_text() == "new"
