"""security-errors-ssrf PR 2 (AC-32..AC-55): marker exceptions map to 400/503, anything else is a logged generic 500."""
from __future__ import annotations

import importlib
import json
import logging
import re
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from arp.api.auth import load_users
from arp.api.main import app
from arp.config import Settings
from arp.errors import ClientInputError, NotConfigured
from arp.llm.factory import build_llm_client
from arp.net_safety import UnsafeURLError
from arp.storage.safe_path import UnsafeIdentifierError
from arp.universe import UniverseRejected

LOGGER = "arp.api.main"


class M(BaseModel):
    n: int


class Body(BaseModel):
    n: int


def _route(fn, method="GET"):
    path = f"/__t/{uuid.uuid4().hex}"
    app.add_api_route(path, fn, methods=[method])
    return path


def _raiser(exc):
    def handler():
        raise exc

    return handler


@pytest.fixture
def client():
    n = len(app.router.routes)
    yield TestClient(app, raise_server_exceptions=False)
    del app.router.routes[n:]


def _errors(caplog):
    return [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.ERROR and r.exc_info]


def _get(client, fn):
    return client.get(_route(fn))


def test_ac32_client_input_error_is_400(client, caplog):  # AC-32, AC-33
    r = _get(client, _raiser(ClientInputError("bad group_by 'x'")))
    assert (r.status_code, r.json()) == (400, {"detail": "bad group_by 'x'"})
    assert _errors(caplog) == []


@pytest.mark.parametrize(
    "exc", [UnsafeIdentifierError("Invalid id: '../x'"), UnsafeURLError("Unsupported URL scheme: 'file'"),
            UniverseRejected("bad GICS code '1' for company 'c'")],
)
def test_ac34_existing_domain_errors_are_400(client, exc):
    r = _get(client, _raiser(exc))
    assert (r.status_code, r.json()) == (400, {"detail": str(exc)})


def test_ac35_not_configured_is_503(client):
    r = _get(client, _raiser(NotConfigured("ARP_ANTHROPIC_API_KEY is not set.")))
    assert (r.status_code, r.json()) == (503, {"detail": "ARP_ANTHROPIC_API_KEY is not set."})


def test_ac36_missing_anthropic_key_is_503(client):
    def h():
        build_llm_client(Settings(standins_dir=None, llm_model="claude-sonnet-4-5", anthropic_api_key=None))

    r = _get(client, h)
    assert r.status_code == 503
    assert r.json()["detail"] == (
        "ARP_ANTHROPIC_API_KEY is not set. Provide an Anthropic API key via environment variable "
        "or a .env file before running any agent pipeline."
    )


def test_ac37_missing_gemini_key_is_503(client):
    def h():
        build_llm_client(Settings(standins_dir=None, llm_model="gemini-2.5-pro", gemini_api_key=None))

    r = _get(client, h)
    assert (r.status_code, r.json()["detail"]) == (
        503, "ARP_GEMINI_API_KEY is not set, and the run uses the Gemini model gemini-2.5-pro.")


