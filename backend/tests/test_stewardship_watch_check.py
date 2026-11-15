"""Watch list, PR 2 (spec stewardship-commitment-loop): the check against documents (button and discovery hook),
finding commitments in notes, the golden command, and the review items carried over from PR 1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import current_user
from arp.api.deps import get_document_content_store, get_engagement_store, get_registry
from arp.api.main import app
from arp.cli import app as cli
from arp.config import get_settings
from arp.db.session import transaction
from arp.discovery import refresh
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.refresh import refresh_hook
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.discovery import DiscoveredDocument
from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    CorrespondenceEntry,
    EvidenceSuggestion,
    IssueStatus,
    Objective,
    WatchTopic,
    evidence_text,
)
from arp.stewardship import watch_check
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.postgres_models import StwEvidenceSuggestionModel, StwObjectiveModel
from tests.conftest import PRINCIPAL

URL = "/api/stewardship"
Q = "The board formed a climate committee in March 2026."
NOTE = "We met the CFO. The CFO committed to publish a transition plan by 31 March 2027. Pay was not discussed."
PROMISE = "The CFO committed to publish a transition plan by 31 March 2027."


@pytest.fixture
def env(pg, monkeypatch, tmp_path):
    standins = tmp_path / "standins"
    (standins / "model").mkdir(parents=True)
    for key in ("ARP_ANTHROPIC_API_KEY", "ARP_GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for name, value in {
        "ENGAGEMENTS_DIR": tmp_path / "engagements", "ENGAGEMENT_STORE": "postgres", "STANDINS_DIR": standins,
        "DOCUMENTS_DIR": tmp_path / "documents", "DOCUMENT_STORE_DIR": tmp_path / "store", "CACHE_DIR": tmp_path / "cache",
        "DISCOVERY_STATE_DIR": tmp_path / "disc", "EVENT_REFRESH_ENABLED": "false",
    }.items():  # fmt: skip
        monkeypatch.setenv(f"ARP_{name}", str(value))
    caches = (get_settings, get_engagement_store, get_registry, get_document_content_store)
    for cached in caches:
        cached.cache_clear()
    yield standins
    for cached in caches:
        cached.cache_clear()


@pytest.fixture
def client(env):
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def store(pg):
    return PostgresEngagementStore(pg)


@pytest.fixture
def issue(env, store):
    _, opened = store.open_issue("C1", "Acme", theme="climate")
    return opened.issue_id


def _says(standins: Path, name: str, output) -> None:
    (standins / "model" / f"{name}.json").write_text(output if isinstance(output, str) else json.dumps({"output": output}))


def _verdict(standins, item_id, verdict="found", quote=Q):
    _says(standins, "WatchCheckDraft", {"results": [{"item_id": item_id, "verdict": verdict, "quote": quote, "reason": "r"}]})


def _calls(standins, name) -> int:
    path = standins / "calls.jsonl"
    return sum(json.loads(line).get("name") == name for line in path.read_text().splitlines()) if path.exists() else 0


def _document(name="AR2026.txt", text=f"Annual report 2026.\n{Q}\nOther matters.") -> Path:
    path = get_settings().documents_dir / "C1" / "other" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _commitment(store, issue, **kw) -> str:
    c = Commitment(text="Name a climate committee", target_date="2027-03-31", **kw)
    store.add_commitment("C1", issue, c)
    return c.commitment_id


def _objective(store, issue) -> str:
    o = Objective(description="Set a 2030 science-based target", objective_type="strategic", status="in_progress")
    store.add_objective("C1", issue, o)
    return o.objective_id


def _check(client, kind, item_id):
    return client.post(f"{URL}/watch-items/{kind}/{item_id}/check", json={"company_id": "C1"})


def _list(client, status="pending"):
    return client.get(f"{URL}/evidence-suggestions", params={"company_id": "C1", "status": status}).json()["suggestions"]


# --- The check on demand (AC-20 to AC-32) -------------------------------------------------------------


def test_check_stores_a_grounded_found_suggestion_and_changes_nothing(client, env, store, issue):
    c = _commitment(store, issue)
    _document()
    _verdict(env, c)

    r = _check(client, "commitment", c)

    assert r.status_code == 200 and r.json() == {"documents": 1, "suggestions": 1, "unclear": 0, "skipped": 0}
    [s] = _list(client)
    assert (s["kind"], s["item_kind"], s["item_id"], s["verdict"], s["doc_title"], s["quote"]) == ("evidence", "commitment", c, "found", "AR2026.txt", Q)
    assert s["engagement_id"] == issue and s["company_id"] == "C1"
    [kept] = store.get("C1").issues[0].commitments
    assert kept.status == "open" and kept.validated_by is None  # AC-26
    assert [e["event_type"] for e in store.events("C1")][-1] == "evidence_suggested"


@pytest.mark.parametrize(
    "verdict, quote",
    [("found", "The board dissolved its climate committee."), ("unclear", ""), ("found", "")],
)
def test_ungrounded_or_unclear_answers_are_counted_not_stored(client, env, store, issue, verdict, quote):
    c = _commitment(store, issue)
    _document()
    _verdict(env, c, verdict, quote)

    assert _check(client, "commitment", c).json() == {"documents": 1, "suggestions": 0, "unclear": 1, "skipped": 0}
    assert all(_list(client, s) == [] for s in ("pending", "confirmed", "rejected"))


def test_a_document_checked_before_is_skipped_even_after_a_rejection(client, env, store, issue):
    c = _commitment(store, issue)
    _document()
    _verdict(env, c)
    _check(client, "commitment", c)

    assert _check(client, "commitment", c).json() == {"documents": 1, "suggestions": 0, "unclear": 0, "skipped": 1}
    assert len(_list(client)) == 1
    client.post(f"{URL}/evidence-suggestions/{_list(client)[0]['suggestion_id']}/reject", json={"reason": "old"})
    assert _check(client, "commitment", c).json()["skipped"] == 1


def test_results_for_items_not_asked_about_are_ignored(client, env, store, issue):
    c = _commitment(store, issue)
    other = _commitment(store, issue)
    _document()
    _verdict(env, other)

    assert _check(client, "commitment", c).json() == {"documents": 1, "suggestions": 0, "unclear": 0, "skipped": 0}


def test_check_without_documents_makes_no_model_call(client, env, store, issue):
    c = _commitment(store, issue)

    assert _check(client, "commitment", c).json() == {"documents": 0, "suggestions": 0, "unclear": 0, "skipped": 0}
    assert _calls(env, "WatchCheckDraft") == 0


def test_check_reads_the_five_newest_documents(client, env, store, issue):
    c = _commitment(store, issue)
    for n in range(6):
        _document(f"R{n}.txt", f"Report {n}.\n{Q}\n")  # distinct texts: the registry dedups equal ones
    _verdict(env, c)

    assert _check(client, "commitment", c).json() == {"documents": 5, "suggestions": 5, "unclear": 0, "skipped": 0}
    assert _calls(env, "WatchCheckDraft") == 5


def test_a_failed_model_call_answers_502_and_stores_nothing(client, env, store, issue):
    c = _commitment(store, issue)
    _document()
    _says(env, "WatchCheckDraft", "{not json")

    r = _check(client, "commitment", c)

    assert (r.status_code, r.json()["detail"]) == (502, "Argus could not check the documents.")
    assert _list(client) == []


def test_objective_and_topic_checks(client, env, store, issue):
    o = _objective(store, issue)
    topic = WatchTopic(engagement_id=issue, question="Has the company named a board climate committee?")
    store.add_watch_topic("C1", issue, topic)
    _document()
    _verdict(env, o)
    assert _check(client, "objective", o).json()["suggestions"] == 1
    _verdict(env, topic.topic_id, "against")
    assert _check(client, "topic", topic.topic_id).json()["suggestions"] == 1
    kinds = {(s["item_kind"], s["verdict"]) for s in _list(client)}
    assert kinds == {("objective", "found"), ("topic", "against")}


def test_only_open_items_of_the_company_can_be_checked(client, env, store, issue):
    c = _commitment(store, issue)
    store.update_commitment_status("C1", issue, c, CommitmentStatus.VERIFIED, "dev", "seen")
    o = _objective(store, issue)
    store.record_objective_result("C1", issue, o, "achieved", "3", "done")
    for kind, item in (("commitment", c), ("objective", o)):
        r = _check(client, kind, item)
        assert (r.status_code, r.json()["detail"]) == (409, "Only open items can be checked.")
    _, other = store.open_issue("C2", "Other", theme="climate")
    theirs = Commitment(text="x", target_date="2027-01-01")
    store.add_commitment("C2", other.issue_id, theirs)
    r = _check(client, "commitment", theirs.commitment_id)  # another company's commitment
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown commitment.")


def test_a_closed_engagement_has_no_watch_items(client, env, store, issue):
    c = _commitment(store, issue)
    store.set_issue_status("C1", issue, IssueStatus.CLOSED)
    assert _check(client, "commitment", c).status_code == 409
    assert store.watch_items("C1") == []


def test_check_on_the_file_store_answers_409(env, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "file")
    get_settings.cache_clear()
    get_engagement_store.cache_clear()
    EngagementStore(tmp_path / "engagements").open_issue("C1", "Acme", theme="climate")
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    try:
        with TestClient(app) as c:
            r = c.post(f"{URL}/watch-items/commitment/cmt_x/check", json={"company_id": "C1"})
    finally:
        app.dependency_overrides.clear()
    assert (r.status_code, r.json()["detail"]) == (409, "Watch items need the Postgres engagement store.")


# --- The automatic run on discovery events (AC-49 to AC-54) --------------------------------------------


async def _discover(path: Path, sha="a" * 64, url="https://x.example/ar.txt") -> list:
    settings = get_settings()
    detector = ChangeDetector(settings.discovery_state_dir, settings.discovery_state_dir / "events.jsonl", on_events=refresh_hook(settings))
    doc = DiscoveredDocument(company_id="C1", doc_type=DocType.OTHER, url=url, local_path=str(path), sha256=sha)
    return await detector.diff_and_record(CompanyRef(company_id="C1", name="Acme"), [doc])


def _both(env, store, issue) -> tuple[str, str]:
    c, o = _commitment(store, issue), _objective(store, issue)
    _says(env, "WatchCheckDraft", {"results": [{"item_id": i, "verdict": "found", "quote": Q} for i in (c, o)]})
    return c, o


async def test_a_new_document_is_checked_against_every_watch_item(env, store, issue):
    c, o = _both(env, store, issue)
    path = _document()

    await _discover(path)

    pending = store.list_suggestions("C1", "pending")
    assert sorted(s.item_id for s in pending) == sorted([c, o]) and len({s.doc_id for s in pending}) == 1
    assert _calls(env, "WatchCheckDraft") == 1


async def test_an_updated_document_is_checked_too(env, store, issue):
    path = _document()
    await _discover(path, sha="b" * 64)  # no watch items yet: no call
    _both(env, store, issue)

    events = await _discover(path)

    assert [e.event_type for e in events] == ["updated_document"] and len(store.list_suggestions("C1", "pending")) == 2


async def test_the_setting_turns_the_automatic_check_off(env, store, issue, monkeypatch):
    monkeypatch.setenv("ARP_WATCH_CHECK_ON_NEW_DOCUMENTS", "false")
    get_settings.cache_clear()
    _both(env, store, issue)

    await _discover(_document())

    assert store.list_suggestions("C1", "pending") == [] and _calls(env, "WatchCheckDraft") == 0


async def test_a_failed_check_stops_neither_discovery_nor_refresh(env, store, issue, monkeypatch):
    monkeypatch.setenv("ARP_EVENT_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ARP_EVENT_REFRESH_SCHEMA_IDS", '["sch1"]')
    get_settings.cache_clear()
    started = []

    async def fake_refresh(events, **kw):
        started.append(events)
        return ["run1"]

    monkeypatch.setattr(refresh, "refresh_on_events", fake_refresh)
    _commitment(store, issue)
    _says(env, "WatchCheckDraft", "{not json")

    events = await _discover(_document())

    assert len(events) == 1 and store.list_suggestions("C1", "pending") == [] and len(started) == 1


async def test_an_unregistered_document_is_skipped(env, store, issue, tmp_path):
    _both(env, store, issue)
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text(Q)

    await _discover(elsewhere)

    assert store.list_suggestions("C1", "pending") == [] and _calls(env, "WatchCheckDraft") == 0


def test_hook_is_off_on_the_file_store(env, monkeypatch):
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "file")
    get_settings.cache_clear()
    assert refresh_hook(get_settings()) is None


# --- Finding commitments in notes (AC-55 to AC-64, AC-111) ---------------------------------------------


def _note(store, issue, kind="meeting", summary=NOTE) -> str:
    entry = CorrespondenceEntry(type=kind, date="2026-10-01T09:00:00+00:00", summary=summary)
    store.add_correspondence("C1", issue, entry)
    return entry.entry_id


def _found(env, quote=PROMISE, target_date="2027-03-31"):
    _says(env, "CommitmentFindDraft", {"commitments": [{"text": "Publish a transition plan", "quote": quote, "target_date": target_date}]})


def _find(client, activity_id):
    return client.post(f"{URL}/activities/{activity_id}/find-commitments")


def test_find_stores_a_grounded_commitment_and_adds_none(client, env, store, issue):
    a = _note(store, issue)
    _found(env)

    assert _find(client, a).json() == {"suggestions": 1, "ungrounded": 0, "skipped": 0}
    [s] = _list(client)
    assert (s["kind"], s["text"], s["target_date"], s["quote"], s["activity_id"]) == ("new_commitment", "Publish a transition plan", "2027-03-31", PROMISE, a)
    assert store.get("C1").issues[0].commitments == []  # AC-60
    assert _find(client, a).json() == {"suggestions": 0, "ungrounded": 0, "skipped": 1}  # AC-59


@pytest.mark.parametrize("quote", ["The CEO promised a new climate policy.", "€" * 667])  # 2,001 bytes
def test_find_drops_ungrounded_and_overlong_quotes(client, env, store, issue, quote):
    a = _note(store, issue, summary=NOTE + " " + "€" * 667)
    _found(env, quote=quote)

    assert _find(client, a).json() == {"suggestions": 0, "ungrounded": 1, "skipped": 0}


def test_find_stores_a_date_that_is_not_iso_as_null(client, env, store, issue):
    _found(env, target_date="31.03.2027")
    _find(client, _note(store, issue))
    assert _list(client)[0]["target_date"] is None


def test_find_only_reads_calls_and_meetings(client, env, store, issue):
    r = _find(client, _note(store, issue, kind="email"))
    assert (r.status_code, r.json()["detail"]) == (409, "Commitments are only looked for in call and meeting notes.")
    r = _find(client, "act_unknown")
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown activity.")


def test_confirming_a_found_commitment_adds_it(client, env, store, issue):
    a = _note(store, issue)
    _found(env, target_date=None)
    _find(client, a)
    sid = _list(client)[0]["suggestion_id"]

    assert client.post(f"{URL}/evidence-suggestions/{sid}/confirm", json={}).json()["detail"] == "A due date is required to add a commitment."
    r = client.post(f"{URL}/evidence-suggestions/{sid}/confirm", json={"target_date": "2027-03-31"})

    assert r.status_code == 200
    [added] = store.get("C1").issues[0].commitments
    assert (added.text, added.target_date, added.made_at[:10], added.recorded_by) == ("Publish a transition plan", "2027-03-31", "2026-10-01", PRINCIPAL.name)
    assert _list(client, "confirmed")[0]["created_commitment_id"] == added.commitment_id


def test_a_found_commitment_on_a_closed_engagement_is_refused(client, env, store, issue):
    """AC-111 (owner decision of 14 Nov 2026)."""
    _found(env)
    _find(client, _note(store, issue))
    sid = _list(client)[0]["suggestion_id"]
    for status in (IssueStatus.RESOLVED, IssueStatus.CLOSED):
        store.set_issue_status("C1", issue, status)

        r = client.post(f"{URL}/evidence-suggestions/{sid}/confirm", json={"target_date": "2027-03-31"})

        assert (r.status_code, r.json()["detail"]) == (409, "This engagement is closed. Reopen it to add a commitment.")
        assert store.get("C1").issues[0].commitments == [] and _list(client)[0]["status"] == "pending"


# --- Carried over from the reviews of #456 ----------------------------------------------------------


def test_evidence_text_without_a_title():
    base = {"kind": "evidence", "company_id": "C1", "engagement_id": "e", "quote": Q}
    assert evidence_text(EvidenceSuggestion(**base, page=4)) == f'page 4: "{Q}"'
    assert evidence_text(EvidenceSuggestion(**base)) == f'"{Q}"'
    assert evidence_text(EvidenceSuggestion(**base, doc_title="AR 2026.pdf", page=4)) == f'AR 2026.pdf, page 4: "{Q}"'


def test_a_found_commitment_without_its_note_is_still_added(client, env, store, issue):
    s = EvidenceSuggestion(kind="new_commitment", company_id="C1", engagement_id=issue, text="Publish a plan", target_date="2027-03-31", quote=Q)
    with transaction(store.dsn) as session:  # written directly: add_suggestions refuses a row without its note
        session.add(StwEvidenceSuggestionModel(**s.model_dump(exclude={"created_at"})))

    r = client.post(f"{URL}/evidence-suggestions/{s.suggestion_id}/confirm", json={})

    assert r.status_code == 200 and store.get("C1").issues[0].commitments[0].text == "Publish a plan"


def test_a_suggestion_must_match_its_items_company_and_engagement(env, store, issue):
    c = _commitment(store, issue)
    _, other = store.open_issue("C2", "Other", theme="climate")
    wrong = [
        EvidenceSuggestion(kind="evidence", company_id="C1", engagement_id=other.issue_id, item_kind="commitment", item_id=c, doc_id="d", quote=Q),
        EvidenceSuggestion(kind="evidence", company_id="C2", engagement_id=issue, item_kind="commitment", item_id=c, doc_id="d", quote=Q),
    ]
    for s in wrong:
        with pytest.raises(ValueError, match="does not match"):
            store.add_suggestions(s.company_id, [s])
    assert store.list_suggestions("C1", "pending") == [] and store.list_suggestions("C2", "pending") == []


# --- Golden command ---------------------------------------------------------------------------------


def test_watch_golden_scores_check_cases(env, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ar.txt").write_text(f"Intro.\n{Q}\n")
    cases = [
        {"id": "c1", "document": "ar.txt", "item_kind": "topic", "text": "Committee?", "proof_statement": None, "label": "found"},
        {"id": "c2", "document": "ar.txt", "item_kind": "objective", "text": "Pay", "proof_statement": None, "label": "silent"},
    ]
    (tmp_path / "cases.json").write_text(json.dumps({"check": cases, "find": []}))
    # one stand-in answers both cases: c1's result counts on c1, the c2 call answers for c1 too and is ignored
    _says(env, "WatchCheckDraft", {"results": [{"item_id": "c1", "verdict": "found", "quote": Q}]})
    args = ["stewardship", "watch-golden", "--kind", "check", "--cases", str(tmp_path / "cases.json"), "--documents-dir", str(tmp_path / "docs")]

    ok = CliRunner().invoke(cli, [*args, "--min-precision", "1", "--min-coverage", "1"])
    low = CliRunner().invoke(cli, [*args, "--min-precision", "1.01", "--min-coverage", "0"])

    assert ok.exit_code == 0 and ok.stdout.strip() == "precision 1.00, coverage 1.00", ok.output
    assert low.exit_code == 1


def test_watch_golden_scores_find_cases(env, tmp_path):
    cases = [{"id": "f1", "activity_type": "meeting", "note": NOTE, "key_phrases": ["publish a transition plan", "name a pay committee"]}]
    (tmp_path / "cases.json").write_text(json.dumps({"check": [], "find": cases}))
    _found(env)

    r = CliRunner().invoke(cli, ["stewardship", "watch-golden", "--kind", "find", "--cases", str(tmp_path / "cases.json"),
                                 "--documents-dir", str(tmp_path), "--min-precision", "0.8", "--min-coverage", "0.7"])  # fmt: skip

    assert r.exit_code == 1 and r.stdout.strip() == "precision 1.00, coverage 0.50"


def test_golden_set_shape():
    """The spec's minimums, and every labelled quote and key phrase is really in its document or note."""
    golden = Path(__file__).parent / "golden" / "watch_check"
    cases = json.loads((golden / "cases.json").read_text())
    check, find = cases["check"], cases["find"]
    assert len(check) >= 24 and len(find) >= 10
    assert all(sum(c["label"] == label for c in check) >= 6 for label in ("found", "against", "silent"))
    assert sum(c["item_kind"] == "objective" for c in check) >= 6
    squash = lambda t: " ".join(t.split())  # noqa: E731
    for c in check:
        text = squash((golden / "documents" / c["document"]).read_text())
        DocType(c["doc_type"])
        assert (c["evidence"] is None) == (c["label"] == "silent") and (c["evidence"] is None or squash(c["evidence"]) in text), c["id"]
    for c in find:
        assert c["activity_type"] in ("call", "meeting") and all(k.lower() in c["note"].lower() for k in c["key_phrases"]), c["id"]


