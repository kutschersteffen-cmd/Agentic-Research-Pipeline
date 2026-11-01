"""Real step functions for the plan executor: each starts an existing run type through its own entry point.

Each adapter runs in the executor's worker thread and drives its async run with `asyncio.run`. Results
are what the script sees: {"id", "run_id", "companies": [{id, name, exposure, included}], "gate"}.
"""
from __future__ import annotations

import asyncio
from typing import Any

from arp.config import Settings
from arp.db.runs import RunStore
from arp.orchestration.review_queue import latest_decisions
from arp.schemas.common import CompanyRef

_RANK = {"none": 0, "minor": 1, "significant": 2, "pure_play": 3}


class StepNotWired(RuntimeError):
    pass


def _companies(run_store: RunStore, universe_run_id: str, ids: list[str] | None) -> list[CompanyRef]:
    refs = run_store.load_companies(universe_run_id)
    if refs is None:
        raise ValueError(f"no companies stored for run {universe_run_id}")
    if ids is None:
        return refs
    wanted = set(ids)
    return [r for r in refs if r.company_id in wanted]


def _has_pending_review(run_store: RunStore, run_id: str) -> bool:
    decided = latest_decisions(run_store, run_id)
    return any(r["item_key"] not in decided for r in run_store.read_review_queue(run_id))


def _result(run_id: str, run_store: RunStore, companies: list[dict] | None = None) -> dict[str, Any]:
    return {"id": run_id, "run_id": run_id, "companies": companies or [],
            "gate": _has_pending_review(run_store, run_id)}


