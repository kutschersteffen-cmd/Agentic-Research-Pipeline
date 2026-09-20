# Equity Index Construction — Enhanced Plan

Status: **partially built.** The composable rule engine and the calibration
store described in sections 6, 7 and 15 now exist: `backend/arp/index/`
(screens, selection, weighting and tilts, the capping waterfall, the
path-dependent trajectory, index shares and divisor), `backend/arp/storage/index_store.py`
(versioned, effective-dated calibrations), `backend/arp/api/routers/index.py`,
`arp index --help`, and a rule-composer UI on the `Index Construction` tab.
An optional optimisation path (`arp/index/optimize.py` and `risk.py`, the
`optimize` extra) implements all three stages of
[`OPTIMIZATION_TOOLING.md`](OPTIMIZATION_TOOLING.md) section 9 — a
least-squares projection, minimum tracking error, and score maximisation
under a tracking-error budget on an estimated or supplied risk model, plus
cardinality limits and an enforced minimum weight as a mixed-integer
programme on SCIP — chosen per calibration, with the deterministic waterfall
as both the default and the fallback.
Phases 1, 3, 5, 6 and 7 are not built: no bitemporal store, no vendor feeds,
no corporate actions, no FX or withholding tax, no total-return variants, no
backtester, no governance workflow, and no file distribution. The rest of
this document describes the target design; section 21 says what to do next.

This document reviews the submitted draft *"Implementation Plan — A Python-Native Equity Index Construction
System"* (DWS, Investment Intelligence & Positioning), keeps what holds up,
fixes what doesn't, and fills the gaps that would otherwise be discovered
mid-build. It is written to be implementable against *this* repository —
see §1 for the build-vs-integrate recommendation.

The draft is a good skeleton: the five architecture principles are the
right five, the phase ordering is broadly right, and the instinct to
validate against a reference index before adding methodology complexity is
correct. What it is missing is almost entirely the *index-mechanics* layer
— divisor, index shares, the four-date rebalance model, corporate-action
treatment, FX, withholding tax — plus a realistic reading of what EU BMR
actually demands. Those are the parts that decide whether the system
produces a defensible number.

**Assumptions made in the absence of the two confirmations the draft's own
"Recommended Next Step" asks for.** Each is flagged where it drives a
decision, and each is cheap to revisit:

- **A1 — Use.** The first index is an *internal* research / model index
  (thematic, cap-weighted with a screen), not yet a published benchmark
  used to price a financial instrument or track a fund. This materially
  changes the BMR scope — see §12. Track B in §20 prices the published-
  benchmark path separately.
- **A2 — Scale.** ~4,000 instruments, daily frequency, 15–20 years of
  history. That is ~20M price rows: small. Storage choice is therefore a
  concurrency and governance question, not a scale question (§3).
- **A3 — Currency.** One index currency (EUR), constituents in local
  currency, single FX fixing source.
- **A4 — Frequency.** End-of-day calculation. No real-time/intraday
  dissemination in v1 (that is a different system — see §14).

---

## 0. What changed vs. the submitted draft

Enhancements are listed worst-consequence-first. §0 is the review; §§1–20
are the plan.

| # | Issue in the draft | Consequence if left | Fix (section) |
|---|---|---|---|
| 1 | **The Phase 1–2 validation gate is impossible as sequenced.** "Replicate a simple cap-weighted benchmark exactly" before Phase 3 requires weighting (Phase 3) *and* the divisor/calculation engine (Phase 4). | The one hard quality gate in the plan silently gets skipped or deferred, which is exactly how data and corporate-action bugs survive to Phase 5. | Walking skeleton: a thin end-to-end vertical slice becomes Phase 2.5, before the full weighting and calculation phases (§15) |
| 2 | **No index-shares concept.** The plan goes "weighting engine" → "divisor engine" with nothing in between. | Target weights have no mechanism to become a continuous index; the divisor engine has nothing to act on. Weights would be silently recomputed daily, which is not an index — it is a daily-rebalanced portfolio. | §8: weights → index shares at the effective close, fixed until the next rebalance |
| 3 | **No corporate-action treatment table.** "Corporate actions" appears as an ingestion concern only. | Every CA becomes an ad-hoc decision at production time; index continuity breaks; the errors are invisible because the index level stays plausible. | §9: per-action-type price/share/divisor treatment, with thresholds as config |
| 4 | **BMR treated as "the `audit_log` module".** | Audit log is maybe 15% of BMR. Missing: benchmark statement, methodology-change and consultation procedure, oversight function, input-data policy, **correction policy**, cessation plan, 5-year records. Discovered late, these stop a launch. | §12: full artifact list, plus the prior question of whether BMR bites at all (A1) |
| 5 | **No four-date rebalance model.** Only "review calendar". | Selection/weight-reference/announcement/effective dates get conflated; results become irreproducible and look-ahead creeps in through the back door. | §5 |
| 6 | **"Byte-identical output" vs. a cvxpy solver.** These are in direct tension: solver version, backend, and tolerance all move the last digits. | The hard reproducibility requirement is violated by the recommended Phase 3 tool. | §7: deterministic iterative capping is the default path; cvxpy is an opt-in extra for genuinely optimisation-based schemes, pinned and determinism-tested |
| 7 | **Point-in-time defined as "an as-of date on every table".** | One timestamp cannot distinguish "the value *for* date D" from "what we *believed on* date D about date D". Vendor restatements then overwrite history invisibly — the exact failure the principle is meant to prevent. | §3: bitemporal (`effective_date`, `knowledge_date`) |
| 8 | **Config is versioned but not time-effective.** | Today's parameters silently rewrite history: a backtest of a 2019 review runs under 2026 caps. | §3.4: configs carry effective-date ranges; the engine selects the version in force on the review date |
| 9 | **No FX, no withholding tax.** | A multi-currency index cannot be computed; a net-return index cannot be computed. Both are usually the first thing a client asks for. | §4 |
| 10 | **"Validated against a reference index" with no numerical tolerance.** | Unfalsifiable gate. "Close enough" gets declared under schedule pressure. | §11.1: explicit acceptance thresholds |
| 11 | **Look-ahead bias listed as a risk with no mechanism.** | Risk registers do not prevent bugs; architecture does. | §11.3: knowledge-date-scoped data access + a future-row injection test |
| 12 | **No buffer rules / fast entry-exit.** | Index churns at every review; turnover and cost explode; the "screening rules drift" risk it names is actually a *stability* problem. | §6.2–6.3 |
| 13 | **Greenfield monorepo, ignoring the existing system.** | Re-implements identity resolution, append-only audit storage, run orchestration, config validation, API, and a thematic screen this repo already has in production form. | §1 + §18 reuse map |
| 14 | **No information-barrier consideration.** | Pending constituent changes are market-sensitive. An unrestricted API serving future-effective constituents is a front-running channel. | §13 |
| 15 | **API as the distribution deliverable.** | The actual consumers (PM, fund accounting, risk) need a stable *file contract* on a schedule; a REST service is secondary. | §14 |
| 16 | **`pyfolio-reloaded` inside the audit path.** | A stale third-party library computing numbers you must defend line-by-line. Turnover and drawdown are ~150 lines you should own. | §16 |
| 17 | **`exchange_calendars` missing entirely.** | Trading-day calendars, holidays and half-days get hand-rolled, wrongly. | §16 |
| 18 | **No "fail loud" override path.** | A hard block with no documented exception route gets bypassed by an ops hack under deadline. | §11.5 |
| 19 | **No base-date / base-level / initial-divisor definition.** | Trivial to specify, awkward to retrofit. | §8.1 |
| 20 | **16–20 weeks to "production-candidate", single engineer.** | Plausible for an internal research index, optimistic for anything published; and single-engineer ownership of published numbers is a bus-factor problem in itself. | §20 |

