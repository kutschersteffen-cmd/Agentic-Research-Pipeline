from __future__ import annotations

from arp.signal_lab.text_panel import manifest_from_text_items
from arp.signal_lab.text_store import make_record


def _rec(company_id, event_time="2020-01-31T23:10:00Z", title="T", body="B"):
    return make_record(source="transcript", source_item_id="x", company_id=company_id,
                       event_time=event_time, knowledge_time="2021-01-01T00:00:00Z", title=title, body=body)


def test_manifest_skips_unlinked_and_buckets_by_event_month():
    rec = _rec("iss_a")
    manifest = manifest_from_text_items([rec, _rec(None)])
    assert manifest == [{"ticker": "iss_a", "period_end": "2020-01-31", "published_at": "2020-01-31T23:10:00Z",
                         "doc_id": rec.item_id, "text": "T\n\nB"}]


def test_manifest_text_is_title_blank_line_body():
    [entry] = manifest_from_text_items([_rec("iss_a", title="Head", body="Line one\nLine two")])
    assert entry["text"] == "Head\n\nLine one\nLine two"


def test_manifest_month_boundary_first_second():
    [entry] = manifest_from_text_items([_rec("iss_a", event_time="2020-02-01T00:00:00Z")])
    assert entry["period_end"] == "2020-02-29"
