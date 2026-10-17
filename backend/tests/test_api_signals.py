from __future__ import annotations

import calendar
import csv
import json
import os
import random
import tempfile

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.main import app
from arp.api.routers import signals as signals_router
from arp.api.routers.signals import APP_RUNNABLE
from arp.cli import app as app_cli
from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.signal_lab.evidence import EvidenceReport, WindowEvidence
from arp.signal_lab.methods.base import method_names
from arp.signal_lab.registry import Recipe, Registry
from arp.signal_lab.stats import IcSummary


def _months(n: int, start_year: int = 2016) -> list[str]:
    out = []
    for i in range(n):
        year, month = start_year + i // 12, i % 12 + 1
        out.append(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")
    return out


def _recipe(**kw) -> Recipe:
    base = dict(
        category="sentiment_narrative", method="a", text_source=None, params={},
        universe="sp500", window_start="2010-01", window_end="2020-12", cost_bps=10.0,
    )
    return Recipe(**{**base, **kw})


def _evidence(series: list[tuple[str, float]] | None, window: str = "post_cutoff", ic_mean: float = 0.02) -> EvidenceReport:
    windows = []
    if series is not None:
        windows.append(
            WindowEvidence(
                window=window, periods=len(series), ic=IcSummary(n=len(series), mean=ic_mean, t_nw=1.0, hit_rate=0.5),
                long_short=None, net_long_short=None, monthly_turnover_pct=None, deflated_sharpe=None, series=series,
            )
        )
    return EvidenceReport(windows=windows, contamination_gap_ic=None, overlap={}, n_trials=1)


@pytest.fixture
def registry(client) -> Registry:
    return Registry(_run_store())


def _register(registry, method: str, series, *, ic_mean: float = 0.02, model=None, **recipe_kw):
    return registry.register(
        _recipe(method=method, **recipe_kw), _evidence(series, ic_mean=ic_mean), data_version="v1", model=model, cutoff=None
    )


def _pair(n: int = 36):
    """AC-6: A's month i = 0.10 + 0.01 * (-1)**i, B's = 0.01 * (-1)**(i + 1)."""
    months = _months(n)
    return (
        [(m, 0.10 + 0.01 * (-1) ** i) for i, m in enumerate(months)],
        [(m, 0.01 * (-1) ** (i + 1)) for i, m in enumerate(months)],
    )


@pytest.fixture
def client(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    cutoffs = tmp_path / "cutoffs.json"
    cutoffs.write_text(json.dumps({"m1": {"cutoff": "2020-01-31", "source": "test"}}))
    monkeypatch.setenv("ARP_TRAINING_CUTOFFS_PATH", str(cutoffs))
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def as_role(role: str) -> None:
    app.dependency_overrides[current_user] = lambda: Principal(user_id=f"u_{role}", name=role, role=role)


def test_list_is_newest_first_and_ignores_sort(client, registry):
    a, b = _pair()
    a_id = _register(registry, "a", a, ic_mean=0.20).experiment_id
    b_id = _register(registry, "b", b, ic_mean=0.01).experiment_id
    for url in ("/api/signals/experiments", "/api/signals/experiments?sort=ic"):
        body = client.get(url).json()
        assert [r["experiment_id"] for r in body] == [b_id, a_id]
    keys = {
        "experiment_id", "category", "method", "universe", "window_start", "window_end", "cost_bps",
        "model", "cutoff", "decision", "n_trials", "created_at", "cutoff_status",
    }
    assert keys <= set(body[0])
    assert body[0]["n_trials"] == registry.list_experiments()[-1].evidence.n_trials


def test_detail_matches_registry_record(client, registry):
    a, _ = _pair()
    record = _register(registry, "a", a)
    resp = client.get(f"/api/signals/experiments/{record.experiment_id}")
    assert resp.status_code == 200
    body, expected = resp.json(), record.model_dump(mode="json")
    for key in ("experiment_id", "recipe", "notes", "model", "cutoff", "decision", "decided_by", "evidence"):
        assert body[key] == expected[key]
    assert body["decision"] == "none"


def test_detail_unknown_is_404(client):
    resp = client.get("/api/signals/experiments/nope")
    assert (resp.status_code, resp.json()["detail"]) == (404, "unknown experiment 'nope'")


def test_cutoff_status(client, registry):
    a, _ = _pair()
    ids = {
        status: _register(registry, method, a, model=model).experiment_id
        for status, method, model in (("none", "x", None), ("recorded", "y", "m1"), ("unknown", "z", "m_unknown"))
    }
    for status, experiment_id in ids.items():
        assert client.get(f"/api/signals/experiments/{experiment_id}").json()["cutoff_status"] == status
    listed = {r["experiment_id"]: r["cutoff_status"] for r in client.get("/api/signals/experiments").json()}
    assert listed == {experiment_id: status for status, experiment_id in ids.items()}


def test_methods_marks_app_runnable(client):
    body = client.get("/api/signals/methods").json()
    assert {m["name"] for m in body} == set(method_names())
    assert {m["name"] for m in body if m["runnable_in_app"]} == APP_RUNNABLE


def _compare(client, a_id, b_id):
    return client.post("/api/signals/compare", json={"a": a_id, "b": b_id})


def test_compare_a_higher(client, registry):
    a, b = _pair()
    a_id, b_id = _register(registry, "a", a).experiment_id, _register(registry, "b", b).experiment_id
    first = _compare(client, a_id, b_id)
    assert first.status_code == 200
    assert (first.json()["verdict"], first.json()["months"], first.json()["n_comparisons"]) == ("a_higher", 36, 1)
    assert _compare(client, a_id, b_id).json() == first.json()


def test_compare_identical_is_insufficient(client, registry):
    series = [(m, 0.01 * (-1) ** i) for i, m in enumerate(_months(36))]
    a_id, b_id = _register(registry, "a", series).experiment_id, _register(registry, "b", series).experiment_id
    body = _compare(client, a_id, b_id).json()
    assert (body["verdict"], body["months"]) == ("insufficient_data", 36)


def test_compare_three_in_scope_counts_three(client, registry):
    a, b = _pair()
    a_id, b_id = _register(registry, "a", a).experiment_id, _register(registry, "b", b).experiment_id
    _register(registry, "c", [(m, 0.0) for m, _ in a])
    assert _compare(client, a_id, b_id).json()["n_comparisons"] == 3


def test_compare_not_comparable_is_422(client, registry):
    a, b = _pair()
    a_id = _register(registry, "a", a).experiment_id
    b_id = _register(registry, "b", b, universe="russell2000").experiment_id
    resp = _compare(client, a_id, b_id)
    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("not comparable: universe differs")


def test_compare_errors_are_422(client, registry):
    a, _ = _pair()
    a_id = _register(registry, "a", a).experiment_id
    old_id = _register(registry, "old", []).experiment_id
    for a_arg, b_arg, text in (
        (a_id, old_id, "re-run it"),
        (a_id, a_id, "itself"),
        (a_id, "nope", "unknown experiment 'nope'"),
    ):
        resp = _compare(client, a_arg, b_arg)
        assert resp.status_code == 422
        assert text in resp.json()["detail"]


def test_viewer_can_read_and_compare(client, registry):
    a, b = _pair()
    a_id, b_id = _register(registry, "a", a).experiment_id, _register(registry, "b", b).experiment_id
    as_role("viewer")
    assert client.get("/api/signals/experiments").status_code == 200
    assert client.get("/api/signals/methods").status_code == 200
    assert _compare(client, a_id, b_id).status_code == 200


def test_no_token_is_401(client, monkeypatch):
    app.dependency_overrides.pop(current_user)
    monkeypatch.setenv("ARP_AUTH_MODE", "local")
    get_settings.cache_clear()
    for resp in (
        client.get("/api/signals/experiments"),
        client.get("/api/signals/methods"),
        client.post("/api/signals/compare", json={"a": "x", "b": "y"}),
    ):
        assert (resp.status_code, resp.json()["detail"]) == (401, "Missing or invalid bearer token")


def test_library_registered_llm_experiment_is_listed(client, registry):
    a, _ = _pair()
    experiment_id = _register(registry, "grounded_llm", a, model="m1").experiment_id
    assert experiment_id in [r["experiment_id"] for r in client.get("/api/signals/experiments").json()]


def _decide(client, experiment_id, decision):
    return client.post(f"/api/signals/experiments/{experiment_id}/decision", json={"decision": decision})


def _detail(client, experiment_id):
    return client.get(f"/api/signals/experiments/{experiment_id}").json()


def test_analyst_cannot_decide(client, registry):
    a, _ = _pair()
    experiment_id = _register(registry, "a", a).experiment_id
    as_role("analyst")
    assert _decide(client, experiment_id, "shelve").status_code == 403
    assert _detail(client, experiment_id)["decision"] == "none"


def test_shelve_records_approver(client, registry):
    a, _ = _pair()
    experiment_id = _register(registry, "a", a).experiment_id
    as_role("approver")
    resp = _decide(client, experiment_id, "shelve")
    assert resp.status_code == 200
    assert (resp.json()["decision"], resp.json()["decided_by"]) == ("shelve", "u_approver")
    detail = _detail(client, experiment_id)
    assert (detail["decision"], detail["decided_by"]) == ("shelve", "u_approver")


def test_graduate_needs_12_months(client, registry):
    experiment_id = _register(registry, "a", [(m, 0.01) for m in _months(5)]).experiment_id
    as_role("approver")
    resp = _decide(client, experiment_id, "graduate")
    assert resp.status_code == 422
    assert "needs post-cutoff evidence with at least 12 IC months" in resp.json()["detail"]


def test_graduate_12_months_no_model(client, registry):
    experiment_id = _register(registry, "a", [(m, 0.01) for m in _months(12)]).experiment_id
    as_role("approver")
    resp = _decide(client, experiment_id, "graduate")
    assert (resp.status_code, resp.json()["decision"]) == (200, "graduate")


def test_graduate_after_shelve_appends(client, registry):
    experiment_id = _register(registry, "x", [(m, 0.01) for m in _months(12)]).experiment_id
    as_role("approver")
    assert _decide(client, experiment_id, "shelve").status_code == 200
    assert _decide(client, experiment_id, "graduate").status_code == 200
    assert _detail(client, experiment_id)["decision"] == "graduate"
    rows = [
        r for r in _run_store().read_results("signal_registry")
        if r["type"] == "decision" and r["experiment_id"] == experiment_id
    ]
    assert [r["decision"] for r in rows] == ["shelve", "graduate"]


def _register_model(registry, model: str, cutoff: str | None):
    return registry.register(
        _recipe(method="a"), _evidence([(m, 0.01) for m in _months(12)]), data_version="v1", model=model, cutoff=cutoff
    ).experiment_id


def test_graduate_refused_when_cutoff_changed(client, registry, tmp_path):
    experiment_id = _register_model(registry, "m1", "2020-01-31")
    (tmp_path / "cutoffs.json").write_text(json.dumps({"m1": {"cutoff": "2021-01-31", "source": "test"}}))
    as_role("approver")
    resp = _decide(client, experiment_id, "graduate")
    assert resp.status_code == 422
    assert "the cutoff for model 'm1' changed since the experiment was evaluated" in resp.json()["detail"]


def test_graduate_refused_when_cutoff_unknown(client, registry):
    experiment_id = _register_model(registry, "m_unknown", None)
    as_role("approver")
    resp = _decide(client, experiment_id, "graduate")
    assert resp.status_code == 422
    assert "cutoff unknown: not evidence" in resp.json()["detail"]
    assert not [r for r in _run_store().read_results("signal_registry") if r["type"] == "decision"]


def test_malformed_cutoff_table_is_422(client, registry, tmp_path):
    experiment_id = _register(registry, "a", [(m, 0.01) for m in _months(12)]).experiment_id
    (tmp_path / "cutoffs.json").write_text("{not json")
    as_role("approver")
    resp = _decide(client, experiment_id, "graduate")
    assert resp.status_code == 422
    assert "malformed JSON" in resp.json()["detail"]


ISSUERS = [f"T{i:02d}" for i in range(30)]
REFUSAL = "{} runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app"


def prices_csv(path, months: int, start: int = 2016) -> list[str]:
    """Wide month-end prices: 30 issuers, seeded random walks above 1000, every value distinct to 2 decimals."""
    rng = random.Random(11)
    dates = _months(months, start)
    levels = {t: 5000.0 + 100 * i for i, t in enumerate(ISSUERS)}
    rows, seen = [], set()
    for d in dates:
        for t in ISSUERS:
            levels[t] = round(levels[t] * (1 + rng.gauss(0.01, 0.05)), 2)
            while levels[t] in seen:  # nudge a collision so every price is distinct
                levels[t] = round(levels[t] + 0.01, 2)
            seen.add(levels[t])
        rows.append([d, *(levels[t] for t in ISSUERS)])
    assert min(seen) > 1000
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *ISSUERS])
        writer.writerows(rows)
    return dates