Two draft statements are worth keeping verbatim because they are the load-
bearing ones: *"every methodology parameter is data, not code"* and *"a
missing free-float figure blocks the run rather than defaulting silently"*.
Everything below is built to make those two true rather than aspirational.

---

## 1. Build inside this repository, not as a greenfield monorepo

**Recommendation: build the engine as `backend/arp/index/` inside the
Agentic Research Pipeline, with the draft's package boundaries preserved as
sub-packages.**

The draft scaffolds a standalone `equity-index-engine/` repo with six
installable packages. The boundaries it chooses are right. The repository
choice is not, because this codebase already runs, in production form, four
of the things the new repo would rebuild:

- **The thematic screen** — the draft's Phase 2 needs "market cap,
  liquidity, free float, **thematic**" screens. The thematic one is the
  hard one, and it is this repo's first pillar: an Advocate/Opposing/
  Adjudicator pipeline producing cited, confidence-scored activity matches
  with a review queue. Rebuilding that is months, not weeks.
- **Issuer identity resolution** — ISIN → `company_id`, with a confidence
  score and a review path for anything ambiguous
  (`portfolio/entity_resolution.py`, `schemas/portfolio.py::SecurityResolution`).
  An index engine needs exactly this to join price/reference data to
  company-level research.
- **Append-only audit storage** — the engagement store's
  `record.json` + `events.jsonl` pattern, and `DataPointObservation`'s
  "a correction is a new observation, never an edit", are already the
  discipline the draft's `idx_governance` is asking for.
- **Run orchestration, API and CLI** — `storage/run_store.py`
  (checkpointed, resumable, file-based runs), the FastAPI router pattern,
  and the `arp` Typer CLI. The draft's Phase 7 is a router file here.

Keeping the draft's module boundaries *inside* this repo means the decision
stays reversible: `backend/arp/index/` has no inbound dependencies from the
rest of `arp`, and a clean outbound seam (§18), so extracting it into its
own repo or workspace packages later is a directory move plus a
`pyproject.toml`, not a rewrite. Name the seam now, defer the split.

**When to choose the standalone repo instead:** if the index engine must be
operated by a different team under a different release cadence and change-
control regime than the research pipeline — which is a plausible outcome of
the BMR administrator decision in §12. In that case, still import this
repo's thematic-screen output as a *data contract* (a signed, versioned
eligible-universe file with an effective date), not as a library.

---

## 2. What the system must actually produce

The draft describes stages but never states the deliverable set. Everything
downstream (file contracts, API, audit) is defined by this list.

| Output | Grain | Consumer |
|---|---|---|
| Index level series — price (PR), gross total return (GTR), net total return (NTR) | index × day × currency | PM, fund accounting, clients |
| Constituent & weight file | index × effective day × security | PM, ops, replication |
| Index shares & divisor history | index × day | reproducibility, audit |
| Pro-forma / pending rebalance pack | index × review | index committee (restricted, §13) |
| Corporate-action journal | index × event | audit, reconciliation |
| Run manifest (input hashes, config version, output hash) | run | reproducibility, BMR records |
| Methodology document + benchmark statement | index × methodology version | committee, external publication |
| Backtest & analytics pack (turnover, capacity, factor drift, tracking vs reference) | index × study | committee approval |

If it is not on this list, it is not in v1.

---

## 3. Point-in-time, done properly

### 3.1 Bitemporal, not as-of

Every ingested fact carries **two** dates:

- `effective_date` — the date the fact is about (the close of 2024-03-15).
- `knowledge_date` — the date we learned it (the vendor delivered it on
  2024-03-18, or restated it on 2024-06-02).

Reads always go through one accessor:

```python
store.get(table, effective_range, knowledge_date=D)   # -> the latest row per key with knowledge_date <= D
```

A restatement is a new row with a later `knowledge_date`, never an update.
This is what makes "a backtest run today reproduces exactly what an index
committee saw on any past date" true rather than a slogan — with a single
as-of column it is not achievable, because the restatement overwrites the
belief.

Cost: storage roughly doubles (irrelevant at A2 scale) and every query
grows a parameter. That parameter is the point (§11.3).

### 3.2 Physical layout

Parquet on disk, partitioned `table/knowledge_date=YYYY-MM-DD/`, queried
through DuckDB. Roughly 20M price rows compresses to a few GB and scans in
under a second. Postgres is warranted for the *governance* tables —
methodology versions, committee approvals, exception records, audit log —
because those have concurrent multi-user writes and need real transactions.
This repo already carries an optional Postgres layer
(`storage/postgres*.py`, the `postgres` extra) to reuse.

So: **Parquet/DuckDB for facts, Postgres for governance.** The draft frames
the DuckDB-vs-Postgres choice as a scale question; at A2 scale it is not.

