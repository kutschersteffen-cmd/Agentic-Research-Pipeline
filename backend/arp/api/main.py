from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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
from arp.api.routers import (
    argus,
    ask,
    authoritative,
    authority_taxonomy,
    bi,
    calibration,
    climate,
    companies,
    decision,
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
    replication,
    reporting,
    revenue_catalogue,
    review,
    rfp,
    runs,
    search,
    security_master,
    signals,
    snapshots,
    stewardship,
    stewardship_intake,
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
    walkthrough,
    xbrl,
)
from arp.db.session import require_cutover, require_postgres
from arp.errors import ClientInputError, NotConfigured
from arp.transition_alignment.benchmarks import check_benchmarks
from arp.transition_barrier.dataset import check_rule_book

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = settings_dep()
    check_rule_book()  # an invalid rule book stops startup, naming its first error
    check_benchmarks()  # so does an invalid benchmarks file
    require_postgres(settings)  # Postgres is the system of record: no DSN or no answer, no app
    require_cutover(settings)  # nor on an un-migrated or un-imported database
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
    scheduler.start()
    taxonomy_researcher_scheduler.start()
    calibration_scheduler.start()
    emerging_themes_scheduler.start()
    portfolio_monitoring_scheduler.start()
    report_scheduler.start()
    publishing_scheduler.start()
    review_analytics_scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        taxonomy_researcher_scheduler.shutdown()
        calibration_scheduler.shutdown()
        emerging_themes_scheduler.shutdown()
        portfolio_monitoring_scheduler.shutdown()
        report_scheduler.shutdown()
        publishing_scheduler.shutdown()
        review_analytics_scheduler.shutdown()


app = FastAPI(title="Agentic Research Pipeline", version="0.1.0", lifespan=lifespan)

# Host check for every route (voting included): a host check, not auth. Stops
# DNS rebinding from turning a foreign site into a loopback "dev" caller.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings_dep().trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_dep().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-RFP-Unapproved"],
)

app.include_router(themes.router, dependencies=[Depends(authorize)])
app.include_router(companies.router, dependencies=[Depends(authorize)])
app.include_router(extraction.router, dependencies=[Depends(authorize)])
app.include_router(documents.router, dependencies=[Depends(authorize)])
app.include_router(discovery.router, dependencies=[Depends(authorize)])
app.include_router(plans.router, dependencies=[Depends(authorize)])
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
app.include_router(voting.router)
app.include_router(xbrl.router, dependencies=[Depends(authorize)])
app.include_router(stewardship.router, dependencies=[Depends(authorize)])
app.include_router(stewardship_intake.router, dependencies=[Depends(authorize)])
app.include_router(financials.router, dependencies=[Depends(authorize)])
app.include_router(tnfd.router, dependencies=[Depends(authorize)])
app.include_router(transition_plan.router, dependencies=[Depends(authorize)])
app.include_router(transition_barrier.router, dependencies=[Depends(authorize)])
app.include_router(transition_alignment.router, dependencies=[Depends(authorize)])
app.include_router(rfp.router, dependencies=[Depends(authorize)])
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
