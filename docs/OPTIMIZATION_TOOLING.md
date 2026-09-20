# Optimization Tooling — What Exists, and What This Engine Would Actually Use

Status: **survey and recommendation.** Nothing here is installed. The index
engine in `backend/arp/index/` deploys no solver, no risk model and no
covariance matrix (see `INDEX_METHODOLOGY_LANDSCAPE.md` §6 C and the plan's
§7.1). This document is what to reach for *if* a methodology needs more than
the deterministic path, and — more usefully — how to tell whether it does.

The short version: the question is not "which optimiser is best". It is
**"which problem class does the methodology generate?"** That answer picks
the solver set, and for most index methodologies it lands somewhere free
software covers completely. Exactly one methodology feature pushes it into
paid territory, and §2 names it.

---

## 1. Three layers, and the one that is actually a decision

```
  methodology feature  →  problem class  →  modeling layer  →  solver
  "cap at 8%"             linear             cvxpy / direct     Clarabel
  "TE ≤ 1.5%"             SOCP               cvxpy              Clarabel / MOSEK
  "at most 80 names"      MIQP               cvxpy / gurobipy   Gurobi / MOSEK / SCIP
```

The modeling layer is a convenience and swappable late. The **problem class
is the decision**, because it is fixed by the methodology and it determines
whether the solver is free, whether it is deterministic, and whether it
terminates in milliseconds or minutes.

Getting this backwards — picking cvxpy first, then discovering the
methodology needs integer variables that its free backends cannot handle —
is the common failure.

---

## 2. What index construction actually asks for

| Methodology feature | Formulation | Class | Free solver? |
|---|---|---|---|
| Minimise distortion from parent weights | `min ‖w − b‖²` s.t. linear | **QP** | Yes |
| Single-name cap, group caps, weight bounds | `w ≤ c`, `Σ_g w ≤ c_g` | linear | Yes |
| Decarbonisation intensity target | `Σ wᵢxᵢ ≤ τ` — **a linear constraint** | linear | Yes |
| Activity-exposure / green-brown floor vs. universe | linear once the universe side is a constant | linear | Yes |
| Maximise a score subject to a TE budget | `max wᵀs` s.t. `(w−b)ᵀΣ(w−b) ≤ τ²` | **SOCP / QCQP** | Yes |
| Minimise TE subject to climate constraints | `min (w−b)ᵀΣ(w−b)` s.t. linear | **QP** (needs Σ) | Yes |
| Factor-exposure neutrality | `Bᵀw = Bᵀb` | linear | Yes |
| **Minimum weight *if held*** | semi-continuous: `w ∈ {0} ∪ [m, c]` | **MIQP** | Barely |
| **At most N constituents** | cardinality: `Σ zᵢ ≤ N` | **MIQP** | Barely |
| Round lots / whole index shares | integer | **MIQP** | Barely |
| Turnover with a fixed cost per trade | fixed-charge | **MIQP** | Barely |

**The headline.** Every constraint an EU PAB or CTB imposes — including the
decarbonisation target, which people assume is exotic — is *linear in the
weights*. So is every cap. The whole regulated core is a QP at worst, and
free solvers handle it comfortably.

**The one feature that changes the bill** is a minimum weight *if held*.
"No constituent below 5 bp" sounds like a bound; it is not. A bound says
`w ≥ m` for everyone, which would force every eligible name into the index.
What the methodology means is `w = 0 or w ≥ m` — a disjunction, requiring a
binary per name, which makes it a mixed-integer quadratic programme. The
same is true of a fixed constituent count. Those two, and essentially only
those two, are what buy a commercial solver.

*What this engine does today:* `ConstraintSet.min_weight` drops names below
the threshold and renormalises. That is a **greedy heuristic** for the
semi-continuous constraint, not a solution to it — it never reconsiders
whether a dropped name should have been held at the floor instead of a name
it kept. Fine for a screening-and-tilting index; not fine if minimum weight
is a binding methodology commitment.

---

## 3. Modeling layers