def _scores_csv(path, dates: list[str]) -> None:
    """The wide shape `build-panel` writes and `--panel` reads: a date column plus one column per issuer."""
    rng = random.Random(3)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *ISSUERS])
        writer.writerows([d, *(round(rng.gauss(0, 1), 4) for _ in ISSUERS)] for d in dates)


def _recipe_file(path, dates, method="price_momentum", params=None, **extra):
    recipe = {
        "category": "sentiment_narrative", "method": method, "text_source": None, "params": params or {},
        "universe": "toy30", "window_start": dates[0], "window_end": dates[-1], **extra,
    }
    path.write_text(json.dumps(recipe))
    return path


def _post_run(client, recipe, prices, **panels):
    files = {"recipe": ("r.json", recipe.read_bytes(), "application/json"), "prices": ("p.csv", prices.read_bytes(), "text/csv")}
    files.update({f"panel_{name}": (f"{name}.csv", p.read_bytes(), "text/csv") for name, p in panels.items()})
    return client.post("/api/signals/runs", files=files)


def _cli_id(recipe, prices) -> str:
    result = CliRunner().invoke(app_cli, ["signals", "run", "--recipe", str(recipe), "--prices", str(prices)])
    assert result.exit_code == 0, result.output
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("experiment_id:"))
    return line.split()[1]