async def test_one_failed_document_does_not_stop_the_next(env, store, issue, monkeypatch):
    c = _commitment(store, issue)
    _verdict(env, c)
    real, seen = watch_check.check_documents, []

    async def first_fails(store_, llm, company_id, items, docs, fuzzy):
        seen.append(docs[0].title)
        if len(seen) == 1:
            raise watch_check.ArgusFailed("timeout")
        return await real(store_, llm, company_id, items, docs, fuzzy)

    monkeypatch.setattr(watch_check, "check_documents", first_fails)
    settings = get_settings()
    detector = ChangeDetector(settings.discovery_state_dir, settings.discovery_state_dir / "events.jsonl", on_events=refresh_hook(settings))
    docs = [
        DiscoveredDocument(company_id="C1", doc_type=DocType.OTHER, url=f"https://x.example/{n}", local_path=str(_document(f"{n}.txt", f"{n}.\n{Q}\n")), sha256=n * 64)
        for n in ("a", "b")
    ]

    await detector.diff_and_record(CompanyRef(company_id="C1", name="Acme"), docs)

    assert len(seen) == 2 and len(store.list_suggestions("C1", "pending")) == 1


def test_evidence_on_an_item_closed_meanwhile_is_skipped(env, store, issue):
    c = _commitment(store, issue)
    s = EvidenceSuggestion(kind="evidence", company_id="C1", engagement_id=issue, item_kind="commitment", item_id=c, doc_id="d", quote=Q)
    store.update_commitment_status("C1", issue, c, CommitmentStatus.VERIFIED, "dev", "seen")

    assert store.add_suggestions("C1", [s]) == (0, 1) and store.list_suggestions("C1", "pending") == []


