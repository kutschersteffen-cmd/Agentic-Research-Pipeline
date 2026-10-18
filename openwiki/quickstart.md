---
type: quickstart
title: Quickstart
description: Orientation for the Agentic Research Pipeline repository. Covers what it does, its two design rules, how to run Postgres, the FastAPI backend, the arp CLI and the React frontend locally, how sign-in works, which checks to run, and which wiki page to read for each kind of task.
tags: [quickstart, setup, orientation, routing]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-34ac182ccebb11435b800ced
    resource: repo://backend/arp/api/auth.py
  - id: openwiki-source-30ae3537dbe994ca14056d4c
    resource: repo://backend/arp/cli/__init__.py
  - id: openwiki-source-c6094f2fa4ec04b771864dae
    resource: repo://backend/arp/cli/db.py
  - id: openwiki-source-07e1021d4b7b6b7207c06144
    resource: repo://backend/arp/config.py
  - id: openwiki-source-aba379072b740ddddafb7888
    resource: repo://backend/arp/grounding.py
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# Quickstart

The Agentic Research Pipeline (ARP) runs agent pipelines for investment research at scale, designed for up to about
4,000 companies per run. Its functions include building thematic company universes, extracting schema-defined data
points from disclosures, assessing transition plans, and analysing portfolios. The full list of numbered functions is
in `README.md`.

Two rules hold throughout the code:

1. **The LLM plans, deterministic code computes.** Models draft, verify and propose. Numbers, routing, aggregation and
   scoring are plain code.
2. **Every citation is re-verified programmatically** against the source document by `backend/arp/grounding.py`. The
   model's own claim to have quoted correctly is never trusted.

## Layout

| Path | What it holds |
|---|---|
| `backend/arp/` | Python package: FastAPI app (`backend/arp/api`), Typer CLI (`backend/arp/cli`), every pipeline |
| `backend/tests/` | pytest suite (needs `ARP_TEST_POSTGRES_DSN`) |
| `frontend/src/` | React + TypeScript (Vite) UI |
| `docs/` | Design and methodology documents, ADRs in `docs/adr/` |
| `notes/` | Decisions written by people. Where a note disagrees with the wiki, the note wins |
| `runs/`, `data/` | Run side files and documents (not part of the wiki) |

## Run it locally

```bash
# Backend (Python 3.11)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # set ARP_ANTHROPIC_API_KEY; ARP_POSTGRES_DSN is preset
docker compose up -d postgres     # required: Postgres + pgvector
arp db init-postgres              # create/upgrade the schema (re-run after upgrades)
uvicorn arp.api.main:app --reload # API on :8000

# Frontend
cd frontend && npm install
cp .env.example .env              # VITE_API_BASE
npm run dev                       # UI on :5173
```

Postgres is mandatory. The API's startup (`backend/arp/api/main.py`) and every CLI command
(`backend/arp/cli/__init__.py`) refuse to run without a reachable, migrated database. Only `arp db ...` skips the
cut-over check. Settings are `ARP_*` environment variables, read from `backend/.env` through `Settings` in
`backend/arp/config.py`.

**Sign-in.** The default `ARP_AUTH_MODE=dev` signs in same-site requests from loopback, or from
`ARP_DEV_TRUSTED_NETWORKS`, as an approver named `ARP_DEV_USER`. For real per-person sign-in, set
`ARP_AUTH_MODE=local` and create `config/users.json` from `config/users.example.json` with a token, `user_id` and role
(`viewer`, `analyst` or `approver`) for each person. See `backend/arp/api/auth.py` and
<!-- openwiki: broken internal link [/openwiki/architecture/overview.md] link "/openwiki/architecture/overview.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[System architecture](/openwiki/architecture/overview.md).

**CLI.** `arp --help` lists the sub-apps (`extract`, `runs`, `publish`, `golden-set`, `db`, ...). The CLI is the
headless path for large batch runs and calls the same pipeline functions as the API.

## Checks

From `.claude/CLAUDE.md`:

- Backend: `cd backend && ruff check . && python3 -m pytest tests/<file>`
- Frontend: `cd frontend && npm run lint && npx tsc -b && npm test`
- After changing an API request or response model: `python scripts/export_openapi.py` in `backend/`, then
  `npm run gen:api` in `frontend/`. `frontend/src/api/contract.ts` fails `tsc -b` if a typed response no longer fits.
- PRs touching `backend/arp/extraction`, `backend/arp/llm`, `backend/arp/golden_set`, `backend/arp/grounding.py` or
  model settings run the real-model golden set (`arp golden-set run`) in CI.

## Where to read next

| If you need to... | Read |
|---|---|
<!-- openwiki: broken internal link [/openwiki/architecture/overview.md] link "/openwiki/architecture/overview.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| See the main parts and how API, CLI, pipelines, LLM layer and Postgres connect | [System architecture](/openwiki/architecture/overview.md) |
<!-- openwiki: broken internal link [/openwiki/architecture/data-flow.md] link "/openwiki/architecture/data-flow.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| Follow a value from a PDF or filing to the screen | [Data flow: documents to UI](/openwiki/architecture/data-flow.md) |
<!-- openwiki: broken internal link [/openwiki/pipeline/extraction.md] link "/openwiki/pipeline/extraction.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| Change how values are extracted, verified, adjudicated or routed to review | [Data-point extraction engine](/openwiki/pipeline/extraction.md) |
<!-- openwiki: broken internal link [/openwiki/pipeline/grounding.md] link "/openwiki/pipeline/grounding.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| Understand why a citation is (not) grounded, or change matching rules | [Citation grounding](/openwiki/pipeline/grounding.md) |
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| Publish, withdraw or read versioned facts as of a date | [Publishing facts](/openwiki/pipeline/publish.md) |
<!-- openwiki: broken internal link [/openwiki/operations/runs-and-review.md] link "/openwiki/operations/runs-and-review.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| Work on run checkpointing, resume or cancel, the fact ledger, or reviewer rules | [Runs, persistence and review](/openwiki/operations/runs-and-review.md) |
<!-- openwiki: broken internal link [/openwiki/integrations/llm-and-retrieval.md] link "/openwiki/integrations/llm-and-retrieval.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| Change model clients, caching, cost, or evidence retrieval | [LLM clients and evidence retrieval](/openwiki/integrations/llm-and-retrieval.md) |
<!-- openwiki: broken internal link [/openwiki/architecture/frontend.md] link "/openwiki/architecture/frontend.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
| Work on screens, routing, the API client or typed contract | [Frontend application](/openwiki/architecture/frontend.md) |

The wiki focuses on the extraction, grounding and publish path. For the other functions (thematic universe,
transition barrier, Decision Studio, index construction, strategy replication, stewardship, Superset BI), start from
their sections in `README.md` and their documents in `docs/`, for example `docs/TECHNICAL_REFERENCE.md`,
`docs/DECISION_MECHANISM.md` and `docs/INDEX_CONSTRUCTION.md`.