def _count(client) -> int:
    return len(client.get("/api/signals/experiments").json())


def _ingest(tmp_path, dates) -> None:
    path = tmp_path / "t.csv"
    rows = [f"{t},{d}T10:00:00Z,Call,Strong growth in {t} this quarter." for d in dates[:8] for t in ISSUERS[:10]]
    path.write_text("issuer_key,event_time,title,text\n" + "\n".join(rows) + "\n")
    result = CliRunner().invoke(app_cli, ["signals", "ingest-transcripts", "--csv", str(path)])
    assert result.exit_code == 0, result.output


@pytest.fixture
def run_files(client, tmp_path):
    dates = prices_csv(tmp_path / "prices.csv", 40)
    return tmp_path, dates, tmp_path / "prices.csv"


def test_run_matches_cli_id(client, run_files):
    tmp_path, dates, prices = run_files
    recipe = _recipe_file(tmp_path / "r.json", dates)
    resp = _post_run(client, recipe, prices)
    assert resp.status_code == 200, resp.text
    assert resp.json()["experiment_id"] == _cli_id(recipe, prices)


def test_run_twice_same_id_one_row(client, run_files):
    tmp_path, dates, prices = run_files
    recipe = _recipe_file(tmp_path / "r.json", dates)
    first = _post_run(client, recipe, prices).json()["experiment_id"]
    trials = client.get("/api/signals/experiments").json()[0]["n_trials"]
    assert _post_run(client, recipe, prices).json()["experiment_id"] == first
    listed = [r for r in client.get("/api/signals/experiments").json() if r["experiment_id"] == first]
    assert len(listed) == 1 and listed[0]["n_trials"] == trials


