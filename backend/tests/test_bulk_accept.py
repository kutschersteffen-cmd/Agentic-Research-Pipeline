from __future__ import annotations

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.review.context import _state
from arp.schemas.common import RunManifest
from arp.schemas.datapoints import DataPointSchema, FieldDefinition
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry

ALICE = Principal(user_id="u_alice", name="Alice Reviewer", role="analyst")
VIEWER = Principal(user_id="u_vic", name="Vic Viewer", role="viewer")
PASS = [{"check_id": "format.data_type", "layer": 1, "outcome": "pass", "severity": "info"}]
FAIL = [{"check_id": "numeric.in_span", "layer": 2, "outcome": "fail", "severity": "block", "detail": "x"}]


def key(i: int, field_id: str = "f1") -> str:
    return f"ISS{i}:{field_id}:2024-12-31"


def _field(field_id: str, checks: list) -> dict:
    return {"field_id": field_id, "field_name": field_id, "value": 100, "confidence": 0.7, "period_end": "2024-12-31",
            "checks": checks, "route_reasons": ["low_confidence"]}


@pytest.fixture
def env(tmp_path):
    rs = RunStore(tmp_path / "runs")
    settings = Settings(schema_registry_dir=tmp_path / "reg", second_review_sample_rate=0.0)
    schema = DataPointSchema(schema_id="sch1", name="s", fields=[
        FieldDefinition(field_id="f1", name="f1", description="d", data_type="number", extraction_instructions="x"),
        FieldDefinition(field_id="f2", name="f2", description="d", data_type="number", extraction_instructions="x",
                        high_risk=True),
        FieldDefinition(field_id="f3", name="f3", description="d", data_type="number", extraction_instructions="x"),
    ])
    reg = SchemaRegistry(settings.schema_registry_dir)
    released = reg.release(reg.save(schema).schema_id, 1)
    reg.record_first_audit("f1", 1, "auditor")  # f3 stays unaudited
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    (rs.run_dir("ext1") / "schema.json").write_text(released.model_dump_json())
    for i in range(11):
        fields = [_field("f1", FAIL if i == 10 else PASS), _field("f2", PASS), _field("f3", PASS)]
        for f in fields:
            rs.append_jsonl(rs._review_queue_path("ext1"), {
                "item_key": key(i, f["field_id"]), "issuer_key": f"ISS{i}", "company_id": f"C{i}", "name": f"Co{i}",
                "field_id": f["field_id"], "period_end": "2024-12-31", "field": f, "route_reasons": f["route_reasons"],
            })
        rs.append_jsonl(rs._results_path("ext1"), {
            "company_id": f"C{i}", "name": f"Co{i}", "issuer_key": f"ISS{i}", "schema_id": "sch1", "run_id": "ext1",
            "fields": fields, "documents": [],
        })
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[get_document_content_store] = lambda: DocumentContentStore(tmp_path / "docs")
    app.dependency_overrides[settings_dep] = lambda: settings
    yield rs, settings
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def client(who=ALICE):
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def items(c, keys):
    out = []
    for k in keys:
        r = c.get(f"/api/review/runs/ext1/items/{k}/context")
        assert r.status_code == 200, r.text
        out.append({"item_key": k, "context_etag": r.json()["etag"]})
    return out


def bulk(c, body_items):
    return c.post("/api/extraction/items/bulk-accept", json={"run_id": "ext1", "items": body_items})


def log_bytes(rs):
    p = rs._review_decisions_path("ext1")
    return p.read_bytes() if p.exists() else b""


def _rejected(rs, keys, offending, why, body_items=None):
    c = client()
    before = log_bytes(rs)
    r = bulk(c, body_items or items(c, keys))
    assert r.status_code == 409, r.text
    assert offending in r.json()["detail"] and why in r.json()["detail"]
    assert log_bytes(rs) == before


def test_high_risk_item_rejects_whole_call(env):
    _rejected(env[0], [key(0), key(1, "f2"), key(2)], key(1, "f2"), "high-risk")


def test_failing_check_rejects_whole_call(env):
    _rejected(env[0], [key(0), key(10), key(2)], key(10), "failing check")


