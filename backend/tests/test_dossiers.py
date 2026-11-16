"""Theme dossiers: one JSON record per theme; its five step states are derived on read from the stores."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_llm_client, get_run_store, get_taxonomy_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.emerging_themes.pipeline import create_emerging_themes_run
from arp.research.pipeline import create_theme_run
from arp.research.taxonomy_sources.corpus_synthesis import _SynthesizedActivityDraft, _SynthesizedActivityDraftList
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.emerging_themes import EmergingThemeCandidate, MentionCitation, MentionSourceType
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.conftest import FakeLLMClient

THEME = ThemeDefinition(name="Grid", description="d")


@pytest.fixture
def env(tmp_path, pg):
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", taxonomies_dir=tmp_path / "tax",
                        cache_dir=tmp_path / "cache")
    run_store, taxonomies = RunStore(pg, settings.runs_dir), TaxonomyStore(settings.taxonomies_dir)
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[get_taxonomy_store] = lambda: taxonomies
    yield TestClient(app), settings, run_store, taxonomies
    for dep in (settings_dep, get_run_store, get_taxonomy_store, get_llm_client):
        app.dependency_overrides.pop(dep, None)


def _taxonomy(taxonomies, ratified: list[tuple[int, str]], versions: int = 1) -> str:
    tid = taxonomies.create("Grid", THEME, DerivationMethod.MANUAL).taxonomy_id
    for _ in range(versions - 1):
        taxonomies.new_version(tid, THEME, DerivationMethod.MANUAL)
    for version, by in ratified:
        taxonomies.ratify(tid, version, by)
    return tid


def _run(settings, run_store, tid, version, status, *, matched=0, pending=0) -> str:
    run_id = create_theme_run(THEME, [], settings, run_store, taxonomy_id=tid, taxonomy_version=version)
    m = run_store.load_manifest(run_id)
    m.status = status
    run_store.save_manifest(m)
    for i in range(matched):
        run_store.append_result(run_id, {"_key": f"c{i}", "company_matches": [{"company_id": f"c{i}"}]})
    run_store.append_result(run_id, {"_key": "none", "company_matches": []})
    for i in range(pending):
        run_store.append_review_item(run_id, {"item_key": f"k{i}"})
    run_store.append_review_item(run_id, {"item_key": "isic:x"})  # sector codes are reviewed elsewhere
    return run_id


def _steps(client, did):
    return [(s["state"], s["detail"]) for s in client.get(f"/api/dossiers/{did}").json()["steps"]]


def test_a_topic_dossier_starts_with_nothing_to_show(env):
    client = env[0]
    d = client.post("/api/dossiers", json={"name": "Grid electrification"}).json()
    assert d["dossier_id"].startswith("dos_") and len(d["dossier_id"]) == 16
    assert (d["origin"], d["taxonomy_id"], d["status"], d["created_by"]) == ("topic", None, "active", "Test")
    steps = client.get(f"/api/dossiers/{d['dossier_id']}").json()["steps"]
    assert [s["title"] for s in steps] == ["Spot", "Define", "Research", "Find companies", "Position and standards"]
    assert [s["state"] for s in steps] == ["skipped", "not_started", "not_started", "not_started", "not_started"]
    assert steps[4]["detail"] == "research note not approved"
    assert [s["href"] for s in steps] == [None, None, None, "#/theme", f"#/themes/{d['dossier_id']}/position"]
    assert client.get("/api/dossiers").json()["items"][0]["current_step"] == 2


def test_create_validates_name_and_taxonomy(env):
    client, _, _, taxonomies = env
    assert client.post("/api/dossiers", json={"name": "  "}).status_code == 422
    assert client.post("/api/dossiers", json={"name": "X", "taxonomy_id": "tax_none"}).status_code == 404
    tid = _taxonomy(taxonomies, [])
    d1 = client.post("/api/dossiers", json={"name": "X", "taxonomy_id": tid}).json()["dossier_id"]
    r = client.post("/api/dossiers", json={"name": "Y", "taxonomy_id": tid})
    assert (r.status_code, r.json()["detail"]) == (409, f"taxonomy '{tid}' already belongs to dossier '{d1}'")


def test_define_follows_the_latest_ratified_version(env):
    client, _, _, taxonomies = env
    draft = _taxonomy(taxonomies, [])
    tid = _taxonomy(taxonomies, [(1, "ana")], versions=2)
    d = client.post("/api/dossiers", json={"name": "A", "taxonomy_id": tid}).json()["dossier_id"]
    e = client.post("/api/dossiers", json={"name": "B", "taxonomy_id": draft}).json()["dossier_id"]
    assert _steps(client, d)[1] == ("done", "v1 ratified by ana")
    assert client.get(f"/api/dossiers/{d}").json()["steps"][1]["href"] == "#/taxonomy"
    assert _steps(client, e)[1] == ("waiting", "ratify a version")
    taxonomies.ratify(tid, 2, "bob")
    assert _steps(client, d)[1] == ("done", "v2 ratified by bob")


def test_find_companies_reads_the_newest_run_for_the_taxonomy(env):
    client, settings, run_store, taxonomies = env
    tid = _taxonomy(taxonomies, [(1, "ana")], versions=3)
    other = _taxonomy(taxonomies, [])
    d = client.post("/api/dossiers", json={"name": "A", "taxonomy_id": tid}).json()["dossier_id"]
    _run(settings, run_store, None, None, JobStatus.COMPLETED)
    _run(settings, run_store, other, 1, JobStatus.COMPLETED)
    assert _steps(client, d)[3] == ("not_started", "no run yet")

    _run(settings, run_store, tid, 1, JobStatus.RUNNING)
    assert _steps(client, d)[3] == ("running", "run in progress")
    _run(settings, run_store, tid, 1, JobStatus.CANCELLED)
    assert _steps(client, d)[3] == ("failed", "last run cancelled")
    _run(settings, run_store, tid, 1, JobStatus.COMPLETED, matched=2, pending=3)
    assert _steps(client, d)[3] == ("waiting", "3 to review")
    run_id = _run(settings, run_store, tid, 1, JobStatus.PARTIALLY_COMPLETED, matched=12)
    assert _steps(client, d)[3] == ("done", "12 companies, taxonomy v1")
    view = client.get(f"/api/dossiers/{d}").json()
    assert view["steps"][3]["href"] == f"#/theme/{run_id}"
    assert client.get("/api/dossiers").json()["items"][0]["current_step"] == 3  # step 3 has not started

    taxonomies.ratify(tid, 3, "bob")
    assert _steps(client, d)[3] == ("waiting", "12 companies, taxonomy v1 · older than v3")
    _run(settings, run_store, tid, 1, JobStatus.COMPLETED, pending=2)
    assert _steps(client, d)[3] == ("waiting", "2 to review · older than v3")


def test_attach_shelve_and_errors(env):
    client, _, _, taxonomies = env
    a, b = _taxonomy(taxonomies, [(1, "ana")]), _taxonomy(taxonomies, [])
    d1 = client.post("/api/dossiers", json={"name": "A"}).json()["dossier_id"]
    d2 = client.post("/api/dossiers", json={"name": "B"}).json()["dossier_id"]
    for _ in range(2):
        r = client.patch(f"/api/dossiers/{d1}", json={"taxonomy_id": a})
        assert (r.status_code, r.json()["taxonomy_id"]) == (200, a)
    assert client.patch(f"/api/dossiers/{d1}", json={"taxonomy_id": b}).status_code == 409
    r = client.patch(f"/api/dossiers/{d2}", json={"taxonomy_id": a})
    assert (r.status_code, r.json()["detail"]) == (409, f"taxonomy '{a}' already belongs to dossier '{d1}'")
    assert client.patch(f"/api/dossiers/{d2}", json={"taxonomy_id": "tax_none"}).status_code == 404
    assert client.patch(f"/api/dossiers/{d2}", json={"status": "shelved"}).status_code == 422
    assert client.patch(f"/api/dossiers/{d2}", json={"status": "shelved", "reason": "  "}).status_code == 422
    s = client.patch(f"/api/dossiers/{d2}", json={"status": "shelved", "reason": "No data"}).json()
    assert (s["status"], s["shelve_reason"], s["shelved_by"]) == ("shelved", "No data", "Test")
    datetime.fromisoformat(s["shelved_at"])
    assert len(client.get(f"/api/dossiers/{d2}").json()["steps"]) == 5
    assert {i["dossier_id"]: i["status"] for i in client.get("/api/dossiers").json()["items"]}[d2] == "shelved"
    for call in (client.get, lambda u: client.patch(u, json={"taxonomy_id": a})):
        r = call("/api/dossiers/dos_000000000000")
        assert (r.status_code, r.json()["detail"]) == (404, "unknown dossier 'dos_000000000000'")


def test_list_is_newest_first(env):
    client, settings, _, _ = env
    folder = settings.runs_dir / "_dossiers"
    folder.mkdir(parents=True)
    for did, at in (("dos_00000000000a", "2026-01-01T00:00:00Z"), ("dos_00000000000b", "2026-01-02T00:00:00Z")):
        (folder / f"{did}.json").write_text(
            f'{{"dossier_id": "{did}", "name": "n", "created_by": "x", "created_at": "{at}", "origin": "topic"}}')
    (folder / "broken.json").write_text("{")
    assert [i["dossier_id"] for i in client.get("/api/dossiers").json()["items"]] == ["dos_00000000000b", "dos_00000000000a"]


def test_viewer_reads_but_cannot_change(env):
    client = env[0]
    did = client.post("/api/dossiers", json={"name": "A"}).json()["dossier_id"]
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="v", name="vic", role="viewer")
    assert client.get("/api/dossiers").status_code == 200
    assert client.get(f"/api/dossiers/{did}").status_code == 200
    assert client.post("/api/dossiers", json={"name": "B"}).status_code == 403
    assert client.patch(f"/api/dossiers/{did}", json={"status": "shelved", "reason": "r"}).status_code == 403


def _candidate(run_store, run_id, name):
    c = EmergingThemeCandidate(
        theme_name=name, description="desc", first_detected_date=datetime.now(UTC).date().isoformat(), signal_velocity=5.0,
        corroborating_sources=[MentionCitation(mention_id="m0", source_type=MentionSourceType.GDELT,
                                               url="https://news.example.com/0", quote="q", grounded=True)],
        candidate_sectors_companies=["acme"], economic_rationale="x", cluster_id="cl", run_id=run_id,
    )
    run_store.append_result(run_id, c.model_dump(mode="json"))
    return c.theme_id


def test_promote_opens_one_dossier_per_taxonomy(env):
    client, _, run_store, taxonomies = env
    draft = _SynthesizedActivityDraftList(
        activities=[_SynthesizedActivityDraft(name="a", in_scope_description="x", out_of_scope_description="y")], corpus_assessment="ok")
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient({"_SynthesizedActivityDraftList": [draft, draft]})
    run_id = create_emerging_themes_run(run_store, [CompanyRef(company_id="acme", name="Acme")], "manual")
    first, second, rejected = (_candidate(run_store, run_id, n) for n in ("One", "Two", "Three"))
    url = f"/api/emerging-themes/runs/{run_id}/candidates"

    r = client.post(f"{url}/{first}/promote", json={"reason": "Strong"})
    assert r.status_code == 200 and r.json()["status"] == "promoted"
    did, tid = r.json()["dossier_id"], r.json()["promoted_to_taxonomy_id"]
    assert "context_brief" not in r.json()
    d = client.get(f"/api/dossiers/{did}").json()
    assert (d["origin"], d["run_id"], d["theme_id"], d["taxonomy_id"]) == ("candidate", run_id, first, tid)
    assert (d["steps"][0]["state"], d["steps"][0]["detail"], d["steps"][0]["href"]) == ("done", "promoted: Strong", "#/emergingThemes")

    assert client.post(f"{url}/{first}/promote", json={"reason": "again"}).status_code == 400
    r = client.post(f"{url}/{second}/promote", json={"reason": "More", "taxonomy_id": tid})
    assert r.json()["dossier_id"] == did
    assert client.post(f"{url}/{rejected}/reject", json={"reason": "no"}).status_code == 200
    assert [i["dossier_id"] for i in client.get("/api/dossiers").json()["items"]] == [did]


def test_missing_records_show_as_failed(env):
    client, settings, run_store, taxonomies = env
    tid = _taxonomy(taxonomies, [(1, "ana")])
    folder = settings.runs_dir / "_dossiers"
    folder.mkdir(parents=True)
    (folder / "dos_00000000000c.json").write_text(
        '{"dossier_id": "dos_00000000000c", "name": "n", "created_by": "x", "created_at": "2026-01-01T00:00:00Z",'
        f' "origin": "candidate", "run_id": "nope", "theme_id": "gone", "taxonomy_id": "{tid}"}}')
    import shutil

    shutil.rmtree(settings.taxonomies_dir / tid)
    steps = _steps(client, "dos_00000000000c")
    assert steps[:2] == [("failed", "candidate not found"), ("failed", "taxonomy not found")]
