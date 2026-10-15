from __future__ import annotations

import pytest

from arp.signal_lab.adapters.transcripts import CsvTranscriptSource

HEADER = "issuer_key,event_time,title,text\n"


def _write(tmp_path, content: str):
    path = tmp_path / "calls.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_two_rows_give_two_transcript_records(tmp_path):
    path = _write(tmp_path, HEADER + "iss_a,2024-01-02T10:00:00Z,Q4 call,hello\niss_b,2024-01-03T10:00:00Z,Q4 call,world\n")
    recs = CsvTranscriptSource(path, now="2024-02-01T00:00:00Z").records()
    assert [r.source for r in recs] == ["transcript", "transcript"]
    assert [r.company_id for r in recs] == ["iss_a", "iss_b"]
    assert recs[0].knowledge_time == "2024-02-01T00:00:00Z"


def test_naive_event_time_names_file_and_row(tmp_path):
    # Row numbers are 1-based over data rows; the header is row 0.
    path = _write(tmp_path, HEADER + "iss_a,2024-01-02T10:00:00Z,t,ok\niss_a,2024-01-03T10:00:00,t,bad\n")
    with pytest.raises(ValueError, match=r"calls\.csv.*row 2"):
        CsvTranscriptSource(path).records()


def test_missing_required_column_raises(tmp_path):
    path = _write(tmp_path, "issuer_key,event_time,title\niss_a,2024-01-02T10:00:00Z,t\n")
    with pytest.raises(ValueError, match=r"calls\.csv.*text"):
        CsvTranscriptSource(path).records()


def test_empty_issuer_key_raises(tmp_path):
    path = _write(tmp_path, HEADER + ",2024-01-02T10:00:00Z,t,x\n")
    with pytest.raises(ValueError, match=r"calls\.csv.*row 1"):
        CsvTranscriptSource(path).records()


def test_explicit_knowledge_time_is_honored(tmp_path):
    path = _write(tmp_path, "issuer_key,event_time,title,text,knowledge_time\niss_a,2024-01-02T10:00:00Z,t,x,2024-01-05T00:00:00Z\n")
    (rec,) = CsvTranscriptSource(path, now="2025-01-01T00:00:00Z").records()
    assert rec.knowledge_time == "2024-01-05T00:00:00Z"


def test_default_source_item_id_is_stable(tmp_path):
    path = _write(tmp_path, HEADER + "iss_a,2024-01-02T10:00:00Z,t,x\n")
    a = CsvTranscriptSource(path, now="2024-02-01T00:00:00Z").records()[0]
    b = CsvTranscriptSource(path, now="2024-03-01T00:00:00Z").records()[0]
    assert a.source_item_id == b.source_item_id
    assert len(a.source_item_id) == 16
    assert a.item_id == b.item_id


@pytest.mark.parametrize("line", ["iss_a\n", "iss_a,2024-01-02T10:00:00Z\n", "iss_a,2024-01-02T10:00:00Z,t\n"])
def test_truncated_row_raises_value_error_with_row(tmp_path, line):
    path = _write(tmp_path, HEADER + line)
    with pytest.raises(ValueError, match=r"calls\.csv.*row 1"):
        CsvTranscriptSource(path).records()


def test_default_source_item_id_ignores_time_spelling(tmp_path):
    path = _write(tmp_path, HEADER + "iss_a,2024-01-02,t,x\niss_a,2024-01-02T23:59:59Z,t,x\n")
    a, b = CsvTranscriptSource(path, now="2024-02-01T00:00:00Z").records()
    assert a.source_item_id == b.source_item_id