### 3.3 Tables

`prices` (close, currency, volume, trading-status), `reference`
(shares outstanding, free-float factor, country of domicile/listing,
currency, GICS, listing status), `corporate_actions` (§9),
`fx_rates`, `withholding_tax_rates`, `calendars`, plus the derived,
append-only `index_shares`, `divisors`, `index_levels`.

Derived tables are written once per (index, effective_date) and never
rewritten; a correction follows the §12.4 correction policy and is written
as a new record with a restatement reason, so the published series and the
corrected series are both recoverable.

### 3.4 Config is time-effective, not just versioned

The draft's "parameters are data, not code" needs one addition or it
silently rewrites history:

```yaml
# configs/methodologies/dws_electrification.yaml
methodology_id: dws_electrification
version: 4
effective_from: 2025-06-20      # first review this version governs
effective_to: null              # open-ended
approved_by: [ "IC-2025-06-11" ] # committee minute reference
parameters:
  universe:
    min_free_float_mcap_eur: 500_000_000
    min_adv_eur_3m: 2_000_000
    buffer: { add_rank: 80, drop_rank: 120 }
  weighting:
    scheme: free_float_mcap
    cap: { single_name: 0.08, ucits_5_10_40: true }
  calendar:
    review_frequency: quarterly
    selection_lag_days: 5
```

The engine resolves the config version **in force on the review date**, not
the latest. Config files are validated by a pydantic model (strict, no
extra keys), and every run records the SHA-256 of the resolved, fully-
expanded config in its manifest.

---

## 4. Reference data the draft omits

| Need | Why it is load-bearing | Decision required |
|---|---|---|
| **Trading calendars** | Which days the index publishes; which exchanges are shut; half-days; what happens when a constituent's exchange is closed but the index publishes (carry last close). | Index calendar = union or intersection of constituent exchanges? Recommend: publish on the index-currency home calendar, carry stale prices for closed venues, flag staleness > N days. |
| **FX fixing** | Every non-EUR constituent's price must be converted at a *stated* fixing, same one every day, or the index is not reproducible. | Which fix (e.g. a 16:00 London fixing), which source, what happens on a fixing-source holiday. |
| **Withholding tax table** | NTR is PR plus dividends net of the withholding rate applicable to a non-resident institutional holder, by country of issuer domicile. Without this table there is no net-return index. | Source and maintenance owner of the rate table; it changes with treaty and domestic-law changes and must itself be bitemporal. |
| **Corporate-action vendor** | CA coverage, not price coverage, is what actually breaks index continuity. Vendors differ substantially in special-dividend and spin-off coverage. | Which feed, and whether a second feed is licensed for the reconciliation check in §11.4. |
| **Free float** | The draft names it in its own "fail loud" example but never sources it. Float factors are vendor-specific and methodology-defining. | Vendor, update cadence, and the threshold below which a float change waits for the next review (§9). |

All five live in `backend/arp/index/reference/`, all five are bitemporal,
and none of them may be defaulted silently.

---

## 5. The four-date rebalance model

The draft has "review calendar". An index review needs four distinct dates,
and conflating any two of them is a reproducibility or look-ahead bug:

| Date | What happens | Uses data known as of |
|---|---|---|
| **Selection date** (`t_sel`) | Eligibility screens run; membership decided. | `knowledge_date = t_sel` |
| **Weight reference date** (`t_ref`) | Prices, shares, float used to compute target weights and index shares. Usually `t_sel` or a few days after. | `knowledge_date = t_ref` |
| **Announcement date** (`t_ann`) | Results published to the restricted audience, then to the market per the methodology. | — (no data read) |
| **Effective date** (`t_eff`) | Changes take effect at the close; new index shares and the new divisor apply from the next open. | prices at `t_eff` close |

Two consequences worth stating explicitly in the methodology document,
because both surprise people:

1. **Weights on the effective close are not the target weights.** Between
   `t_ref` and `t_eff` prices move, and index shares are fixed at `t_ref`
   pricing. Drift of 1–3% relative on a name is normal. A cap tested on
   `t_eff` weights will therefore show small breaches by construction; the
   methodology must say which date the cap binds on (recommend: `t_ref`,
   with a monitoring-only check at `t_eff`).
2. **The selection lag is the look-ahead control.** `t_ann − t_sel ≥ 5`
   trading days is the standard buffer that makes the results replicable by
   a fund before they bind.

---

## 6. Universe & eligibility

### 6.1 Screen order is methodology, and it is order-dependent

Screens compose non-commutatively (liquidity-then-size ≠ size-then-
liquidity when both rank-cut). The screen sequence is therefore part of the
config, and the universe builder emits a per-company **screen trace**
(passed/failed each screen, with the value tested and the threshold) —
which is also the evidence pack the committee reviews and the audit trail
BMR wants for input data.

### 6.2 Buffers (the draft's missing stability mechanism)

Rank-based membership without a buffer churns every review. Standard
mechanism: a name enters at rank ≤ `add_rank` and only leaves at rank >
`drop_rank`, with `drop_rank > add_rank`. Same for the thematic screen: a
company enters at exposure ≥ `x%` and exits below `y% < x%`. Buffers are
the single highest-leverage turnover control and cost one config block.

### 6.3 Intra-review events (fast entry / fast exit)

Membership is not only decided at reviews:

- **Fast exit** — bankruptcy, delisting, acquisition completion,
  prolonged suspension: deleted at the last traded price (or zero where
  there is none), divisor adjusted, no replacement by default.
- **Fast entry** — large IPOs, if the methodology allows them (recommend:
  it does not, in v1; defer to the next review).
- **Spin-offs** — the spun entity enters the index temporarily at its
  first traded price and is sold at the next close unless independently
  eligible.

Each of these needs a rule *in config*, not a judgement call at 18:00 on
the day.

### 6.4 Thematic screen: reuse, with a hard constraint

The thematic eligibility input comes from this repo's universe builder, but
under one non-negotiable condition: **the index consumes a frozen, signed,
effective-dated snapshot, never a live query.** An LLM-derived exposure
score that can change between runs is incompatible with determinism. The
contract is a file:

```
taxonomies/<theme_id>/index_snapshots/<t_sel>.json   # company_id, exposure, confidence, run_id, content hash
```