| Layer | What it is | Fits us when |
|---|---|---|
| **cvxpy** | Disciplined-convex modeling; verifies convexity, canonicalises to the solver's form, swaps backends by a keyword. Ships with Clarabel, OSQP, SCS; reaches HiGHS, PIQP, ProxQP, DAQP, Gurobi, MOSEK, SCIP, Knitro, cuOpt and others when installed. | The default choice for anything convex. The convexity check alone is worth it: a malformed methodology constraint fails at build time instead of returning a plausible wrong answer. |
| **qpsolvers** | A thin unified `solve_qp()` over ~20 QP backends, plus **qpbenchmark** for success-rate/accuracy/time comparisons on real problem sets. | When the problem is *only* a QP. Less machinery than cvxpy, and the benchmark makes the backend choice evidence-based rather than folkloric. |
| **Pyomo** | General algebraic modeling; LP/MILP/NLP/MINLP, many solvers. | If the problem stops being convex — piecewise transaction costs, logical conditions. Heavier than we need today. |
| **linopy** | Labelled-array modeling (xarray-style) that assembles the sparse matrix. | Large structured problems with natural index dimensions. Elegant, but our problem is one vector of N names. |
| **PuLP** | LP/MILP only, simple. | Prototyping; too narrow here (no QP). |
| **AMPL / GAMS / JuMP** | Mature algebraic languages (JuMP in Julia). Academic bundles often include commercial solvers. | Not for a Python service. |
| **Direct solver API** (`gurobipy`, `mosek.fusion`) | No abstraction layer. | Only when you need solver-specific features — callbacks, warm starts, solution pools. |

**For this repo: cvxpy**, behind the existing `apply_constraints` seam, with
open-source backends only. It keeps the door open to a commercial backend
later without touching the calling code.

---

## 4. Open-source solvers

| Solver | Classes | Algorithm | Licence | Notes |
|---|---|---|---|---|
| **Clarabel** | LP, QP, SOCP, SDP, exponential | Interior point (Rust) | Apache-2.0 | cvxpy's default since 1.5, replacing ECOS. The sensible first choice. |
| **OSQP** | QP | ADMM (first-order) | Apache-2.0 | Very fast, warm-startable, **moderate accuracy** — it converges to a loose tolerance quickly. For a published index, tighten the tolerance and verify constraints independently. |
| **SCS** | Conic (LP/QP/SOCP/SDP) | ADMM | MIT | Same accuracy caveat as OSQP. |
| **HiGHS** | LP, MIP, **convex QP** | Simplex / IPM / branch-and-cut | MIT | Excellent LP and MILP. **No native MIQP** — so it does not solve the cardinality case directly. |
| **PIQP / ProxQP / DAQP / qpOASES / quadprog** | QP | Proximal IPM, augmented Lagrangian, active set | Mostly BSD/LGPL | Specialist QP solvers; reachable through qpsolvers and mostly through cvxpy. Worth benchmarking rather than assuming. |
| **SCIP** | MILP, **MINLP**, MIQP | Branch-cut-and-price | Apache-2.0 (since 9.0; 10.0 confirms) | **The only credible free MIQP route.** The licence change matters: it used to be academic-only, which is why older advice says MIQP requires paying. Slower than Gurobi, often by a lot, but it is genuinely usable now. |
| **CBC / GLPK** | LP, MILP | Branch-and-cut / simplex | EPL / GPL | Older; HiGHS supersedes both for new work. |
| **Ipopt** | NLP | Interior point | EPL | For genuinely non-convex objectives. Local optima only — a poor fit for a methodology that must be defensible. |
| **NVIDIA cuOpt** | LP, QP; beta MIP, QCQP, SOCP | GPU | Apache-2.0 | Newly open-sourced and GPU-accelerated. Interesting for very large problems; at 4,000 names we are nowhere near needing it, and beta status plus GPU non-determinism are both disqualifying for a published index today. |

---

## 5. Commercial solvers

**Gurobi, MOSEK, COPT, FICO Xpress, IBM CPLEX, Artelys Knitro.** All reach
MIQP/MISOCP; all are materially faster than SCIP on hard integer problems;
all are free for academics and **none publishes commercial pricing** — it is
a sales conversation, typically an annual named-user or enterprise licence.

