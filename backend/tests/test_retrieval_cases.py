from __future__ import annotations

import hashlib
import http.server
import json
import threading

import pytest
from typer.testing import CliRunner

from arp.cli import app

FILLER = "Our revenue grew strongly this year and the dividend was raised. " * 2000  # far more than 12 chunks


def _write_case(tmp_path, company_id, field_id, gold, body):
    folder = tmp_path / "documents" / company_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.txt").write_text(body)
    return {"case_id": f"{company_id}-{field_id}", "schema_id": "transition_plan_indicators", "field_id": field_id,
            "company_id": company_id, "document": "report.txt", "gold": [{"span_text": gold}],
            "labelled_by": "agent", "spot_checked": False}


def _run(*args):
    return CliRunner().invoke(app, ["golden-set", "retrieval", *args])


@pytest.fixture(autouse=True)
def _postgres(pg, monkeypatch, tmp_path):  # the arp CLI needs its system of record
    monkeypatch.setenv("ARP_DOCUMENT_STORE_DIR", str(tmp_path / "store"))


def test_cases_mode_reports_recall_stale_spans_and_min_recall(tmp_path):
    cases = [
        _write_case(tmp_path, "a", "tp_a_ambition_3", "We commit to a net zero target for the whole group by 2045.",
                    FILLER + "We commit to a net zero target for the whole group by 2045. " + FILLER),
        # line breaks, an en dash and curly quotes in the document; plain text in the gold span
        _write_case(tmp_path, "b", "tp_a_emissions_59", 'Scope 1 GHG emissions were 1,234 tCO2e in 2023-2024 ("direct").',
                    FILLER + "Scope 1 GHG emissions were\n1,234 tCO2e in 2023–2024 (“direct”). " + FILLER),
        _write_case(tmp_path, "c", "tp_a_structure_15", "This sentence is not in the document.", FILLER),
    ]
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases))
    out = tmp_path / "report.json"

    result = _run("--cases", str(cases_file), "--no-hybrid", "--no-rerank", "--out", str(out))
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("2 gold span(s) over 2 field(s): recall@5 100.0%, recall@12 100.0%")
    assert "Left out 1 span(s) whose text no longer matches the current parse." in result.stderr
    report = json.loads(out.read_text())
    assert report["run_id"] is None and report["stale_spans"] == 1 and report["misses"] == []

    result = _run("--cases", str(cases_file), "--no-hybrid", "--no-rerank", "--min-recall", "1.01")
    assert result.exit_code == 2  # out of range

    cases[2] = _write_case(tmp_path, "c", "tp_a_structure_15", "Totally unrelated words about lunch menus.",
                           FILLER + "Totally unrelated words about lunch menus.")  # no keyword: never in the top 12
    cases_file.write_text(json.dumps(cases))
    result = _run("--cases", str(cases_file), "--no-hybrid", "--no-rerank", "--min-recall", "0.9")
    assert result.exit_code == 1
    assert "recall@12 66.7% is below the minimum 90.0%" in result.stderr


@pytest.mark.parametrize("args", [[], ["--cases", "x.json", "--run-id", "r"]])
def test_exactly_one_source(args):
    result = _run(*args)
    assert result.exit_code == 2
    assert "Pass exactly one of --cases or --run-id." in result.stderr


def test_documents_are_downloaded_and_hash_checked(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    body = (FILLER + "We commit to a net zero target for the whole group by 2045. " + FILLER).encode()
    (served / "report.txt").write_bytes(body)
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(served), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cases_file = tmp_path / "cases.json"
        cases_file.write_text(json.dumps([{
            "case_id": "a", "schema_id": "transition_plan_indicators", "field_id": "tp_a_ambition_3", "company_id": "a",
            "document": "report.txt", "gold": [{"span_text": "net zero target for the whole group by 2045"}],
            "labelled_by": "agent", "spot_checked": False}]))
        url = f"http://127.0.0.1:{server.server_port}/report.txt"
        documents = tmp_path / "documents.json"

        documents.write_text(json.dumps([{"company_id": "a", "document": "report.txt", "url": url, "sha256": "0" * 64}]))
        result = _run("--cases", str(cases_file), "--no-hybrid", "--no-rerank")
        assert result.exit_code == 1
        assert "Document report.txt does not match its recorded hash." in result.stderr
        assert not (tmp_path / "documents" / "a" / "report.txt").exists()

        sha = hashlib.sha256(body).hexdigest()
        documents.write_text(json.dumps([{"company_id": "a", "document": "report.txt", "url": url, "sha256": sha}]))
        result = _run("--cases", str(cases_file), "--no-hybrid", "--no-rerank")
        assert result.exit_code == 0, result.output
        assert (tmp_path / "documents" / "a" / "report.txt").read_bytes() == body

        (tmp_path / "documents" / "a" / "report.txt").write_bytes(body + b"tampered")
        result = _run("--cases", str(cases_file), "--no-hybrid", "--no-rerank")
        assert result.exit_code == 1  # a file already present is checked too
    finally:
        server.shutdown()