# --- Review fixes (spec commitment-loop-review-fixes): an objective without a description ------------------------


def _blank_objectives(store, issue) -> tuple[str, str]:
    """Two in-progress objectives, one with description "" and one with NULL, written directly (intake refuses both)."""
    empty, null = _objective(store, issue), _objective(store, issue)
    with transaction(store.dsn) as session:
        session.get(StwObjectiveModel, empty).description = ""
        session.get(StwObjectiveModel, null).description = None
    return empty, null


def test_blank_descriptions_are_watch_items_ac9(env, store, issue):
    empty, null = _blank_objectives(store, issue)
    items = {i.item_id: i.text for i in store.watch_items("C1") if i.item_kind == "objective"}
    assert items == {empty: "", null: ""}


def test_blank_descriptions_read_as_empty_on_the_record_ac10(client, env, store, issue):
    empty, null = _blank_objectives(store, issue)
    r = client.get("/api/engagement/records/C1")
    assert r.status_code == 200, r.text
    (i,) = r.json()["issues"]
    assert {o["objective_id"]: o["description"] for o in i["objectives"]} == {empty: "", null: ""}


def test_check_on_an_objective_with_a_null_description_ac11(client, env, store, issue):
    _, null = _blank_objectives(store, issue)
    _document()
    _verdict(env, null, "unclear", quote="")
    r = _check(client, "objective", null)
    assert (r.status_code, r.json()) == (200, {"documents": 1, "suggestions": 0, "unclear": 1, "skipped": 0})


async def test_automatic_check_with_blank_descriptions_ac12(env, store, issue):
    c = _commitment(store, issue)
    _blank_objectives(store, issue)
    _verdict(env, c)
    path = _document()

    await _discover(path)

    (s,) = store.list_suggestions("C1", "pending")
    assert (s.item_kind, s.item_id) == ("commitment", c) and s.doc_id
