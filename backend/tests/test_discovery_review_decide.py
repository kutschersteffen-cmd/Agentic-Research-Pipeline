"""A reviewer's decision on a discovered document keeps or drops it
(spec: discovery-review-queue; AC-11..30, Review Focus 2, 3, 5)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.discovery import crawler, downloader
from arp.discovery.downloader import CAPTURE_LOG
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.schemas.common import CompanyRef
from arp.storage.document_blob_store import blob_store_for
from tests.discovery_review_support import C1, C2, URL_A, URL_B, Bodies, run_discovery_for, sha, site

pytestmark = pytest.mark.usefixtures("pg")
ALICE = Principal(user_id="u_alice", name="Alice", role="analyst")
BOB = Principal(user_id="u_bob", name="Bob", role="analyst")
CAROL = Principal(user_id="u_carol", name="Carol", role="approver")
APPROVE = {"decision": "approve", "reason_code": "confirmed"}
REJECT = {"decision": "reject", "reason_code": "wrong_entity"}


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    for module in (crawler, downloader):
        monkeypatch.setattr(module, "ssrf_guard_request_hook", noop)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def bodies(tmp_path):
    return Bodies(tmp_path)


def _transport(bodies, requests=None):
    return site({"c2.example": {URL_A: bodies.b1, URL_B: bodies.b2}}, requests)


class Env:
    def __init__(self, rs, run_id, settings, bodies):
        self.rs, self.run_id, self.settings, self.bodies = rs, run_id, settings, bodies
        self.key1, self.key2 = f"discovered:C2:{sha(bodies.b1)}", f"discovered:C2:{sha(bodies.b2)}"
        app.dependency_overrides[get_run_store] = lambda: rs
        app.dependency_overrides[get_document_content_store] = lambda: None
        app.dependency_overrides[settings_dep] = lambda: settings

    def client(self, who):
        app.dependency_overrides[current_user] = lambda: who
        return TestClient(app)

    def decide(self, who, body, key=None, run_id=None):
        key, run_id = key or self.key1, run_id or self.run_id
        c = self.client(who)
        etag = c.get(f"/api/review/runs/{run_id}/items/{key}/context").json()["etag"]
        return c.post(f"/api/review/runs/{run_id}/items/{key}/decision", json={**body, "context_etag": etag})

    def context(self, key=None):
        r = self.client(ALICE).get(f"/api/review/runs/{self.run_id}/items/{key or self.key1}/context")
        assert r.status_code == 200, r.text
        return r.json()

    def manifest(self, company="C2"):
        return json.loads((self.settings.discovery_state_dir / f"{company}.json").read_text())

    def payload(self, key=None):
        return self.context(key)["item"]["payload"]


@pytest.fixture
async def env(tmp_path, pg, bodies):
    rs, run_id, settings = await run_discovery_for(tmp_path, pg, [C1, C2], _transport(bodies), second_review_sample_rate=0.0)
    return Env(rs, run_id, settings, bodies)


def _tree_hashes(*roots: Path) -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for r in roots for p in sorted(r.rglob("*")) if p.is_file()}


async def test_reject_drops_the_document(env, tmp_path):
    local = Path(env.payload()["local_path"])
    captures = (env.settings.documents_dir / CAPTURE_LOG).read_text().count("\n")
    r = env.decide(ALICE, REJECT)
    assert r.status_code == 200, r.text
    ctx = env.context()
    assert (ctx["state"], ctx["item"]["decision"]["decision"]) == ("final", "reject")  # AC-11, AC-33 basis
    assert not local.exists()  # AC-12
    [moved] = list((env.settings.documents_dir / "_rejected" / "C2" / "10-K").iterdir())  # AC-13
    assert sha(moved.read_bytes()) == sha(env.bodies.b1)
    assert env.manifest()[URL_A]["review"] == "rejected"  # AC-14
    docs = await LocalFileDocumentSource(env.settings.documents_dir).fetch(C2)  # AC-15
    assert all(sha(Path(d.local_path).read_bytes()) != sha(env.bodies.b1) for d in docs)
    assert blob_store_for(IndexingConfig.from_settings(env.settings)).exists(sha(env.bodies.b1))  # AC-16
    assert (env.settings.documents_dir / CAPTURE_LOG).read_text().count("\n") == captures  # AC-16b


async def test_rejected_document_is_not_fetched_or_queued_again(env, tmp_path, pg, bodies):
    env.decide(ALICE, REJECT)
    requests: list[str] = []
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C2], _transport(bodies, requests), run_store=env.rs)
    assert URL_A not in requests  # AC-17
    assert f"discovered:C2:{sha(bodies.b1)}" not in {q["item_key"] for q in rs.read_review_queue(run_id)}  # AC-19


async def test_rejected_bytes_at_a_new_url_are_not_kept(env, tmp_path, pg, bodies):
    env.decide(ALICE, REJECT)
    copy = "https://c2.example/copy.pdf"
    transport = site({"c2.example": {copy: bodies.b1}})
    await run_discovery_for(tmp_path, pg, [C2], transport, run_store=env.rs)
    kept = [p for p in (env.settings.documents_dir / "C2").rglob("*.pdf") if p.read_bytes() == bodies.b1]
    assert kept == []  # AC-18


async def test_approve_keeps_and_is_not_queued_again(env, tmp_path, pg, bodies):
    local = Path(env.payload()["local_path"])
    assert env.decide(ALICE, APPROVE).status_code == 200
    assert env.manifest()[URL_A]["review"] == "approved"  # AC-20
    assert local.exists()  # AC-21
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C2], _transport(bodies), run_store=env.rs)
    keys = {q["item_key"] for q in rs.read_review_queue(run_id)}
    assert env.key1 not in keys  # AC-22: same URL, same bytes
    assert env.key2 in keys


async def test_approve_clears_when_bytes_change(env, tmp_path, pg, bodies):
    env.decide(ALICE, APPROVE)
    from tests.discovery_review_support import LONG_TEXT, make_pdf_bytes

    b5 = make_pdf_bytes(tmp_path, "b5.pdf", [LONG_TEXT, "Unrelated Group Gamma"])
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C2], site({"c2.example": {URL_A: b5}}), run_store=env.rs)
    assert f"discovered:C2:{sha(b5)}" in {q["item_key"] for q in rs.read_review_queue(run_id)}  # AC-23
    assert env.manifest()[URL_A]["review"] is None


async def test_first_of_two_reviews_does_nothing_yet(tmp_path, pg, bodies):
    rs, run_id, settings = await run_discovery_for(tmp_path, pg, [C2], _transport(bodies), second_review_sample_rate=1.0)
    env = Env(rs, run_id, settings, bodies)
    local = Path(env.payload()["local_path"])
    r = env.decide(ALICE, APPROVE)
    assert r.json()["state"] == "first_done"  # AC-24
    assert local.exists()  # AC-24b
    assert env.manifest()[URL_A].get("review") is None  # AC-25


async def test_undecided_changes_nothing(env):
    assert Path(env.payload()["local_path"]).exists()  # AC-26
    assert env.manifest()[URL_A].get("review") is None  # AC-27


async def test_no_documents_item_decisions(env):
    before = _tree_hashes(env.settings.documents_dir, env.settings.discovery_state_dir)
    r = env.decide(ALICE, REJECT, key="no_documents:C1")
    assert r.status_code == 422 and r.json()["detail"] == "reject is not a decision for a no_documents item"  # AC-28
    assert env.decide(ALICE, APPROVE, key="no_documents:C1").json()["state"] == "final"  # AC-29
    assert _tree_hashes(env.settings.documents_dir, env.settings.discovery_state_dir) == before  # AC-30


async def test_reject_when_file_already_gone_still_marks_manifest(env):
    Path(env.payload()["local_path"]).unlink()  # Review Focus 2
    assert env.decide(ALICE, REJECT).json()["state"] == "final"
    assert env.manifest()[URL_A]["review"] == "rejected"


async def test_disagreement_resolved_by_approver_decides(tmp_path, pg, bodies):
    rs, run_id, settings = await run_discovery_for(tmp_path, pg, [C2], _transport(bodies), second_review_sample_rate=1.0)
    env = Env(rs, run_id, settings, bodies)
    local = Path(env.payload()["local_path"])
    env.decide(ALICE, APPROVE)  # Review Focus 3: first approves, second rejects, approver resolves reject
    assert env.decide(BOB, REJECT).json()["state"] == "disagreed"
    assert local.exists()
    assert env.decide(CAROL, REJECT).json()["state"] == "final"
    assert not local.exists() and env.manifest()[URL_A]["review"] == "rejected"


async def test_approve_after_reject_is_ignored_and_reject_after_approve_moves(env):
    # Flipping a final decision is a new round that a second reviewer must confirm (spec question 2).
    env.decide(ALICE, REJECT)
    assert env.decide(ALICE, APPROVE).json()["state"] == "first_done"
    assert env.decide(BOB, APPROVE).json()["state"] == "second_done"  # approve is now effective: the file stays dropped
    assert env.manifest()[URL_A]["review"] == "rejected"
    local2 = Path(env.payload(env.key2)["local_path"])
    env.decide(ALICE, APPROVE, key=env.key2)
    env.decide(BOB, APPROVE, key=env.key2)
    assert env.manifest()[URL_B]["review"] == "approved" and local2.exists()
    env.decide(ALICE, REJECT, key=env.key2)
    assert env.decide(BOB, REJECT, key=env.key2).json()["state"] == "second_done"
    assert env.manifest()[URL_B]["review"] == "rejected" and not local2.exists()


async def test_company_id_with_dash_and_dot(tmp_path, pg, bodies):
    c = CompanyRef(company_id="C-2.x", name="Second Co", country="DE", website="https://c2.example/")
    rs, run_id, settings = await run_discovery_for(tmp_path, pg, [c], _transport(bodies))
    env = Env(rs, run_id, settings, bodies)
    key = f"discovered:C-2.x:{sha(bodies.b1)}"
    local = Path(env.payload(key)["local_path"])
    assert env.decide(ALICE, REJECT, key=key).json()["state"] == "final"  # Review Focus 5
    assert not local.exists()
    assert env.manifest("C-2.x")[URL_A]["review"] == "rejected"
    assert (settings.documents_dir / "_rejected" / "C-2.x" / "10-K").is_dir()