@pytest.mark.parametrize(
    "method,params,refused",
    [
        *((m, {}, m) for m in ("grounded_llm", "issuer_first", "embedding_ridge", "topic_attention", "finbert")),
        ("composite", {"components": [{"method": "price_momentum"}, {"method": "grounded_llm"}]}, "grounded_llm"),
    ],
)
def test_run_refuses_llm_and_model_methods(client, run_files, method, params, refused):
    tmp_path, dates, prices = run_files
    before = _count(client)
    resp = _post_run(client, _recipe_file(tmp_path / "r.json", dates, method, params), prices)
    assert (resp.status_code, resp.json()["detail"]) == (422, REFUSAL.format(refused))
    assert _count(client) == before


def test_run_window_outside_prices(client, tmp_path):
    prices_csv(tmp_path / "prices.csv", 36, 2020)
    recipe = _recipe_file(tmp_path / "r.json", ["2019-01-31", "2021-12-31"])
    resp = _post_run(client, recipe, tmp_path / "prices.csv")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "recipe window 2019-01-31..2021-12-31 is outside the price file 2020-01-31..2022-12-31"


def test_run_needs_analyst(client, run_files):
    tmp_path, dates, prices = run_files
    before = _count(client)
    as_role("viewer")
    assert _post_run(client, _recipe_file(tmp_path / "r.json", dates), prices).status_code == 403
    assert _count(client) == before


