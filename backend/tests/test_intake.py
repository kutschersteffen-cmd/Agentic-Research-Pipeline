import asyncio
import json
from pathlib import Path

from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from arp.ingestion.intake import IntakeState, check_intake
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.schemas.common import CompanyRef


def _blank_pdf(path: Path, pages: int = 2) -> Path:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    with path.open("wb") as f:
        w.write(f)
    return path


def _text_pdf(path: Path) -> Path:
    c = canvas.Canvas(str(path))
    c.drawString(72, 700, "Scope 1 emissions were 1,234 tonnes CO2e in the reporting year.")
    c.save()
    return path


def _truncated_pdf(path: Path) -> Path:
    data = _text_pdf(path).read_bytes()
    path.write_bytes(data[: len(data) // 2])
    return path


def test_scanned_pdf_goes_to_ocr(tmp_path):
    r = check_intake(_blank_pdf(tmp_path / "s.pdf"), "k1", seen={})
    assert r.state == IntakeState.OCR_NEEDED


def test_truncated_pdf_is_quarantined(tmp_path):
    r = check_intake(_truncated_pdf(tmp_path / "t.pdf"), "k2", seen={})
    assert (r.state, r.reason) == (IntakeState.QUARANTINED, "truncated")


def test_text_pdf_accepted(tmp_path):
    assert check_intake(_text_pdf(tmp_path / "a.pdf"), "k3", seen={}).state == IntakeState.ACCEPTED


def test_empty_file_quarantined(tmp_path):
    p = tmp_path / "e.txt"
    p.write_bytes(b"")
    r = check_intake(p, "k4", seen={})
    assert (r.state, r.reason) == (IntakeState.QUARANTINED, "empty")


def test_corrupt_xlsx_quarantined(tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_bytes(b"not a zip at all")
    assert check_intake(p, "k5", seen={}).state == IntakeState.QUARANTINED


def test_duplicate_by_content_key(tmp_path):
    a, b = tmp_path / "10-K" / "a.pdf", tmp_path / "other" / "b.pdf"
    a.parent.mkdir()
    b.parent.mkdir()
    _text_pdf(a)
    b.write_bytes(a.read_bytes())
    seen: dict[str, str] = {}
    assert check_intake(a, "same", seen=seen).state == IntakeState.ACCEPTED
    r = check_intake(b, "same", seen=seen)
    assert r.state == IntakeState.DUPLICATE
    assert r.duplicate_of.endswith("a.pdf")


def test_refetch_same_file_is_not_duplicate(tmp_path):
    p = _text_pdf(tmp_path / "a.pdf")
    seen: dict[str, str] = {}
    assert check_intake(p, "k", seen=seen).state == IntakeState.ACCEPTED
    assert check_intake(p, "k", seen=seen).state == IntakeState.ACCEPTED


def test_fetch_skips_non_accepted_and_logs(tmp_path):
    d = tmp_path / "docs" / "acme" / "sustainability_report"
    d.mkdir(parents=True)
    (d / "good.txt").write_text("Scope 1 emissions were 10 tonnes.")
    _blank_pdf(d / "blank.pdf")
    _truncated_pdf(d / "cut.pdf")
    source = LocalFileDocumentSource(tmp_path / "docs")
    docs = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    assert [x.title for x in docs] == ["good.txt"]
    rows = [json.loads(line) for line in (tmp_path / "docs" / "_intake.jsonl").read_text().splitlines()]
    assert {r["state"] for r in rows} == {"ocr_needed", "quarantined"}
    assert len(rows) == 2


def test_intake_error_is_logged_as_quarantined(tmp_path, monkeypatch):
    from arp.ingestion import local_files

    d = tmp_path / "docs" / "acme" / "sustainability_report"
    d.mkdir(parents=True)
    (d / "good.txt").write_text("Scope 1 emissions were 10 tonnes.")

    def boom(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(local_files, "check_intake", boom)
    source = LocalFileDocumentSource(tmp_path / "docs")
    assert asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme"))) == []
    rows = [json.loads(line) for line in (tmp_path / "docs" / "_intake.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["state"] == "quarantined" and "intake error" in rows[0]["reason"]
