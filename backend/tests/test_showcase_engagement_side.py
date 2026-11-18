"""Spec showcase-stewardship-fixes, PR B: engagement state, trigger scan, dossier, contacts and letters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.routers import engagement, stewardship
from arp.config import Settings
from arp.engagement.research_agent import NoDocuments, ResearchDossierDraft, research_company_issue
from arp.engagement.tracking_agent import log_meeting_summary_validated, log_outreach_sent
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.engagement import (
    Contact,
    EngagementIssue,
    EngagementRecord,
    MilestoneStage,
    OutreachLetterDraft,
    TriggerSource,
)
from arp.stewardship.process import StreamStore
from arp.storage.engagement_store import EngagementStore
from tests.conftest import PRINCIPAL, FakeLLMClient
from tests.test_engagement_research_agent import _FixedDocSource

EVIDENCE_MSG = "Evidence is required to verify a commitment."
TODAY = datetime.now(UTC).date()
FUTURE = (TODAY + timedelta(days=30)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


@pytest.fixture
def store(tmp_path):
    return EngagementStore(tmp_path / "e")


def _client(store: EngagementStore, settings: Settings | None = None, registry=None) -> TestClient:
    app = FastAPI()
    app.include_router(engagement.router)
    app.include_router(stewardship.router)
    app.dependency_overrides[deps.get_engagement_store] = lambda: store
    app.dependency_overrides[deps.get_stream_store] = lambda: StreamStore(store.engagements_dir.parent / "s")
    app.dependency_overrides[deps.settings_dep] = lambda: settings or Settings()
    app.dependency_overrides[deps.get_registry] = lambda: registry or DocumentSourceRegistry([])
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    return TestClient(app)


def _issue_with_commitment(client: TestClient, company: str, target_date: str | None = None) -> tuple[str, str]:
    client.post("/api/engagement/records", json={"company_id": company, "name": company})
    issue_id = client.post(f"/api/engagement/records/{company}/issues?name={company}", json={"theme": "climate"}).json()["issue_id"]
    body = {"company_id": company, "issue_id": issue_id, "text": "Cut emissions"}
    if target_date:
        body["target_date"] = target_date
    commitment_id = client.post("/api/stewardship/tracking/commitments", json=body).json()["commitment_id"]
    return issue_id, commitment_id


def _record(client, company):
    return client.get(f"/api/engagement/records/{company}").json()


def _issue(client, company, issue_id):
    return next(i for i in _record(client, company)["issues"] if i["issue_id"] == issue_id)


def _verify(client, company, issue_id, body):
    return client.post(f"/api/engagement/records/{company}/issues/{issue_id}/verify-commitment", json=body)


def _track_verify(client, company, issue_id, commitment_id, **extra):
    body = {"company_id": company, "issue_id": issue_id, "status": "verified", **extra}
    return client.post(f"/api/stewardship/tracking/commitments/{commitment_id}", json=body)


# --- G5: evidence on verify (AC-72..84) ---


@pytest.mark.parametrize("evidence", ["  ", ""])
def test_blank_evidence_is_refused_and_nothing_changes(store, evidence):  # AC-72, 73, 74
    client = _client(store)
    issue_id, cid = _issue_with_commitment(client, "C72")
    res = _verify(client, "C72", issue_id, {"commitment_id": cid, "evidence": evidence})
    assert (res.status_code, res.json()["detail"]) == (422, EVIDENCE_MSG)
    issue = _issue(client, "C72", issue_id)
    assert issue["commitments"][0]["status"] == "open" and issue["status"] == "open"


@pytest.mark.parametrize("body", [{}, {"evidence": None}])
def test_missing_evidence_is_refused_before_the_target_date(store, body):  # AC-75, 76
    client = _client(store)
    issue_id, cid = _issue_with_commitment(client, "C75", FUTURE)
    res = _verify(client, "C75", issue_id, {"commitment_id": cid, **body})
    assert (res.status_code, res.json()["detail"]) == (422, EVIDENCE_MSG)


def test_evidence_is_stored_on_verify(store):  # AC-77
    client = _client(store)
    issue_id, cid = _issue_with_commitment(client, "C77", FUTURE)
    res = _verify(client, "C77", issue_id, {"commitment_id": cid, "evidence": "Board minutes 2026-11-01, p. 3"})
    assert res.status_code == 200
    [c] = _issue(client, "C77", issue_id)["commitments"]
    assert (c["status"], c["evidence"]) == ("verified", "Board minutes 2026-11-01, p. 3")


@pytest.mark.parametrize("target_date", [None, YESTERDAY])
def test_missing_evidence_passes_when_due_or_undated(store, target_date):  # AC-78, 79 (must not change)
    client = _client(store)
    issue_id, cid = _issue_with_commitment(client, "C78", target_date)
    assert _verify(client, "C78", issue_id, {"commitment_id": cid}).status_code == 200
    assert _issue(client, "C78", issue_id)["commitments"][0]["status"] == "verified"


def test_tracking_verify_asks_for_evidence(store):  # AC-80, 81, 82
    client = _client(store)
    issue_id, cid = _issue_with_commitment(client, "C80", FUTURE)
    res = _track_verify(client, "C80", issue_id, cid)
    assert (res.status_code, res.json()["detail"]) == (422, EVIDENCE_MSG)
    issue_id2, cid2 = _issue_with_commitment(client, "C81")
    res = _track_verify(client, "C81", issue_id2, cid2, evidence="  ")
    assert (res.status_code, res.json()["detail"]) == (422, EVIDENCE_MSG)
    assert _track_verify(client, "C80", issue_id, cid, evidence="Annual report 2026, p. 41").status_code == 200
    [c] = _issue(client, "C80", issue_id)["commitments"]
    assert (c["status"], c["evidence"]) == ("verified", "Annual report 2026, p. 41")


def test_tracking_verify_and_missed_without_evidence_still_pass(store):  # AC-83, 84 (must not change)
    client = _client(store)
    issue_id, cid = _issue_with_commitment(client, "C83")
    assert _track_verify(client, "C83", issue_id, cid).status_code == 200
    assert _issue(client, "C83", issue_id)["commitments"][0]["status"] == "verified"
    issue_id, cid = _issue_with_commitment(client, "C84", FUTURE)
    body = {"company_id": "C84", "issue_id": issue_id, "status": "missed"}
    assert client.post(f"/api/stewardship/tracking/commitments/{cid}", json=body).status_code == 200
    assert _issue(client, "C84", issue_id)["commitments"][0]["status"] == "missed"


# --- G5: escalation of a resolved or closed issue (AC-88..91) ---


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_resolved_or_closed_issue_cannot_be_escalated(store, status):  # AC-88, 89, 90
    client = _client(store)
    company = f"E{status}"
    issue_id, _ = _issue_with_commitment(client, company)
    close = {"company_id": company, "issue_id": issue_id, "status": status, "outcome": "x"}
    assert client.post("/api/stewardship/tracking/close", json=close).status_code == 200
    before = _issue(client, company, issue_id)
    res = client.post(
        f"/api/engagement/records/{company}/issues/{issue_id}/escalate",
        json={"stage": "written_escalation_to_board", "reason": ""},
    )
    assert (res.status_code, res.json()["detail"]) == (409, "A resolved or closed issue cannot be escalated.")
    after = _issue(client, company, issue_id)
    assert after["escalation_stage"] == before["escalation_stage"]
    assert len(after["escalation_history"]) == len(before["escalation_history"])


def test_open_issue_can_still_be_escalated(store):  # AC-91 (must not change)
    client = _client(store)
    issue_id, _ = _issue_with_commitment(client, "E91")
    res = client.post(
        f"/api/engagement/records/E91/issues/{issue_id}/escalate", json={"stage": "written_escalation_to_board", "reason": ""}
    )
    assert res.status_code == 200
    assert _issue(client, "E91", issue_id)["escalation_stage"] == "written_escalation_to_board"


# --- G5: outreach logged twice, milestones never move back (AC-93..100) ---


def test_same_outreach_twice_adds_one_entry(store):  # AC-93, 94, 95, 97
    client = _client(store)
    client.post("/api/engagement/records", json={"company_id": "O93", "name": "O"})
    issue_id = client.post("/api/engagement/records/O93/issues?name=O", json={"theme": "climate"}).json()["issue_id"]
    url = f"/api/engagement/records/O93/issues/{issue_id}/log-outreach-sent"
    for summary, expected in [("S", 1), ("S", 1), ("T", 2), ("S", 2)]:
        assert client.post(url, json={"summary": summary}).status_code == 200
        assert len(_issue(client, "O93", issue_id)["correspondence"]) == expected
    assert _issue(client, "O93", issue_id)["milestone_stage"] == "contacted"


def test_outreach_on_a_resolved_issue_keeps_milestone_and_status(store):  # AC-96
    client = _client(store)
    issue_id, cid = _issue_with_commitment(client, "O96")
    assert _verify(client, "O96", issue_id, {"commitment_id": cid}).status_code == 200
    assert client.post(f"/api/engagement/records/O96/issues/{issue_id}/log-outreach-sent", json={"summary": "U"}).status_code == 200
    issue = _issue(client, "O96", issue_id)
    assert (issue["milestone_stage"], issue["status"]) == ("commitment_verified", "resolved")


def _at_stage(store, stage: MilestoneStage) -> str:
    _, issue = store.open_issue("M", "M", theme="climate")
    store.set_milestone_stage("M", issue.issue_id, stage)
    return issue.issue_id


def _stage(store, issue_id):
    return next(i for i in store.get("M").issues if i.issue_id == issue_id).milestone_stage


def test_outreach_does_not_move_dialogue_back(store):  # AC-98
    issue_id = _at_stage(store, MilestoneStage.DIALOGUE_OPENED)
    log_outreach_sent(store, "M", issue_id, "S", "Ana")
    assert _stage(store, issue_id) == MilestoneStage.DIALOGUE_OPENED


def test_meeting_summary_does_not_move_verified_back(store):  # AC-99
    issue_id = _at_stage(store, MilestoneStage.COMMITMENT_VERIFIED)
    log_meeting_summary_validated(store, "M", issue_id, "Met", [], "Ana")
    assert _stage(store, issue_id) == MilestoneStage.COMMITMENT_VERIFIED


def test_meeting_summary_still_moves_contacted_forward(store):  # AC-100 (must not change)
    issue_id = _at_stage(store, MilestoneStage.CONTACTED)
    log_meeting_summary_validated(store, "M", issue_id, "Met", [], "Ana")
    assert _stage(store, issue_id) == MilestoneStage.RESPONSE_RECEIVED


# --- G6: signals for companies not in the list (AC-106..109) ---


def _scan(client, signal_ids):
    return client.post(
        "/api/engagement/trigger-scan",
        json={
            "companies": [{"company_id": "C1", "name": "Acme"}],
            "signals": [{"company_id": c, "theme": "climate"} for c in signal_ids],
        },
    )


def test_scan_reports_unlisted_signals(store):  # AC-106, 107, 108, 109
    client = _client(store)
    res = _scan(client, ["C2"])
    assert res.status_code == 200
    assert not [e for e in res.json()["events"] if e["company_id"] == "C2"]
    assert res.json()["unlisted_signals"] == {"count": 1, "company_ids": ["C2"]}
    assert client.get("/api/engagement/records/C2").status_code == 404
    assert _scan(client, ["C1"]).json()["unlisted_signals"] == {"count": 0, "company_ids": []}
    assert _scan(client, ["C3", "C2", "C2"]).json()["unlisted_signals"] == {"count": 3, "company_ids": ["C2", "C3"]}


# --- G7: dossier without documents (AC-112, 113, 115) ---

NO_DOCS = "No documents are loaded for No Docs AG (NODOCS). Upload them in Data Library, then draft the dossier."


def test_dossier_without_documents_is_refused_without_a_model_call(store, monkeypatch):  # AC-112
    client = _client(store)
    client.post("/api/engagement/records", json={"company_id": "NODOCS", "name": "No Docs AG"})
    issue_id = client.post("/api/engagement/records/NODOCS/issues?name=No%20Docs%20AG", json={"theme": "climate"}).json()["issue_id"]

    def no_model():
        raise AssertionError("the model client was built")

    monkeypatch.setattr(engagement, "get_llm_client", no_model)
    res = client.post(
        f"/api/engagement/records/NODOCS/issues/{issue_id}/dossier", json={"company_id": "NODOCS", "name": "No Docs AG"}
    )
    assert (res.status_code, res.json()["detail"]) == (422, NO_DOCS)


async def test_research_agent_makes_no_model_call_without_documents():  # AC-113
    llm = FakeLLMClient({})
    with pytest.raises(NoDocuments, match="No documents are loaded for No Docs AG"):
        await research_company_issue(
            CompanyRef(company_id="NODOCS", name="No Docs AG"),
            EngagementIssue(theme="climate", source=TriggerSource.MANUAL),
            EngagementRecord(company_id="NODOCS", name="No Docs AG"),
            registry=DocumentSourceRegistry([]), llm=llm, fuzzy_threshold=0.9, confidence_review_threshold=0.6,
        )
    assert llm.calls == []


async def test_research_agent_still_calls_the_model_with_one_document():  # AC-115 (must not change)
    doc = SourceDocument(company_id="C1", doc_type=DocType.SUSTAINABILITY_REPORT, title="AR", full_text="Climate plan text.")
    draft = ResearchDossierDraft(summary="s", controversy_context="c", peer_benchmark_notes="p", confidence=0.9)
    llm = FakeLLMClient({"ResearchDossierDraft": [draft]})
    dossier, _, _ = await research_company_issue(
        CompanyRef(company_id="C1", name="Acme"),
        EngagementIssue(theme="climate", source=TriggerSource.MANUAL),
        EngagementRecord(company_id="C1", name="Acme"),
        registry=DocumentSourceRegistry([_FixedDocSource([doc])]), llm=llm, fuzzy_threshold=0.9, confidence_review_threshold=0.6,
    )
    assert llm.calls == ["ResearchDossierDraft"] and dossier.summary == "s"


# --- G13: contact email (AC-147..151) ---

BAD_EMAIL = "Enter a valid email address, or leave it empty."


def test_contact_email_is_checked(store):  # AC-147, 148, 149, 150
    client = _client(store)
    client.post("/api/engagement/records", json={"company_id": "K", "name": "K"})
    url = "/api/engagement/records/K/contacts"
    for email in ["not-an-email", "a@b", "a b@c.de"]:
        res = client.post(url, json={"name": "A", "role": "IR", "email": email})
        assert (res.status_code, res.json()["detail"]) == (422, BAD_EMAIL), email
    assert _record(client, "K")["contacts"] == []
    for email in ["a@example.org", None, ""]:
        assert client.post(url, json={"name": "A", "role": "IR", "email": email}).status_code == 200
    assert len(_record(client, "K")["contacts"]) == 3


def test_stored_contact_with_a_bad_email_still_loads(store):  # AC-151 (must not change)
    store.get_or_create("K", "K")
    store.add_contact("K", Contact(name="A", role="IR", email="not-an-email"))
    res = _client(store).get("/api/engagement/records/K")
    assert res.status_code == 200 and res.json()["contacts"][0]["email"] == "not-an-email"


# --- G13: letter placeholders and fund name (AC-152..154) ---


def _letter(store, monkeypatch, fund_name, subject, body, cited=()):
    letter = OutreachLetterDraft(subject=subject, body=body, recommended_recipient="IR")
    monkeypatch.setattr(engagement, "get_llm_client", lambda: FakeLLMClient({"OutreachLetterDraft": [letter]}))
    client = _client(store, Settings(fund_name=fund_name))
    client.post("/api/engagement/records", json={"company_id": "L", "name": "L"})
    issue_id = client.post("/api/engagement/records/L/issues?name=L", json={"theme": "climate"}).json()["issue_id"]
    dossier = {
        "company_id": "L", "issue_id": issue_id, "summary": "s", "controversy_context": "", "peer_benchmark_notes": "",
        "engagement_history_summary": "", "confidence": 0.9,
        "citations": [{"doc_id": d, "doc_type": "sustainability_report", "quote": "q"} for d in cited],
    }
    res = client.post(
        f"/api/engagement/records/L/issues/{issue_id}/outreach-letter",
        json={"company_name": "L", "recipient": "IR", "dossier": dossier},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_fund_name_fills_the_placeholder(store, monkeypatch):  # AC-152
    out = _letter(store, monkeypatch, "Alpha Fund", "Engagement request from [Fund name]", "Dear IR, [Fund name] writes.")
    assert "Alpha Fund" in out["subject"] and "Alpha Fund" in out["body"]
    assert "[Fund name]" not in out["subject"] + out["body"] and out["placeholders"] == []


def test_without_fund_name_the_placeholder_is_listed(store, monkeypatch):  # AC-153
    out = _letter(store, monkeypatch, None, "Engagement request from [Fund name]", "Dear IR, [Fund name] writes.")
    assert out["subject"] == "Engagement request from [Fund name]" and out["body"] == "Dear IR, [Fund name] writes."
    assert out["placeholders"] == ["[Fund name]"]


def test_placeholders_in_order_without_citations(store, monkeypatch):  # AC-154
    out = _letter(store, monkeypatch, None, "[Fund name]", "On [Date] we read [doc_1]. Reply by [Date].", cited=["doc_1"])
    assert out["placeholders"] == ["[Fund name]", "[Date]"]
