"""The extraction schema generated from a ratified taxonomy version, its endpoints, and the theme-run gate."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.routers import taxonomies, themes
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import NotResumable, check_resumable
from arp.research.revenue_exposure.resolver import RevenueResolverContext, resolve_company_activity_exposure
from arp.research.taxonomy_schema import build_taxonomy_schema
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.conftest import PRINCIPAL
from tests.postgres_helpers import replace_results


def _activity(activity_id: str, name: str, keywords: list[str] | None = None) -> ActivityDefinition:
    return ActivityDefinition(
        activity_id=activity_id, name=name, in_scope_description=f"{name} in scope.", out_of_scope_description="",
        seed_keywords=keywords or [],
    )


def _taxonomy(version=1, status=TaxonomyStatus.RATIFIED, keywords=None) -> Taxonomy:
    theme = ThemeDefinition(name="Grid", description="", activities=[_activity("act_1", "HV cables", keywords), _activity("act_2", "Transformers")])
    return Taxonomy(taxonomy_id="tax_a", name="Grid", version=version, theme=theme, derivation_method=DerivationMethod.MANUAL, status=status)


# --- build_taxonomy_schema ---------------------------------------------------

def test_schema_has_four_fields_per_activity_in_order():
    schema = build_taxonomy_schema(_taxonomy())
    assert (schema.schema_id, schema.name, schema.description) == ("sch_tax_a_v1", "Grid v1", "Generated from taxonomy tax_a v1.")
    assert [f.field_id for f in schema.fields] == [
        f"tax_a_{a}_{m}_pct" for a in ("act_1", "act_2") for m in ("revenue", "capex", "opex", "rd")
    ]
    assert {(f.data_type.value, f.unit, f.required, f.version) for f in schema.fields} == {("percentage", "%", False, 1)}
    assert [f.name for f in schema.fields[:4]] == [
        "HV cables: revenue share", "HV cables: CapEx share", "HV cables: OpEx share", "HV cables: R&D intensity",
    ]


def test_schema_text_and_keywords():
    by_id = {f.field_id: f for f in build_taxonomy_schema(_taxonomy(keywords=["hvdc"])).fields}
    capex, opex = by_id["tax_a_act_1_capex_pct"], by_id["tax_a_act_1_opex_pct"]
    swap = ("capital expenditure (CapEx)", "operating expenditure (OpEx)")
    assert opex.description == capex.description.replace(*swap)
    assert opex.extraction_instructions == capex.extraction_instructions.replace(*swap)
    assert not any("{company" in f.description + f.extraction_instructions for f in by_id.values())
    assert by_id["tax_a_act_1_revenue_pct"].seed_keywords == ["hvdc", "revenue"]
    assert opex.seed_keywords == ["hvdc", "opex"]
    assert by_id["tax_a_act_1_rd_pct"].seed_keywords == ["hvdc", "research and development", "R&D"]


def test_schema_is_deterministic_and_refuses_drafts():
    t = _taxonomy()
    assert build_taxonomy_schema(t).model_dump(exclude={"created_at"}) == build_taxonomy_schema(t).model_dump(exclude={"created_at"})
    with pytest.raises(ValueError, match=r"^Taxonomy tax_a v2 is a draft; ratify it first\.$"):
        build_taxonomy_schema(_taxonomy(version=2, status=TaxonomyStatus.DRAFT))


# --- endpoints and gate ------------------------------------------------------

@pytest.fixture
def api(tmp_path, pg):
    """tax_a: v1 ratified, v2 a draft, nothing registered."""
    store = TaxonomyStore(tmp_path / "taxonomies")
    t = _taxonomy()
    created = store.create("Grid", t.theme, DerivationMethod.MANUAL)
    tid = created.taxonomy_id
    store.ratify(tid, 1, "ana")
    store.new_version(tid, ThemeDefinition(name="Grid", description="", activities=[t.theme.activities[0]]), DerivationMethod.MANUAL, "")
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    run_store = RunStore(pg, settings.runs_dir)
    app = FastAPI()
    app.include_router(taxonomies.router)
    app.include_router(themes.router)
    app.dependency_overrides.update({
        deps.get_taxonomy_store: lambda: store, deps.settings_dep: lambda: settings,
        deps.get_run_store: lambda: run_store, deps.get_registry: lambda: None,
        current_user: lambda: PRINCIPAL,
    })
    return TestClient(app), tid, SchemaRegistry(settings.postgres_dsn), run_store


def test_generate_is_idempotent_and_get_reads_it(api):
    client, tid, registry, _ = api
    assert client.get(f"/api/taxonomies/{tid}/versions/1/schema").json()["detail"] == f"No schema for {tid} v1"
    first = client.post(f"/api/taxonomies/{tid}/versions/1/schema").json()
    assert first["schema_id"] == f"sch_{tid}_v1" and first["release_flag"] is False
    registry.release(first["schema_id"], first["version"], released_by="own")
    again = client.post(f"/api/taxonomies/{tid}/versions/1/schema").json()
    assert (again["version"], again["release_flag"]) == (first["version"], True)
    assert client.get(f"/api/taxonomies/{tid}/versions/1/schema").json()["version"] == first["version"]


def test_schema_endpoints_refuse_drafts_and_unknown_versions(api):
    client, tid, _, _ = api
    for method in (client.post, client.get):
        draft = method(f"/api/taxonomies/{tid}/versions/2/schema")
        assert (draft.status_code, draft.json()["detail"]) == (409, f"Taxonomy {tid} v2 is a draft; ratify it first.")
        missing = method(f"/api/taxonomies/{tid}/versions/9/schema")
        assert (missing.status_code, missing.json()["detail"]) == (404, f"Taxonomy not found: {tid} v9")


def test_ratify_registers_the_schema_and_never_fails_because_of_it(api, monkeypatch):
    client, tid, _, _ = api
    res = client.post(f"/api/taxonomies/{tid}/ratify", json={"version": 2})
    assert res.status_code == 200 and res.json()["status"] == "ratified"
    schema = client.get(f"/api/taxonomies/{tid}/versions/2/schema").json()
    assert len(schema["fields"]) == 4 and {f["version"] for f in schema["fields"]} == {2} and schema["release_flag"] is False

    monkeypatch.setattr(SchemaRegistry, "save", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no db")))
    assert client.post(f"/api/taxonomies/{tid}/ratify", json={"version": 1}).status_code == 200
    assert client.get(f"/api/taxonomies/{tid}/versions/1/schema").status_code == 404


def _run(client, **body):
    return client.post("/api/themes/runs", json={"companies": [{"company_id": "c1", "name": "Acme"}], **body})


def test_theme_run_gate(api, monkeypatch):
    client, tid, registry, run_store = api
    theme = {"name": "t", "description": "d"}
    for body in ({"theme": theme}, {"theme": theme, "taxonomy_id": tid, "taxonomy_version": 1}):
        res = _run(client, **body)
        assert (res.status_code, res.json()["detail"]) == (400, "Theme runs start from a taxonomy version: send taxonomy_id, not theme.")
    draft = f"Taxonomy {tid} v2 is a draft; ratify it and release its schema first."
    assert _run(client, taxonomy_id=tid, taxonomy_version=2).json()["detail"] == draft
    assert _run(client, taxonomy_id=tid).json()["detail"] == draft  # latest is v2
    unreleased = f"Schema sch_{tid}_v1 is not released; release it first."
    assert _run(client, taxonomy_id=tid, taxonomy_version=1).json()["detail"] == unreleased
    saved = client.post(f"/api/taxonomies/{tid}/versions/1/schema").json()
    res = _run(client, taxonomy_id=tid, taxonomy_version=1)
    assert (res.status_code, res.json()["detail"]) == (409, unreleased)
    missing = _run(client, taxonomy_id="tax_zz")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Taxonomy not found: tax_zz")

    registry.release(saved["schema_id"], saved["version"], released_by="own")
    monkeypatch.setattr(themes, "schedule_llm_run", lambda *, create_fn, **_k: create_fn())
    res = _run(client, taxonomy_id=tid, taxonomy_version=1)
    assert res.status_code == 200
    params = run_store.load_manifest(res.json()["run_id"]).params
    assert (params["taxonomy_id"], params["taxonomy_version"]) == (tid, 1)
    assert (params["extraction_schema_id"], params["extraction_schema_version"]) == (f"sch_{tid}_v1", saved["version"])


def test_results_fill_opex_on_old_rows(api):
    client, _, _, run_store = api
    run_id = JobManager(run_store).create_run("theme", {}, 1).run_id
    old = {"activity_id": "a", "revenue": {"source": "unresolved"}, "capex": {"source": "unresolved"}, "sector_relevant": True}
    replace_results(run_store, run_id, [{"_key": "c1", "company_matches": [{"activity_id": "a", "revenue_exposure": old}]}])
    row = client.get(f"/api/themes/runs/{run_id}/results").json()["results"][0]
    assert row["revenue_exposure"]["opex"]["source"] == "unresolved"


def test_theme_run_from_before_schemas_is_not_resumable(api):
    _, _, _, run_store = api
    manifest = JobManager(run_store).create_run("theme", {"taxonomy_id": "tax_a"}, 1, companies=[CompanyRef(company_id="c1", name="Acme")])
    with pytest.raises(NotResumable, match="Started before taxonomy schemas; start a new run."):
        check_resumable(run_store, manifest.run_id)


# --- the exposure tier extracts only the released schema's fields ------------

class _Docs(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


class _Recording:
    """Answers 18.5 for every field and records each prompt."""

    def __init__(self, doc: SourceDocument, quote: str):
        self.prompts: list[str] = []
        self._draft = ExtractionDraft(value=18.5, raw_value_text=quote, citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], confidence=0.9)

    async def complete_structured(self, *, system, prompt, output_model, **_k):
        from arp.llm.base import LLMUsage

        self.prompts.append(prompt)
        out = self._draft if issubclass(output_model, ExtractionDraft) else VerifierOutput(agrees=True, confidence=0.9, notes="ok")
        return out, LLMUsage(input_tokens=1, output_tokens=1, provider="fake")


async def test_revenue_tier_extracts_revenue_capex_opex_of_the_released_schema(tmp_path):
    taxonomy = _taxonomy(keywords=["cable"])
    schema = build_taxonomy_schema(taxonomy).model_copy(update={"release_flag": True, "version": 3})
    quote = "18.5% of revenue came from cable sales"
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text=f"{quote}, capex and opex alike.")
    llm = _Recording(doc, quote)
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    ctx = RevenueResolverContext(catalogue_by_company={}, mappings=[], registry=DocumentSourceRegistry([_Docs([doc])]), settings=settings, schema=schema)

    result, _ = await resolve_company_activity_exposure(
        CompanyRef(company_id="c1", name="Acme"), taxonomy.theme.activities[0], None, documents=[doc], ctx=ctx, llm=llm
    )
    for m in (result.revenue, result.capex, result.opex):
        assert (m.source, m.value_pct, m.citation.schema_version) == ("extracted", 0.185, "sch_tax_a_v1:v3")
    named = {line for p in llm.prompts for line in p.splitlines() if line.startswith("Field: ")}
    assert named == {"Field: HV cables: revenue share", "Field: HV cables: CapEx share", "Field: HV cables: OpEx share"}


def test_cli_theme_run_gate(api, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from arp.cli import app as app_cli
    from arp.config import get_settings

    _, tid, _, _ = api
    monkeypatch.setenv("ARP_TAXONOMIES_DIR", str(tmp_path / "taxonomies"))
    get_settings.cache_clear()
    universe = tmp_path / "u.csv"
    universe.write_text("company_id,name\nc1,Acme\n")
    cases = [
        (["--theme", "t.json"], "Theme runs start from a taxonomy version: send taxonomy_id, not theme."),
        (["--taxonomy", tid, "--taxonomy-version", "2"], f"Taxonomy {tid} v2 is a draft; ratify it and release its schema first."),
        (["--taxonomy", tid, "--taxonomy-version", "1"], f"Schema sch_{tid}_v1 is not released; release it first."),
    ]
    for args, message in cases:
        result = CliRunner().invoke(app_cli, ["theme", "run", *args, "--universe", str(universe)])
        assert result.exit_code == 1 and message in result.output


def test_industry_anchored_taxonomy_needs_an_input_output_model(api):
    client, *_ = api
    res = client.post("/api/taxonomies", json={"name": "t", "derivation_method": "industry_anchored", "use_sample_io": False})
    assert (res.status_code, res.json()["detail"]) == (
        400, "No input-output data available: run arp io build-full and set ARP_VALUE_CHAIN_DIR, or set use_sample_io.")
