from __future__ import annotations

import pytest
import typer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal
from arp.api.deps import get_stream_store
from arp.api.review_endpoints import submit_review
from arp.api.routers import stewardship as stewardship_router
from arp.cli._shared import cli_principal
from arp.config import Settings
from arp.orchestration.review_queue import latest_decisions, record_review_decision
from arp.stewardship.process import StreamStore
from arp.storage.run_store import RunStore
from tests.conftest import PRINCIPAL


@pytest.fixture
def run_store(tmp_path):
    return RunStore(tmp_path / "runs")


def test_decision_row_records_user_id_and_role(run_store):
    record_review_decision(run_store, "r1", "k", "approve", "ignored", None, principal=PRINCIPAL)
    row = latest_decisions(run_store, "r1")["k"]
    assert (row["user_id"], row["role"], row["reviewer"]) == ("u_test", "approver", "Test")


def test_escalate_is_accepted(run_store):
    submit_review(run_store, "r1", item_key="k", decision="escalate", edited_value=None, principal=PRINCIPAL)
    assert latest_decisions(run_store, "r1")["k"]["decision"] == "escalate"


def test_old_decision_rows_without_user_id_still_load(run_store):
    run_store.append_jsonl(run_store.review_decisions_path("r1"), {"item_key": "k", "decision": "approve", "reviewer": "old"})
    row = latest_decisions(run_store, "r1")["k"]
    assert row["reviewer"] == "old" and "user_id" not in row


def test_cli_principal_requires_token(tmp_path, monkeypatch):
    users = tmp_path / "users.json"
    users.write_text('{"users": [{"token": "t1", "user_id": "u1", "name": "Una", "role": "analyst"}]}')
    settings = Settings(users_file=users)
    monkeypatch.delenv("ARP_CLI_TOKEN", raising=False)
    with pytest.raises(typer.Exit):
        cli_principal(settings)
    monkeypatch.setenv("ARP_CLI_TOKEN", "t1")
    assert cli_principal(settings) == Principal(user_id="u1", name="Una", role="analyst")
    monkeypatch.setenv("ARP_CLI_TOKEN", "nope")
    with pytest.raises(typer.Exit):
        cli_principal(settings)


def test_stewardship_approved_by_comes_from_principal(tmp_path):
    from arp.api.auth import current_user

    streams = StreamStore(tmp_path / "streams")
    app = FastAPI()
    app.include_router(stewardship_router.router)
    app.dependency_overrides[get_stream_store] = lambda: streams
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        # Another user saved v1; the body's `approved_by` must not be able to impersonate them.
        r = c.post("/api/stewardship/policies/house_voting/activate", json={"version": 0, "approved_by": "Mallory"})
        assert r.status_code == 200
        assert r.json()["approved_by"] == "u_test"


def test_engagement_sent_by_comes_from_principal(tmp_path):
    from arp.api.auth import current_user
    from arp.api.deps import get_engagement_store
    from arp.api.routers import engagement as engagement_router
    from arp.storage.engagement_store import EngagementStore

    store = EngagementStore(tmp_path / "eng")
    _, issue = store.open_issue("ACME", "Acme", theme="climate_transition")
    app = FastAPI()
    app.include_router(engagement_router.router)
    app.dependency_overrides[get_engagement_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        r = c.post(
            f"/api/engagement/records/ACME/issues/{issue.issue_id}/log-outreach-sent",
            json={"summary": "letter", "sent_by": "Mallory"},
        )
    assert r.status_code == 200, r.text
    assert "Mallory" not in r.text and "Test" in r.text


def test_draft_sent_by_comes_from_principal(tmp_path):
    from arp.api.routers.stewardship import SentRequest, mark_draft_sent
    from arp.schemas.engagement import CorrespondenceType
    from arp.stewardship import drafting
    from arp.storage.engagement_store import EngagementStore

    streams = StreamStore(tmp_path / "streams")
    eng = EngagementStore(tmp_path / "eng")
    _, issue = eng.open_issue("ACME", "Acme", theme="climate_transition")
    drafts = stewardship_router._drafts(streams)
    d = drafting.create(drafts, eng, stewardship_router._blocklist(streams), company_id="ACME", issue_id=issue.issue_id, type=CorrespondenceType.LETTER, text="Dear board", created_by="author")
    drafting.approve(drafts, d["draft_id"], "approver_x")
    out = mark_draft_sent(d["draft_id"], SentRequest(**{"sent_by": "Mallory"}), streams, eng, PRINCIPAL)
    assert out["history"][-1]["by"] == "u_test"


def test_cli_decision_import_has_no_by_option_and_uses_principal(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from arp.cli.decision import decision_app

    monkeypatch.delenv("ARP_CLI_TOKEN", raising=False)
    f = tmp_path / "t.json"
    f.write_text("{}")
    assert CliRunner().invoke(decision_app, ["import", str(f), "--by", "x"]).exit_code != 0  # option gone
    res = CliRunner().invoke(decision_app, ["import", str(f)])
    assert res.exit_code == 1 and "ARP_CLI_TOKEN" in res.output
