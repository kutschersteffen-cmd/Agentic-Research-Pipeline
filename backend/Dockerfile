# syntax=docker/dockerfile:1
#
# Corporate Readiness Plan, Phase 1 (see docs/CORPORATE_READINESS_PLAN.md).
# Builds the FastAPI backend (and CLI) into a runnable image. This is an
# additive way to run the app -- `uvicorn arp.api.main:app --reload` from a
# local venv (see README "Setup") keeps working exactly as before.
#
# Build context is the repo root (see docker-compose.yml) so the resulting
# image preserves the same on-disk layout the app already assumes:
# arp/config.py resolves REPO_ROOT as two directories above itself, i.e.
# /app here, with runs/, taxonomies/, portfolios/, etc. created under it at
# startup via Settings.ensure_dirs().
#
# Optional extras (postgres, emerging_themes -- see backend/pyproject.toml)
# are opt-in via a build arg, matching their opt-in status locally:
#   docker build -f backend/Dockerfile --build-arg EXTRAS=postgres .

ARG PYTHON_VERSION=3.11-slim

# ---- builder: install into a venv so the runtime stage doesn't need a
# compiler toolchain or pip's own footprint ----
FROM python:${PYTHON_VERSION} AS builder

# Some transitive dependencies (docling's PDF backends, fastembed's ONNX
# runtime, emerging_themes' hdbscan/umap-learn) need a compiler and a few
# shared libs to build/run; keep this list minimal and revisit if a build
# fails on a package without a manylinux wheel for your platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app/backend
COPY backend/pyproject.toml ./
# A minimal package stub so `pip install .` can resolve build metadata
# before the real source is copied -- keeps the dependency-install layer
# cacheable across source-only changes.
RUN mkdir -p arp && touch arp/__init__.py

ARG EXTRAS=""
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -n "$EXTRAS" ]; then pip install ".[${EXTRAS}]"; else pip install .; fi

COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -n "$EXTRAS" ]; then pip install ".[${EXTRAS}]"; else pip install .; fi

# ---- runtime: slim image, non-root, only what's needed to run ----
FROM python:${PYTHON_VERSION} AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin arp

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=builder /app/backend ./backend

# Pre-create every path a named volume mounts onto (docker-compose.yml) so
# it exists, owned by the non-root user, before Docker seeds a fresh volume
# from it -- an empty directory at a mount point with no prior content
# would otherwise be created owned by root, which the arp user can't write
# to (see docs/CORPORATE_READINESS_PLAN.md Phase 1 notes).
RUN mkdir -p /app/runs /app/taxonomies /app/portfolios /app/data/documents \
        /app/engagements /app/ballots /app/backend/.cache \
        /app/backend/.discovery_state /app/backend/.document_store \
    && chown -R arp:arp /app

USER arp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "arp.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
