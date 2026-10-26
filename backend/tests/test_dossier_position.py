"""Dossier step 5: position -> standards -> extraction -> check, with the model answered by the test stand-ins."""

import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from arp import standins
from arp.api import deps, run_scheduling
from arp.api.auth import Principal, authorize, current_user, load_users
from arp.api.deps import (
    get_engagement_store,
    get_extraction_starter,
    get_run_store,
    get_stream_store,
    get_taxonomy_store,
    settings_dep,
)
from arp.api.main import app
from arp.config import Settings
from arp.db import models as m
from arp.db.fields import SchemaRegistry
from arp.db.session import engine
from arp.research.pipeline import create_theme_run
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.datapoints import DataPointSchema, FieldDefinition
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.stewardship.policies import PolicyStore
from arp.stewardship.process import StreamStore
from arp.stewardship.trigger_store import TriggerStore
from arp.storage.engagement_store import EngagementStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.themes.position import PositionDraft, PositionParagraph, PositionStore
from arp.themes.research import NoteItem, NoteSections, ResearchNote, ResearchRound, ResearchStore

USERS = {"own": Principal(user_id="own", name="own", role="approver"), "ana": Principal(user_id="ana", name="ana", role="analyst"),
         "vic": Principal(user_id="vic", name="vic", role="viewer")}
P_OK = {"summary": "Grid build-out", "paragraphs": [{"text": "Permits and capex.", "cites": ["R1", "O1"]},
                                                     {"text": "Supply chains.", "cites": ["R2"]}]}
NEW = {"field_id": "fld_plan", "name": "Board-approved transition plan", "description": "d", "data_type": "boolean",
       "extraction_instructions": "x"}


def _std(sid, field, op, value, severity, data="existing", title=None):
    return {"standard_id": sid, "title": title or f"{sid} title", "expectation": "e", "definition": "d",
            "where_reported": "annual report", "rests_on": [1], "severity": severity, "field_id": field, "operator": op,
            "value": value, "data": data}


S1 = _std("S1", "fld_scope3", "==", True, "high", title="Scope 3 emissions disclosed")
S2 = _std("S2", "fld_grid_capex", ">=", 20, "medium")
S3 = _std("S3", "fld_plan", "==", True, "low", data="new")
S_OK = {"standards": [S1, S2, S3], "new_fields": [NEW]}
S_TWO = {"standards": [S1, S2], "new_fields": []}


def _fields(pg):
    registry = SchemaRegistry(pg)
    base = registry.save(DataPointSchema(schema_id="base", name="base", fields=[
        FieldDefinition(field_id="fld_scope3", name="Scope 3 emissions disclosed", description="d", data_type="boolean",
                        extraction_instructions="x"),
        FieldDefinition(field_id="fld_grid_capex", name="Grid capex share", description="d", data_type="percentage",
                        unit="%", extraction_instructions="x"),
        FieldDefinition(field_id="fld_rating", name="Rating", description="d", data_type="enum", allowed_values=["A", "B", "C"],
                        extraction_instructions="x"),
        FieldDefinition(field_id="fld_name", name="Name", description="d", data_type="string", extraction_instructions="x"),
    ]))
    registry.release(base.schema_id, base.version, released_by="own")
    registry.save(DataPointSchema(schema_id="drafts", name="drafts", fields=[
        FieldDefinition(field_id="fld_draft", name="Draft", description="d", data_type="number", extraction_instructions="x")]))


def _company(pg, name) -> uuid.UUID:
    with Session(engine(pg)) as s, s.begin():
        c = m.Company(name=name)
        s.add(c)
        s.flush()
        return c.id


def _fact(pg, entity, field, value, *, status=m.FactStatus.APPROVED, state=m.ValueState.FOUND, period="2024-12-31"):
    with Session(engine(pg)) as s, s.begin():
        version = max(r.version for r in s.query(m.FieldDefinition).filter_by(field_id=field))
        obs = m.FieldObservation(company_id=entity, field_id=field, field_version=version, source_kind=m.SourceKind.MANUAL,
                                 value=value, value_state=state, period_end=date.fromisoformat(period))
        s.add(obs)
        s.flush()
        for old in s.query(m.CompanyFact).filter_by(company_id=entity, field_id=field, valid_to=None):
            s.delete(old)
        s.flush()
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        s.add(m.CompanyFact(company_id=entity, field_id=field, period_end=date.fromisoformat(period), value=value,
                            canonical_value=value if numeric else None, status=status, observation_id=obs.id))