produced by an explicit `arp index freeze-universe` step, approved, and
then immutable. The LLM is upstream of the index boundary; nothing
stochastic crosses it. This mirrors the principle already in force across
this codebase — the model proposes, a deterministic engine computes.

---

## 7. Weighting & constraints

A survey of how MSCI, ISS STOXX and Solactive actually construct their ESG,
thematic and PAB/CTB indices — and a catalogue of the construction approaches
worth supporting, split into screening/selection rules, simple tilt rules,
optimisation formulations and path-dependent approaches — is in
[`INDEX_METHODOLOGY_LANDSCAPE.md`](INDEX_METHODOLOGY_LANDSCAPE.md). Its §7
carries four amendments to this section: an index **state store** for
path-dependent methodologies, the optimiser's **relaxation ladder as versioned
config** rather than error handling, mandatory **floors and ceilings on tilt
multipliers**, and a declared fallback for **absolute-threshold screens that can
empty a sector**. Its §7.4 note that `min_weight` is only a heuristic for
the semi-continuous constraint is now resolved: the real constraint is
available via `solver.enforce_semicontinuous`, and it gives a materially
different index.

### 7.1 Deterministic capping first

Replace the draft's "cvxpy-based capping/redistribution solver" as the
default with an **iterative waterfall**, which is what index providers
actually use and is deterministic by construction:

```
repeat:
    over = { i : w_i > cap_i }
    if over is empty: stop
    for i in over: w_i = cap_i
    excess = 1 - sum(w)
    redistribute excess pro-rata across uncapped names
until no breach or max_iter
```

It converges monotonically, has a closed-form termination proof for a
single uniform cap, and produces identical output on every machine. The
draft's own risk column ("capping algorithm doesn't converge or breaches
its own cap") is largely a solver risk that this design removes.

[`OPTIMIZATION_TOOLING.md`](OPTIMIZATION_TOOLING.md) surveys what is
available if that day comes, and makes the point that matters for scoping:
every constraint an EU PAB or CTB imposes is linear in the weights, so the
regulated core is a QP at worst. The one methodology feature that forces a
mixed-integer programme — and therefore a commercial solver — is a
*minimum weight if held*, which is a disjunction rather than a bound.

The least-squares projection now built is the shape this section
anticipated, and it carries every control listed below: the solver is pinned
per calibration and part of its config hash, tolerances are explicit, every
constraint is re-verified independently of the solver's status, a repeat-solve
test asserts determinism, and failure falls back to the deterministic path
with an exception recorded rather than relaxing anything silently. What it
does *not* restore is cross-machine byte-identity, which is why it is opt-in
and the waterfall remains the default.

Where the convex solver *is* genuinely needed — factor-tilt optimisation,
tracking-error-constrained weighting, multi-constraint problems with an
objective — it becomes an opt-in extra with:

- a pinned solver and solver version, recorded in the run manifest;
- explicit tolerances, and a check that the returned solution satisfies
  every constraint to a stated epsilon (never trust `status == optimal`);
- a determinism test running the same problem 100× and byte-comparing;
- a deterministic fallback if the solver fails, never a silent relaxation.

### 7.2 Regulatory constraints belong in the weighting layer

If the index will back a UCITS fund, the **5/10/40** rule (no issuer above
10%; the sum of issuers above 5% must not exceed 40%) and the ESMA index-
eligibility expectations (sufficiently diversified, adequate market
benchmark, appropriately published) are weighting constraints, not
compliance paperwork. 5/10/40 as a constraint set is a second waterfall
pass, and it interacts with the single-name cap — the interaction must be
tested, since capping to 8% can still breach the 40% aggregate.

If the index is to be labelled an **EU Climate Transition** or **Paris-
Aligned Benchmark**, a further minimum-standards regime applies
(baseline decarbonisation vs. the investable universe, a year-on-year
self-decarbonisation trajectory, mandatory exclusions, and a green-
activity exposure requirement). That is a methodology decision with
material engineering cost — a decarbonisation trajectory constraint makes
weighting path-dependent across reviews, which the current design would
need an explicit state carry-forward to support. Flag it now, before the
weighting engine is written, because retrofitting path dependence is
expensive. *Legal/compliance owns the determination; this is scoping, not
advice.*

---

## 8. Index shares, the divisor, and the calculation engine

This is the section the draft is missing, and it is the core of the system.

### 8.1 Definitions

```
MC_t  = Σ_i  p_{i,t} · s_i · fx_{i,t}          market capitalisation of the index
I_t   = MC_t / D_t                              index level
```

`s_i` — **index shares** — are fixed between rebalances. They are *not*
shares outstanding: `s_i = shares_outstanding × free_float_factor ×
capping_factor`, all as of `t_ref`. Between rebalances, weights drift with
price, which is what makes a cap-weighted index self-maintaining and
low-turnover.

At the base date: choose `I_0` (100 or 1000), compute `D_0 = MC_0 / I_0`.

### 8.2 Weights → index shares (the missing link)

At the effective close, given target weights `w_i` from §7:

```
s_i = w_i · (I_{t_eff} · D_{t_eff}) / (p_{i,t_ref} · fx_{i,t_ref})
s_i = round(s_i, shares_precision)          # policy, fixed in config
D_new = MC_new / I_{t_eff}                  # recomputed AFTER rounding
```

Order matters: rounding first, then deriving the divisor, guarantees the
published shares exactly reproduce the published level. Do it the other way
and the index is off by a rounding residual that compounds.

### 8.3 Divisor adjustment

Any event that changes `MC` without a corresponding investor return must
leave `I` unchanged:

```
D_after = D_before · (MC_after / MC_before)
```

where `MC_before` uses pre-event shares and the prior close, and `MC_after`
uses post-event shares and the adjusted price. This single identity, plus
the treatment table in §9 deciding *which* events qualify, is the whole
divisor engine. The property test writes itself: for every event,
`I_before == I_after` to the published precision.

### 8.4 Total return and net return

```
GTR_t = GTR_{t-1} · (MC_t + Σ_i d_{i,t} · s_i · fx_{i,t}) / MC_{t-1}
NTR_t = NTR_{t-1} · (MC_t + Σ_i d_{i,t} · (1 - τ_{c(i),t}) · s_i · fx_{i,t}) / MC_{t-1}
```