def test_ac38_duplicate_token_users_file_is_503(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    users = [{"token": "t", "user_id": f"u{i}", "name": "N", "role": "viewer"} for i in range(2)]
    Path("users.json").write_text(json.dumps({"users": users}))
    r = _get(client, lambda: load_users(Path("users.json")))
    assert (r.status_code, r.json()["detail"]) == (
        503, "Users file users.json has a blank or duplicate token or a duplicate user_id.")


def _generic_500(r):
    assert r.status_code == 500
    assert set(r.json()) == {"detail", "request_id"}
    assert r.json()["detail"] == "Internal error"
    assert re.fullmatch(r"[0-9a-f]{32}", r.json()["request_id"])
    return r.json()["request_id"]


def test_ac39_to_42_validation_error_in_handler_is_generic_500(client, caplog):
    r = _get(client, lambda: M(n="secret-input"))
    rid = _generic_500(r)
    assert "secret-input" not in r.text and "validation error" not in r.text
    errs = _errors(caplog)
    assert len(errs) == 1 and rid in errs[0].getMessage()
    assert type(errs[0].exc_info[1]).__name__ == "ValidationError"  # pydantic_core


def test_ac43_request_ids_differ(client, caplog):
    path = _route(lambda: M(n="x"))
    a, b = client.get(path).json()["request_id"], client.get(path).json()["request_id"]
    assert a != b
    msgs = [r.getMessage() for r in _errors(caplog)]
    assert len(msgs) == 2 and a in msgs[0] and b in msgs[1]


def test_ac44_runtime_error_is_generic_500(client, caplog):
    r = _get(client, _raiser(RuntimeError("db password=hunter2 down")))
    _generic_500(r)
    assert "hunter2" not in r.text
    errs = _errors(caplog)
    assert len(errs) == 1 and type(errs[0].exc_info[1]) is RuntimeError


def test_ac45_bare_value_error_is_generic_500(client, caplog):
    r = _get(client, _raiser(ValueError("leak-45")))
    _generic_500(r)
    assert "leak-45" not in r.text
    assert len(_errors(caplog)) == 1


def test_ac46_request_validation_is_422_without_input(client):
    def h(body: Body):
        return {}

    r = client.post(_route(h, "POST"), json={"n": "secret-input"})
    assert r.status_code == 422
    (item,) = r.json()["detail"]
    assert set(item) == {"type", "loc", "msg"}
    assert (item["loc"], item["type"]) == (["body", "n"], "int_parsing")
    assert "secret-input" not in r.text


def test_ac48_http_exception_unchanged(client, caplog):
    r = _get(client, _raiser(HTTPException(404, "nope")))
    assert (r.status_code, r.json()) == (404, {"detail": "nope"})
    assert _errors(caplog) == []


# AC-55: every class that answers 400/503 today keeps that status. (module, class)
_400 = [
    ("arp.universe", "UniverseRejected"), ("arp.storage.safe_path", "UnsafeIdentifierError"),
    ("arp.net_safety", "UnsafeURLError"), ("arp.projects.store", "ProjectError"),
    ("arp.research.value_chain.model", "ShockError"), ("arp.research.value_chain.model", "UnknownMaterial"),
    ("arp.research.value_chain.links", "LinkError"), ("arp.research.value_chain.revenue", "RecipeError"),
    ("arp.research.taxonomy_schema", "ThemeRunRefused"), ("arp.research.exposure_layers", "LayerSettingsError"),
    ("arp.orchestration.jobs", "NotResumable"), ("arp.orchestration.plan_interp", "PlanScriptError"),
    ("arp.orchestration.plan_planner", "PlanRejected"), ("arp.snapshots.client", "SnapshotInvalid"),
    ("arp.snapshots.build", "SnapshotSettling"), ("arp.publish.release", "WithdrawalError"),
    ("arp.publish.facts", "LicenceRefused"), ("arp.transition_alignment.benchmarks", "BenchmarksError"),
    ("arp.holdings.intake", "IntakeError"), ("arp.holdings.security_master", "MasterRejected"),
    ("arp.transition_barrier.rule_book", "RuleBookError"), ("arp.reporting.chart_builder", "ChartDataError"),
]
_503 = [
    ("arp.storage.opensearch_client", "OpenSearchNotConfigured"),
    ("arp.transition_barrier.refresh.pipeline", "RefreshDisabledError"),
    ("arp.reporting.browser", "BrowserUnavailable"), ("arp.orchestration.jobs", "RunBusy"),
    ("arp.orchestration.plan_store", "PlanNotReplannable"), ("arp.orchestration.plan_executor", "PlanNotRunnable"),
    ("arp.orchestration.plan_interp", "StepLimitExceeded"), ("arp.snapshots.client", "SnapshotHashMismatch"),
    ("arp.snapshots.build", "SnapshotFrozen"), ("arp.publish.facts", "ConcurrentPublish"),
]

# Not in the spec's table; the owner chose to keep today's status.
_EXTRA = [
    ("arp.storage.opensearch_client", "OpenSearchExtraNotInstalled", 503),
    ("arp.storage.taxonomy_store", "TaxonomyVersionConflict", 503),
    ("arp.storage.postgres", "PostgresExtraNotInstalled", 503),
    ("arp.storage.document_blob_store", "CaptureStoreError", 503),
    ("arp.storage.object_store_client", "ObjectStoreExtraNotInstalled", 503),
    ("arp.xbrl_pipeline.verify", "CircularRunError", 400),
    ("arp.xbrl_pipeline.verify", "UnsupportedRunError", 400),
    ("arp.argus.start", "StartError", 400),
    ("arp.rfp.fill", "FillRefused", 400),
    ("arp.db.importer", "ImportFailed", 503),
    ("arp.db.fields", "FieldIdCollision", 400),
    ("arp.db.fields", "UnreleasedFieldError", 400),
    ("arp.db.fields", "FieldVersionError", 400),
    ("arp.index.optimize", "RiskModelCoverageError", 400),
    ("arp.index.fields", "DataQualityBlock", 503),
    ("arp.index.risk", "RiskModelError", 400),
    ("arp.authoritative.store", "StalePublish", 400),
    ("arp.company_graph", "CompanyGraphError", 503),
]


@pytest.mark.parametrize(
    "mod,name,status", [(m, n, 400) for m, n in _400] + [(m, n, 503) for m, n in _503] + _EXTRA
)
def test_ac55_status_quo_per_class(client, mod, name, status):
    cls = getattr(importlib.import_module(mod), name)
    # Not every class takes one string: OpenSearchNotConfigured takes none, ThemeRunRefused and IntakeError (status, message).
    for args in (("m",), (400, "m"), ()):
        try:
            exc = cls(*args)
            break
        except TypeError:
            continue
    r = _get(client, _raiser(exc))
    assert (r.status_code, r.json()) == (status, {"detail": str(exc)})