Two things matter more than speed for our purposes:

- **MOSEK** is the conic specialist — if the formulation is SOCP-heavy
  (tracking-error budgets, robust variants), it is the natural fit.
- **Gurobi** is the strongest general MIQP engine and the one most
  portfolio-construction literature benchmarks against.

On determinism, Gurobi's own position is worth quoting precisely: it
guarantees the same solution and the same algorithmic path from the same
model and parameters **on the same machine** — and warns that Python sets
can reorder variables and change the model itself. That is a *weaker*
guarantee than an index needs, which is byte-identical output across
machines and across years. §8 is about containing that gap.

---

## 6. Portfolio libraries — a layer above the solver

| Library | What it gives | Built on |
|---|---|---|
| **skfolio** | scikit-learn-shaped portfolio optimisation, risk measures, model selection, cross-validation. Reached 1.0 in 2026. | cvxpy |
| **Riskfolio-Lib** | The widest menu of risk measures and allocation models (mean-risk, risk parity, hierarchical, OWA). v7.x, actively maintained. | cvxpy |
| **PyPortfolioOpt** | Classical efficient frontier, Black-Litterman, HRP. The most approachable; narrower scope. | cvxpy |
| **cvxportfolio** | Multi-period optimisation and backtesting, from the Boyd group with BlackRock. Closest to a production research framework. | cvxpy |

All four sit on cvxpy, which is itself an argument for cvxpy as the modeling
layer: borrowing a formulation from any of them is then a copy, not a port.

**None of them is an index engine, and the gap is not small.** They have no
divisor, no index shares, no rebalance calendar, no effective-dated
methodology versioning, no path-dependent trajectory state, no construction
funnel and no audit trail — all of which are the substance of
`backend/arp/index/`. What they are genuinely good for: **reference
formulations** to check ours against, **risk estimators** (shrinkage
covariance, robust estimators) if we ever need Σ, and **research** outside
the index pipeline. Treat them as a library to read, not a dependency to
adopt.

---

## 7. Vendor index optimisers

If the goal is to match a published index provider rather than to build,
these are what the providers themselves use:

- **MSCI Open Optimizer** — the engine behind many MSCI indices, including
  the Global Minimum Volatility family; consumes MSCI Models Direct risk
  model files directly. Also available as Barra Optimizer on FactSet, with a
  Python client (`fds.sdk.BarraPortfolioOptimizer`).
- **Axioma Portfolio Optimizer** (SimCorp) — has a Python API and
  optimisation web services, deliberately open to third-party and in-house
  risk, return and cost models rather than only Axioma's. Also in the
  FactSet API catalogue with a Python client
  (`fds.sdk.AxiomaEquityOptimizer`).
- **Northfield**, **Bloomberg PORT** — same category.

These are bought for the **risk model and the support**, not the solver. The
trade is a licence, an external dependency in the reproducibility chain, and
someone else's version schedule — against not having to build or defend
factor risk estimation yourself. That is a real trade, and for a published
benchmark it is often the right one. It is also mostly orthogonal to this
engine: they would replace `weighting/` and nothing else.

---

## 8. Determinism — the constraint that disqualifies most of the above

The plan makes byte-identical output a hard requirement (§10). A solver
threatens it in five ways, each with a containment:

| Threat | Containment |
|---|---|
| Solver version changes the last digits | Pin the exact version; record it and the lockfile hash in the run manifest |
| Multithreading reorders floating-point accumulation | **Run single-threaded.** At 4,000 names the cost is irrelevant |
| Presolve / heuristics / seeds differ across builds | Fix every parameter explicitly, including the seed; never rely on defaults |
| Degenerate optima — several weight vectors, equal objective | Add a deterministic tie-break (e.g. a tiny penalty on distance to the previous index) so the choice is a rule, not the solver's mood |
| First-order solvers (OSQP, SCS) stop at a loose tolerance | Tighten it, and **verify every constraint independently** — never trust a returned `optimal` status |

Plus the two the plan already requires: a determinism test that solves the
same problem repeatedly and byte-compares, and the relaxation ladder as
versioned config rather than a `try/except`.

