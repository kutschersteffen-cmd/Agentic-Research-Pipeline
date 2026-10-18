---
type: system architecture
title: System architecture
description: How the Agentic Research Pipeline fits together. A FastAPI app and a Typer CLI share the same pipelines in backend/arp, which call models through one structured-output LLM interface, model per-item flows as LangGraph graphs, persist runs and facts in Postgres, and serve a React SPA in frontend/src.
tags: [architecture, backend, fastapi, cli, postgres, langgraph, auth, frontend]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-34ac182ccebb11435b800ced
    resource: repo://backend/arp/api/auth.py
  - id: openwiki-source-437a2f8588e05b5405bb765e
    resource: repo://backend/arp/api/main.py
  - id: openwiki-source-30ae3537dbe994ca14056d4c
    resource: repo://backend/arp/cli/__init__.py
  - id: openwiki-source-07e1021d4b7b6b7207c06144
    resource: repo://backend/arp/config.py
  - id: openwiki-source-6be4c107bfed89be7d9d1a4d
    resource: repo://backend/arp/llm/base.py
  - id: openwiki-source-a850b0b27f6f0e0ef23cbc3c
    resource: repo://backend/arp/orchestration/jobs.py
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# System architecture

The repository is one Python package, `backend/arp`, with two front doors (an HTTP API and a CLI), plus a React SPA in
`frontend/src` that talks only to the API. Postgres with pgvector is the required system of record. Two rules hold
across the code, as `README.md` states. First, the LLM plans and deterministic code computes. Second, every citation is
re-verified programmatically against the source text (`backend/arp/grounding.py`) instead of being trusted from the
model.

```
frontend/src (React + Vite)            arp CLI (Typer, backend/arp/cli)
        │  fetch + bearer token                 │
        ▼                                       ▼
FastAPI app (backend/arp/api/main.py) ──► pipelines (extraction, research, voting, …)
  routers/*  ·  auth  ·  deps                     │
  in-process schedulers                           ├─► LLM layer (backend/arp/llm) ── Anthropic / Gemini
  job launcher (background asyncio tasks)         ├─► ingestion + retrieval (documents → evidence)
                                                  ├─► grounding.py (citation re-verification)
                                                  └─► Postgres: RunStore, fact ledger, published facts
```

## Entry points

**HTTP API.** `backend/arp/api/main.py` builds the FastAPI app. On startup (`lifespan`) it refuses to run without a
reachable Postgres (`require_postgres`) or on a database that has not been migrated and cut over (`require_cutover`).
In `auth_mode="local"` it also loads the users file, so a bad file stops startup. It then starts the in-process
schedulers: runs, taxonomy researcher, calibration, emerging themes, portfolio monitoring, reports, publishing and
review analytics. Each feature has a router in `backend/arp/api/routers/` mounted under `/api/...`. Two middlewares sit
in front: `TrustedHostMiddleware`, which stops DNS-rebinding into the loopback dev bypass, and CORS for
`allowed_origins`.

**CLI.** `arp = "arp.cli:app"` (`backend/pyproject.toml`) is the Typer app in `backend/arp/cli/__init__.py`, described
as "the headless path for 1000s-of-companies batch runs". Its callback applies the same Postgres and cut-over checks to
every command. `arp db ...` is exempt from the cut-over check because it performs the migration and import. Commands
are sub-apps per feature (`extract`, `runs`, `publish`, `golden-set`, `db`, ...) and call the same pipeline functions
as the routers.

## Authentication and roles

`backend/arp/api/auth.py` defines a `Principal` with a role of `viewer`, `analyst` or `approver` (ranked in that order)
plus optional grants (`snapshot_reader`, `holdings_reader`).

- `current_user` reads a bearer token and looks it up in `users_file` (JSON, see `config/users.example.json`). In
  `auth_mode="dev"` (the current default in `backend/arp/config.py`), same-site requests from loopback or
  `dev_trusted_networks` are signed in as `dev_user` with the approver role.
- `authorize` is the router-level dependency used by most routers: viewers may use safe methods (GET/HEAD/OPTIONS), and
  any other method needs analyst.
- Endpoints with stronger requirements add `require_role("approver")`. Publishing and withdrawing facts are examples
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
  (see [Publishing facts](/openwiki/pipeline/publish.md)).

## Dependency wiring and configuration

`backend/arp/config.py` holds `Settings`, a pydantic-settings class whose environment variables use the prefix `ARP_`
and which reads `.env`. It includes model ids (`llm_model`, plus a deliberately different `llm_verifier_model`),
grounding and review thresholds, data directories (`runs_dir`, `documents_dir`, ...), `postgres_dsn` and the auth mode.