def build_steps(settings: Settings, run_store: RunStore) -> dict[str, Any]:
    from arp.api.deps import get_registry
    from arp.llm.factory import build_llm_client, build_verifier_llm_client

    def universe_build(*, taxonomy_id: str, source: str) -> dict[str, Any]:
        from arp.db.fields import SchemaRegistry
        from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
        from arp.research.pipeline import load_theme_run_matches, run_thematic_universe
        from arp.research.taxonomy_schema import released_run_schema
        from arp.storage.taxonomy_store import TaxonomyStore
        from arp.universe import load_company_universe

        # shortcut: `source` is a universe file path; portfolio ids come with the Plans page (plan task 9).
        taxonomy, schema = released_run_schema(TaxonomyStore(settings.taxonomies_dir), SchemaRegistry(settings.postgres_dsn),
                                               taxonomy_id, None)
        companies = load_company_universe(source)
        run_id = asyncio.run(run_thematic_universe(
            taxonomy.theme, companies, llm=build_llm_client(settings), verifier_llm=build_verifier_llm_client(settings),
            registry=get_registry(), settings=settings, run_store=run_store,
            indirect_model=resolve_indirect_exposure_model(settings, use_sample=False), universe_path=source,
            taxonomy_id=taxonomy.taxonomy_id, taxonomy_version=taxonomy.version, extraction_schema=schema))
        best: dict[str, dict] = {c.company_id: {"id": c.company_id, "name": c.name, "exposure": "none",
                                                "included": False} for c in companies}
        for m in load_theme_run_matches(run_store, run_id) or []:
            row = best.setdefault(m.company_id, {"id": m.company_id, "name": m.name, "exposure": "none",
                                                 "included": False})
            if _RANK[m.exposure_estimate.value] > _RANK[row["exposure"]]:
                row["exposure"] = m.exposure_estimate.value
            row["included"] = row["included"] or m.verdict.value == "include"
        return _result(run_id, run_store, list(best.values()))

    def document_discovery(*, universe_run_id: str, doc_types: list[str] | None = None,
                           companies: list[str] | None = None) -> dict[str, Any]:
        from arp.discovery.pipeline import create_discovery_run, execute_discovery_run

        refs = _companies(run_store, universe_run_id, companies)
        run_id = create_discovery_run(refs, doc_types, "research_plan", run_store)
        asyncio.run(execute_discovery_run(run_id, refs, settings=settings, run_store=run_store, doc_types=doc_types))
        return _result(run_id, run_store)

    def extraction(*, universe_run_id: str, schema_id: str, companies: list[str] | None = None) -> dict[str, Any]:
        from arp.db.fields import SchemaRegistry
        from arp.extraction.pipeline import create_extraction_run, execute_extraction_run

        schema = SchemaRegistry(settings.postgres_dsn).get(schema_id)
        refs = _companies(run_store, universe_run_id, companies)
        run_id = create_extraction_run(schema, refs, settings, run_store)  # refuses an unreleased schema
        asyncio.run(execute_extraction_run(run_id, schema, refs, llm=build_llm_client(settings),
                                           verifier_llm=build_verifier_llm_client(settings), registry=get_registry(),
                                           settings=settings, run_store=run_store))
        return _result(run_id, run_store)

    def financials_extraction(*, universe_run_id: str, companies: list[str] | None = None) -> dict[str, Any]:
        from arp.extraction.financials_pipeline import (
            create_financials_extraction_run,
            execute_financials_extraction_run,
        )

        refs = _companies(run_store, universe_run_id, companies)
        run_id = create_financials_extraction_run(refs, settings, run_store)
        asyncio.run(execute_financials_extraction_run(run_id, refs, llm=build_llm_client(settings),
                                                      verifier_llm=build_verifier_llm_client(settings),
                                                      registry=get_registry(), settings=settings, run_store=run_store))
        return _result(run_id, run_store)

    def xbrl_facts(*, universe_run_id: str, companies: list[str] | None = None, market: str = "auto") -> dict[str, Any]:
        from arp.xbrl_pipeline.fetch import create_xbrl_run, execute_xbrl_run

        refs = _companies(run_store, universe_run_id, companies)
        run_id = create_xbrl_run(refs, None, False, run_store, market=market)
        asyncio.run(execute_xbrl_run(run_id, refs, settings=settings, run_store=run_store, tags=None, refresh=False,
                                     market=market))
        return _result(run_id, run_store)

    def decision_score(*, source_run_id: str, framework_id: str | None = None) -> dict[str, Any]:
        from arp.api.deps import get_decision_store
        from arp.decision import templates

        if framework_id is not None:
            config = get_decision_store().latest_ratified(framework_id)
            if config is None:
                raise ValueError(f"framework {framework_id} has no ratified version")
            templates.attach_to_run(run_store, source_run_id, config)
        stored = templates.score_run(run_store, source_run_id)  # None: no framework pinned on the run
        if stored is None:
            raise ValueError(f"run {source_run_id} has no decision framework attached; pass framework_id")
        if stored.get("error"):
            raise RuntimeError(f"the rules step failed: {stored['error']}")
        return {"id": source_run_id, "run_id": None, "result_ref": f"decision:{source_run_id}", "companies": []}

    def report_render(*, source_ids: list[str], template_id: str | None = None) -> dict[str, Any]:
        from arp.api.deps import get_reporting_store
        from arp.reporting.service import ReportingService
        from arp.schemas.reporting import ReportRequest, ReportStatus, RunRef

        service = ReportingService(get_reporting_store())
        request = ReportRequest(title="Research plan report", qualitative_notes="", template_id=template_id,
                                run_refs=[RunRef(kind="run", ref_id=i) for i in source_ids])

        async def _go():
            manifest = await service.create_and_plan(request, build_llm_client(settings))
            # A house deck stops at its storyline for a person to approve (its own gate); others render now.
            return manifest if manifest.status == ReportStatus.STORYLINE_READY else await service.render_from_plan(
                manifest.report_id)

        manifest = asyncio.run(_go())
        return {"id": manifest.report_id, "run_id": None, "result_ref": f"report:{manifest.report_id}",
                "companies": [], "gate": manifest.status == ReportStatus.STORYLINE_READY}

    def not_wired(kind: str):
        def fn(**_: Any) -> dict[str, Any]:
            raise StepNotWired(f"{kind} is not wired to a run type yet")
        return fn

    return {
        "universe_build": universe_build,
        "document_discovery": document_discovery,
        "extraction": extraction,
        "financials_extraction": financials_extraction,
        "xbrl_facts": xbrl_facts,
        "decision_score": decision_score,
        # shortcut: an index review needs candidate market data a plan cannot supply; wire once candidates have a source.
        "index_construct": not_wired("index_construct"),
        "report_render": report_render,
    }


def build_reviewed(run_store: RunStore):
    """A gated run is reviewed once it has no pending review item left; a gated report once its storyline is
    approved."""
    def reviewed(call: dict[str, Any]) -> bool:
        ref = call.get("result_ref") or ""
        if ref.startswith("report:"):
            from arp.api.deps import get_reporting_store
            from arp.schemas.reporting import ReportStatus

            manifest = get_reporting_store().load_manifest(ref.removeprefix("report:"))
            return manifest is not None and manifest.status != ReportStatus.STORYLINE_READY
        return not call.get("run_id") or not _has_pending_review(run_store, call["run_id"])
    return reviewed
