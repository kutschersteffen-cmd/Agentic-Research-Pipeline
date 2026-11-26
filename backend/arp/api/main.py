from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from arp.api.auth import Principal, authorize, current_user, load_users
from arp.api.deps import (
    get_calibration_scheduler,
    get_emerging_themes_scheduler,
    get_portfolio_monitoring_scheduler,
    get_publishing_scheduler,
    get_report_scheduler,
    get_review_analytics_scheduler,
    get_scheduler,
    get_taxonomy_researcher_scheduler,
    settings_dep,
)
from arp.api.request_limit import RequestSizeLimit
from arp.api.routers import (
    agent,
    agent_board,
    argus,
    ask,
    authoritative,
    authority_taxonomy,
    bi,
    calibration,
    capabilities,
    climate,
    companies,
    decision,
    desk,
    discovery,
    documents,
    dossier_position,
    dossier_research,
    dossiers,
    emerging_themes,
    engagement,
    extraction,
    financials,
    holdings,
    identity,
    index,
    outputs,
    overlap,
    plans,
    portfolio,
    projects,
    publish,
    refine,
    replication,
    reporting,
    revenue_catalogue,
    review,
    rfp,
    runs,
    sandbox_tools,
    search,
    security_master,
    signals,
    snapshots,
    stewardship,
    stewardship_cockpit,
    stewardship_intake,
    stewardship_overlap,
    stewardship_watch,
    stewardship_worklist,
    taxonomies,
    taxonomy_researcher,
    themes,
    tnfd,
    transition_alignment,
    transition_barrier,
    transition_plan,
    universe,
    universe_workbench,
    value_chain,
    voting,
    waiting,
    walkthrough,
    xbrl,
)
from arp.db.session import require_cutover, require_postgres
from arp.errors import ClientInputError, NotConfigured
from arp.refine.turns import reap_stale_turns
from arp.research_desk.turn import reap_stale_desk_turns
from arp.schemas.thematic import OLD_FORMAT_MESSAGE
from arp.stewardship.universe import wait_for_fill
from arp.transition_alignment.benchmarks import check_benchmarks
from arp.transition_barrier.dataset import check_rule_book

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _fill_observations(settings) -> None:
    """Starts filling the per-file observation cache (PortfolioStore.latest_observation) from
    `observations_latest.json` in a thread; start-up waits for it, at most `universe.FILL_WAIT_S`, so the first
    Workbench request after a restart is a warm one (spec workbench-review-fixes). Best effort: a failure only leaves
    the cache cold."""
    from arp.stewardship.universe import start_fill
    from arp.storage.portfolio_store_factory import build_portfolio_store

    try:
        start_fill(build_portfolio_store(settings))
    except Exception:  # noqa: BLE001 -- a cold cache is only slower, never wrong
        logger.warning("Could not fill the observation cache", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = settings_dep()
    if settings.auth_mode == "dev" and "*" in settings.allowed_origins:
        raise NotConfigured(
            'ARP_AUTH_MODE=dev with "*" in ARP_ALLOWED_ORIGINS lets any website act as the dev approver. '
            "List the real origins in ARP_ALLOWED_ORIGINS, or set ARP_AUTH_MODE=local."
        )
    check_rule_book()  # an invalid rule book stops startup, naming its first error
    check_benchmarks()  # so does an invalid benchmarks file
    require_postgres(settings)  # Postgres is the system of record: no DSN or no answer, no app
    require_cutover(settings)  # nor on an un-migrated or un-imported database
    # shortcut: fails every running turn at startup, safe only with one API worker; reap by age or worker id before running several
    reap_stale_turns()  # a turn left `running` by the last process can never finish: fail it, unlocking its document
    reap_stale_desk_turns()  # the same for Research Desk turns
    settings.ensure_dirs()
    if settings.standins_dir is not None:
        logger.warning("Test stand-ins are ON: web search, fetch and model answers come from %s", settings.standins_dir)
    if settings.auth_mode == "local":
        load_users(settings.users_file)  # a bad users file stops startup
    scheduler = get_scheduler()
    taxonomy_researcher_scheduler = get_taxonomy_researcher_scheduler()
    calibration_scheduler = get_calibration_scheduler()
    emerging_themes_scheduler = get_emerging_themes_scheduler()
    portfolio_monitoring_scheduler = get_portfolio_monitoring_scheduler()
    report_scheduler = get_report_scheduler()
    publishing_scheduler = get_publishing_scheduler()
    review_analytics_scheduler = get_review_analytics_scheduler()
    _fill_observations(settings)
    await asyncio.to_thread(wait_for_fill)  # ~2 s on the 2,581-company showcase house, with the compact file
    scheduler.start()
    taxonomy_researcher_scheduler.start()
    calibration_scheduler.start()
    emerging_themes_scheduler.start()
    portfolio_monitoring_scheduler.start()
    report_scheduler.start()
    publishing_scheduler.start()
    review_analytics_scheduler.start()
    plan_worker = plans.start_plan_worker(settings) if settings.plan_worker_seconds > 0 else None
    try:
        yield
    finally:
        if plan_worker is not None:
            plan_worker.cancel()
        scheduler.shutdown()
        taxonomy_researcher_scheduler.shutdown()
        calibration_scheduler.shutdown()
        emerging_themes_scheduler.shutdown()
        portfolio_monitoring_scheduler.shutdown()
        report_scheduler.shutdown()
        publishing_scheduler.shutdown()
        review_analytics_scheduler.shutdown()


app = FastAPI(title="Agentic Research Pipeline", version="0.1.0", lifespan=lifespan)

# Host check for every route: a host check, not auth. Stops
# DNS rebinding from turning a foreign site into a loopback "dev" caller.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings_dep().trusted_hosts)

# Whole-request size limit: inside CORS (the browser can read the 413), before sign-in and any body read.
app.add_middleware(RequestSizeLimit)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_dep().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-RFP-Unapproved"],
)
# The 8 MB stewardship worklist goes compressed when the browser accepts it; event streams are left as they are.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(themes.router, dependencies=[Depends(authorize)])
app.include_router(companies.router, dependencies=[Depends(authorize)])
app.include_router(extraction.router, dependencies=[Depends(authorize)])
app.include_router(documents.router, dependencies=[Depends(authorize)])
app.include_router(discovery.router, dependencies=[Depends(authorize)])
app.include_router(plans.router, dependencies=[Depends(authorize)])
app.include_router(plans.templates_router, dependencies=[Depends(authorize)])
app.include_router(agent_board.router, dependencies=[Depends(authorize)])
app.include_router(capabilities.router, dependencies=[Depends(authorize)])
app.include_router(agent.router, dependencies=[Depends(authorize)])
app.include_router(sandbox_tools.router)  # signed in by its execution token, not a user (spec agent-panel-code-mode)
app.include_router(identity.router, dependencies=[Depends(authorize)])
app.include_router(runs.router, dependencies=[Depends(authorize)])
app.include_router(universe.router, dependencies=[Depends(authorize)])
app.include_router(universe_workbench.router, dependencies=[Depends(authorize)])
app.include_router(argus.router, dependencies=[Depends(authorize)])
app.include_router(taxonomies.router, dependencies=[Depends(authorize)])
app.include_router(authority_taxonomy.router, dependencies=[Depends(authorize)])
app.include_router(overlap.router, dependencies=[Depends(authorize)])
app.include_router(revenue_catalogue.router, dependencies=[Depends(authorize)])
app.include_router(engagement.router, dependencies=[Depends(authorize)])
app.include_router(voting.router, dependencies=[Depends(authorize)])
app.include_router(xbrl.router, dependencies=[Depends(authorize)])
app.include_router(stewardship.router, dependencies=[Depends(authorize)])
app.include_router(stewardship_cockpit.router, dependencies=[Depends(authorize)])
app.include_router(stewardship_intake.router, dependencies=[Depends(authorize)])
app.include_router(stewardship_overlap.router, dependencies=[Depends(authorize)])
app.include_router(stewardship_watch.router, dependencies=[Depends(authorize)])
app.include_router(stewardship_worklist.router, dependencies=[Depends(authorize)])
app.include_router(financials.router, dependencies=[Depends(authorize)])
app.include_router(tnfd.router, dependencies=[Depends(authorize)])
app.include_router(transition_plan.router, dependencies=[Depends(authorize)])
app.include_router(transition_barrier.router, dependencies=[Depends(authorize)])
app.include_router(transition_alignment.router, dependencies=[Depends(authorize)])
app.include_router(rfp.router, dependencies=[Depends(authorize)])
app.include_router(refine.router, dependencies=[Depends(current_user)])  # own role check: a viewer's 403 names the page
app.include_router(desk.router)  # every endpoint requires an analyst
app.include_router(portfolio.router, dependencies=[Depends(authorize)])
app.include_router(climate.router, dependencies=[Depends(authorize)])
app.include_router(decision.router, dependencies=[Depends(authorize)])
app.include_router(authoritative.router, dependencies=[Depends(authorize)])
app.include_router(bi.router, dependencies=[Depends(authorize)])
app.include_router(projects.router, dependencies=[Depends(authorize)])
app.include_router(search.router, dependencies=[Depends(authorize)])
app.include_router(emerging_themes.router, dependencies=[Depends(authorize)])
app.include_router(dossiers.router, dependencies=[Depends(authorize)])
app.include_router(dossier_research.router, dependencies=[Depends(authorize)])
app.include_router(dossier_position.router, dependencies=[Depends(authorize)])
app.include_router(taxonomy_researcher.router, dependencies=[Depends(authorize)])
app.include_router(calibration.router, dependencies=[Depends(authorize)])
app.include_router(reporting.router, dependencies=[Depends(authorize)])
app.include_router(replication.router, dependencies=[Depends(authorize)])
# current_user, not authorize: any signed-in user may read and compare (POST /compare is not a change).
app.include_router(signals.router, dependencies=[Depends(current_user)])
app.include_router(index.router, dependencies=[Depends(authorize)])
app.include_router(review.router, dependencies=[Depends(authorize)])
app.include_router(waiting.router, dependencies=[Depends(authorize)])
app.include_router(walkthrough.router, dependencies=[Depends(authorize)])
app.include_router(publish.router, dependencies=[Depends(authorize)])
app.include_router(snapshots.router, dependencies=[Depends(authorize)])
app.include_router(holdings.router, dependencies=[Depends(authorize)])
app.include_router(security_master.router, dependencies=[Depends(authorize)])
app.include_router(outputs.router, dependencies=[Depends(authorize)])
app.include_router(security_master.feeds_router, dependencies=[Depends(authorize)])
app.include_router(security_master.issues_router, dependencies=[Depends(authorize)])
app.include_router(security_master.search_router, dependencies=[Depends(authorize)])
app.include_router(value_chain.router, dependencies=[Depends(authorize)])
app.include_router(ask.router, dependencies=[Depends(authorize)])


