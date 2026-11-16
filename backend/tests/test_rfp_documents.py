"""rfp-approved-answers-first-design §5: reference documents (unit rows; holdout rows covered here too)."""

from __future__ import annotations

from datetime import date

import pytest

from arp.ingestion import local_files
from arp.rfp import store
from tests import rfp_fixtures as fx
from tests import test_rfp_api as api

env = api.env  # the fixture

TITLE = "Stewardship Statement 2025"


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(store, "today", lambda: date(2026, 11, 15))


def upload(env, name="ref_stmt.docx", data=None, *, who="bob", title=TITLE, document_date="2025-12-31", **form):
    fields = {"title": title, **({"document_date": document_date} if document_date else {}),
              **{k: str(v) for k, v in form.items()}}
    return env.as_(who).post("/api/rfp/documents", data=fields, files={"file": (name, data or fx.ref_stmt_docx())})


def listed(env):
    r = env.as_("bob").get("/api/rfp/documents")
    assert r.status_code == 200
    return r.json()


def doc(env, name="ref_stmt.docx", data=None, **kw):
    """`DOC` (and variants): uploaded by bob, then `review_by` set to 2099-12-31."""
    r = upload(env, name, data, **kw)
    assert r.status_code == 200, r.text
    r = env.as_("bob").put(f"/api/rfp/documents/{r.json()['id']}", json={"review_by": "2099-12-31"})
    assert r.status_code == 200, r.text
    return r.json()


def pdf_parse_standin(monkeypatch):
    """Docling's PDF parse replaced by the fixture text and its page starts; the text-layer check runs for real."""
    page1, page2 = "\n\n".join(fx.STMT[:2]), "\n\n".join(fx.STMT[2:])
    monkeypatch.setattr(local_files, "_extract_pdf_text", lambda path: (f"{page1}\n\n{page2}", [0, len(page1) + 2], []))


def test_ac_15_upload_lists_the_document(env):
    assert upload(env).status_code == 200
    assert listed(env) == [{
        "id": listed(env)[0]["id"], "title": TITLE, "filename": "ref_stmt.docx", "document_date": "2025-12-31",
        "review_by": "2026-12-31", "priority": 1, "status": "active", "uploaded_by": "bob", "pages": None,
    }]


def test_ac_16_analyst_cannot_upload(env):
    assert upload(env, who="alice").status_code == 403
    assert listed(env) == []


def test_ac_17_wrong_file_type(env):
    doc(env)
    before = listed(env)
    r = upload(env, "notes.txt", b"some notes")
    assert (r.status_code, r.json()["detail"]) == (400, "notes.txt is not a .pdf or .docx file.")
    assert listed(env) == before


def test_ac_18_scanned_pdf_is_refused(env):
    before = listed(env)
    r = upload(env, "ref_scan.pdf", fx.ref_scan_pdf())
    assert (r.status_code, r.json()["detail"]) == (400, "ref_scan.pdf has no text layer; upload the original document.")
    assert listed(env) == before


def test_ac_19_pdf_page_count(env, monkeypatch):
    pdf_parse_standin(monkeypatch)
    doc(env, "ref_stmt.pdf", fx.ref_stmt_pdf())
    assert [d["pages"] for d in listed(env)] == [2]


def test_ac_20_replaces_retires_the_old_one(env):
    old = upload(env, document_date="2024-12-31").json()
    r = upload(env, replaces=old["id"])
    assert r.status_code == 200
    assert {d["id"]: d["status"] for d in listed(env)} == {old["id"]: "retired", r.json()["id"]: "active"}


def test_ac_21_replaces_unknown_id(env):
    doc(env)
    before = listed(env)
    r = upload(env, replaces=999999)
    assert (r.status_code, r.json()["detail"]) == (404, "Reference document not found")
    assert listed(env) == before


def test_ac_22_analyst_cannot_retire(env):
    d = doc(env)
    assert env.as_("alice").post(f"/api/rfp/documents/{d['id']}/retire").status_code == 403
    assert [x["status"] for x in listed(env)] == ["active"]


def test_ac_35_put_priority_only(env):
    d = doc(env)
    assert env.as_("bob").put(f"/api/rfp/documents/{d['id']}", json={"priority": 3}).status_code == 200
    assert [(x["priority"], x["title"]) for x in listed(env)] == [(3, TITLE)]


def test_ac_43_put_unknown_id(env):
    r = env.as_("bob").put("/api/rfp/documents/999999", json={"priority": 2})
    assert (r.status_code, r.json()["detail"]) == (404, "Reference document not found")


def test_ac_44_upload_without_date(env):
    before = listed(env)
    assert upload(env, document_date=None).status_code == 422
    assert listed(env) == before


def test_ac_49_priority_zero_on_upload(env):
    before = listed(env)
    assert upload(env, priority=0).status_code == 422
    assert listed(env) == before


def test_ac_50_retire_unknown_id(env):
    r = env.as_("bob").post("/api/rfp/documents/999999/retire")
    assert (r.status_code, r.json()["detail"]) == (404, "Reference document not found")


def test_ac_51_list_order(env):
    doc2 = doc(env, "ref_policy.docx", fx.ref_policy_docx(), title="Voting Policy 2025", priority=2)
    first = doc(env)
    assert [d["id"] for d in listed(env) if d["status"] == "active"] == [first["id"], doc2["id"]]


def test_ac_54_priority_zero_on_put(env):
    d = doc(env)
    assert env.as_("bob").put(f"/api/rfp/documents/{d['id']}", json={"priority": 0}).status_code == 422
    assert [x["priority"] for x in listed(env)] == [1]


def test_empty_title_is_refused(env):
    assert upload(env, title="").status_code == 422
    d = doc(env)
    assert env.as_("bob").put(f"/api/rfp/documents/{d['id']}", json={"title": ""}).status_code == 422


def test_suffix_case_is_ignored(env):
    r = upload(env, "STATEMENT.DOCX")
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "STATEMENT.DOCX"


def test_unreadable_docx_is_a_400(env):
    r = upload(env, "broken.docx", b"not a zip")
    assert (r.status_code, r.json()["detail"]) == (400, "broken.docx could not be read; upload the original document.")
    assert listed(env) == []