**The honest summary:** you can make a solver reproducible enough for a
published index, but it is real work and permanent maintenance. The current
entropy tilt gets it for free. That is the trade, and it is the reason the
build plan sequences the optimiser last rather than first.

---

## 9. Recommendation

Staged, cheapest first. Each stage is independently useful and none blocks
the next.

**Stage 0 — now. Nothing.** The entropy tilt meets PAB/CTB targets exactly,
respects every cap, and is byte-identical everywhere. No solver is
justified by anything currently in scope.

**Stage 1 — a true least-squares projection (~1 week).** Add cvxpy with
open-source backends behind a new `weighting/optimize.py`, implementing
`min ‖w − b‖²` subject to the existing `ConstraintSet` plus the intensity
target. What it buys over the current path:

- a provable optimum for a stated objective, rather than a defensible
  heuristic;
- **all constraints binding simultaneously** instead of tilt-then-project,
  which removes the composition question entirely;
- one formulation that covers group caps, factor neutrality and ratio floors
  without another bespoke pass.

Ship it as an opt-in `[optimize]` extra with the §8 controls, chosen per
calibration, with the deterministic path staying the default. Both paths
run on the same inputs, so the calibration records which one produced the
index.

**Stage 2 — a tracking-error budget (weeks, plus a licence).** The
formulation is easy (SOCP; Clarabel or MOSEK handles it). The hard part is
**Σ** — a factor covariance matrix, which is a data licence and a modelling
commitment, not a solver choice. Decide the risk model first; the solver
follows in an afternoon.

**Stage 3 — semi-continuous or cardinality constraints (only if needed).**
This is the MIQP step and the only one that needs a commercial solver, with
SCIP as the free fallback now that it is Apache-2.0. **Do not take this
stage speculatively.** Take it when a methodology commits to a minimum
weight if held or a fixed constituent count — and note that this engine's
`min_weight` heuristic is the thing that becomes insufficient at that point.

**The seam already exists.** `apply_constraints(weights, candidates,
constraints)` is a pure function from weights to weights, and the trajectory
solve already takes a `project` callable. A solver drops in at exactly those
two points with no change to screens, selection, tilts, calibration storage,
the API or the UI.

---

## 10. Before adopting any of this

1. **Name the problem class first** (§2). If nothing in the methodology is
   semi-continuous or cardinality-constrained, stop before the commercial
   tier.
2. **Benchmark on our own problems**, not on published suites — qpbenchmark
   is the right harness, our review instances the right data.
3. **Decide the tie-break rule** before the first degenerate optimum, not
   after.
4. **Write the relaxation ladder into config** at the same time as the
   solver, not later (plan §7.3).
5. **Check the licence terms for production use**, not just for evaluation —
   academic-free says nothing about a fund administrator.
6. **Budget the maintenance**, not just the integration: a pinned solver is
   a dependency you now own across upgrades, and its upgrade cadence is not
   yours.

---

## 11. Verification status

Researched September 2026 via search; the vendor and project sites
themselves are blocked by this session's egress policy, so versions and
licence terms should be confirmed at the source before anything is
purchased or pinned.

| Claim | Confidence |
|---|---|
| Problem-class mapping in §2, and semi-continuous ⇒ MIQP | High — this is formulation, not a product fact |
| cvxpy default moved ECOS → Clarabel (1.5), ECOS dropped as a dependency (1.6), still callable | High |
| HiGHS solves convex QP but has no native MIQP | Medium-high |
| SCIP 9.0/10.0 under Apache-2.0 | Medium-high — **verify before relying on it commercially** |
| Gurobi determinism is same-machine, same-parameters | High — their own documented position |
| skfolio 1.0 (2026), Riskfolio-Lib 7.x, both active; all four portfolio libraries built on cvxpy | Medium-high |
| Axioma Portfolio Optimizer Python API / web services; FactSet Python clients for both Axioma and Barra | Medium-high |
| cuOpt open-sourced Apache-2.0, LP/QP with MIP/QCQP/SOCP in beta | Medium |
| No commercial solver publishes pricing; all offer free academic licences | High |
