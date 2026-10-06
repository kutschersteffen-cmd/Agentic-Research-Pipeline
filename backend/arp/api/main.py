from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

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
    bi,
    calibration,
    climate,
    decision,
    discovery,
    documents,
    emerging_themes,
    engagement,
    extraction,
    financials,
    holdings,
    identity,
    index,
    outputs,
    overlap,
    portfolio,
    projects,
    publish,
    replication,
    reporting,
    revenue_catalogue,
    review,
    runs,
    search,
    security_master,
    snapshots,
    stewardship,
    taxonomies,
    taxonomy_researcher,
    themes,
    tnfd,
    transition_barrier,
    transition_plan,
    universe,
    voting,
)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = settings_dep()
    settings.ensure_dirs()
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
)

app.include_router(themes.router, dependencies=[Depends(authorize)])
app.include_router(extraction.router, dependencies=[Depends(authorize)])
app.include_router(documents.router, dependencies=[Depends(authorize)])
app.include_router(discovery.router, dependencies=[Depends(authorize)])
app.include_router(identity.router, dependencies=[Depends(authorize)])
app.include_router(runs.router, dependencies=[Depends(authorize)])
app.include_router(universe.router, dependencies=[Depends(authorize)])
app.include_router(taxonomies.router, dependencies=[Depends(authorize)])
app.include_router(overlap.router, dependencies=[Depends(authorize)])
app.include_router(revenue_catalogue.router, dependencies=[Depends(authorize)])
app.include_router(engagement.router, dependencies=[Depends(authorize)])
app.include_router(voting.router)
app.include_router(stewardship.router, dependencies=[Depends(authorize)])
app.include_router(financials.router, dependencies=[Depends(authorize)])
app.include_router(tnfd.router, dependencies=[Depends(authorize)])
app.include_router(transition_plan.router, dependencies=[Depends(authorize)])
app.include_router(transition_barrier.router, dependencies=[Depends(authorize)])
app.include_router(portfolio.router, dependencies=[Depends(authorize)])
app.include_router(climate.router, dependencies=[Depends(authorize)])
app.include_router(decision.router, dependencies=[Depends(authorize)])
app.include_router(bi.router, dependencies=[Depends(authorize)])
app.include_router(projects.router, dependencies=[Depends(authorize)])
app.include_router(search.router, dependencies=[Depends(authorize)])
app.include_router(emerging_themes.router, dependencies=[Depends(authorize)])
app.include_router(taxonomy_researcher.router, dependencies=[Depends(authorize)])
app.include_router(calibration.router, dependencies=[Depends(authorize)])
app.include_router(reporting.router, dependencies=[Depends(authorize)])
app.include_router(replication.router, dependencies=[Depends(authorize)])
app.include_router(index.router, dependencies=[Depends(authorize)])
app.include_router(review.router, dependencies=[Depends(authorize)])
app.include_router(publish.router, dependencies=[Depends(authorize)])
app.include_router(snapshots.router, dependencies=[Depends(authorize)])
app.include_router(holdings.router, dependencies=[Depends(authorize)])
app.include_router(security_master.router, dependencies=[Depends(authorize)])
app.include_router(outputs.router, dependencies=[Depends(authorize)])
app.include_router(security_master.feeds_router, dependencies=[Depends(authorize)])
app.include_router(security_master.issues_router, dependencies=[Depends(authorize)])


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    # build_llm_client raises RuntimeError when no API key is configured;
    # surface it as a clean 503 instead of an opaque 500.
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    # Covers both request-shape validation raised deep in a pipeline (e.g.
    # aggregation.py's unknown group_by/metric) and safe_path.py's
    # identifier validation -- either way this is a client error, not a
    # server fault, so it's a 400 rather than an opaque 500.
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/me")
def me(user: Principal = Depends(current_user)) -> Principal:
    return user
