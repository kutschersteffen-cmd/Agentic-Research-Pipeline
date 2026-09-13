# Review: open-source Generative BI against this system's GenBI layer

Four open-source projects were put forward as implementing "this exact
architecture": [WrenAI](https://github.com/Canner/WrenAI),
[Cube Core](https://github.com/cube-js/cube),
[Text2SqlAgent](https://github.com/Text2SqlAgent/text2sql-framework), and the
[Agentic BI Platform](https://github.com/Ratnesh-181998/agentic-bi-natural-language-querying)
reference template. All four exist and all four were reviewed against
`backend/arp/portfolio/genbi/` (see §5c of
[`PORTFOLIO_RISK_EXPOSURE_PLAN.md`](PORTFOLIO_RISK_EXPOSURE_PLAN.md)).

**Headline finding: they are the same *product* shape and a materially
different *safety* architecture.** Three of the four make the LLM emit SQL
and then work hard to make that SQL safe — dry-run validation, correction
loops, a semantic layer to stop it inventing columns. This system never lets
a model emit a query language at all: the planner emits a closed, typed
`PanelSpec` (7 dimensions × 3 metrics) that is validated by set membership
against live directories, and the numbers are computed by
`portfolio/aggregation.py`. Their hardest problem — "is this generated SQL
right?" — is one this design does not have.

The corollary is the honest cost: they can answer questions this system
structurally cannot (window functions, cohorts, ad-hoc ratios, arbitrary
joins), and they work against any warehouse rather than one purpose-built
holdings model.

## 1. The four, factually

| Project | What it is | Maturity / license | Where the LLM's output lands |
|---|---|---|---|
| **WrenAI** | Full GenBI stack: UI, AI service (FastAPI), engine (DataFusion), Ibis server; MDL semantic layer; text-to-SQL → Vega-Lite charts → saved dashboards | ~17.6k ★, Apache-2.0 core; **RLS and parts of the GenBI UI are commercial** | Free-form SQL, constrained by MDL + retrieval, then dry-run validated |
| **Cube Core** | Semantic layer only — metrics/dimensions/joins/access rules defined once in code, exposed over SQL/REST/GraphQL, with a relational pre-aggregation cache | ~20.8k ★, Apache-2.0 backend / MIT client; agentic features in Cube Cloud | Nothing: Cube is the *governed surface* an agent queries |
| **Text2SqlAgent** | Lightweight SDK: hands the model one `execute_sql` tool and lets it explore schemas, test queries, self-correct | ~156 ★, MIT; "20/20 on Spider" is a very small sample | Free-form SQL, executed live against the database during exploration |
| **Agentic BI Platform** | Reference template: FastAPI + LangGraph + Streamlit, six agents (metadata, RAG, SQL, impact, execute, BI), reflexion loop, Plotly output | ~4 ★, 48 commits, Apache-2.0; the "99% SQL accuracy" claim is unsubstantiated | Free-form SQL with an error-feedback correction cycle |

Read the last two as *patterns*, not as dependencies. The Agentic BI repo is a
well-drawn wiring diagram at four stars; Text2SqlAgent's "let the model roam
the database" stance is the opposite of the governance posture this codebase
takes everywhere else.

## 2. The one idea that matters, and what its own numbers say

Cube's and WrenAI's shared thesis is the semantic layer: give the model
business meaning (certified metrics, join paths, enum values, default fact
tables), not just DDL. Cube's own
[paired benchmark](https://github.com/cubedevinc/semantic-layer-benchmark)
(100 questions, three frontier models, McNemar p < 0.002) measures the gain:
**+17 to +23 percentage points** from adding ~9 KB of semantic-layer
markdown.

The number worth staring at is not the gain but the ceiling. With the
semantic layer, all three models **converge at roughly 68% accuracy**;
without it they sit at 46–51%. Model choice mattered less than the presence
of the semantic layer — and even the best configuration gets roughly one
question in three wrong.

For a general BI tool answering exploratory questions, 68% with a visible
SQL statement the analyst can read is a reasonable trade. For a number that
goes into a client's exposure report, it is not. That gap is the entire
justification for the design already built here: this system's planner
cannot emit an invalid query, because validity is a set-membership test
(`genbi/planner.py::_validate`) rather than a dry run, and because there is
no query language between the plan and the engine.

## 3. Concept mapping: theirs → ours

| Their concept | Our equivalent | Difference that matters |
|---|---|---|
| MDL / Cube data model (semantic layer) | `aggregation.DIMENSIONS`, `AnalyticSpec`/`PivotSpec`, `datapoint_mapping.py`'s source cascade, `climate/schemas.py` | Ours is code-enforced and tiny (7 dimensions, 3 metrics) rather than a modelling language — no expressive surface to get wrong, and no separate artifact to drift from the engine |
| Schema retrieval + column pruning (WrenAI: 60–80% schema reduction) | Not needed — `planner.build_context` sends the *whole* directory (portfolios, issuers, sectors, asset classes, dates, fields) | Our vocabulary is small enough to fit in a prompt whole; no retrieval step to mis-rank |
| Dry-run validation of generated SQL | `_validate()` re-checks every planned panel against live directories before it can run | Failure is caught before execution, and by exact match, not by the database rejecting it |
| Reflexion / `sql_correction` loop | Invalid panel is **dropped with a named warning**; the rest of the dashboard still ships | We chose visibility over repair — see §5, this is the one place their pattern has something to offer |
| Vega-Lite chart generation | Fixed `chart` hint → `AggregationView`/`TrendView`/`PivotTable` | Less flexible, deliberately: charts stay inside one reviewed visual system |
| Saved dashboards (SQLite metadata) | `DashboardSpec` in `portfolios/dashboards.json`; `run_dashboard()` re-executes with **zero LLM calls** | We persist the plan, never results or prose, so a re-run cannot serve a stale number under a fresh date |
| Natural-language summary of results | `genbi/narrator.py` + `check_grounding` | See §4 |
| Cube pre-aggregation cache; RLS | — | Genuine gaps, see §5 |

## 4. What this system does that none of the four documents doing

1. **Token-level numeric grounding of the narrative.** All four generate prose
   or chart captions over query results. In none of their documentation did I
   find a check that the *numbers in that prose* match the numbers the query
   returned — the summary is trusted because the SQL was validated. Here,
   `narrator.check_grounding` re-checks every figure and date in generated
   text against the computed facts, and treats an arithmetically derivable
   but never-computed figure as ungrounded. (Absence in a README is not proof
   of absence in the code; but it is not a documented feature of any of them,
   whereas it is a stated control here.)
2. **The plan is the artifact, not the answer.** WrenAI persists dashboard
   configurations too, but the re-run path still goes through the AI service.
   `service.run_dashboard()` is LLM-free by construction, which is what makes
   a generated dashboard usable as a recurring report.
3. **Data coverage as a first-class fact.** `observations.py` always reports
   what share of market value actually had the data point and what was
   excluded for missing it. Generic BI tools report the average; the
   honest answer to "what is our portfolio's carbon intensity" is an average
   plus a coverage percentage, and that is domain knowledge no semantic layer
   ships with.
4. **Per-panel isolation.** One unexecutable panel degrades to a failed panel;
   the dashboard still renders. Their pipelines are single-question, so the
   failure mode does not arise.

## 5. Real gaps these projects expose, in priority order

1. **Worked examples in the planner prompt** (WrenAI's
   `historical_question_indexing`). We already persist accepted
   `DashboardSpec`s and `AnalyticSpec`s and then ignore them at planning
   time. Feeding a handful of previously accepted specs as few-shot examples
   is a small change against a known-good accuracy lever.
2. **A planner eval set.** WrenAI ships an evaluation framework; Cube ships a
   benchmark. We have unit tests that prove the *validator* works, and
   nothing that measures whether the planner picks sensible panels. The
   in-house pattern already exists — `arp/golden_set/` (cases + runner + CLI)
   for extraction — and extends naturally: brief → expected panel shape, run
   before any planner-prompt change ships.
3. **A bounded re-plan pass.** Today a rejected panel is simply gone from the
   dashboard. Their reflexion loop suggests the better behaviour: feed the
   rejection reason back once, re-plan that panel only, and show both
   attempts. Bounded (one retry), visible, and never allowed to silently
   change the question.
4. **A business-alias layer.** "The flagship fund", "our carbon footprint",
   "the bond book" do not appear in any directory we send. A small
   alias/glossary map (portfolio tags → phrases, metric synonyms) is the
   cheapest part of a semantic layer and the part we most obviously lack.
5. **Access control.** Cube and WrenAI both treat row/column-level security as
   core (WrenAI charges for it). This system has **no authentication or
   per-mandate segregation at all** — every dashboard sees every portfolio.
   That is defensible for a single-analyst local tool and indefensible the
   day two mandates share an instance. Worth deciding deliberately rather
   than by default.
6. **Caching / pre-aggregation.** Every re-run recomputes from JSONL
   snapshots. Fine at demo scale; the opt-in `PostgresPortfolioStore` is the
   right place for Cube-style pre-aggregation if snapshot history and
   universe size grow.
7. **An agent-facing surface.** Cube's strategic bet is that the semantic
   layer becomes the thing *other* agents call. Our `/api/portfolio/aggregate`
   and `/bi/execute` already are a governed numeric surface; exposing them
   over MCP would let an external agent get grounded portfolio numbers
   without ever touching holdings data directly. Speculative, cheap, and
   aligned with where both Cube and WrenAI are heading.

## 6. What not to adopt

- **Free-form text-to-SQL as the generation target.** Replacing the closed
  spec with generated SQL would trade a validity guarantee for a ~68% ceiling
  (§2) in exchange for expressiveness this domain has not yet asked for. If
  genuinely ad-hoc SQL becomes a requirement, add it as a *second, clearly
  labelled* path — raw query, shown SQL, no narration — rather than routing
  the governed dashboards through it.
- **Autonomous schema exploration** (Text2SqlAgent's `execute_sql` loop). Its
  appeal is zero setup; its cost is an agent issuing unreviewed queries
  against live data, which is the opposite of the review/grounding discipline
  the rest of this codebase enforces.
- **Accuracy claims without a harness.** The "99% SQL accuracy" (Agentic BI)
  and "20/20 Spider" (Text2SqlAgent) figures are marketing until reproduced
  on a stated eval set — which is exactly the argument for building our own
  (§5.2) rather than citing theirs.

## 7. Verdict

WrenAI and Cube are serious, well-engineered projects solving the *general*
problem: any warehouse, any question, governed as well as free-form SQL can
be governed. This system solves a *narrow* problem — portfolio and climate
risk over a purpose-built holdings model — and buys a guarantee the general
tools cannot offer: the model chooses among validated queries and writes
checked prose, but never produces a number.

Nothing in the four argues for re-platforming. The semantic-layer literature
argues for tightening what we already have: examples, a planner eval set, a
bounded repair loop, an alias layer, and a decision about access control
before this is multi-user.

## Sources

- [Canner/WrenAI](https://github.com/Canner/WrenAI) — GenBI stack, MDL semantic layer, Apache-2.0 core
- [WrenAI architecture notes (gist)](https://gist.github.com/coderplay/9023fa0e251883b5586de4529be4857a) — service split, intent classification, retrieval, dry-run validation, correction, Vega-Lite charts
- [cube-js/cube](https://github.com/cube-js/cube) — semantic layer, pre-aggregation cache, access rules
- [cubedevinc/semantic-layer-benchmark](https://github.com/cubedevinc/semantic-layer-benchmark) — paired benchmark, +17–23pp, ~68% ceiling
- [Text2SqlAgent/text2sql-framework](https://github.com/Text2SqlAgent/text2sql-framework) — `execute_sql` agent loop, MIT
- [Ratnesh-181998/agentic-bi-natural-language-querying](https://github.com/Ratnesh-181998/agentic-bi-natural-language-querying) — six-agent LangGraph template with reflexion loop