with `d_{i,t}` the gross dividend per share going ex on `t`, and
`τ_{c,t}` the withholding rate for issuer country `c` in force on `t`
(bitemporal, §4). Dividends are reinvested across the whole index at the
ex-date close — state this convention explicitly in the methodology, since
the alternative (reinvest into the paying name) is also defensible and
produces a different series.

---

## 9. Corporate-action treatment

Config-driven, one row per action type. `Δprice` = adjust the prior close;
`Δshares` = change index shares; `ΔD` = divisor changes.

| Action | Δprice | Δshares | ΔD | Notes |
|---|---|---|---|---|
| Ordinary cash dividend | no (PR falls naturally) | no | no | Reinvested in GTR/NTR only |
| Special dividend | yes (close − amount) | no | **yes** | Treated as capital return; threshold in config decides "special" |
| Stock split / bonus | yes (÷ ratio) | yes (× ratio) | no | MC unchanged by construction — a good invariant test |
| Rights issue | yes (theoretical ex-rights price) | yes | **yes** | TERP formula fixed in config |
| Share-count change ≥ threshold | no | yes | **yes** | Effective at the stated date |
| Share-count change < threshold | no | deferred | no | Applied at the next review — prevents constant churn |
| Free-float factor change ≥ threshold | no | yes | **yes** | Same threshold logic |
| Spin-off | yes (parent) | yes (both) | **yes** | Spun entity added at first price, sold per §6.3 |
| M&A, cash consideration | — | delete target | **yes** | Deleted at offer/last price on completion |
| M&A, stock consideration | — | acquirer shares up, target deleted | **yes** | Exchange ratio from the CA feed |
| Bankruptcy / delisting | last price or 0 | delete | **yes** | Zero only where no price exists |
| Suspension | carry last close | no | no | Hard-fail if stale > `max_stale_days` |
| Ticker / ISIN / domicile change | no | no | no | Reference only — but domicile change moves `τ` |

Every applied action is written to the corporate-action journal with the
divisor before and after, which is the artifact that makes an index
continuity dispute resolvable in minutes rather than days.

---

## 10. Determinism: what "byte-identical" actually requires

The draft states the requirement. These are the mechanics that deliver it,
and each is cheap only if designed in:

1. **Locked dependencies** — `uv.lock` committed; the lock hash in the run
   manifest. A transitive numpy bump can move the last digit.
2. **Fixed rounding policy** — stated decimal precision for index shares,
   weights, and published levels, applied at stated points (§8.2), never
   incidentally via formatting.
3. **Deterministic summation** — sum market caps in a fixed sort order
   (by `security_id`), or use `math.fsum`. Float addition is not
   associative; a set-ordering change moves the result.
4. **No unordered iteration** — no dependence on `set` or pre-3.7 dict
   ordering anywhere in the numeric path; enforced by review and a lint
   rule.
5. **No wall-clock or environment reads** in the numeric path. The run's
   `knowledge_date` is an input, never `date.today()`.
6. **Pinned solver, or no solver** (§7.1).
7. **Run fingerprint** — SHA-256 over (input-table hashes + resolved config
   hash + code version) → SHA-256 of the output. Every run records both.
   Re-running a past review and getting a different output hash is a
   build-breaking test, not a discussion.
8. **A golden-run regression suite** — a stored set of historical runs with
   their expected output hashes, re-executed in CI. This repo already has
   the pattern (`arp golden-set run`, `backend/arp/golden_set/`); reuse the
   runner shape.

---

## 11. Validation

### 11.1 Acceptance thresholds for reference replication

The draft's gate needs numbers. Proposed, for committee ratification:

| Check | Threshold |
|---|---|
| Daily return difference vs. reference | ≤ 0.5 bp on ≥ 99% of days; max ≤ 2 bp |
| Annualised tracking difference | ≤ 2 bp over the full test window |
| Constituent set agreement | ≥ 99.5% of (date, security) cells exact; **every** mismatch individually explained in writing |
| Weight agreement at each effective date | ≤ 1 bp per name |
| Divisor continuity across every CA | index level unchanged to published precision |

The "every mismatch explained" row is the one that finds real bugs. A 0.4%
disagreement is not noise; it is usually one wrong free-float factor or one
missing special dividend.

### 11.2 Where the reference data comes from

Replicating a licensed index needs its *constituent history*, which is
usually a separate and expensive licence. Two cheaper routes, in order of
preference:

1. **A tracker ETF's published daily holdings** as ground truth — daily
   weights, free, and this repo already parses ETF holdings files
   (`research/taxonomy_sources/etf_holdings.py`, the ETF-overlap feature).
   It is the fund, not the index, so expect small cash/sampling
   differences — tolerances in §11.1 should be loosened by roughly 2× for
   this route, and the reason recorded.
2. **A published-methodology index with an obtainable constituent list**
   (a national blue-chip index), replicated from primary sources.

Confirm the licence position before Phase 1 — this is the draft's own
"undersized data licence discovered mid-build" risk, and constituent
history is the specific line item that gets missed.

### 11.3 Look-ahead bias: architectural, not procedural

Make it impossible rather than forbidden:

- The backtester receives a `knowledge_date` and can only read through the
  bitemporal accessor (§3.1). No other read path exists — enforced by
  keeping the raw-file reader private to the storage package.
- **Future-row injection test**: run a backtest, record the output hash;
  insert rows with `knowledge_date` after the run's dates, including
  restatements of values the run used; re-run; assert the hash is
  unchanged. This is the single most valuable test in the suite, and it
  only works if §3.1 was built first — which is why it cannot be a
  Phase 5 activity.

### 11.4 Corporate-action completeness