def _numbers(value):
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _numbers(v)


def test_run_stores_no_prices(client, run_files):
    tmp_path, dates, prices = run_files
    experiment_id = _post_run(client, _recipe_file(tmp_path / "r.json", dates), prices).json()["experiment_id"]
    with prices.open(newline="") as f:
        price_values = {float(v) for row in list(csv.reader(f))[1:] for v in row[1:]}
    rows = [r for r in _run_store().read_results("signal_registry") if r.get("experiment_id") == experiment_id]
    assert rows
    for doc in (client.get(f"/api/signals/experiments/{experiment_id}").json(), rows):
        assert not set(_numbers(doc)) & price_values


@pytest.fixture
def temp_dirs(monkeypatch):
    names = []

    class Recording(tempfile.TemporaryDirectory):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            names.append(self.name)

    monkeypatch.setattr(signals_router.tempfile, "TemporaryDirectory", Recording)
    return names


def test_upload_dir_removed(client, run_files, temp_dirs):
    tmp_path, dates, prices = run_files
    assert _post_run(client, _recipe_file(tmp_path / "r.json", dates), prices).status_code == 200
    late = _recipe_file(tmp_path / "late.json", dates, window_end="2099-12-31")
    assert _post_run(client, late, prices).status_code == 422
    assert len(temp_dirs) == 2
    assert not any(os.path.exists(name) for name in temp_dirs)


def test_run_narrative_attention_matches_cli(client, run_files):
    tmp_path, dates, prices = run_files
    _ingest(tmp_path, dates)
    recipe = _recipe_file(tmp_path / "r.json", dates, "narrative_attention", {"terms": ["growth"]})
    resp = _post_run(client, recipe, prices)
    assert resp.status_code == 200, resp.text
    assert resp.json()["experiment_id"] == _cli_id(recipe, prices)


@pytest.mark.parametrize(
    "method,params",
    [
        ("panel", {"name": "p1"}),
        ("sestm", {}),
        ("transform", {"base": {"method": "price_momentum"}}),
        ("composite", {"components": [{"method": "price_momentum"}, {"method": "price_momentum", "params": {"formation_period_months": 6}}]}),
    ],
)
def test_run_app_runnable_methods(client, run_files, method, params):
    tmp_path, dates, prices = run_files
    panels = {}
    if method == "panel":
        _scores_csv(tmp_path / "p1.csv", dates)
        panels["p1"] = tmp_path / "p1.csv"
    if method == "sestm":
        _ingest(tmp_path, dates)
    resp = _post_run(client, _recipe_file(tmp_path / "r.json", dates, method, params), prices, **panels)
    assert resp.status_code == 200, resp.text
    assert resp.json()["experiment_id"]


def test_run_malformed_inputs_are_422(client, run_files):
    tmp_path, dates, prices = run_files
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    resp = _post_run(client, bad, prices)
    assert resp.status_code == 422 and resp.json()["detail"].startswith("invalid recipe")
    recipe = json.loads(_recipe_file(tmp_path / "r.json", dates).read_text())
    del recipe["universe"]
    bad.write_text(json.dumps(recipe))
    resp = _post_run(client, bad, prices)
    assert resp.status_code == 422 and "universe" in resp.json()["detail"]


def test_run_method_failure_is_422(client, run_files, temp_dirs):
    tmp_path, dates, prices = run_files
    resp = _post_run(client, _recipe_file(tmp_path / "r.json", dates, "panel", {"name": "p1"}), prices)
    assert (resp.status_code, resp.json()["detail"]) == (422, "missing panel 'p1'; available: none")
    assert temp_dirs and not any(os.path.exists(name) for name in temp_dirs)


def test_run_bad_parts_are_422(client, run_files):
    tmp_path, dates, prices = run_files
    recipe = _recipe_file(tmp_path / "r.json", dates, "panel", {"name": "p1"})
    resp = client.post("/api/signals/runs", files={"recipe": ("r.json", recipe.read_bytes(), "application/json")})
    assert (resp.status_code, resp.json()["detail"]) == (422, "missing file part 'prices'")
    _scores_csv(tmp_path / "p1.csv", dates)
    resp = _post_run(client, recipe, prices, **{"../p1": tmp_path / "p1.csv"})
    assert (resp.status_code, resp.json()["detail"]) == (422, "Invalid panel name: '../p1'")
