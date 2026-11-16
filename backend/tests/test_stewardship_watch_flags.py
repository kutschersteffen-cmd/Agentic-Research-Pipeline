"""Watch list, PR 3 (spec stewardship-commitment-loop): `watch_flags`, the ballot banner data and the dossier
watch list."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import current_user
from arp.api.deps import get_engagement_store, get_registry, get_run_store
from arp.api.main import app
from arp.api.routers import engagement as engagement_router
from arp.config import get_settings
from arp.engagement.drafting_agent import draft_talking_points
from arp.engagement.research_agent import ResearchDossierDraft
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.engagement import (
    Commitment,
    EngagementIssue,
    IssueStatus,
    MeetingTalkingPoints,
    Objective,
    ResearchDossier,
    WatchTopic,
)
from arp.schemas.voting import CompanyBallot, HumanVoteDecision, Proposal, ProposalType, VotePosition, VoteRecord
from arp.stewardship.tracking import triggers, watch_flags, watch_flags_by_company, watch_list
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.run_store import RunStore
from arp.voting.ballot_casting import ManualInstructionBallotPlatform, cast_vote
from tests.conftest import PRINCIPAL, FakeLLMClient
from tests.test_engagement_research_agent import _FixedDocSource
from tests.test_stewardship_watch import _suggest

TODAY = datetime.now(UTC).date()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
SBT = "Set a 2030 science-based target"
TOPIC = "Has the company named a board climate committee?"


@pytest.fixture
def store(pg):
    return PostgresEngagementStore(pg)


def _issue(store, company_id="C1") -> str:
    return store.open_issue(company_id, company_id, theme="climate")[1].issue_id


def _obj(store, issue, company_id="C1", **kw) -> str:
    o = Objective(description=SBT, objective_type="strategic", **{"status": "in_progress", **kw})
    store.add_objective(company_id, issue, o)
    return o.objective_id


def _cmt(store, issue, text="Publish a transition plan", company_id="C1", **kw) -> str:
    c = Commitment(text=text, **kw)
    store.add_commitment(company_id, issue, c)
    return c.commitment_id


def test_overdue_commitment_ac83(store):
    cid = _cmt(store, _issue(store), target_date=YESTERDAY)
    (f,) = watch_flags(store, "C1")
    assert (f.item_kind, f.item_id, f.kind, f.since, f.target_date) == ("commitment", cid, "overdue", YESTERDAY, YESTERDAY)
    assert f.message == f'Commitment overdue: "Publish a transition plan" was due {YESTERDAY}.'


def test_broken_commitment_ac84(store):
    _cmt(store, _issue(store), text="Name a climate committee", status="missed", validated_at="2026-10-02T09:00:00+00:00")
    (f,) = watch_flags(store, "C1")
    assert (f.kind, f.since) == ("broken", "2026-10-02")
    assert f.message == 'Commitment broken: "Name a climate committee" was marked not met on 2026-10-02.'


def test_overdue_and_failed_objective_ac85_ac86(store):
    issue = _issue(store)
    _obj(store, issue, target_date=YESTERDAY)
    (f,) = watch_flags(store, "C1")
    assert (f.item_kind, f.kind, f.message) == ("objective", "overdue", f'Objective overdue: "{SBT}" was due {YESTERDAY}.')

    issue2 = _issue(store, "C2")
    _obj(store, issue2, "C2", status="closed", result="not_achieved", closed_at="2026-10-02T12:00:00+00:00")
    (f,) = watch_flags(store, "C2")
    assert (f.kind, f.since) == ("broken", "2026-10-02")
    assert f.message == f'Objective failed: "{SBT}" was closed as not achieved on 2026-10-02.'


def test_no_flags_ac87_ac89(store):
    issue = _issue(store)
    _cmt(store, issue, status="verified")
    _obj(store, issue, status="closed", result="achieved")
    _obj(store, issue, status="abandoned", result="abandoned")
    _cmt(store, issue)
    _obj(store, issue)
    for due in (TODAY.isoformat(), TOMORROW):
        _cmt(store, issue, target_date=due)
        _obj(store, issue, target_date=due)
    _obj(store, issue, target_date="31/12/2025")
    store.add_watch_topic("C1", issue, WatchTopic(engagement_id=issue, question=TOPIC, target_date=YESTERDAY))
    closed = _issue(store)
    _cmt(store, closed, target_date=YESTERDAY)
    store.set_issue_status("C1", closed, IssueStatus.CLOSED)
    assert watch_flags(store, "C1", TODAY) == []  # TODAY, not the clock: a run that crosses midnight UTC
    assert watch_flags(store, "NOBODY", TODAY) == []


def test_order_ac88(store):
    issue = _issue(store)
    late = _cmt(store, issue, target_date="2026-09-01")
    early = _cmt(store, issue, target_date="2026-08-01")
    obj = _obj(store, issue, target_date="2026-08-01")
    broken = _cmt(store, issue, status="missed")
    assert [f.item_id for f in watch_flags(store, "C1", date(2026, 11, 14))] == [broken, early, obj, late]


def test_by_company_ac90(store):
    _cmt(store, _issue(store, "A"), "A", target_date=YESTERDAY, company_id="A")
    _obj(store, _issue(store, "B"), "B", status="closed", result="deterioration", closed_at="2026-10-02T00:00:00+00:00")
    _cmt(store, _issue(store, "Z"), company_id="Z", target_date=TOMORROW)
    flags = watch_flags_by_company(store.list_all())
    assert flags == {"A": watch_flags(store, "A"), "B": watch_flags(store, "B")}
    assert flags["B"][0].message == f'Objective failed: "{SBT}" was closed as deterioration on 2026-10-02.'


def test_file_store_ac91(tmp_path):
    files = EngagementStore(tmp_path)
    _cmt(files, _issue(files), target_date=YESTERDAY)
    (f,) = watch_flags(files, "C1")
    assert f.message == f'Commitment overdue: "Publish a transition plan" was due {YESTERDAY}.'


# --- Ballots (AC-92, AC-93, AC-95) ---------------------------------------------------------------------


def test_ballots_carry_flags_when_read_ac92_ac93(store, pg, tmp_path):
    _cmt(store, _issue(store), target_date=YESTERDAY)
    runs = RunStore(pg, tmp_path / "runs")
    for company in ("C1", "C2"):
        runs.append_result("r1", CompanyBallot(company_id=company, name=company, meeting_id="m").model_dump(mode="json"))
    app.dependency_overrides.update({get_run_store: lambda: runs, get_engagement_store: lambda: store, current_user: lambda: PRINCIPAL})
    try:
        ballots = TestClient(app).get("/api/voting/runs/r1/ballots").json()["ballots"]
    finally:
        app.dependency_overrides.clear()
    by_company = {b["company_id"]: b["watch_flags"] for b in ballots}
    assert by_company == {"C1": [f.model_dump(mode="json") for f in watch_flags(store, "C1")], "C2": []}
    assert len(by_company["C1"]) == 1


async def test_cast_ignores_watch_flags_ac95(tmp_path):
    proposal = Proposal(company_id="C1", meeting_id="m", proposal_number="1", type=ProposalType.DIRECTOR_ELECTION, sponsor="Management", resolution_text="Elect.")
    record = VoteRecord(proposal=proposal, human_decision=HumanVoteDecision(vote=VotePosition.FOR, decided_by="pm"))
    cast = await cast_vote(ManualInstructionBallotPlatform(tmp_path), record)
    assert cast.cast_confirmation.status == "confirmed"


# --- The dossier watch list (AC-104 to AC-108) ---------------------------------------------------------


def test_watch_list_order_flags_and_evidence(store, pg):
    issue = _issue(store)
    obj = _obj(store, issue, target_date=YESTERDAY)
    topic = WatchTopic(engagement_id=issue, question=TOPIC)
    store.add_watch_topic("C1", issue, topic)
    later = _cmt(store, issue, target_date=TOMORROW, proof_statement="A plan is published")
    _cmt(store, issue, status="verified")
    _suggest(pg, issue, item_kind="topic", item_id=topic.topic_id)
    store.confirm_suggestion(store.list_suggestions("C1", "pending")[0].suggestion_id, "dev")

    entries = watch_list(store, "C1", issue)
    assert [(e.item_kind, e.item_id, e.flag) for e in entries] == [
        ("objective", obj, "overdue"), ("commitment", later, None), ("topic", topic.topic_id, None),
    ]
    assert entries[1].proof_statement == "A plan is published"
    assert entries[2].evidence == ['Evidence: AR2026.txt: "The board formed a climate committee in March 2026." (confirmed by dev)']


def test_watch_list_broken_only_and_empty_ac106_ac107(store, tmp_path):
    issue = _issue(store)
    missed = _cmt(store, issue, status="missed")
    _obj(store, issue, status="closed", result="achieved")
    assert [(e.item_id, e.flag) for e in watch_list(store, "C1", issue)] == [(missed, "broken")]
    assert watch_list(store, "C1", _issue(store)) == []
    files = EngagementStore(tmp_path)
    file_issue = _issue(files)
    _cmt(files, file_issue, target_date=YESTERDAY)
    assert [(e.item_kind, e.flag) for e in watch_list(files, "C1", file_issue)] == [("commitment", "overdue")]


def test_dossier_endpoint_fills_watch_list_ac104(store, monkeypatch, tmp_path):
    issue = _issue(store)
    _obj(store, issue, target_date=YESTERDAY)
    store.add_watch_topic("C1", issue, WatchTopic(engagement_id=issue, question=TOPIC))
    draft = ResearchDossierDraft(summary="s", controversy_context="c", peer_benchmark_notes="p", confidence=0.9)
    monkeypatch.setattr(engagement_router, "get_llm_client", lambda: FakeLLMClient({"ResearchDossierDraft": [draft]}))
    doc = SourceDocument(company_id="C1", doc_type=DocType.SUSTAINABILITY_REPORT, title="AR", full_text="Climate plan text.")
    get_settings.cache_clear()
    app.dependency_overrides.update({
        get_engagement_store: lambda: store, current_user: lambda: PRINCIPAL,
        get_registry: lambda: DocumentSourceRegistry([_FixedDocSource([doc])]),
    })  # fmt: skip
    try:
        res = TestClient(app).post(f"/api/engagement/records/C1/issues/{issue}/dossier", json={"company_id": "C1", "name": "C1"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200, res.text
    assert [(e["item_kind"], e["flag"]) for e in res.json()["dossier"]["watch_list"]] == [("objective", "overdue"), ("topic", None)]


async def test_talking_points_prompt_has_the_watch_list_ac108(store):
    issue = _issue(store)
    _obj(store, issue, target_date=YESTERDAY)
    store.add_watch_topic("C1", issue, WatchTopic(engagement_id=issue, question=TOPIC))
    dossier = ResearchDossier(company_id="C1", issue_id=issue, summary="s", controversy_context="c", peer_benchmark_notes="p",
                              engagement_history_summary="h", confidence=0.9, watch_list=watch_list(store, "C1", issue))
    llm = FakeLLMClient({"MeetingTalkingPoints": [MeetingTalkingPoints(objectives=[], points=[])]})
    await draft_talking_points("C1", EngagementIssue(theme="climate"), dossier, llm)
    assert "Watch list:" in llm.prompts[0] and SBT in llm.prompts[0] and TOPIC in llm.prompts[0]


# --- Review fixes (spec commitment-loop-review-fixes) --------------------------------------------------


def test_a_due_date_with_a_time_flags_on_its_date_part_ac2_ac5(store):
    cid = _cmt(store, _issue(store), target_date=f"{YESTERDAY}T10:00:00")
    (f,) = watch_flags(store, "C1")
    assert (f.item_kind, f.item_id, f.kind, f.target_date, f.since) == ("commitment", cid, "overdue", YESTERDAY, YESTERDAY)
    assert f.message == f'Commitment overdue: "Publish a transition plan" was due {YESTERDAY}.'
    missed = [t for t in triggers([store.get("C1")], 30) if t["type"] == "commitment_missed"]
    assert [t["reason"] for t in missed] == [f"Past its target date {YESTERDAY}, not verified: Publish a transition plan"]


def test_an_objective_due_date_with_a_time_or_a_note_flags_ac3_ac6(store):
    issue = _issue(store)
    _obj(store, issue, target_date=f"{YESTERDAY}T10:00:00")
    (f,) = watch_flags(store, "C1")
    assert (f.item_kind, f.kind, f.target_date) == ("objective", "overdue", YESTERDAY)
    assert f.message == f'Objective overdue: "{SBT}" was due {YESTERDAY}.'
    other = _issue(store, "C2")
    _obj(store, other, company_id="C2", target_date="2025-12-31 (approx.)")
    (f,) = watch_flags(store, "C2")
    assert (f.kind, f.target_date) == ("overdue", "2025-12-31")


def test_due_today_with_a_time_is_not_overdue_ac4(store):
    _cmt(store, _issue(store), target_date=f"{TODAY.isoformat()}T00:00:00")
    assert watch_flags(store, "C1", TODAY) == []


def test_cli_dossier_carries_the_watch_list_ac7_ac8(store, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from arp.cli import app as cli
    from arp.cli import engagement as cli_engagement

    issue = _issue(store)
    _cmt(store, issue, target_date=f"{YESTERDAY}T10:00:00")
    draft = ResearchDossierDraft(summary="s", controversy_context="c", peer_benchmark_notes="p", confidence=0.9)
    doc = SourceDocument(company_id="C1", doc_type=DocType.SUSTAINABILITY_REPORT, title="AR", full_text="Climate plan text.")
    monkeypatch.setattr(cli_engagement, "build_llm_client", lambda _s: FakeLLMClient({"ResearchDossierDraft": [draft]}))
    monkeypatch.setattr(cli_engagement, "_registry", lambda: DocumentSourceRegistry([_FixedDocSource([doc])]))
    monkeypatch.setattr(cli_engagement, "_engagement_store", lambda: store)
    universe, out = tmp_path / "u.csv", tmp_path / "dossier.json"
    universe.write_text("company_id,name\nC1,Acme\n")

    res = CliRunner().invoke(cli, ["engagement", "dossier-draft", "C1", issue, "--universe", str(universe), "--out", str(out)])

    assert res.exit_code == 0, res.output
    dossier = ResearchDossier.model_validate_json(out.read_text())
    assert [e.model_dump(mode="json") for e in dossier.watch_list] == [e.model_dump(mode="json") for e in watch_list(store, "C1", issue)]
    assert [e.flag for e in dossier.watch_list] == ["overdue"]
    llm = FakeLLMClient({"MeetingTalkingPoints": [MeetingTalkingPoints(objectives=[], points=[])]})
    asyncio.run(draft_talking_points("C1", EngagementIssue(theme="climate"), dossier, llm))
    assert "Publish a transition plan" in llm.prompts[0] and "Watch list:\n(none)" not in llm.prompts[0]