The check that catches missing CAs without a second vendor: any overnight
return exceeding `k` (e.g. 20%, or `n`σ of the name's trailing vol) with no
corporate action on file is a **hard block** pending review. Most missing
special dividends and unadjusted splits present exactly this way. If a
second CA feed is licensed, add a straight diff of the two feeds' event
sets as a second control.

### 11.5 Fail loud needs an exception path

"Blocks the run" without a documented override route means someone will
edit a Parquet file at 19:00 on a review date. The override path:
a named approver records an exception (reason, scope, expiry) in the
governance store; the run proceeds; the exception is stamped into the run
manifest and appears on the committee pack. Exceptions are visible,
expiring, and counted — an exception rate trending up is itself a
reportable metric.

### 11.6 Test types per package

| Package | Characteristic tests |
|---|---|
| `data` | schema validation; bitemporal accessor returns the correct belief; restatement does not mutate history |
| `reference` | calendar edge cases (half-days, DST, exchange holidays); FX fixing holiday fallback |
| `universe` | screen order dependence; buffer hysteresis (a name at rank 100 stays in); screen trace completeness |
| `weighting` | cap never breached (property); weights sum to 1 ± ε (property); waterfall converges (property, random inputs); 5/10/40 interaction |
| `calc` | divisor continuity per CA type (table-driven); worked examples from published methodology documents as golden vectors; shares-rounding residual = 0 |
| `backtest` | future-row injection; determinism across runs; turnover matches a hand-computed fixture |
| `governance` | audit log is append-only and tamper-evident; config effective-date resolution |

---

## 12. Governance: the BMR reality check

### 12.1 First, the prior question

BMR applies to a benchmark that is *used* — to determine amounts payable
under a financial instrument, to measure a fund's performance for tracking
or fee purposes, or to define an asset allocation. An internal research
index that informs discretionary decisions and is not published as a
benchmark may sit outside it (A1). **This determination belongs to
compliance and should be obtained in Phase 0**, because the answer changes
the build by roughly the margin in §20. The draft asserts the exposure
without asking the question, which risks over-building for an internal
tool — or, worse, under-building for a published one.

### 12.2 If it is in scope, the audit log is a fraction of it

Artifacts required beyond `audit_log.py`:

- **Benchmark statement** per index (what it measures, its limitations,
  discretion and when it is exercised, potential cessation).
- **Methodology document**, published, with a defined change and
  consultation procedure.
- **Oversight function** — a committee with defined membership, terms of
  reference, and minuted decisions, separate from the people running the
  calculation.
- **Input-data policy** — sources, hierarchy, what constitutes sufficient
  and reliable data, expert-judgement policy.
- **Correction policy** (§12.4).
- **Cessation / transition plan** — what happens to users if the index
  stops.
- **Records** — inputs, outputs, discretion exercised, minutes, retained
  (5 years is the commonly applied period).
- **Administrator authorisation / registration**, or delegation of
  calculation and administration to an authorised administrator — which is
  a genuine strategic option and the main reason the standalone-repo
  variant in §1 might win.

Engineering owns: the audit log, the run manifests, the methodology-config
versioning, the exception register, the correction workflow, and rendering
the methodology document from the config so that the document and the code
cannot diverge (`docs/methodology/<index>.md` generated, not hand-written —
this is a small piece of work with an outsized governance payoff).

### 12.3 Build it from day one — the draft says so, its own table doesn't

The draft's governance note says build it alongside Phases 1–2; the phase
table puts it at Phase 6. The table is wrong. Split it: **audit primitives
(append-only event log, run manifests, config versioning) are Phase 1
cross-cutting work**; committee workflow, benchmark statement and
methodology rendering stay late (§15).

### 12.4 The correction policy nobody writes until they need it

Define before go-live: what happens when a price or CA error is found
*after* publication. Industry norm is a threshold policy — below a stated
impact, the error is noted but the published series is not restated; above
it, a correction is published within a stated window with notification to
users. Implementation: published levels are immutable; a correction writes
a new record with `restatement_of` and a reason, and both series remain
queryable. Without this, the first production error becomes an ad-hoc
decision made under pressure.

---

## 13. Information barriers (absent from the draft)

Pending constituent changes between `t_sel` and `t_ann` are market-sensitive:
an ahead-of-announcement list of additions and deletions is tradeable
information. Controls:

- Pro-forma and pending-rebalance artifacts are written to a separate
  restricted path with its own access control, never to the general output
  store.
- **The API and file distribution must not serve constituents with
  `effective_date > today`.** This is a hard rule in the serving layer,
  with a test, not a convention.
- Access to pending packs is logged (who, what, when), which is also a
  BMR records item.
- The backtest/research path reads only published, effective data by
  default; reading pending data requires an explicit, logged flag.

---

## 14. Distribution: files first, API second

The draft's Phase 7 ("lowest-risk phase, can slip") is right about the API
and wrong about distribution. PM, fund accounting and risk consume *files
on a schedule*, and that contract is what actually blocks them:

- `levels_<index>_<date>.csv` — PR/GTR/NTR, divisor, index MC.
- `constituents_<index>_<date>.csv` — security_id, ISIN, name, index
  shares, price, fx, weight, capping factor.
- `ca_journal_<index>_<date>.csv`.
- A `.sha256` sidecar and a manifest per delivery; a stated publication
  deadline (e.g. T+0 by 20:00 CET) and a stated late/failure procedure.

Schema-stable, versioned, additive-only columns. The FastAPI service
(`backend/arp/api/routers/index.py`, following this repo's existing router
pattern) then serves the same data for the UI and ad-hoc queries, and is
genuinely low-risk once the files exist. Real-time/intraday dissemination
is explicitly out of scope (A4) — it is a different system with different
latency and failover requirements, and pretending otherwise is how index
projects double in size.

---

## 15. Revised build sequence

The key change: a **walking skeleton** — one index, one methodology, end to
end, thin — before any phase is built out. It makes the draft's validation
gate achievable, surfaces integration bugs when they are cheap, and gives
the committee something to look at in week 6 rather than week 16.

| Phase | Duration | Deliverable | Change vs. draft |
|---|---|---|---|
| **0 — Scope & decisions** | 1 wk | Data + constituent-history licence confirmed; BMR determination (§12.1); target methodology; repo decision (§1); acceptance thresholds ratified (§11.1) | Narrowed; BMR question and constituent-history licence added; thinner because §1 removes the stack decisions |
| **1 — Bitemporal store + reference data + audit primitives** | 3–4 wks | Prices, reference, CAs, FX, tax, calendars, all bitemporal; pandera schemas; append-only audit log, run manifests, config versioning | Audit primitives pulled forward from Phase 6 (§12.3); reference data (§4) added |
| **2 — Universe & eligibility** | 2 wks | Screens, buffers, screen trace, frozen thematic snapshot (§6.4) | Buffers and trace added; shorter because the thematic screen is reused, not built |
| **2.5 — Walking skeleton** ⭐ | 2 wks | Uncapped free-float cap-weighted index, end to end: shares → divisor → PR level → constituent file. **Gate: replicates the reference index to §11.1 thresholds.** | **New.** Makes the draft's impossible gate possible |
| **3 — Corporate actions & return variants** | 3 wks | Full §9 treatment table, GTR/NTR, CA journal, CA-completeness check (§11.4) | **New as a distinct phase** — was buried inside draft Phases 1 and 4 |
| **4 — Weighting & constraints** | 3 wks | Deterministic waterfall capping, 5/10/40, alternative schemes; optional cvxpy extra | Deterministic path replaces solver-first (§7.1) |
| **5 — Backtesting & validation** | 2–3 wks | Historical replication, look-ahead injection test, determinism suite, turnover/capacity analytics, golden-run CI | Look-ahead test moves from "risk" to a built control |
| **6 — Governance & committee workflow** | 2 wks | Committee pack generation, exception register, generated methodology document, correction workflow, benchmark statement template | Narrowed — primitives already delivered in Phase 1 |
| **7 — Distribution** | 1–2 wks | File contract + publication schedule, then the API router, then UI | Files promoted ahead of the API (§14) |

Total: **19–22 weeks** for Track A (§20). The added time is Phase 2.5 and
the CA phase; the saved time is Phases 0, 2 and 6, because of reuse and
because governance primitives stop being a retrofit.

Phase-3-and-later work on a *second* methodology (factor tilt, optimisation-
based capping) adds 3–4 weeks, as the draft says — but only if §7.1's
determinism controls are in place first.

---

## 16. Dependencies, revised

| Package | Purpose | Change |
|---|---|---|
| `polars` | Core dataframe work | Keep. Single engine, not "polars/pandas" — pick one; mixing them doubles the null/dtype edge cases |
| `pyarrow` + `duckdb` | Parquet storage + query | **Added** — the concrete form of the point-in-time store (§3.2) |
| `pandera` | Schema validation at every boundary | Keep; pin a version with the polars backend and use it in lazy mode |
| `exchange_calendars` | Trading calendars, holidays, half-days | **Added** — a hand-rolled calendar is a guaranteed bug source |
| `pydantic` | Config + methodology parameter validation | Keep; already this repo's convention |
| `sqlalchemy` + PostgreSQL | Governance tables only, not facts | Narrowed (§3.2); the `postgres` extra already exists here |
| `numpy` / `scipy` | Numerics; solvers where needed | Keep |
| `cvxpy` | Optimisation-based schemes only | **Demoted to an optional extra** with the §7.1 controls |
| `pytest` + `hypothesis` | Unit + property tests | Keep — property tests are the right tool for cap/weight/divisor invariants |
| ~~`pyfolio-reloaded`~~ | Backtest analytics | **Dropped from the audit path.** Turnover, drawdown and capacity are ~150 lines you must be able to defend line-by-line; keep it as an optional exploratory extra only |
| `FastAPI` + `uvicorn` | Distribution API | Keep — already present in this repo |
| `uv` | Dependency management + lockfile | Keep; the lock hash is a determinism input (§10) |

Turnover, defined explicitly since it is a reported number:
`one-way turnover = 0.5 · Σ_i |w_i^{new} − w_i^{drifted}|`, where
`w^{drifted}` are pre-rebalance weights at the effective close, *not* the
previous target weights. Capacity: days-to-trade at a stated % of ADV, per
name, at a stated AUM.

---

## 17. Repository layout

Inside this repo, preserving the draft's boundaries as the future extraction
seam (§1):

```
backend/arp/index/
├── contracts.py              # shared typed models — the seam between sub-packages
├── reference/                # calendars, FX, withholding tax, CA taxonomy   (§4)
├── data/
│   ├── loaders/              # vendor feed connectors (arp/ingestion/ pattern)
│   ├── bitemporal.py         # the single read accessor                      (§3.1)
│   └── schemas.py            # pandera schemas
├── universe/
│   ├── screens.py            # size, liquidity, float, thematic              (§6)
│   └── builder.py            # + screen trace
├── weighting/
│   ├── schemes.py
│   ├── capping.py            # deterministic waterfall                       (§7.1)
│   └── optimize.py           # optional cvxpy path
├── calc/
│   ├── index_shares.py       # weights → shares                              (§8.2)
│   ├── divisor.py            # the §8.3 identity
│   ├── corporate_actions.py  # the §9 treatment table
│   └── index_calculator.py   # PR / GTR / NTR
├── backtest/
│   ├── backtester.py
│   └── analytics.py          # turnover, capacity, drawdown — ours           (§16)
├── governance/
│   ├── audit_log.py          # Phase 1, not Phase 6                          (§12.3)
│   ├── methodology_config.py # effective-dated config resolution             (§3.4)
│   ├── exceptions.py         # the override register                         (§11.5)
│   └── render.py             # config → methodology document                 (§12.2)
└── pipelines/
    └── run_review.py         # universe → weighting → calc, one review

backend/arp/api/routers/index.py     # Phase 7, existing router pattern
backend/arp/cli.py                   # + `arp index ...` commands
configs/methodologies/<index>.yaml   # versioned, effective-dated             (§3.4)
indices/                             # file-based output store, append-only
  <index_id>/levels/ constituents/ divisors/ ca_journal/ manifests/
  <index_id>/pending/                # RESTRICTED — pro-forma packs           (§13)
docs/methodology/<index>.md          # generated
```

`backend/arp/index/` depends outward on `arp.storage`, `arp.schemas.common`
and the frozen universe snapshot only. Nothing in `arp` depends inward on
`arp.index`. That is the extraction seam, and it should be enforced by an
import-linter rule in CI so it survives contact with deadlines.

---

## 18. Reuse map

| Need | Reuse from this repo | New |
|---|---|---|
| Thematic eligibility screen | `research/` Advocate/Opposing/Adjudicator pipeline + `taxonomies/` | Freeze/sign/effective-date snapshot step (§6.4) |
| Sector/industry classification | `research/standards_mapping/` (GICS/NACE/NAICS/SIC) as-is | — |
| ISIN → issuer identity | `portfolio/entity_resolution.py`, `SecurityResolution` | Index-specific review gate (an unresolved ISIN blocks a review) |
| Append-only audit storage | `engagement_store.py` (`record.json` + `events.jsonl`), `DataPointObservation` | `governance/audit_log.py` with run-manifest fingerprints |
| Checkpointed, resumable runs | `storage/run_store.py` | Review-run state machine |
| Review queue for low-confidence items | `orchestration/review_queue.py` | Data-quality blocks + exceptions routed into it (§11.5) |
| Golden-set regression runner | `golden_set/runner.py` shape | Golden *runs* keyed on output hash (§10.8) |
| Reference index ground truth | `research/taxonomy_sources/etf_holdings.py` | Comparison harness + tolerance report (§11.2) |
| Config validation | pydantic + `config.py` conventions | Effective-dated methodology resolution (§3.4) |
| API + CLI + frontend shell | FastAPI routers, Typer CLI, React app | `routers/index.py`, `arp index`, an index page |
| Point-in-time bitemporal store | — | New (§3) |
| Calendars, FX, withholding tax | — | New (§4) |
| Index shares, divisor, CA treatment, level engine | — | New (§8, §9) — the irreducible core |
| Capping / constraints | — | New (§7) |
| Backtester + index analytics | — | New (§5, §16) |

Roughly a third of the draft's scope is already here in production form.
The two-thirds that is genuinely new is the index mechanics — which is also
the two-thirds the draft specifies least.

---

## 19. Decisions needed before Phase 1

1. **BMR determination** (§12.1) — internal research index or published
   benchmark? Drives ~10–14 weeks of engineering and the org's
   administrator question. *Owner: compliance.*
2. **Licence scope** — prices, reference, corporate actions, free float,
   *and constituent history for the reference index* (§11.2). The last one
   is the one usually missed. *Owner: data sourcing.*
3. **Methodology** — single cap-weighted thematic index, or a family?
   Family means the weighting engine is built for plurality from the start;
   [`INDEX_METHODOLOGY_LANDSCAPE.md`](INDEX_METHODOLOGY_LANDSCAPE.md) §6 is the
   menu that choice is made from, and its §7.2 the build order.
   Any CTB/PAB labelling ambition must be declared now (§7.2), because
   decarbonisation trajectories make weighting path-dependent.
4. **Index currency, FX fixing source, and the withholding-tax table owner**
   (§4).
5. **Acceptance thresholds** (§11.1) — ratified by whoever will sign off
   the index, before the work is done rather than after.
6. **Repo decision** (§1) — integrated (recommended) or standalone, which
   partly follows from 1.
7. **Base date and base level**, and whether history is backfilled to the
   base date or the index starts live (§8.1).
8. **Who reviews the numbers.** A single engineer producing index levels
   that other people trade against is a control weakness independent of
   code quality; a named second reviewer for methodology and production
   output should be part of the plan, not an afterthought.

---

## 20. Effort, re-estimated

| Track | Scope | Estimate |
|---|---|---|
| **A — Internal research index** (A1) | §15 in full: one methodology, bitemporal store, full CA handling, PR/GTR/NTR, deterministic capping, validated backtest, audit trail, file distribution | **19–22 weeks**, one engineer |
| **A+ — Second methodology** | Factor tilt or optimisation-based capping, on top of A | **+3–4 weeks** (as drafted) |
| **B — Published benchmark under BMR** | A, plus correction workflow at production grade, cessation plan, oversight tooling, dissemination SLA and failover, a parallel-run period against the incumbent, external audit support | **+10–14 weeks** engineering, plus non-engineering authorisation time that typically dominates the calendar |

The draft's 16–20 weeks is defensible for Track A *if* the thematic screen
is reused rather than rebuilt (§1) and if BMR turns out to be Track A's
lighter regime. It is not achievable for Track B, and the draft's 1–2 weeks
for governance is the specific line that does not survive contact with
§12.2.

Three things drive this schedule more than engineering throughput, and all
three are organisational: **licence delivery** (including constituent
history), **corporate-action data coverage**, and **the BMR
determination**. All three are Phase 0 items for exactly that reason.

---

## 20b. What the rule engine already settles

Four things in this plan were open questions when it was written and are now
decided in code, because building them answered them:

1. **Path dependence needs an index state object**, not a config flag. A
   review is `f(data, spec, state[t-1])`: `IndexState` carries the
   decarbonisation base and base date, required vs. achieved metric, the
   shortfall owed under the compensation rule, which of the two
   simultaneous reduction constraints currently binds, the divisor and
   level, and the prior weights and members that turnover and selection
   buffers need. It is written per review alongside the result.
2. **PAB/CTB compliance does not require a licensed risk model.** The
   trajectory is met by solving a single bounded exponential tilt with the
   constraint set applied *inside* the objective, by bisection. It is
   deterministic, needs no covariance matrix, and lands on the target
   exactly. Composing tilt and capping inside one solve rather than
   alternating them is what makes it converge -- alternating hands weight
   straight back to the names the tilt just took it from.
3. **Infeasibility is routine and must be diagnosed, not iterated.** When a
   target sits below what the constraint set can reach, the engine reports
   the frontier -- the lowest weighted average attainable by filling from
   the best names at the single-name cap -- and names the three ways out
   (relax the cap, widen the universe, lower the ambition). The same
   applies to an infeasible group cap, which is detected up front instead
   of oscillating between groups.
4. **Every relaxation and override is a recorded exception**, carried on the
   review result and shown in the UI, exactly as section 11.5 requires. The
   `block` / `fail` / `pass` policy on each rule's missing-value handling is
   part of the calibration, so an override is a versioned, diffable
   decision rather than an edit to a data file.

## 21. Recommended next step

Unchanged in spirit from the draft, sharpened in content. Before Phase 0
closes, obtain in writing:

1. the **BMR determination** (§12.1);
2. the **licence scope including reference-index constituent history**
   (§11.2);
3. the **methodology target** — single index or family, and any CTB/PAB
   labelling ambition (§7.2).

Then build Phase 1 and Phase 2.5 as one continuous push: a thin,
end-to-end, bitemporal, reference-replicating cap-weighted index. Nothing
after that is safe to estimate until that gate is green, and nothing before
it is worth optimising.