`backend/arp/api/deps.py` turns settings into cached singletons that routers receive through `Depends`:
`get_run_store` (the Postgres `RunStore`), `get_registry` (document sources), `get_document_content_store`,
`get_xbrl_source`, `publish_store_dep`, `blob_store_dep` and the LLM clients.

## Running long work

Routers do not run pipelines inline. `schedule_llm_run` (`backend/arp/api/run_scheduling.py`) resolves both LLM clients
first, then creates the run, then hands the coroutine to `get_job_launcher().launch`
(`backend/arp/orchestration/jobs.py`). The local launcher runs it as a background asyncio task inside a run lease
(`hold_run`), so only one worker executes a given run. Execution then goes through the shared batch runner, which
checkpoints every company into Postgres and can resume or cancel (see
<!-- openwiki: broken internal link [/openwiki/operations/runs-and-review.md] link "/openwiki/operations/runs-and-review.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Runs, persistence and review](/openwiki/operations/runs-and-review.md)).

## Backend subsystems

| Area | Packages | Role |
|---|---|---|
| Ingestion | `backend/arp/ingestion`, `backend/arp/discovery` | Document sources (local files, EDGAR, ESEF), parsing, document identity, IR-site crawling and identity resolution |
| Planning and retrieval | `backend/arp/planning`, `backend/arp/retrieval` | Which fields and periods apply, which documents to route, evidence chunk selection (BM25 or hybrid) |
| Extraction | `backend/arp/extraction`, `backend/arp/checks`, `backend/arp/normalise` | Extractor/verifier/adjudicator graphs, record checks, units, periods and FX |
| Grounding | `backend/arp/grounding.py` | Programmatic citation verification |
| Persistence | `backend/arp/db`, `backend/arp/storage` | SQLAlchemy models, RunStore, fact ledger, blob and content stores |
| Orchestration | `backend/arp/orchestration` | Batch runner, job manager and launcher, review queue, cost tracking, schedulers |
| Publishing | `backend/arp/publish`, `backend/arp/snapshots` | Versioned published facts, releases, outbox, monthly snapshots |
| Other functions | `backend/arp/research`, `backend/arp/transition_plan`, `backend/arp/transition_barrier`, `backend/arp/portfolio`, `backend/arp/holdings`, `backend/arp/decision`, `backend/arp/index`, `backend/arp/replication`, `backend/arp/emerging_themes`, `backend/arp/voting`, `backend/arp/engagement`, `backend/arp/stewardship`, `backend/arp/reporting`, `backend/arp/bi`, `backend/arp/xbrl_pipeline`, `backend/arp/agents` | The numbered functions listed in `README.md` (thematic universe, transition assessments, portfolio risk, Decision Studio, index construction, strategy replication, stewardship, reports, Superset BI, XBRL facts, standing agents) |
| Evaluation | `backend/arp/golden_set` | Golden-set precision and retrieval evaluation against a real model |

The wiki covers the extraction path, which the owner's brief marks as the priority:
<!-- openwiki: broken internal link [/openwiki/pipeline/extraction.md] link "/openwiki/pipeline/extraction.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
<!-- openwiki: broken internal link [/openwiki/pipeline/grounding.md] link "/openwiki/pipeline/grounding.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Data-point extraction engine](/openwiki/pipeline/extraction.md), [Citation grounding](/openwiki/pipeline/grounding.md),
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Publishing facts](/openwiki/pipeline/publish.md), and the model and evidence layer in
<!-- openwiki: broken internal link [/openwiki/integrations/llm-and-retrieval.md] link "/openwiki/integrations/llm-and-retrieval.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[LLM clients and evidence retrieval](/openwiki/integrations/llm-and-retrieval.md).

## Frameworks

- **Anthropic SDK** (through LangChain's Anthropic client) behind one narrow `LLMClient.complete_structured` interface.
  Every agent gets schema-validated output, never free text.
- **LangGraph** models per-item multi-step flows (for example the extract → verify → adjudicate → aggregate graph).
  Batch fan-out, checkpointing and resumability stay outside the graphs, in the batch runner and the Postgres
  `RunStore`.
- **LlamaIndex / BM25 and local embeddings** handle evidence selection.

## Frontend

<!-- openwiki: broken internal link [/openwiki/architecture/frontend.md] link "/openwiki/architecture/frontend.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
The SPA is described in [Frontend application](/openwiki/architecture/frontend.md). It reaches every backend feature
through `frontend/src/api/client.ts`, and its types are generated from the backend's OpenAPI schema. For how a value
<!-- openwiki: broken internal link [/openwiki/architecture/data-flow.md] link "/openwiki/architecture/data-flow.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
travels from a document to the screen, see [Data flow: documents to UI](/openwiki/architecture/data-flow.md).
