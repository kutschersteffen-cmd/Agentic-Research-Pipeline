import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.config import get_settings
from arp.schemas.common import CompanyRef, RunManifest
from arp.schemas.thematic import ActivityDefinition, CompanyMatch, ThemeDefinition


@pytest.fixture
def client(run_store, tmp_path, monkeypatch):
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_viewer", name="viewer", role="viewer")
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_run_store, None)
    get_settings.cache_clear()


NAMES = {"act_stacks": "Stacks", "act_bop": "Balance of plant", "act_svc": "Services"}


def rev(act, x, src):
    return {"activity_id": act, "revenue": {"value_pct": x, "source": src},
            "capex": {"value_pct": None, "source": "unresolved"}, "sector_relevant": True}


def rd(act, r, n):
    return {"activity_id": act, "rd_intensity": {"value_pct": r, "source": "extracted" if r is not None else "unresolved"},
            "news_mentions": {"value_pct": n, "source": "news" if n is not None else "unresolved"}, "sector_relevant": True}


def m(cid, act, verdict, est, **keys):
    d = CompanyMatch(company_id=cid, name=cid, activity_id=act, activity_name=NAMES[act], verdict=verdict,
                     exposure_estimate=est, confidence=0.9, adjudicator_rationale="r").model_dump(mode="json")
    d.update(keys)
    return d


def fixture_g():
    beta_rev = rev("act_bop", 0.08, "modelled")
    beta_rev["revenue"].update(low_pct=0.05, high_pct=0.11)
    beta_rev["capex"] = {"value_pct": 0.30, "source": "extracted"}
    return {
        "Alpha": [
            m("alpha", "act_stacks", "include", "pure_play", revenue_exposure=rev("act_stacks", 0.71, "reported"),
              relation="makes", rd_exposure=rd("act_stacks", 0.14, 0.60)),
            m("alpha", "act_svc", "include", "significant", revenue_exposure=rev("act_svc", 0.11, "extracted")),
            m("alpha", "act_bop", "exclude", "none"),
        ],
        "Beta": [m("beta", "act_bop", "include", "minor", revenue_exposure=beta_rev, relation="makes")],
        "Gamma": [m("gamma", "act_stacks", "include", "significant", relation="operates")],
        "Delta": [m("delta", "act_stacks", "exclude", "none", rd_exposure=rd("act_stacks", 0.90, None))],
        "Epsilon": [m("epsilon", "act_stacks", "include", "pure_play", revenue_exposure=rev("act_stacks", 0.55, "catalogue"),
                      flagged_for_review=True, company_role="pure_player")],
        "Zeta": [m("zeta", "act_stacks", "include", "minor", company_role="innovator", rd_exposure=rd("act_stacks", 0.80, None))],
        "Omega": [],
    }


def save(store, companies, run_id="R", theme=True):
    store.save_manifest(RunManifest(run_id=run_id, run_type="theme"))
    store.save_companies(run_id, [CompanyRef(company_id=n.lower(), name=n) for n in companies])
    for n, matches in companies.items():
        if matches:
            store.append_result(run_id, {"_key": n.lower(), "company_matches": matches})
    if theme:
        acts = [ActivityDefinition(activity_id=a, name=NAMES[a], tier=t, in_scope_description="i", out_of_scope_description="o")
                for a, t in (("act_stacks", "core"), ("act_bop", "enabling"), ("act_svc", "core"))]
        path = store.run_dir(run_id) / "theme.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ThemeDefinition(name="Electrolysers", description="d", activities=acts).model_dump_json())


def rows(client, run_id="R"):
    res = client.get(f"/api/themes/runs/{run_id}/exposure")
    assert res.status_code == 200, res.text
    return {r["name"]: r for r in res.json()["rows"]}, res.json()


