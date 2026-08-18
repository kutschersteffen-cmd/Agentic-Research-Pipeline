from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from arp.api.deps import get_scheduler, settings_dep
from arp.api.routers import climate, discovery, documents, engagement, extraction, financials, identity, overlap, portfolio, revenue_catalogue, runs, taxonomies, themes, universe, voting

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings_dep().ensure_dirs()
    scheduler = get_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Agentic Research Pipeline", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(themes.router)
app.include_router(extraction.router)
app.include_router(documents.router)
app.include_router(discovery.router)
app.include_router(identity.router)
app.include_router(runs.router)
app.include_router(universe.router)
app.include_router(taxonomies.router)
app.include_router(overlap.router)
app.include_router(revenue_catalogue.router)
app.include_router(engagement.router)
app.include_router(voting.router)
app.include_router(financials.router)
app.include_router(portfolio.router)
app.include_router(climate.router)


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
