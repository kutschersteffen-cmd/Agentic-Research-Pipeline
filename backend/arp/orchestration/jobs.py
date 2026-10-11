from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from arp.llm.factory import batch_settings, build_llm_client, build_verifier_llm_client
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import JobStatus, RunManifest
from arp.storage.postgres import _CONNECT_TIMEOUT_SECONDS
from arp.storage.run_store import RunStore

if TYPE_CHECKING:
    from arp.config import Settings
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.llm.base import LLMClient

logger = logging.getLogger(__name__)


class RunBusy(RuntimeError):
    """Another worker already holds this run's lease."""


_LEASE_NS = 0x41525054  # "ARPT": keeps run leases apart from any other advisory lock user
_LEASE = text("SELECT pg_try_advisory_lock(:ns, hashtext(:id))")


@lru_cache
def _lease_engine(dsn: str) -> Engine:
    """No pool: a lease holds its connection for the whole run, which must not use up the app's pool."""
    connect_args = {} if "connect_timeout" in dsn else {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}
    return create_engine(dsn, poolclass=NullPool, connect_args=connect_args)


@contextmanager
def run_lease(run_store: RunStore, run_id: str) -> Iterator[None]:
    """One worker per run, across processes and machines: a Postgres advisory lock on the run id,
    held on its own connection. Raises RunBusy if another session holds it. Freed when the holder
    exits, or when its connection dies, so a crashed worker never leaves a run stuck."""
    # ponytail: a dropped lease connection frees the lease while the worker runs on; a heartbeat that
    # stops the worker is the upgrade path.
    key = {"ns": _LEASE_NS, "id": run_id}
    with _lease_engine(run_store.dsn).connect() as conn:
        got = conn.scalar(_LEASE, key)
        conn.commit()  # the session-level lock outlives the transaction; no transaction stays open
        if not got:
            raise RunBusy(f"Run {run_id} already has a worker")
        # No unlock: closing the unpooled connection ends the session, which frees the lock, and an
        # unlock on a connection that already died would replace the run's own outcome.
        yield


_held: ContextVar[frozenset[str]] = ContextVar("held_runs", default=frozenset())


@contextmanager
def hold_run(run_store: RunStore, run_id: str) -> Iterator[None]:
    """`run_lease`, re-entrant within one task context: a no-op if this
    context already holds the run (a launcher or resume_run that then calls
    the pipeline), else takes the lease and marks it held. Every batch run
    goes through it (run_company_batch, execute_discovery_run), so a second
    worker on the same run raises RunBusy however it was started. The
    outermost holder marks the run failed when its body raises."""
    if run_id in _held.get():
        yield
        return
    with run_lease(run_store, run_id):
        token = _held.set(_held.get() | {run_id})
        try:
            yield
        except Exception as exc:
            _mark_failed(run_store, run_id, exc)
            raise
        finally:
            _held.reset(token)


def _mark_failed(run_store: RunStore, run_id: str, exc: Exception) -> None:
    """A crash before the run finished would leave it "running" forever."""
    try:
        JobManager(run_store).finish_run(run_id, error=f"{type(exc).__name__}: {exc}")
    except Exception:  # noqa: BLE001 - the run's own error is the one to raise
        logger.exception("could not mark run %s failed", run_id)


class LocalJobLauncher:
    """Runs a run's job as a background task in this process, under the
    run's lease. `run_store` is a factory so the app's current settings
    decide where `runs/` is at launch time."""

    def __init__(self, run_store: Callable[[], RunStore]) -> None:
        self._run_store = run_store
        self._tasks: set[asyncio.Task] = set()  # strong refs: a running task is never garbage-collected

    def launch(self, run_id: str, job: Callable[[], Awaitable[None]], *, run_store: RunStore | None = None) -> None:
        """`run_store`, when given, is where the lease is taken (the caller's
        own store); otherwise the factory's."""

        async def _leased() -> None:
            try:
                with hold_run(run_store or self._run_store(), run_id):
                    await job()
            except Exception:  # noqa: BLE001 - nobody awaits the task
                logger.exception("Job for run %s failed", run_id)

        task = asyncio.create_task(_leased(), name=run_id)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> list[str]:
        """Waits for every launched job, including any launched meanwhile, so a
        short-lived caller (a CLI `asyncio.run`) does not cancel them on exit.
        Returns the run ids it waited for."""
        drained: list[str] = []
        while self._tasks:
            tasks = list(self._tasks)
            drained += [t.get_name() for t in tasks]
            await asyncio.gather(*tasks, return_exceptions=True)
            self._tasks.difference_update(tasks)
        return drained


