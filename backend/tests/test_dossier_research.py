"""Dossier step 3: source plan -> approval -> cited note -> approval, answered by the test stand-ins."""

import asyncio
import io
import json
import re

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from arp import standins
from arp.api import deps, run_scheduling
from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_run_store, get_taxonomy_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore

IEA, EUROSTAT, TTX, PAPER = "https://iea.org/weo", "https://ec.europa.eu/eurostat/x", "https://ttx.org/b", "https://doi.org/10.1/x"
GRID, PRICES = "Grid investment must double by 2030.", "Electricity prices rose 12% in 2023."
SEARCH = [("IEA World Energy Outlook", IEA), ("Eurostat energy statistics", EUROSTAT), ("Think Tank X brief", TTX),
          ("J. Energy Econ paper", PAPER)]
CATEGORIES = {IEA: "intergovernmental", EUROSTAT: "official_statistics", TTX: "none", PAPER: "academic"}
USERS = {"ana": Principal(user_id="a", name="ana", role="analyst"), "vic": Principal(user_id="v", name="vic", role="viewer")}


def _write(folder, name, data):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _item(title, *cites, channel=None):
    return {"title": title, "text": f"{title} text", "channel": channel, "citations": [{"source_id": s, "quote": q} for s, q in cites]}


@pytest.fixture
def env(tmp_path, pg, monkeypatch):
    folder = tmp_path / "standins"
    folder.mkdir()
    settings = Settings(standins_dir=folder, anthropic_api_key=None, gemini_api_key=None, runs_dir=tmp_path / "runs",
                        taxonomies_dir=tmp_path / "tax", cache_dir=tmp_path / "cache")
    monkeypatch.setattr(standins, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    run_store, taxonomies = RunStore(pg, settings.runs_dir), TaxonomyStore(settings.taxonomies_dir)
    jobs, who = [], {"user": USERS["ana"]}

    class Launcher:
        def launch(self, run_id, job):
            jobs.append(job)

    monkeypatch.setattr(run_scheduling, "get_job_launcher", Launcher)
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: who["user"]
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[get_taxonomy_store] = lambda: taxonomies
    _write(folder, "search.json", {"results": [{"title": t, "url": u} for t, u in SEARCH]})
    _write(folder, "model/SourceClassificationDraft.json", {"output": {"sources": [
        {"url": u, "category": c, "publisher": "p", "why": "w", "how": "h"} for u, c in CATEGORIES.items()]}})
    _write(folder, "fetch.json", {IEA: {"text": f"Intro. {GRID} Outro."}, EUROSTAT: {"text": f"{PRICES} More."}})

    class Env:
        client = TestClient(app)

        def __init__(self):
            self.folder, self.taxonomies, self.settings = folder, taxonomies, settings
            tid = taxonomies.create("Grid", ThemeDefinition(name="Grid", description="d"), DerivationMethod.MANUAL).taxonomy_id
            taxonomies.ratify(tid, 1, "ana")
            self.tid = tid
            self.d = self.client.post("/api/dossiers", json={"name": "D", "taxonomy_id": tid}).json()["dossier_id"]

        def as_(self, name):
            who["user"] = USERS[name]

        def run_jobs(self):
            while jobs:
                asyncio.run(jobs.pop(0)())

        def drop_jobs(self):  # as a crash would
            jobs.clear()

        def url(self, path=""):
            return f"/api/dossiers/{self.d}/research{path}"

        def research(self):
            return self.client.get(self.url()).json()

        def step3(self, did=None):
            s = self.client.get(f"/api/dossiers/{did or self.d}").json()["steps"][2]
            return s["state"], s["detail"]

        def note_stand_in(self, **sections):
            _write(folder, "model/ResearchNoteDraft.json", {"output": sections})

        def ids(self):
            return {s["url"]: s["source_id"] for s in self.research()["rounds"][-1]["sources"]}

        def proposed(self):
            assert self.client.post(self.url("/propose")).status_code == 202
            self.run_jobs()

        def approved(self):
            self.proposed()
            assert self.client.post(self.url("/plan/approve")).status_code == 200

    yield Env()
    for dep in (current_user, settings_dep, get_run_store, get_taxonomy_store):
        app.dependency_overrides.pop(dep, None)


def _default_note(e):
    ids = e.ids()
    e.note_stand_in(
        risks=[_item("Prices", (ids[EUROSTAT], PRICES))],
        opportunities=[_item("Grid", (ids[IEA], GRID))],
        growth_potential=[_item("Demand", (ids[IEA], "Demand will triple."))],
        transmission_channels=[_item("Capex", (ids[IEA], GRID), (ids[EUROSTAT], "Prices fell."), channel="financial")],
    )
    return ids


def _pdf(text: str) -> bytes:
    """A one-page PDF whose extracted text is `text`."""
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    w = PdfWriter()
    page = w.add_blank_page(300, 300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 10 Tf 10 150 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_proposal_keeps_the_four_categories_in_search_order(env):
    assert env.research() == {"dossier_id": env.d, "approved_round": None, "rounds": []}
    assert env.step3() == ("not_started", "propose sources")
    r = env.client.post(env.url("/propose"))
    assert r.status_code == 202 and r.json()["round"] == 1 and r.json()["run_id"]
    assert env.step3() == ("running", "proposing sources")
    assert env.client.post(env.url("/propose")).json()["detail"] == "round 1 is in progress"
    env.run_jobs()
    rnd = env.research()["rounds"][0]
    assert (rnd["plan_status"], rnd["taxonomy_version"]) == ("proposed", 1)
    assert [s["url"] for s in rnd["sources"]] == [IEA, EUROSTAT, PAPER]
    assert [s["category"] for s in rnd["sources"]] == ["intergovernmental", "official_statistics", "academic"]
    assert all(re.fullmatch(r"src_[0-9a-f]{12}", s["source_id"]) and s["added_by"] == "model" for s in rnd["sources"])
    assert rnd["sources"][0]["title"] == "IEA World Energy Outlook"
    assert env.step3() == ("waiting", "approve 3 sources")
    assert env.client.get("/api/dossiers").json()["items"][0]["current_step"] == 3
    calls = [json.loads(line) for line in (env.folder / "calls.jsonl").read_text().splitlines()]
    assert [c["name"] for c in calls if c["kind"] == "model"] == ["SourceClassificationDraft"]


def test_a_failed_search_fails_the_round_and_it_can_be_proposed_again(env):
    _write(env.folder, "search.json", {"error": "down"})
    env.proposed()
    assert env.research()["rounds"][0]["plan_status"] == "proposal_failed"
    assert env.step3() == ("failed", "source proposal failed")
    _write(env.folder, "search.json", {"results": [{"title": t, "url": u} for t, u in SEARCH]})
    r = env.client.post(env.url("/propose"))
    assert (r.status_code, r.json()["round"]) == (202, 1)


def test_at_most_twelve_sources(env):
    urls = [f"https://u{i}.int/r" for i in range(14)]
    _write(env.folder, "search.json", {"results": [{"title": u, "url": u} for u in urls]})
    _write(env.folder, "model/SourceClassificationDraft.json", {"output": {"sources": [
        {"url": u, "category": "intergovernmental", "publisher": "p", "why": "w", "how": "h"} for u in urls]}})
    env.proposed()
    assert [s["url"] for s in env.research()["rounds"][0]["sources"]] == urls[:12]


def test_editing_and_approving_the_plan(env):
    env.proposed()
    body = {"title": "ECB bulletin", "publisher": "ECB", "url": "https://ecb.europa.eu/b", "category": "central_bank_regulator",
            "why": "w", "how": "h"}
    assert env.client.post(env.url("/sources"), json={**body, "category": "think_tank"}).status_code == 422
    assert env.client.post(env.url("/sources"), json={**body, "why": "  "}).status_code == 422
    added = env.client.post(env.url("/sources"), json=body).json()
    assert added["added_by"] == "ana" and re.fullmatch(r"src_[0-9a-f]{12}", added["source_id"])
    assert len(env.research()["rounds"][0]["sources"]) == 4
    assert env.client.delete(env.url(f"/sources/{added['source_id']}")).status_code == 200
    assert [s["url"] for s in env.research()["rounds"][0]["sources"]] == [IEA, EUROSTAT, PAPER]
    r = env.client.delete(env.url("/sources/src_000000000000"))
    assert (r.status_code, r.json()["detail"]) == (404, "unknown source 'src_000000000000'")
    assert env.client.post(env.url("/note")).json()["detail"] == "approve the source plan first"

    ids = env.ids()
    approved = env.client.post(env.url("/plan/approve")).json()
    assert (approved["plan_status"], approved["plan_approved_by"]) == ("approved", "ana")
    assert env.step3() == ("waiting", "write the note")
    assert env.client.post(env.url("/sources"), json=body).json()["detail"] == "the source plan is not open for edits"
    assert env.client.delete(env.url(f"/sources/{ids[IEA]}")).json()["detail"] == "the source plan is not open for edits"
    assert env.client.post(env.url("/note/approve")).json()["detail"] == "there is no written note"


def test_an_empty_plan_cannot_be_approved(env):
    env.proposed()
    for sid in env.ids().values():
        env.client.delete(env.url(f"/sources/{sid}"))
    assert env.client.post(env.url("/plan/approve")).json()["detail"] == "add at least one source"
    assert env.step3() == ("waiting", "add sources")


def test_the_note_keeps_only_grounded_citations(env):
    env.approved()
    ids = _default_note(env)
    assert env.client.post(env.url("/note")).status_code == 202
    assert env.step3() == ("running", "writing note")
    env.run_jobs()
    note = env.research()["rounds"][0]["note"]
    s = note["sections"]
    assert note["status"] == "written"
    assert [c["source_id"] for c in s["risks"][0]["citations"]] == [ids[EUROSTAT]]
    assert [c["source_id"] for c in s["opportunities"][0]["citations"]] == [ids[IEA]]
    assert (s["financial_relevance"], s["growth_potential"]) == ([], [])
    assert s["transmission_channels"][0]["channel"] == "financial"
    assert s["transmission_channels"][0]["citations"] == [{"source_id": ids[IEA], "quote": GRID, "page": None}]
    assert all(re.fullmatch(r"itm_[0-9a-f]{12}", i["item_id"]) for items in s.values() for i in items)
    assert (note["dropped_items"], note["unread_sources"]) == (1, [{"source_id": ids[PAPER], "reason": "fetch failed"}])
    assert env.step3() == ("waiting", "approve the note")
    pdf = ("y.pdf", _pdf("Storage costs fell 40%."), "application/pdf")
    assert env.client.post(env.url(f"/sources/{ids[PAPER]}/file"), files={"file": pdf}).json()["detail"] == "the note is already written"


def test_an_uploaded_pdf_is_read_and_cited_with_its_page(env):
    env.approved()
    ids = _default_note(env)
    draft = json.loads((env.folder / "model/ResearchNoteDraft.json").read_text())["output"]
    draft["opportunities"].append(_item("Storage", (ids[PAPER], "Storage costs fell 40%.")))
    env.note_stand_in(**draft)
    r = env.client.post(env.url(f"/sources/{ids[PAPER]}/file"), files={"file": ("p.pdf", _pdf("Storage costs fell 40%."), "application/pdf")})
    assert r.status_code == 200 and r.json()["file"]["filename"] == "p.pdf"
    env.client.post(env.url("/note"))
    env.run_jobs()
    note = env.research()["rounds"][0]["note"]
    assert [i["citations"][0]["page"] for i in note["sections"]["opportunities"]] == [None, 1]
    assert note["unread_sources"] == []


def test_upload_type_and_size(env, monkeypatch):
    env.approved()
    iea = env.ids()[IEA]
    assert env.client.post(env.url(f"/sources/{iea}/file"), files={"file": ("x.exe", b"0" * 1024)}).status_code == 415
    monkeypatch.setattr(env.settings, "max_upload_bytes", 10)
    assert env.client.post(env.url(f"/sources/{iea}/file"), files={"file": ("x.pdf", b"0" * 11)}).status_code == 413


def test_unreadable_sources(env):
    env.approved()
    ids = _default_note(env)
    _write(env.folder, "fetch.json", {IEA: {"text": GRID}, EUROSTAT: {"text": ""}})
    env.client.post(env.url("/note"))
    env.run_jobs()
    assert env.research()["rounds"][0]["note"]["unread_sources"] == [
        {"source_id": ids[EUROSTAT], "reason": "no text extracted"}, {"source_id": ids[PAPER], "reason": "fetch failed"}]
    env.client.post(env.url("/note/reject"), json={"reason": "r"})
    env.client.post(env.url("/plan/approve"))
    _write(env.folder, "fetch.json", {})
    env.client.post(env.url("/note"))
    env.run_jobs()
    note = env.research()["rounds"][0]["note"]
    assert (note["status"], note["error"]) == ("write_failed", "no approved source could be read")
    assert env.step3() == ("failed", "note failed: no approved source could be read")


def test_unknown_source_ids_and_long_titles(env):
    env.approved()
    ids = _default_note(env)
    draft = json.loads((env.folder / "model/ResearchNoteDraft.json").read_text())["output"]
    draft["risks"].append(_item("Ghost", ("src_000000000000", GRID)))
    draft["risks"][0]["title"] = "x" * 150
    env.note_stand_in(**draft)
    env.client.post(env.url("/note"))
    env.run_jobs()
    note = env.research()["rounds"][0]["note"]
    assert [i["citations"][0]["source_id"] for i in note["sections"]["risks"]] == [ids[EUROSTAT]]
    assert note["sections"]["risks"][0]["title"] == "x" * 120
    assert note["dropped_items"] == 2


def test_approve_reject_and_a_new_round(env):
    env.approved()
    _default_note(env)
    env.client.post(env.url("/note"))
    env.run_jobs()
    first = {i["item_id"] for items in env.research()["rounds"][0]["note"]["sections"].values() for i in items}
    for body in ({}, {"reason": "  "}):
        assert env.client.post(env.url("/note/reject"), json=body).status_code == 422
    r = env.client.post(env.url("/note/reject"), json={"reason": "Too thin"}).json()
    assert (r["note"]["status"], r["plan_status"]) == ("rejected", "proposed")
    assert env.step3() == ("waiting", "note rejected: Too thin")
    body = {"title": "t", "publisher": "p", "url": "https://x.gov/y", "category": "official_statistics", "why": "w", "how": "h"}
    extra = env.client.post(env.url("/sources"), json=body)
    assert extra.status_code == 200
    env.client.delete(env.url(f"/sources/{extra.json()['source_id']}"))
    env.client.post(env.url("/plan/approve"))
    assert env.step3() == ("waiting", "write the note")
    env.client.post(env.url("/note"))
    env.run_jobs()
    second = env.research()["rounds"][0]["note"]
    assert second["status"] == "written"
    assert not first & {i["item_id"] for items in second["sections"].values() for i in items}

    approved = env.client.post(env.url("/note/approve")).json()["note"]
    assert (approved["status"], approved["approved_by"]) == ("approved", "ana")
    assert env.research()["approved_round"] == 1
    assert env.step3() == ("done", "note r1 approved by ana")
    assert env.client.get("/api/dossiers").json()["items"][0]["current_step"] == 4
    risk_ids = env.research()["rounds"][0]["note"]["sections"]["risks"][0]["item_id"]
    assert env.research()["rounds"][0]["note"]["sections"]["risks"][0]["item_id"] == risk_ids

    round1 = env.ids()
    r = env.client.post(env.url("/propose"))
    assert r.json()["round"] == 2
    env.run_jobs()
    view = env.research()
    assert view["approved_round"] == 1 and view["rounds"][1]["plan_status"] == "proposed"
    assert env.ids() == round1 and list(round1) == [IEA, EUROSTAT, PAPER]
    assert env.step3() == ("waiting", "approve 3 sources")


def test_drift_viewers_shelving_and_unknown_dossiers(env):
    env.approved()
    _default_note(env)
    env.client.post(env.url("/note"))
    env.run_jobs()
    env.as_("vic")
    assert env.client.get(env.url()).status_code == 200
    for path in ("/propose", "/plan/approve", "/note/approve"):
        assert env.client.post(env.url(path)).status_code == 403
    env.as_("ana")
    env.client.post(env.url("/note/approve"))
    env.taxonomies.new_version(env.tid, ThemeDefinition(name="Grid", description="d"), DerivationMethod.MANUAL)
    env.taxonomies.ratify(env.tid, 2, "bob")
    assert env.step3() == ("waiting", "note r1 approved by ana · older than v2")
    assert env.client.get("/api/dossiers").json()["items"][0]["current_step"] == 3
    env.client.patch(f"/api/dossiers/{env.d}", json={"status": "shelved", "reason": "r"})
    assert env.client.post(env.url("/propose")).json()["detail"] == "dossier is shelved"
    r = env.client.get("/api/dossiers/dos_000000000000/research")
    assert (r.status_code, r.json()["detail"]) == (404, "unknown dossier 'dos_000000000000'")


def test_a_draft_taxonomy_cannot_be_researched(env):
    tid = env.taxonomies.create("B", ThemeDefinition(name="B", description="d"), DerivationMethod.MANUAL).taxonomy_id
    e = env.client.post("/api/dossiers", json={"name": "E", "taxonomy_id": tid}).json()["dossier_id"]
    r = env.client.post(f"/api/dossiers/{e}/research/propose")
    assert (r.status_code, r.json()["detail"]) == (409, "ratify a taxonomy first")
    step = env.client.get(f"/api/dossiers/{e}").json()["steps"][2]
    assert (step["state"], step["detail"], step["href"]) == ("not_started", "ratify a taxonomy first", None)
    assert env.client.get(f"/api/dossiers/{env.d}").json()["steps"][2]["href"] == f"#/themes/{env.d}/research"


def test_the_shown_quote_is_the_source_text_and_a_plan_holds_twelve_sources(env):
    env.proposed()
    body = {"title": "t", "publisher": "p", "category": "official_statistics", "why": "w", "how": "h"}
    for i in range(9):
        assert env.client.post(env.url("/sources"), json={**body, "url": f"https://x.gov/{i}"}).status_code == 200
    r = env.client.post(env.url("/sources"), json={**body, "url": "https://x.gov/13"})
    assert (r.status_code, r.json()["detail"]) == (409, "a plan holds at most 12 sources")
    for sid in list(env.ids().values())[3:]:
        env.client.delete(env.url(f"/sources/{sid}"))
    env.client.post(env.url("/plan/approve"))
    ids = env.ids()
    env.note_stand_in(risks=[_item("Prices", (ids[EUROSTAT], "electricity  prices rose 12% in 2023."))])
    env.client.post(env.url("/note"))
    env.run_jobs()
    assert env.research()["rounds"][0]["note"]["sections"]["risks"][0]["citations"][0]["quote"] == PRICES


def test_a_new_upload_keeps_the_file_an_earlier_round_read(env):
    env.approved()
    ids = _default_note(env)
    pdf = lambda text: {"file": ("p.pdf", _pdf(text), "application/pdf")}  # noqa: E731
    env.client.post(env.url(f"/sources/{ids[PAPER]}/file"), files=pdf("Storage costs fell 40%."))
    env.client.post(env.url("/note"))
    env.run_jobs()
    env.client.post(env.url("/note/approve"))
    env.proposed()
    env.client.post(env.url(f"/sources/{ids[PAPER]}/file"), files=pdf("Other text."))
    from arp.themes.research import ResearchRecord, ResearchStore

    store = ResearchStore(env.settings.runs_dir / "_dossiers" / "research")
    record = ResearchRecord.model_validate(env.research())
    paths = [store.file_path(env.d, next(s for s in r.sources if s.source_id == ids[PAPER])) for r in record.rounds]
    assert paths[0] != paths[1] and all(p.is_file() for p in paths)


def test_a_round_whose_run_died_reads_as_failed_and_can_be_retried(env, pg):  # AC-72
    run_store = RunStore(pg, env.settings.runs_dir)

    def die(run_id):  # past the lease grace, with no worker holding the lease: what a restart leaves behind
        m = run_store.load_manifest(run_id)
        m.created_at = "2026-01-01T00:00:00+00:00"
        run_store.save_manifest(m)

    die(env.client.post(env.url("/propose")).json()["run_id"])
    env.drop_jobs()
    assert env.research()["rounds"][0]["plan_status"] == "proposal_failed"
    assert env.step3() == ("failed", "source proposal failed")
    r = env.client.post(env.url("/propose"))
    assert (r.status_code, r.json()["round"]) == (202, 1)
    env.run_jobs()
    env.client.post(env.url("/plan/approve"))
    _default_note(env)

    die(env.client.post(env.url("/note")).json()["run_id"])
    env.drop_jobs()
    note = env.research()["rounds"][0]["note"]
    assert (note["status"], note["error"]) == ("write_failed", "the run stopped before the note was written")
    assert env.step3() == ("failed", "note failed: the run stopped before the note was written")
    assert env.client.post(env.url("/note")).status_code == 202
    env.run_jobs()
    assert env.research()["rounds"][0]["note"]["status"] == "written"
