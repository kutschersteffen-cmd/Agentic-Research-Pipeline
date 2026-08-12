import pytest

from arp.discovery.change_detector import ChangeDetector
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.discovery import DiscoveredDocument, DocumentEventType


def _doc(url: str, sha: str, doc_type=DocType.SUSTAINABILITY_REPORT) -> DiscoveredDocument:
    return DiscoveredDocument(company_id="c1", doc_type=doc_type, url=url, sha256=sha)


async def test_new_document_raises_new_event(tmp_path):
    detector = ChangeDetector(tmp_path / "state", tmp_path / "events.jsonl")
    company = CompanyRef(company_id="c1", name="Acme")
    events = await detector.diff_and_record(company, [_doc("https://acme.com/esg.pdf", "hash1")])
    assert len(events) == 1
    assert events[0].event_type == DocumentEventType.NEW_DOCUMENT


async def test_unchanged_document_raises_no_event_on_second_pass(tmp_path):
    detector = ChangeDetector(tmp_path / "state", tmp_path / "events.jsonl")
    company = CompanyRef(company_id="c1", name="Acme")
    doc = _doc("https://acme.com/esg.pdf", "hash1")
    await detector.diff_and_record(company, [doc])
    events2 = await detector.diff_and_record(company, [doc])
    assert events2 == []


async def test_changed_hash_raises_updated_event(tmp_path):
    detector = ChangeDetector(tmp_path / "state", tmp_path / "events.jsonl")
    company = CompanyRef(company_id="c1", name="Acme")
    await detector.diff_and_record(company, [_doc("https://acme.com/esg.pdf", "hash1")])
    events = await detector.diff_and_record(company, [_doc("https://acme.com/esg.pdf", "hash2")])
    assert len(events) == 1
    assert events[0].event_type == DocumentEventType.UPDATED_DOCUMENT


async def test_events_persisted_to_global_feed(tmp_path):
    events_path = tmp_path / "events.jsonl"
    detector = ChangeDetector(tmp_path / "state", events_path)
    company = CompanyRef(company_id="c1", name="Acme")
    await detector.diff_and_record(company, [_doc("https://acme.com/esg.pdf", "hash1")])
    recent = ChangeDetector.read_recent_events(events_path)
    assert len(recent) == 1
    assert recent[0]["company_id"] == "c1"
