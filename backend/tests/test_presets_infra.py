import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import settings_dep
from arp.api.routers import extraction as extraction_router
from arp.checks.plausibility import check_less_or_equal, check_sum_identity, check_sum_to_target
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.presets import registry as presets
from arp.schemas.datapoints import DataPointSchema, FieldDataType
from tests.test_checks_plausibility import _field, _run, _spec


def test_le_of_warns_when_exceeding():
    spec, elig = _spec("aligned", le_of=["eligible"]), _spec("eligible")
    r = _run(check_less_or_equal, spec, _field("aligned", 40), [_field("eligible", 30)], [elig])
    assert (r.check_id, r.outcome, r.severity) == ("le_of", "fail", "warn")
    r = _run(check_less_or_equal, spec, _field("aligned", 30), [_field("eligible", 40)], [elig])
    assert r.outcome == "pass"


def test_le_of_not_applicable_on_other_period():
    spec = _spec("aligned", le_of=["eligible"])
    r = _run(check_less_or_equal, spec, _field("aligned", 40), [_field("eligible", 30, period="2023-12-31")])
    assert r.outcome == "not_applicable"


def _sum(a, b, own, **cfg):
    spec = _spec("t", sum_target=100, sum_of=["a", "b"], **cfg)
    return _run(check_sum_to_target, spec, _field("t", own), [_field("a", a), _field("b", b)])


def test_le_of_each_sibling():
    spec = _spec("x", le_of=["p", "q"])
    others = [_field("p", 50), _field("q", 20)]
    r = _run(check_less_or_equal, spec, _field("x", 30), others)
    assert r.outcome == "fail" and "q" in r.detail


def test_sum_to_target_100():
    assert _sum(60, 30, 10).outcome == "pass"
    r = _sum(60, 30, 0)
    assert (r.check_id, r.outcome, r.severity) == ("sum_target", "fail", "warn")
    assert _sum(60, 30, 10.5, sum_tolerance=0.01).outcome == "pass"


def test_sum_identity_skipped_with_sum_target():
    spec = _spec("t", sum_target=100, sum_of=["a", "b"])
    r = _run(check_sum_identity, spec, _field("t", 10), [_field("a", 60), _field("b", 30)])
    assert r.outcome == "not_applicable"


def test_sum_to_target_not_applicable_without_target_or_part():
    assert _run(check_sum_to_target, _spec("t", sum_of=["a"]), _field("t", 1), [_field("a", 1)]).outcome == "not_applicable"
    spec = _spec("t", sum_target=100, sum_of=["a", "b"])
    assert _run(check_sum_to_target, spec, _field("t", 1), [_field("a", 1)]).outcome == "not_applicable"


def _dummy() -> DataPointSchema:
    return DataPointSchema(schema_id="dummy", name="Dummy", fields=[_spec("x", FieldDataType.NUMBER)])


@pytest.fixture
def dummy(monkeypatch):
    monkeypatch.setitem(presets.PRESETS, "dummy", _dummy)


def test_install_preset_idempotent(pg, tmp_path, dummy):
    reg = SchemaRegistry()
    a = presets.install_preset("dummy", reg)
    assert presets.install_preset("dummy", reg).version == a.version
    with pytest.raises(KeyError):
        presets.install_preset("nope", reg)


def _client(tmp_path, role):
    app = FastAPI()
    app.include_router(extraction_router.router)
    settings = Settings(anthropic_api_key="x", schema_registry_dir=tmp_path / "schemas")
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role=role)
    return TestClient(app)


def test_presets_endpoint_and_install_requires_analyst(pg, tmp_path, dummy):
    listed = _client(tmp_path, "viewer").get("/api/extraction/presets").json()
    assert {"preset_id": "dummy", "name": "Dummy", "field_count": 1} in listed
    url = "/api/extraction/presets/dummy/install"
    assert _client(tmp_path, "viewer").post(url).status_code == 403
    ok = _client(tmp_path, "analyst").post(url)
    assert ok.status_code == 200 and ok.json() == {"schema_id": "dummy", "version": 1}
    assert _client(tmp_path, "analyst").post("/api/extraction/presets/nope/install").status_code == 404