@pytest.fixture
def env(tmp_path, pg, monkeypatch):
    folder = tmp_path / "standins"
    (folder / "model").mkdir(parents=True)
    settings = Settings(standins_dir=folder, anthropic_api_key=None, gemini_api_key=None, runs_dir=tmp_path / "runs",
                        taxonomies_dir=tmp_path / "tax", cache_dir=tmp_path / "cache",
                        stewardship_streams_dir=tmp_path / "streams")
    monkeypatch.setattr(standins, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    run_store, taxonomies = RunStore(pg, settings.runs_dir), TaxonomyStore(settings.taxonomies_dir)
    streams = StreamStore(settings.stewardship_streams_dir)
    who, started = {"user": USERS["own"]}, []

    class Launcher:
        def launch(self, run_id, job):
            job().close()  # never run: the extraction itself is not under test

    monkeypatch.setattr(run_scheduling, "get_job_launcher", Launcher)

    def fake_starter():
        def start(schema, companies, settings):
            started.append((schema, companies))
            run_id = run_store_create(schema)
            return run_id
        return start

    def run_store_create(schema):
        from arp.orchestration.job_manager import JobManager
        manifest = JobManager(run_store).create_run(
            "extraction", {"schema_id": schema.schema_id, "schema_version": f"{schema.schema_id}:v{schema.version}"}, 1)
        return manifest.run_id

    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: who["user"]
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[get_taxonomy_store] = lambda: taxonomies
    app.dependency_overrides[get_stream_store] = lambda: streams
    app.dependency_overrides[get_extraction_starter] = fake_starter

    tid = taxonomies.create("Grid", ThemeDefinition(name="Grid", description="d"), DerivationMethod.MANUAL).taxonomy_id
    taxonomies.ratify(tid, 1, "own")
    client = TestClient(app)
    did = client.post("/api/dossiers", json={"name": "Grid electrification", "taxonomy_id": tid}).json()["dossier_id"]
    e1, e2, e4 = _company(pg, "Alpha"), _company(pg, "Beta"), _company(pg, "Delta")
    companies = [CompanyRef(company_id="C1", name="Alpha", entity_id=e1, sector="Utilities"),
                 CompanyRef(company_id="C2", name="Beta", entity_id=e2, sector="Utilities"),
                 CompanyRef(company_id="C3", name="Gamma"), CompanyRef(company_id="C4", name="Delta", entity_id=e4)]
    run_id = create_theme_run(ThemeDefinition(name="Grid", description="d"), companies, settings, run_store,
                              taxonomy_id=tid, taxonomy_version=1)
    manifest = run_store.load_manifest(run_id)
    manifest.status = JobStatus.COMPLETED
    run_store.save_manifest(manifest)
    for c in companies:
        run_store.append_result(run_id, {"_key": c.company_id, "company_matches": [] if c.company_id == "C4" else [{"company_id": c.company_id}]})
    _fields(pg)
    _fact(pg, e1, "fld_scope3", True)
    _fact(pg, e1, "fld_grid_capex", 25, status=m.FactStatus.AUTO_ACCEPTED)
    _fact(pg, e2, "fld_scope3", False)
    _fact(pg, e2, "fld_grid_capex", None, state=m.ValueState.NOT_FOUND)

    class Env:
        def __init__(self):
            self.client, self.did, self.folder, self.started, self.pg = client, did, folder, started, pg
            self.run_store, self.e1, self.e2, self.streams = run_store, e1, e2, streams
            self.positions = PositionStore(settings.runs_dir / "_positions")

        def as_(self, name):
            who["user"] = USERS[name]

        def model(self, name, output):
            (folder / "model" / f"{name}.json").write_text(json.dumps({"output": output}))

        def prompts(self, name):
            calls = [json.loads(line) for line in (folder / "calls.jsonl").read_text().splitlines()]
            return [c["prompt"] for c in calls if c.get("name") == name]

        def approve_note(self, round_=1):
            def fn(record):
                items = NoteSections(risks=[NoteItem(item_id="R1", title="Permitting delays", text="t", citations=[]),
                                            NoteItem(item_id="R2", title="Supply-chain bottlenecks", text="t", citations=[])],
                                     opportunities=[NoteItem(item_id="O1", title="Grid capex boom", text="t", citations=[])])
                record.rounds.append(ResearchRound(round=round_, taxonomy_version=1, plan_status="approved",
                                                   note=ResearchNote(status="approved", sections=items, approved_by="own")))
            ResearchStore(settings.runs_dir / "_dossiers" / "research").update(did, fn)

        def url(self, path):
            return f"/api/dossiers/{did}/{path}"

        def post(self, path, body=None, user=None):
            if user:
                self.as_(user)
            return self.client.post(self.url(path), json=body if body is not None else {})

        def step5(self):
            s = self.client.get(f"/api/dossiers/{did}").json()["steps"][4]
            return s["state"], s["detail"]

        def approved_position(self):
            self.approve_note()
            self.model("PositionDraft", P_OK)
            assert self.post("position/draft", user="ana").status_code == 200
            assert self.post("position/approve", {"version": 1}, user="own").status_code == 200

        def active(self, standards):
            self.approved_position()
            self.model("StandardsDraft", standards)
            assert self.post("standards/draft", user="ana").json() == {"version": 1}
            return self.post("standards/activate", {"version": 1}, user="own")

    yield Env()
    for dep in (current_user, settings_dep, get_run_store, get_taxonomy_store, get_stream_store, get_extraction_starter,
                get_engagement_store):
        app.dependency_overrides.pop(dep, None)


def test_position_needs_an_approved_note_and_validates_drafts(env):
    assert env.post("position/draft", user="ana").json()["detail"] == "research note not approved"
    assert env.step5() == ("not_started", "research note not approved")
    assert env.client.get(f"/api/dossiers/{env.did}").json()["steps"][4]["href"] == f"#/themes/{env.did}/position"
    env.approve_note()
    assert env.step5() == ("not_started", "draft the position")
    bad = {"summary": "s", "paragraphs": [{"text": "a", "cites": ["X9", "O1"]}, {"text": "b", "cites": ["R2"]}]}
    for paragraphs, message in [
        (bad["paragraphs"], "unknown item 'X9'"),
        ([{"text": "a", "cites": ["R1"]}, {"text": "b", "cites": ["R2"]}], "item 'O1' not cited"),
        ([], "no paragraphs"),
        ([{"text": "a", "cites": ["R1", "O1"]}, {"text": "b", "cites": []}], "paragraph 2 cites nothing"),
        ([{"text": " ", "cites": ["R1", "O1", "R2"]}], "paragraph 1 is blank"),
    ]:
        env.model("PositionDraft", {"summary": "s", "paragraphs": paragraphs})
        r = env.post("position/draft")
        assert (r.status_code, r.json()["detail"]) == (502, f"position draft invalid: {message}")
    assert env.client.get(env.url("position")).json()["versions"] == []


def test_draft_redraft_edit_and_approve_the_position(env):
    env.approve_note()
    env.model("PositionDraft", P_OK)
    v1 = env.post("position/draft", user="ana").json()
    assert (v1["version"], v1["created_by"], v1["path"], v1["note_version"], v1["instructions"], len(v1["paragraphs"])) == (
        1, "model", "model_draft", 1, None, 2)
    assert env.step5() == ("waiting", "approve position v1")
    assert env.post("position/approve", {"version": 1}).status_code == 403
    v2 = env.post("position/draft", {"instructions": "Stress grid permitting delays"}).json()
    assert (v2["version"], v2["instructions"]) == (2, "Stress grid permitting delays")
    assert "Stress grid permitting delays" in env.prompts("PositionDraft")[-1] and "Permits and capex." in env.prompts("PositionDraft")[-1]
    r = env.post("position/approve", {"version": 1}, user="own")
    assert (r.status_code, r.json()["detail"]) == (409, "only the latest version can be approved (v2)")
    edited = {**P_OK, "paragraphs": [{**P_OK["paragraphs"][0], "text": "Changed."}, P_OK["paragraphs"][1]]}
    v3 = env.post("position/versions", edited).json()
    assert (v3["version"], v3["created_by"], v3["path"]) == (3, "own", "owner_edit")
    r = env.post("position/versions", {**P_OK, "paragraphs": [{"text": "a", "cites": ["R1", "R2"]}]})
    assert (r.status_code, r.json()["detail"]) == (422, "item 'O1' not cited")
    assert env.post("position/versions", P_OK, user="ana").status_code == 403
    assert env.post("position/approve", {"version": 3}, user="own").json()["approved_by"] == "own"
    assert env.client.get(env.url("position")).json()["approved_version"] == 3
    assert env.step5() == ("not_started", "draft standards")


def test_a_newer_approved_note_makes_the_position_stale(env):
    env.approved_position()
    env.approve_note(round_=2)
    assert env.step5() == ("waiting", "position rests on note v1, v2 approved")
    r = env.post("position/approve", {"version": 1}, user="own")
    assert (r.status_code, r.json()["detail"]) == (409, "position v1 rests on note v1; v2 is approved")


@pytest.mark.parametrize("change, message", [
    (lambda s: s["standards"][0].update(field_id="fld_draft"), "standard 'S1': unknown or unreleased field 'fld_draft'"),
    (lambda s: s["standards"][0].update(operator=">="), "standard 'S1': operator '>=' does not fit boolean"),
    (lambda s: s["standards"][1].update(definition=" "), "standard 'S2': definition is blank"),
    (lambda s: s["standards"][0].update(rests_on=[9]), "standard 'S1': position has no paragraph 9"),
    (lambda s: s["new_fields"].append({**NEW, "field_id": "fld_spare", "name": "Spare"}), "new field 'Spare' is used by no standard"),
    (lambda s: s["standards"][0].update(field_id="fld_name", value="x"), "standard 'S1': field 'fld_name' is string, not checkable"),
    (lambda s: s["standards"][1].update(standard_id="S1"), "standard ids must be S1..Sn"),
    (lambda s: s["standards"][2].update(field_id="fld_other"), "standard 'S3': field 'fld_other' is not in the new schema"),
    (lambda s: s["standards"][1].update(field_id="fld_rating", operator="==", value="D"), "standard 'S2': value \"D\" does not fit enum"),
])
def test_invalid_standards_drafts_are_not_saved(env, change, message):
    env.approved_position()
    draft = json.loads(json.dumps(S_OK))
    change(draft)
    env.model("StandardsDraft", draft)
    r = env.post("standards/draft", user="ana")
    assert (r.status_code, r.json()["detail"]) == (502, f"standards draft invalid: {message}")
    assert env.client.get(env.url("standards")).json()["versions"][-1]["version"] == 0


def test_draft_activate_extract_and_check(env):
    assert env.post("standards/draft", user="ana").json()["detail"] == "position not approved"
    env.approved_position()
    env.model("StandardsDraft", S_OK)
    assert env.post("standards/draft", user="ana").json() == {"version": 1}
    view = env.client.get(env.url("standards")).json()
    v1 = view["versions"][1]
    assert (view["active_version"], v1["created_by"], v1["path"]) == (0, "model", "model_draft")
    assert [s["data"] for s in v1["standards"]] == ["existing", "existing", "new"]
    assert v1["schema"]["schema_id"].startswith("theme_std_") and [f["field_id"] for f in v1["schema"]["fields"]] == ["fld_plan"]
    assert env.step5() == ("waiting", "approve standards v1")
    assert env.post("standards/activate", {"version": 1}, user="ana").status_code == 403
    assert env.post("standards/activate", {"version": 7}, user="own").json()["detail"] == "unknown standards version 7"
    r = env.post("standards/activate", {"version": 1}).json()
    assert (r["approved_by"], r["path"], r["extraction_run_id"] is not None) == ("own", "model_draft", True)
    schema, companies = env.started[0]
    assert [c.company_id for c in companies] == ["C1", "C2", "C3"]
    assert (schema.version, schema.released_by, schema.release_flag) == (1, "own", True)
    run = env.run_store.load_manifest(r["extraction_run_id"])
    run.status = JobStatus.RUNNING
    env.run_store.save_manifest(run)
    assert env.step5() == ("running", "extracting 1 data points")
    run.status = JobStatus.FAILED
    env.run_store.save_manifest(run)
    assert env.step5() == ("failed", "extraction failed")
    run.status = JobStatus.COMPLETED
    env.run_store.save_manifest(run)
    assert env.step5() == ("waiting", "check companies")
    check = env.post("standards/check", user="ana").json()
    assert check["flagged"] == 1
    assert [(r["name"], r["standard_id"], r["result"]) for r in check["results"]][:4] == [
        ("Alpha", "S1", "met"), ("Alpha", "S2", "met"), ("Alpha", "S3", "no_data"), ("Beta", "S1", "unmet")]
    assert env.step5() == ("done", "3 standards · 1 flagged")


def test_the_check_flags_failures_as_stored_triggers(env):
    env.active(S_TWO)
    assert env.started == []
    check = env.post("standards/check", user="ana").json()
    assert [(r["name"], r["standard_id"], r["result"]) for r in check["results"]] == [
        ("Alpha", "S1", "met"), ("Alpha", "S2", "met"), ("Beta", "S1", "unmet"), ("Beta", "S2", "no_data"),
        ("Gamma", "S1", "no_data"), ("Gamma", "S2", "no_data")]
    assert check["flagged"] == 1
    std = [t for t in env.client.get("/api/stewardship/triggers").json()["triggers"] if t["rule"].startswith("std:")]
    assert [(t["issuer_id"], t["type"], t["theme"], t["severity"], t["rule"], t["reason"], t["status"]) for t in std] == [
        ("C2", "theme_standard", "Grid electrification", "high", f"std:{env.did}:S1",
         "Scope 3 emissions disclosed: false, expected == true", "open")]
    TriggerStore(env.streams.root).transition(std[0]["trigger_id"], "resolved", "own")
    env.post("standards/check")
    again = [t for t in env.client.get("/api/stewardship/triggers").json()["triggers"] if t["rule"].startswith("std:")]
    assert [(t["trigger_id"], t["status"]) for t in again] == [(std[0]["trigger_id"], "resolved")]
    _fact(env.pg, env.e1, "fld_grid_capex", 0, state=m.ValueState.ZERO)
    _fact(env.pg, env.e1, "fld_scope3", True, status=m.FactStatus.PENDING_REVIEW)
    rows = {(r["name"], r["standard_id"]): (r["result"], r["value"]) for r in env.post("standards/check").json()["results"]}
    assert rows[("Alpha", "S2")] == ("unmet", 0) and rows[("Alpha", "S1")] == ("no_data", None)


def test_owner_edits_activate_alone_and_four_eyes_stays_for_house_policies(env):
    env.approved_position()
    r = env.post("standards/versions", {**S_TWO, "standards": [{**S1, "field_id": "fld_draft"}, S2]}, user="own")
    assert (r.status_code, r.json()["detail"]) == (422, "standard 'S1': unknown or unreleased field 'fld_draft'")
    assert env.post("standards/versions", S_TWO, user="ana").status_code == 403
    assert env.post("standards/versions", S_TWO, user="own").json() == {"version": 1}
    r = env.post("standards/activate", {"version": 1}).json()
    assert (r["approved_by"], r["path"], r["extraction_run_id"]) == ("own", "owner_edit", None)
    assert env.client.get(env.url("standards")).json()["activations"][-1]["path"] == "owner_edit"
    assert env.client.get("/api/stewardship/policies/theme_standards").json()["detail"] == "Unknown policy"
    env.as_("ana")
    graph = PolicyStore(env.streams.root).content("monitoring_rules", 0)
    v = env.client.post("/api/stewardship/policies/monitoring_rules/versions", json={"content": graph}).json()["version"]
    r = env.client.post("/api/stewardship/policies/monitoring_rules/activate", json={"version": v})
    assert (r.status_code, r.json()["detail"]) == (
        422, "Four-eyes rule: a version must be activated by someone other than the person who saved it")


def test_activation_needs_current_position_and_companies_and_a_started_extraction(env):
    env.approved_position()
    env.model("StandardsDraft", S_OK)
    env.post("standards/draft", user="ana")

    def boom():
        def start(schema, companies, settings):
            raise RuntimeError("boom")
        return start

    starter = app.dependency_overrides[get_extraction_starter]
    app.dependency_overrides[get_extraction_starter] = boom
    r = env.post("standards/activate", {"version": 1}, user="own")
    assert (r.status_code, r.json()["detail"]) == (502, "extraction could not start: boom")
    assert env.client.get(env.url("standards")).json()["active_version"] == 0
    app.dependency_overrides[get_extraction_starter] = starter
    env.model("PositionDraft", P_OK)
    env.post("position/draft", user="ana")
    env.post("position/approve", {"version": 2}, user="own")
    r = env.post("standards/activate", {"version": 1})
    assert (r.status_code, r.json()["detail"]) == (409, "standards v1 rest on position v1; v2 is approved")


def test_viewers_read_only(env):
    env.approved_position()
    env.as_("vic")
    assert env.client.get(env.url("position")).status_code == 200
    assert env.client.get(env.url("standards")).status_code == 200
    for path in ("position/draft", "position/versions", "position/approve", "standards/draft", "standards/versions",
                 "standards/activate", "standards/check"):
        assert env.client.post(env.url(path), json={}).status_code == 403, path


def test_standards_endpoints_need_postgres(tmp_path, monkeypatch):
    """AC-54: without a DSN, the standards writes answer 503 (the position endpoints are unaffected)."""
    monkeypatch.delenv("ARP_POSTGRES_DSN", raising=False)
    settings = Settings(postgres_dsn=None, runs_dir=tmp_path / "runs", stewardship_streams_dir=tmp_path / "streams")
    positions = PositionStore(settings.runs_dir / "_positions")
    positions.add("dos_x", PositionDraft(summary="s", paragraphs=[PositionParagraph(text="t", cites=["R1"])]),
                  note_version=1, created_by="model", path="model_draft", instructions=None)
    positions.approve("dos_x", 1, "own")
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: USERS["own"]
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(settings.stewardship_streams_dir)
    try:
        client = TestClient(app)
        for path, body in [("draft", {}), ("versions", S_TWO), ("activate", {"version": 1}), ("check", None)]:
            r = client.post(f"/api/dossiers/dos_x/standards/{path}", json=body)
            assert (r.status_code, r.json()["detail"]) == (503, "ARP_POSTGRES_DSN is required: Postgres is the system of record."), path
    finally:
        for dep in (current_user, settings_dep, get_stream_store):
            app.dependency_overrides.pop(dep, None)


def test_user_id_model_is_reserved(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": [{"user_id": "model", "name": "M", "role": "approver", "token": "t"}]}))
    with pytest.raises(RuntimeError, match="user id 'model' is reserved"):
        load_users(path)


def test_the_real_starter_creates_the_run_on_the_exposed_companies_and_a_second_activation_extends_the_schema(env):
    app.dependency_overrides.pop(get_extraction_starter)
    r = env.active(S_OK).json()
    run = env.run_store.load_manifest(r["extraction_run_id"])
    assert [c.company_id for c in env.run_store.load_companies(run.run_id)] == ["C1", "C2", "C3"]
    sid = run.params["schema_id"]
    assert sid.startswith("theme_std_") and SchemaRegistry(env.pg).get(sid, 1).released_by == "own"
    run.status = JobStatus.COMPLETED
    env.run_store.save_manifest(run)
    s4 = {**_std("S4", "fld_permit", "==", True, "low", data="new")}
    env.model("StandardsDraft", {"standards": [S1, S2, {**S3, "data": "existing"}, s4],
                                 "new_fields": [{**NEW, "field_id": "fld_permit", "name": "Grid permit filed"}]})
    assert env.post("standards/draft", user="ana").json() == {"version": 2}
    v2 = env.client.get(env.url("standards")).json()["versions"][2]
    assert [s["data"] for s in v2["standards"]][2:] == ["existing", "new"]
    r2 = env.post("standards/activate", {"version": 2}, user="own").json()
    assert r2["extraction_run_id"] not in (None, r["extraction_run_id"])
    schema = SchemaRegistry(env.pg).get(sid, 2)
    assert (schema.release_flag, len(schema.fields)) == (True, 2)
    assert env.step5() == ("running", "extracting 2 data points")


def test_an_engagement_opens_from_a_standards_trigger(env):
    env.active(S_TWO)
    assert env.post("standards/check", user="ana").status_code == 200
    env.as_("own")
    app.dependency_overrides[get_engagement_store] = lambda: EngagementStore(env.streams.root.parent / "engagements")
    issue = env.client.post("/api/stewardship/monitoring/open-engagement", json={"issuer_id": "C2", "rule": f"std:{env.did}:S1"})
    assert issue.status_code == 200
    t = issue.json()["trigger"]
    assert (t["theme"], t["severity"], t["sector"]) == ("Grid electrification", "high", "Utilities")
