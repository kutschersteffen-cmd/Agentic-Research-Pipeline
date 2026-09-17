# CLAUDE.md — working in this repository

Agent-facing contract for the Agentic Research Pipeline. [`README.md`](README.md)
covers *what* the system does and how to run it; this file covers the rules a
change has to respect. Read this first, then load only the one `docs/` page your
task needs (map at the bottom).

## The two invariants

Everything else in this file is downstream of these. A change that breaks either
is wrong even if the tests pass.

1. **The LLM plans, deterministic code computes.** Models choose, classify,
   draft and decide *what* to look at. They never produce the number that
   reaches a user. Portfolio figures, backtest statistics, exposure
   propagation, financed emissions and XBRL-resolved totals are computed by
   ordinary Python from structured inputs. When you are tempted to let a model
   return a computed value, return the inputs instead and compute it.
2. **Every citation is re-verified programmatically.** `arp/grounding.py`
   re-locates each quoted span in the original document text and resolves its
   page number or sheet name *from the match position*. A page number reported
   by a model is never trusted and never stored. `grounding.py` depends on
   nothing but `arp.schemas` — no LangChain, no LangGraph, no LlamaIndex. Keep
   it that way; its independence is what makes it a check rather than part of
   the thing it is checking.

## Verification

```bash
bash scripts/verify.sh              # ruff + pytest + oxlint + tsc/vite build
bash scripts/verify.sh --backend    # backend only
```

`.github/workflows/ci.yml` runs this exact script, so green here means green
there. Run it before handing work back. It needs no API key and no network.

First-time setup is in the README; in short, `cd backend && pip install -e
".[dev]"` and `cd frontend && npm install`. CI additionally installs
`postgres,opensearch,emerging_themes,object_storage` — if a test you touched
imports one of those, install the extra rather than deleting the test.

Single test while iterating: `cd backend && pytest tests/test_grounding.py -q`.

## Module map

21 packages under `backend/arp/`, layered. Imports run downward only; the layer
order below is the real one, derived from the import graph:

| Layer | Packages |
|---|---|
| Entry points | `api` (FastAPI, 25 routers), `cli` (Typer) |
| Standing agents | `agents`, `golden_set` |
| Discovery | `emerging_themes` |
| Pipelines | `research`, `replication` |
| Domain | `portfolio`, `voting`, `transition_plan`, `transition_barrier`, `reporting`, `engagement`, `extraction`, `discovery` |
| Infrastructure | `retrieval`, `ingestion`, `orchestration`, `storage` |
| Primitives | `llm`, `grounding`, `universe`, `net_safety` |
| Leaves | `schemas`, `config` |

Two things to know before you add an import:

- **`schemas` and `config` are leaves.** They import nothing from `arp`. Putting
  a runtime dependency in either inverts the whole graph.
- **The four infrastructure packages are currently entangled** —
  `storage` imports upward into `retrieval`, `ingestion` and `orchestration` in
  five places. That is known debt, not a licence to add more. If you need a
  constant or a config object in two of those packages, put it in a leaf; do
  not reach sideways. (`EMBED_DIM` and `IndexingConfig` are the existing
  offenders and are the pattern to avoid, not to copy.)

## Conventions that are easy to get wrong

**All model calls go through `LLMClient.complete_structured`.** Never free text,
never a raw `anthropic` or `langchain` call from a pipeline. Structured output is
schema-forced and runs through a bounded validation-retry loop; anything
downstream is entitled to assume it was validated. The interface is
`arp/llm/base.py` — one narrow abstraction, deliberately.

**The extractor and the verifier must stay on different models.**
`Settings.llm_model` and `Settings.llm_verifier_model` default to different
models on purpose: an extractor and a verifier sharing weights repeat each
other's failure modes instead of catching them. Do not "simplify" them into one
setting.

**File-based stores are the source of truth.** Postgres, OpenSearch and object
storage are *additive read-model projections*. A default install has none of
them and must keep working identically. Never write business state that exists
only in a projection, and never make a default-path code route require one.

**Optional extras must stay optional.** `postgres`, `opensearch`,
`object_storage`, `emerging_themes` and `replication` are opt-in extras, so
their imports are deliberately deferred inside functions
(`retrieval/content_store_factory.py`, `retrieval/search_indexer.py`,
`emerging_themes/clustering.py` are the canonical examples). Hoisting one of
those to module scope breaks a default install with an `ImportError`. When you
see a function-local `import`, assume it is load-bearing until you have checked
which case it is.

**Tests never touch the network or need an API key.** Use `FakeLLMClient` from
`tests/conftest.py` — scripted responses keyed by output-model class name. An
autouse fixture forces `ARP_HYBRID_RETRIEVAL_ENABLED=false` because the real
path downloads a ~220 MB embedding model; a test that wants hybrid retrieval
constructs its own `Settings(hybrid_retrieval_enabled=True, ...)` and mocks
`embed_texts`. Tests that genuinely need a real backend gate on an env var and
skip without it:

```python
DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres backend")
```

**Settings come from `Settings` (`arp/config.py`), prefix `ARP_`.** Pydantic
settings, `.env`-backed. Do not read `os.environ` directly in pipeline code, and
do not add a field you are not going to read — a setting that looks enforced but
is not is worse than no setting.

**Prompt edits are a versioned event.** Every record carries `provenance`
(model + a hash of the prompt content). Changing a system prompt changes that
hash, which is the point. Run `arp golden-set run` before shipping a prompt or
model change.

**Runs are checkpointed and resumable.** Results append to
`runs/<run_id>/results.jsonl` per company. Preserve that: no rewriting completed
rows, no holding a whole batch in memory before a single write, and per-company
failures stay isolated rather than failing the run.

## Style

- Python 3.11+, `ruff` (config in `backend/pyproject.toml`): line length 130,
  `E501` and `B008` intentionally ignored — `B008` because FastAPI's `Depends()`
  idiom is used throughout `api/routers/`. Run `ruff check .`, not your own
  preferences.
- `ruff format` is **not** enforced yet; do not reformat files you are not
  otherwise changing.
- Comments explain *why*, and this codebase's existing comments are unusually
  substantive. Match that register — when you encode a non-obvious trade-off,
  write down the reasoning, as the surrounding code does.
- Conventional-ish commit subjects in English; no model identifiers in commit
  messages, PR bodies or code comments.

## Where to look

| Task | Read |
|---|---|
| Any module, the agent stack, dependencies | `docs/TECHNICAL_REFERENCE.md` |
| Why a precision control exists / what it catches | `docs/METHODOLOGY.md` |
| Storage layer, projections, the SQLite/Postgres split | `docs/DATABASE_STORAGE_REVIEW.md` |
| Portfolio monitoring, Generative BI, climate analytics | `docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md`, `docs/GENBI_LANDSCAPE_REVIEW.md` |
| Backtests, in/out-of-sample, known limitations | `docs/STRATEGY_REPLICATION_METHODOLOGY.md` |
| Transition plan / barrier assessments | `docs/TRANSITION_BARRIER_ASSESSMENT.md`, `docs/EMERGING_THEMES_VOCABULARY.md` |
| Auth, secrets, deployment posture | `docs/CORPORATE_READINESS_PLAN.md` |
| Windows / corporate proxy setup | `docs/INSTALLATION.md` |

## Do not

- Return a computed figure from a model, or store a model-reported page number.
- Make `grounding.py` depend on the agent stack.
- Add an import that points upward in the layer table.
- Hoist a deferred import without checking whether it guards an optional extra.
- Reformat or restructure files outside the change you were asked to make.
- Weaken a test to make it pass, or delete one whose extra is merely missing.
