import hashlib
import json

import httpx
from typer.testing import CliRunner

from arp.cli import app
from arp.pageindex import cli as C
from arp.pageindex import navigate as N
from arp.pageindex import tree as T
from tests.test_pageindex_run import FakeLLM

runner = CliRunner()
SPAN = "SSAB commits to net zero by 2045."


def _cite(page):
    def nav(prompt, model):
        kw = dict(answer="YES", pages=[page], quotes=["q"])
        return N.Step(action="answer", **kw) if model is N.Step else N.Answer(**kw)
    return nav


def _setup(monkeypatch, tmp_path, cite_page=2, span=SPAN, sha=None, present=True):
    data = b"%PDF fake"
    d = tmp_path / "dir" / "ssab"
    d.mkdir(parents=True)
    if present:
        (d / "d.pdf").write_bytes(data)
    cases = tmp_path / "c.json"
    cases.write_text(json.dumps([{"case_id": "c1", "field_id": "tp_a_headline_1", "company_id": "ssab",
                                  "document": "d.pdf", "gold": [{"span_text": span}]}]))
    (tmp_path / "documents.json").write_text(json.dumps([{"company_id": "ssab", "document": "d.pdf",
        "url": "https://example.test/d.pdf", "sha256": sha or hashlib.sha256(data).hexdigest()}]))
    monkeypatch.setattr(T, "page_texts", lambda _p: ["cover", f"Our plan. {SPAN}", "other"])
    monkeypatch.setattr(C, "make_llm", lambda: (FakeLLM(nav=_cite(cite_page)), "m"))
    return cases


def _golden(cases, tmp_path, *extra):
    return runner.invoke(app, ["pageindex", "golden", "--cases", str(cases), "--documents-dir", str(tmp_path / "dir"), *extra])


def test_hit(monkeypatch, tmp_path):
    r = _golden(_setup(monkeypatch, tmp_path), tmp_path, "--min-recall", "1")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "PageIndex golden: recall 1.00 (1/1), yes-rate 1.00, stale 0"


def test_miss(monkeypatch, tmp_path):
    r = _golden(_setup(monkeypatch, tmp_path, cite_page=3), tmp_path, "--min-recall", "1")
    assert r.exit_code == 1
    assert r.stdout.strip() == "PageIndex golden: recall 0.00 (0/1), yes-rate 1.00, stale 0"


def test_stale(monkeypatch, tmp_path):
    r = _golden(_setup(monkeypatch, tmp_path, span="Not in the report."), tmp_path, "--min-recall", "0")
    assert r.exit_code == 0
    assert r.stdout.strip() == "PageIndex golden: recall 0.00 (0/0), yes-rate 1.00, stale 1"


def test_hash_mismatch(monkeypatch, tmp_path):
    r = _golden(_setup(monkeypatch, tmp_path, sha="0" * 64), tmp_path)
    assert r.exit_code == 1
    assert "Document d.pdf does not match its recorded hash." in r.stderr


def test_fetch_failure(monkeypatch, tmp_path):
    cases = _setup(monkeypatch, tmp_path, present=False)

    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", boom)
    r = _golden(cases, tmp_path)
    assert r.exit_code == 1
    assert r.stderr.strip() == "Could not fetch d.pdf: down"
