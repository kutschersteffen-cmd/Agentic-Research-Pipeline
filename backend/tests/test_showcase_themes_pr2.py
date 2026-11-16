"""showcase-themes-fixes PR 2: the API side of defects 7, 8 (links), 12."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import Principal, authorize, current_user
from arp.api.main import app
from arp.api.routers import emerging_themes as emerging_router
from arp.emerging_themes import pipeline as pipeline_module
from arp.emerging_themes.pipeline import create_emerging_themes_run, execute_emerging_themes_run
from arp.llm.base import LLMUsage
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.taxonomy import DerivationMethod
from arp.storage.run_store import RunStore
from arp.storage.topic_store import TopicStateStore
from tests.conftest import FakeLLMClient
from tests.test_api_authority_taxonomy import BASE, _start, client  # noqa: F401 - client is a fixture
from tests.test_dossiers import THEME, _run, _taxonomy, env  # noqa: F401 - env is a fixture
from tests.test_emerging_themes_pipeline import _fake_cluster_tags, _FixedMentionSource, _mentions, _settings


class _MillionTokenLLM(FakeLLMClient):
    """Every call reports 1M input tokens under a model the price table does not know."""

    async def complete_structured(self, **kwargs):
        out, _ = await super().complete_structured(**kwargs)
        return out, LLMUsage(input_tokens=1_000_000, output_tokens=0, model="not-in-the-price-table")


async def test_emerging_run_records_cost_and_model(tmp_path, monkeypatch, pg):  # AC-51, AC-52
    from arp.emerging_themes.context_brief import _ContextBriefDraft
    from arp.emerging_themes.extraction import _TagDraft, _TagDraftList
    from arp.emerging_themes.synthesis import _CandidateDraft

    monkeypatch.setattr(pipeline_module, "cluster_tags", _fake_cluster_tags)
    settings = _settings(tmp_path).model_copy(update={"llm_model": "m1", "emerging_themes_company_exposure_enabled": False})
    run_store = RunStore(pg, settings.runs_dir)
    companies = [CompanyRef(company_id="acme", name="Acme Battery Co")]
    tag = _TagDraft(label="solid-state", claim="c", entity_names=["Acme Battery Co"], action_type="capex",
                    quote="Acme Battery Co unveils solid-state battery breakthrough")
    llm = _MillionTokenLLM({
        "_TagDraftList": [_TagDraftList(tags=[tag])] * 5,
        "_CandidateDraft": [_CandidateDraft(theme_name="T", description="d", economic_rationale="e", rationale="r")],
        "_ContextBriefDraft": [_ContextBriefDraft(why_now=[], early_evidence=[], by_company=[], groups=[])],
    })
    run_id = create_emerging_themes_run(run_store, companies, "manual")
    await execute_emerging_themes_run(run_id, companies, llm=llm, sources=[_FixedMentionSource(_mentions())],
                                      settings=settings, run_store=run_store,
                                      topic_store=TopicStateStore(tmp_path / "topics"))
    manifest = run_store.load_manifest(run_id)
    assert len(llm.calls) == 7
    assert manifest.estimated_cost_usd == 3.0 * len(llm.calls)
    assert manifest.model == "m1"


def test_emerging_schedule_refuses_a_non_positive_interval(tmp_path):  # AC-57
    saved = []

    class _Scheduler:
        def load_config(self):
            return None

        def save_config(self, config):
            saved.append(config)

    api = FastAPI()
    api.include_router(emerging_router.router)
    api.dependency_overrides[deps.get_emerging_themes_scheduler] = lambda: _Scheduler()
    c = TestClient(api)
    for hours in (0, -1):
        assert c.put("/api/emerging-themes/schedule", json={"enabled": True, "interval_hours": hours}).status_code == 422
    assert saved == []
    assert c.put("/api/emerging-themes/schedule", json={"enabled": True, "interval_hours": 24}).status_code == 200


def test_step_4_waiting_links_to_the_review(env):  # noqa: F811 - AC-60
    c, settings, run_store, taxonomies = env
    tid = _taxonomy(taxonomies, [(1, "ana")])
    d = c.post("/api/dossiers", json={"name": "A", "taxonomy_id": tid}).json()["dossier_id"]
    run_id = _run(settings, run_store, tid, 1, JobStatus.COMPLETED, pending=1)
    step = c.get(f"/api/dossiers/{d}").json()["steps"][3]
    assert (step["state"], step["detail"], step["href"]) == ("waiting", "1 to review", f"#/review/theme/{run_id}")


def test_unshelve(env):  # noqa: F811 - AC-88, AC-121, AC-129
    c = env[0]
    d = c.post("/api/dossiers", json={"name": "A"}).json()["dossier_id"]
    before = c.get(f"/api/dossiers/{d}").json()
    res = c.patch(f"/api/dossiers/{d}", json={"status": "active"})
    assert (res.status_code, res.json()) == (200, before)
    c.patch(f"/api/dossiers/{d}", json={"status": "shelved", "reason": "parked"})
    assert c.patch(f"/api/dossiers/{d}", json={"status": "shelved"}).status_code == 422
    assert c.patch(f"/api/dossiers/{d}", json={"status": "archived"}).status_code == 422
    body = c.patch(f"/api/dossiers/{d}", json={"status": "active"}).json()
    assert (body["status"], body["shelved_by"], body["shelved_at"], body["shelve_reason"]) == ("active", None, None, None)


def test_viewer_cannot_unshelve(env):  # noqa: F811 - AC-122
    c = env[0]
    d = c.post("/api/dossiers", json={"name": "A"}).json()["dossier_id"]
    c.patch(f"/api/dossiers/{d}", json={"status": "shelved", "reason": "parked"})
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="v", name="vic", role="viewer")
    assert c.patch(f"/api/dossiers/{d}", json={"status": "active"}).status_code == 403
    assert c.get(f"/api/dossiers/{d}").json()["status"] == "shelved"


def test_new_version_keeps_the_derivation_method(env):  # noqa: F811 - AC-82, AC-101
    c, _, _, taxonomies = env
    for method in (DerivationMethod.LLM_DRAFT, DerivationMethod.MANUAL):
        tid = taxonomies.create("Grid", THEME, method).taxonomy_id
        res = c.post(f"/api/taxonomies/{tid}/versions", json={"theme": THEME.model_copy(update={"description": "e"}).model_dump()})
        assert (res.status_code, res.json()["derivation_method"]) == (200, method.value)


def test_authority_sources_refuse_non_web_addresses(client):  # noqa: F811 - AC-84, 85, 119, 120, 102
    rid = _start(client).json()["id"]
    for urls, bad in ((["not a url"], "not a url"), (["ftp://a.org/x"], "ftp://a.org/x"),
                      (["https://a.org/x", "http://"], "http://"), (["http://[::1"], "http://[::1")):
        res = client.post(f"{BASE}/{rid}/sources", json={"urls": urls, "files": []})
        assert (res.status_code, res.json()["detail"]) == (
            422, f'Not a web address: "{bad}". Enter a full address starting with http:// or https://.')
    state = client.get(f"{BASE}/{rid}").json()
    assert state["stage"] == "awaiting_sources" and not (state.get("selection") or {}).get("urls")
    assert client.post(f"{BASE}/{rid}/sources", json={"urls": ["https://a.invalid/x"], "files": []}).status_code == 200


def test_authority_sources_store_trimmed_addresses(client):  # noqa: F811 - code review note 5
    rid = _start(client).json()["id"]
    res = client.post(f"{BASE}/{rid}/sources", json={"urls": [" https://a.org/x\n"], "files": []})
    assert (res.status_code, res.json()["selection"]["urls"]) == (200, ["https://a.org/x"])