def test_stale_etag_rejects_whole_call(env):
    c = client()
    body = items(c, [key(0), key(1), key(2)])
    body[1]["context_etag"] = "stale"
    _rejected(env[0], [], key(1), "changed", body)


def test_all_low_risk_accepted_with_sample(env):
    keys = [key(i) for i in range(10)]
    c = client()
    r = bulk(c, items(c, keys))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["accepted"] == 10 and len(out["second_review"]) >= 1
    for k in keys:
        s = _state(env[0], "ext1", k)
        assert s.first["decision"] == "approve" and s.first["snapshot_id"]
        if k in out["second_review"]:
            assert s.state == "first_done" and s.first["second_reasons"] == ["bulk_sample"]
        else:
            assert s.state == "final" and not s.first["second_required"]


def test_bulk_requires_analyst(env):
    c = client(VIEWER)
    r = bulk(c, [{"item_key": key(0), "context_etag": "x"}])
    assert r.status_code == 403
    assert log_bytes(env[0]) == b""


def test_bulk_decisions_have_no_user_id_in_response(env):
    c = client()
    r = bulk(c, items(c, [key(0), key(1)]))
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"accepted", "second_review"}
    assert "u_alice" not in r.text and "user_id" not in r.text


def test_rate_zero_samples_exactly_the_smallest_hash(env):
    env[1].bulk_accept_sample_rate = 0.0
    keys = [key(i) for i in range(10)]
    c = client()
    r = bulk(c, items(c, keys))
    assert r.status_code == 200, r.text
    assert r.json()["second_review"] == [min(keys, key=lambda k: sha256(k.encode()).hexdigest())]


def test_prior_run_value_change_forces_second_review(env):
    rs = env[0]
    rs.save_manifest(RunManifest(run_id="old", run_type="extraction", created_at="2020-01-01T00:00:00+00:00"))
    rs.append_jsonl(rs._results_path("old"), {"company_id": "C0", "issuer_key": "ISS0", "run_id": "old",
                                             "fields": [{**_field("f1", PASS), "value": 999, "route_reasons": []}]})
    env[1].bulk_accept_sample_rate = 0.0
    keys = [key(0), key(1)]
    c = client()
    r = bulk(c, items(c, keys))
    assert r.status_code == 200, r.text
    assert key(0) in r.json()["second_review"]
    s = _state(rs, "ext1", key(0))
    assert s.state == "first_done" and "published_change" in s.first["second_reasons"]


def test_first_audit_pending_forces_second_review(env):
    keys = [key(0, "f3"), key(1, "f3")]
    c = client()
    r = bulk(c, items(c, keys))
    assert r.status_code == 200, r.text
    assert r.json()["second_review"] == keys
    for k in keys:
        s = _state(env[0], "ext1", k)
        assert s.state == "first_done" and "first_audit_pending" in s.first["second_reasons"]


def test_items_of_one_company_do_not_stale_each_other(env):
    """An item's etag folds in only its own decisions, so writing one item leaves the next one valid."""
    c = client()
    body = items(c, [key(0), key(0, "f3")])
    r = bulk(c, body)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 2
    assert {row["item_key"] for row in env[0].read_jsonl(env[0]._review_decisions_path("ext1"))} == {key(0), key(0, "f3")}


def test_duplicate_key_rejects_whole_call(env):
    c = client()
    body = items(c, [key(0), key(1)])
    _rejected(env[0], [], "listed twice", "nothing", [*body, body[0]])


def test_escalated_item_rejects_whole_call(env):
    c = client()
    [esc] = items(c, [key(1)])
    r = c.post(f"/api/review/runs/ext1/items/{key(1)}/decision",
               json={"decision": "escalate", "reason_code": "other", "context_etag": esc["context_etag"]})
    assert r.status_code == 200, r.text
    _rejected(env[0], [key(0), key(1)], key(1), "escalated")


def test_span_moved_never_decided_item_rejects_whole_call(env):
    from arp.orchestration.reground import _reopen

    _reopen(env[0], "ext1", key(1), "old", "new")  # what re-grounding does for a moved span, no decision yet
    _rejected(env[0], [key(0), key(1)], key(1), "escalated")