def test_fixture_g(client, run_store):
    save(run_store, fixture_g())
    by_name, body = rows(client)
    assert set(body) == {"run_id", "thresholds", "rows"}
    assert body["thresholds"] == {"pure_play": 0.7, "majority": 0.5, "partial": 0.05}
    assert [r["name"] for r in body["rows"]] == ["Alpha", "Epsilon", "Beta", "Gamma", "Zeta", "Delta", "Omega"]
    a = by_name["Alpha"]
    assert {k: a[k] for k in ("tier", "share", "share_low", "share_high", "share_basis", "momentum", "momentum_band",
                              "momentum_signals", "role", "needs_check")} == {
        "tier": "pure_play", "share": 0.82, "share_low": None, "share_high": None, "share_basis": "extracted",
        "momentum": 0.37, "momentum_band": "medium", "momentum_signals": {"rd": 0.14, "capex": None, "mentions": 0.6},
        "role": "maker", "needs_check": False}
    assert [(x["share"], x["basis"], x["relation"], x["role"]) for x in a["activities"]] == [
        (0.71, "reported", "makes", "maker"), (0.11, "extracted", None, "maker"), (None, None, None, None)]
    b = by_name["Beta"]
    assert (b["tier"], b["share"], b["share_low"], b["share_high"], b["share_basis"], b["momentum"], b["role"]) == (
        "partial", 0.08, 0.05, 0.11, "modelled", 0.3, "supplier")
    g = by_name["Gamma"]
    assert (g["tier"], g["share"], g["share_basis"], g["momentum_band"], g["role"]) == ("partial", None, "label", None, "operator")
    d = by_name["Delta"]
    assert (d["tier"], d["share_basis"], d["role"], d["momentum_signals"]["rd"]) == ("out", None, None, None)
    e = by_name["Epsilon"]
    assert (e["tier"], e["share_basis"], e["role"], e["needs_check"]) == ("majority", "catalogue", "maker", True)
    z = by_name["Zeta"]
    assert (z["tier"], z["share_basis"], z["momentum"], z["momentum_band"], z["role"]) == ("ecosystem", "label", 0.8, "high", "developer")
    o = by_name["Omega"]
    assert (o["tier"], o["role"], o["activities"]) == ("out", None, [])


def test_tier_settings(client, run_store, monkeypatch):
    save(run_store, fixture_g())
    monkeypatch.setenv("ARP_THEME_TIER_PURE_PLAY", "0.9")
    by_name, body = rows(client)
    assert body["thresholds"]["pure_play"] == 0.9 and by_name["Alpha"]["tier"] == "majority"
    for env, value, detail in [
        ("ARP_THEME_TIER_MAJORITY", "0.95", "ARP_THEME_TIER_PARTIAL < ARP_THEME_TIER_MAJORITY < ARP_THEME_TIER_PURE_PLAY is required"),
        ("ARP_THEME_TIER_PURE_PLAY", "1.5", "ARP_THEME_TIER_PURE_PLAY must be greater than 0 and at most 1"),
        ("ARP_THEME_TIER_PARTIAL", "0", "ARP_THEME_TIER_PARTIAL must be greater than 0 and at most 1"),
    ]:
        monkeypatch.delenv("ARP_THEME_TIER_PURE_PLAY", raising=False)
        monkeypatch.setenv(env, value)
        res = client.get("/api/themes/runs/R/exposure")
        assert (res.status_code, res.json()["detail"]) == (503, detail)
        monkeypatch.delenv(env)


def test_modelled_sums_lead_and_cap(client, run_store):
    g = fixture_g()
    g["Beta"].append(m("beta", "act_stacks", "include", "minor", revenue_exposure=rev("act_stacks", 0.20, "reported")))
    g["Theta"] = [m("theta", a, "include", "significant", revenue_exposure=rev(a, x, "reported"))
                  for a, x in (("act_stacks", 0.70), ("act_svc", 0.60))]
    g["Xi"] = [m("xi", "act_stacks", "include", "minor", revenue_exposure=rev("act_stacks", 0.20, "modelled"))]
    g["Mu"] = [m("mu", "act_stacks", "uncertain", "none", revenue_exposure=rev("act_stacks", 0.40, "extracted"))]
    save(run_store, g)
    by_name, _ = rows(client)
    b = by_name["Beta"]
    assert (b["share"], b["share_low"], b["share_high"], b["share_basis"], b["role"]) == (0.28, 0.25, 0.31, "modelled", "maker")
    assert (by_name["Theta"]["share"], by_name["Theta"]["tier"]) == (1.0, "pure_play")
    x = by_name["Xi"]
    assert (x["share_low"], x["share_high"], x["activities"][0]["share_low"]) == (0.2, 0.2, None)
    mu = by_name["Mu"]
    assert (mu["tier"], mu["share"], mu["activities"][0]["basis"]) == ("out", None, None)


def test_without_theme_json_tier_counts_as_core(client, run_store):
    save(run_store, fixture_g(), theme=False)
    assert rows(client)[0]["Beta"]["role"] == "maker"


def test_unknown_and_wrong_type_run(client, run_store):
    run_store.save_manifest(RunManifest(run_id="X", run_type="extraction"))
    for rid in ("nope", "X"):
        res = client.get(f"/api/themes/runs/{rid}/exposure")
        assert (res.status_code, res.json()["detail"]) == (404, f"unknown theme run '{rid}'")
