from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.routers import themes
from arp.schemas.common import RunManifest
from arp.schemas.exposure import IndirectExposureResult
from arp.storage.run_store import RunStore
from tests.postgres_helpers import replace_results


def test_stored_icio_run_results_still_load(tmp_path, pg):
    store = RunStore(pg, tmp_path)
    store.save_manifest(RunManifest(run_id="r1", run_type="theme"))
    old = {"company_id": "c1", "isic_code": "27", "code_scheme": "icio", "upstream_exposure": 0.4,
           "downstream_exposure": 0.6, "core_sector": True, "icio_edition": "X"}
    replace_results(store, "r1", [{"company_matches": [{"company_id": "c1", "indirect_exposure": old}]}])
    app = FastAPI()
    app.include_router(themes.router)
    app.dependency_overrides[get_run_store] = lambda: store
    prefix = next(r.path for r in themes.router.routes if r.path.endswith("/runs/{run_id}/results")).removesuffix("/runs/{run_id}/results")
    r = TestClient(app).get(f"{prefix}/runs/r1/results")
    assert r.status_code == 200
    ie = r.json()["results"][0]["indirect_exposure"]
    assert (ie["io_edition"], ie["code_scheme"]) == ("X", "icio") and "icio_edition" not in ie
    m = IndirectExposureResult.model_validate(old)
    assert m.io_edition == "X" and "icio_edition" not in m.model_dump(mode="json")


def test_new_result_defaults_to_exiobase():
    r = IndirectExposureResult(company_id="c", isic_code="s", upstream_exposure=0, downstream_exposure=0,
                               core_sector=False, io_edition="e")
    assert r.code_scheme == "exiobase" and r.model_dump(mode="json")["io_edition"] == "e"