@app.exception_handler(NotConfigured)
async def runtime_error_handler(request: Request, exc: NotConfigured) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ClientInputError)
async def client_input_error_handler(request: Request, exc: ClientInputError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    # An unmigrated core_isic_codes theme is 422 (spec 2026-11-04 decision 8) on every load path;
    # any other bare ValueError stays a server fault.
    if OLD_FORMAT_MESSAGE in str(exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return await server_error_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Same 422 as FastAPI's default, minus `input`, `ctx` and `url`: they echo what the client sent.
    detail = [{"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(Exception)
async def server_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Anything that is not a marker class is a server fault: log it with its traceback, tell the client nothing.
    request_id = uuid.uuid4().hex
    logger.error("Unhandled error on %s %s (request_id=%s)", request.method, request.url.path, request_id, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal error", "request_id": request_id})


if settings_dep().standins_dir is not None:

    @app.middleware("http")
    async def stand_ins_header(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-ARP-Stand-ins"] = "on"
        return response


@app.get("/api/health")
def health() -> dict:
    if settings_dep().standins_dir is not None:
        return {"status": "ok", "stand_ins": True}
    return {"status": "ok"}


@app.get("/api/me")
def me(user: Principal = Depends(current_user)) -> Principal:
    return user


class _IsolatedStaticFiles(StaticFiles):
    """The built frontend, with the cross-origin isolation headers Decision Studio's threaded WebAssembly
    needs (the same two frontend/vite.config.ts and nginx.conf send)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        return response


def mount_frontend(app: FastAPI, dist: Path | None) -> None:
    """Serve the built frontend at / (ARP_FRONTEND_DIST). Mounted last, so every API route wins."""
    if dist is not None:
        app.mount("/", _IsolatedStaticFiles(directory=dist, html=True), name="frontend")


mount_frontend(app, settings_dep().frontend_dist)