_launcher: LocalJobLauncher | None = None


def get_job_launcher() -> LocalJobLauncher:
    global _launcher
    if _launcher is None:
        from arp.api.deps import get_run_store

        # ponytail: a cloud_run launcher plugs in here at Cloud switch-on.
        _launcher = LocalJobLauncher(get_run_store)
    return _launcher


class NotResumable(ValueError):
    """This run cannot be resumed; the message says why."""


def _reached_every_company(run_store: RunStore, manifest: RunManifest) -> bool:
    """Every stored company has a result or was stopped for review. company_count is no guide: it counts
    refs save_companies may drop, and a company with review items counts as completed and for review."""
    companies = run_store.load_companies(manifest.run_id)
    if not companies:  # a theme run from before companies.json
        return True
    done = run_store.done_keys(manifest.run_id, include_errors=True)
    return {c.company_id for c in companies} <= done


def check_resumable(run_store: RunStore, run_id: str) -> RunManifest:
    """The run's manifest, or NotResumable saying why it can't be resumed."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise NotResumable("Unknown run_id")
    if manifest.status == JobStatus.COMPLETED and _reached_every_company(run_store, manifest):
        raise NotResumable("already completed")  # a completed run that missed companies resumes for them
    if manifest.run_type not in RESUMABLE:
        raise NotResumable(f"{manifest.run_type} runs are not resumable; start a new run")
    # A theme run may instead have a universe file (runs from before companies.json).
    if not run_store.has_companies(run_id) and not (
        manifest.run_type == "theme" and manifest.params.get("universe_path")
    ):
        raise NotResumable("run has no stored inputs")
    return manifest


def _xbrl_source(settings: Settings):
    """Built as arp.api.deps.get_xbrl_source builds it; the pipelines
    themselves check xbrl_facts_enabled."""
    from arp.ingestion.edgar import EdgarDocumentSource
    from arp.ingestion.indexing_config import IndexingConfig
    from arp.ingestion.xbrl import XbrlFactSource
    from arp.retrieval.content_store_factory import content_store_for

    edgar = EdgarDocumentSource(
        settings.edgar_user_agent,
        settings.cache_dir,
        content_store=content_store_for(settings),
        submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
        indexing_config=IndexingConfig.from_settings(settings),  # the blob store tagged values are frozen into
    )
    return XbrlFactSource(edgar, settings.cache_dir, ttl_hours=settings.xbrl_facts_ttl_hours)


def restart_run(run_store: RunStore, run_id: str) -> None:
    """Marks the run RUNNING again (error and cancel request cleared), with
    its counts rebuilt from the files: failed items are retried, so they no
    longer count; tokens and cost stay, that money was spent. review_count
    stays too: review-stopped items are never re-run, and discovery records
    review counts without review_queue rows."""
    with run_store.lock(run_id):
        current = run_store.load_manifest(run_id)
        current.completed_count = len(run_store.done_keys(run_id))
        current.failed_count = 0
        current.cancel_requested = False
        current.status = JobStatus.RUNNING
        current.error = None
        run_store.save_manifest(current)


async def resume_run(
    run_id: str,
    *,
    settings: Settings,
    run_store: RunStore,
    registry: DocumentSourceRegistry,
    llm: LLMClient | None = None,
    verifier_llm: LLMClient | None = None,
    lease: bool = True,
) -> str:
    """Continues a run that was killed, failed, partly failed or cancelled,
    from what its creator stored (manifest params, companies.json). Items
    already in results.jsonl, or stopped for review, are not run again;
    plain failures are retried. Holds the run's lease throughout unless
    `lease=False` (the caller -- a LocalJobLauncher -- already holds it)."""
    manifest = check_resumable(run_store, run_id)
    run_type = manifest.run_type
    companies = run_store.load_companies(run_id)

    # The run keeps the models it started on.
    run_settings = settings.model_copy(
        update={k: v for k, v in (("llm_model", manifest.model), ("llm_verifier_model", manifest.verifier_model)) if v}
    )
    run_settings = batch_settings(run_settings, bool(manifest.params.get("batch")))
    if run_settings.llm_batch:
        # A batch run resumes on batch clients: callers' pre-built clients are real-time.
        llm = verifier_llm = None
    if run_type not in {"discovery", "xbrl_fetch"}:  # no LLM steps
        llm = llm or build_llm_client(run_settings)
        verifier_llm = verifier_llm or build_verifier_llm_client(run_settings)

    with hold_run(run_store, run_id) if lease else nullcontext():
        restart_run(run_store, run_id)

        common = {"settings": run_settings, "run_store": run_store}
        llms = {"llm": llm, "verifier_llm": verifier_llm, "registry": registry}
        return await _RESUME[run_type](run_id, manifest, companies, **common, **llms)


async def _resume_theme(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.research.pipeline import resume_theme_run

    return await resume_theme_run(run_id, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings,
                                  run_store=run_store)


async def _resume_extraction(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.extraction.pipeline import execute_extraction_run, load_run_schema

    schema = load_run_schema(run_store, run_id)
    return await execute_extraction_run(run_id, schema, companies, llm=llm, verifier_llm=verifier_llm, registry=registry,
                                        settings=settings, run_store=run_store, xbrl_source=_xbrl_source(settings))


async def _resume_financials(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.extraction.financials_pipeline import execute_financials_extraction_run

    return await execute_financials_extraction_run(
        run_id, companies, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store,
        xbrl_source=_xbrl_source(settings),
    )


async def _resume_tnfd(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.extraction.tnfd_pipeline import execute_tnfd_extraction_run

    return await execute_tnfd_extraction_run(run_id, companies, manifest.params["as_of"], llm=llm, verifier_llm=verifier_llm,
                                             registry=registry, settings=settings, run_store=run_store)


async def _resume_transition_plan(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.transition_plan.pipeline import execute_transition_plan_run

    return await execute_transition_plan_run(run_id, companies, llm=llm, verifier_llm=verifier_llm, registry=registry,
                                             settings=settings, run_store=run_store)


async def _resume_identity(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.discovery.identity_pipeline import execute_identity_run

    return await execute_identity_run(run_id, companies, llm=llm, settings=settings, run_store=run_store)


async def _resume_discovery(run_id, manifest, companies, *, settings, run_store, **_) -> str:
    from arp.discovery.pipeline import execute_discovery_run
    from arp.schemas.discovery import DiscoveryRunParams

    params = DiscoveryRunParams.model_validate(manifest.params)
    return await execute_discovery_run(run_id, companies, doc_types=params.doc_types or None, settings=settings,
                                       run_store=run_store)


async def _resume_xbrl_fetch(run_id, manifest, companies, *, settings, run_store, **_) -> str:
    from arp.xbrl_pipeline.fetch import execute_xbrl_run

    return await execute_xbrl_run(
        run_id, companies, settings=settings, run_store=run_store, tags=manifest.params.get("tags"),
        refresh=bool(manifest.params.get("refresh")), market=manifest.params.get("market", "sec"),
    )


# One entry per resumable run type: how a resume continues it.
_RESUME: dict[str, Callable[..., Awaitable[str]]] = {
    "theme": _resume_theme,
    "extraction": _resume_extraction,
    "financials": _resume_financials,
    "tnfd": _resume_tnfd,
    "transition_plan": _resume_transition_plan,
    "identity": _resume_identity,
    "discovery": _resume_discovery,
    "xbrl_fetch": _resume_xbrl_fetch,
}
RESUMABLE = frozenset(_RESUME)
