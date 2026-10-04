"""Event-driven refresh (E20): a new or updated filing starts one extraction run per issuer and
configured released schema, deduplicated per filing and capped per UTC day."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from arp.schemas.common import CompanyRef
from arp.schemas.discovery import DocumentEvent, DocumentEventType
from arp.storage.jsonl_io import append_jsonl, read_jsonl

if TYPE_CHECKING:
    from arp.config import Settings
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.orchestration.jobs import LocalJobLauncher
    from arp.schemas.datapoints import DataPointSchema
    from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

_REFRESH_TYPES = {DocumentEventType.NEW_DOCUMENT, DocumentEventType.UPDATED_DOCUMENT}


def _universe(settings: Settings) -> dict[str, CompanyRef]:
    if not settings.discovery_schedule_universe_path:
        return {}
    from arp.universe import load_company_universe

    try:
        return {c.company_id: c for c in load_company_universe(settings.discovery_schedule_universe_path)}
    except (OSError, ValueError) as exc:
        logger.warning("Refresh: discovery universe unreadable, using event identities: %s", exc)
        return {}


def _job(run_id: str, schema: DataPointSchema, companies: list[CompanyRef], settings: Settings,
         run_store: RunStore, registry: DocumentSourceRegistry):
    async def job() -> None:
        from arp.extraction.pipeline import execute_extraction_run
        from arp.llm.factory import build_llm_client, build_verifier_llm_client
        from arp.orchestration.jobs import _xbrl_source

        await execute_extraction_run(
            run_id, schema, companies, llm=build_llm_client(settings), verifier_llm=build_verifier_llm_client(settings),
            registry=registry, settings=settings, run_store=run_store, xbrl_source=_xbrl_source(settings),
        )

    return job


async def refresh_on_events(
    events: list[DocumentEvent],
    *,
    settings: Settings,
    run_store: RunStore,
    registry: DocumentSourceRegistry,
    launcher: LocalJobLauncher | None = None,
    parent: tuple[str, str, str] | None = None,
    company_hint: CompanyRef | None = None,
) -> list[str]:
    """Starts and launches the refresh runs for `events`; returns their run ids. `registry` is the
    document-source registry the runs extract from; schemas come from the schema registry.
    `parent` = (company_id, schema_id, run_id) of the extraction run whose Document management
    step found the documents: that run already uses them, so its own pair is recorded, not run."""
    if not (settings.event_refresh_enabled and settings.event_refresh_schema_ids):
        return []
    events = [e for e in events if e.event_type in _REFRESH_TYPES]
    if not events:
        return []
    from arp.extraction.pipeline import create_extraction_run
    from arp.orchestration.jobs import get_job_launcher
    from arp.storage.schema_registry import SchemaRegistry, UnreleasedFieldError

    schemas = []
    for schema_id in settings.event_refresh_schema_ids:
        try:
            schemas.append(SchemaRegistry(settings.schema_registry_dir).get(schema_id))
        except KeyError:
            logger.warning("Refresh: schema %s not found, skipped", schema_id)

    launcher = launcher or get_job_launcher()
    universe = _universe(settings)
    fired_path = settings.event_refresh_state_dir / "fired.jsonl"
    # ponytail: no await between reading fired.jsonl and appending to it, so one event loop never
    # double-fires; a second process could. Lock the file if refresh runs in several workers.
    fired = read_jsonl(fired_path) if fired_path.exists() else []
    seen = {(r.get("company_id"), r.get("schema_id"), r.get("sha256")) for r in fired}
    today = datetime.now(UTC).date().isoformat()
    runs_today = sum(1 for r in fired if str(r.get("fired_at", ""))[:10] == today and not r.get("parent"))

    run_ids: list[str] = []
    for event in events:
        sha = event.document.sha256 or event.document.url
        company = universe.get(event.company_id) or company_hint or CompanyRef(company_id=event.company_id, name=event.company_name)
        for schema in schemas:
            key = (event.company_id, schema.schema_id, sha)
            if key in seen:
                continue
            if parent and (event.company_id, schema.schema_id) == parent[:2]:
                seen.add(key)
                append_jsonl(fired_path, {"company_id": key[0], "schema_id": key[1], "sha256": sha, "run_id": parent[2],
                                          "parent": True, "fired_at": datetime.now(UTC).isoformat()})
                continue
            if runs_today >= settings.event_refresh_max_runs_per_day:
                logger.warning("Refresh: daily cap of %d runs reached; %s not refreshed",
                               settings.event_refresh_max_runs_per_day, event.company_id)
                return run_ids
            try:
                run_id = create_extraction_run(schema, [company], settings, run_store)
            except UnreleasedFieldError as exc:
                logger.warning("Refresh: schema %s skipped: %s", schema.schema_id, exc)
                continue
            seen.add(key)
            runs_today += 1
            append_jsonl(fired_path, {"company_id": key[0], "schema_id": key[1], "sha256": sha,
                                      "run_id": run_id, "fired_at": datetime.now(UTC).isoformat()})
            launcher.launch(run_id, _job(run_id, schema, [company], settings, run_store, registry), run_store=run_store)
            run_ids.append(run_id)
    return run_ids


def refresh_hook(settings: Settings, run_store: RunStore | None = None, *, parent: tuple[str, str, str] | None = None):
    """The ChangeDetector `on_events` callback when refresh is on, else None. `parent`: see refresh_on_events."""
    if not (settings.event_refresh_enabled and settings.event_refresh_schema_ids):
        return None

    async def on_events(events: list[DocumentEvent], company: CompanyRef | None = None) -> None:
        from arp.api.deps import build_registry
        from arp.retrieval.content_store_factory import content_store_for
        from arp.storage.postgres_projection_config import ProjectionConfig
        from arp.storage.run_store import RunStore

        store = run_store or RunStore(settings.runs_dir, projection_config=ProjectionConfig.from_settings(settings))
        await refresh_on_events(
            events, settings=settings, run_store=store,
            registry=build_registry(settings, content_store_for(settings)), parent=parent, company_hint=company,
        )

    return on_events
