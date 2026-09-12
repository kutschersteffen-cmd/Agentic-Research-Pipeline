# syntax=docker/dockerfile:1
FROM python:3.11-slim

# build-essential/libpq-dev/libxml2-dev/libxslt1-dev cover source builds for
# any dependency without a manylinux wheel on this platform (lxml, psycopg
# fall back to these if no prebuilt wheel matches); libgomp1 is required at
# runtime by numpy/onnxruntime (fastembed's backend). curl is only for the
# HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY arp ./arp

# postgres extra: this image is meant to run against real Postgres, not the
# file-based default store (see docker-compose.yml at the repo root).
RUN pip install --no-cache-dir -e ".[postgres]"

RUN useradd --create-home --uid 1000 arp
USER arp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "arp.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
