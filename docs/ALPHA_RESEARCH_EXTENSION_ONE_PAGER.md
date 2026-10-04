# Alpha Research Extension: one-pager

**Status:** proposal, nothing built. **Extends:** #11 Strategy Replication, #12 Emerging Themes, #2 Taxonomy Library, #16 Index Construction.
**Sources:** the "Agentic Quant Research Pipeline" spec (code unusable, four ideas kept), STOXX whitepaper *From narrative to signal* (June 2026), Huang & Fan *Beyond Prompting* (arXiv 2603.14288).

## Problem

ARP proves a result is **real** (HLZ-scaled t-hurdle, DSR, PBO). It cannot yet show a result is **new** (not a repackaged known factor) or **honestly counted** (`num_trials_attempted` is self-reported). Narrative inputs (themes, sentiment) never reach the backtest engine as one flow.

## Four ideas

| # | Idea | What it adds | Reuses |
|---|---|---|---|
| 1 | **Factor Zoo registry + incremental-alpha gate** | Accepted strategies' return series are stored. A candidate is regressed on price momentum, standard factors and the registry; the gate is the residual-alpha t-stat. Correlation alone is not accepted. | `replication/backtest_engine.py` returns, `compare.py` hurdle |
| 2 | **Trial ledger** | Every attempt, including rejected ones, is appended with spec hash, family, verdict, reason. `num_trials_attempted` is read from the ledger. | `StrategySpec.num_trials_attempted`, `deflated_sharpe.py` |
| 3 | **Narrative-to-signal bridge** | Turns theme or company narrative scores into a point-in-time signal panel the #11 engine can backtest. | `sentiment_scoring.py`, `emerging_themes/scoring.py`, `company_exposure.py`, `SignalType.TEXT_SENTIMENT` |
| 4 | **IPS-constrained allocation** (optional) | Return/Risk debate proposes weights across registry factors; cvxpy solves; plain Python re-verifies every IPS constraint. | debate pattern in #1, `index/optimize.py` |

## Narrative momentum: reference definition

Taken from STOXX: a **quarterly, issuer-level ordinal score, -2 to +2**, of how positive or negative public coverage of a company is. Five categories, equal-weighted, each with a confidence and a grounded citation. It is a sentiment *level*, so it maps onto the existing `TEXT_SENTIMENT` path. A change-over-lookback version is an optional variant, never the default.

| STOXX practice | ARP treatment |
|---|---|
| Ordinal -2..+2, fixed thresholds | Adopt: fewer wording-drift effects than continuous scores |
| Burst consistency: rerun identical config 20-30 times | Adopt as a gate on the scoring stage |
| LLM-as-judge calibrated on human pass/fail | Adopt for sampled QA, human rubric first |
| Scores skew to +1, vary by sector | Score **relative to sector peers** (cohort normalisation as in Decision Studio) |
| Live Google search with a before-date filter: 7-15% leakage remains | **Do not copy.** Score stored, dated documents (filings, archives): point-in-time by construction, narrower coverage |
| Model and prompt versions | Pin both in the snapshot; a model swap is a new signal version |

Their own gap, which we close: they show a 0.4 correlation with price momentum but no test of alpha **after** removing it. Narrative tone often follows returns, so idea 1 is mandatory for this signal.

## Two entry points, one object

Both start a `SignalCandidate` (family id, origin, signal definition, snapshot ref). Everything after the bridge is identical.

```
 A. THEME LEVEL                         B. COMPANY LEVEL
 ratified Taxonomy theme or             predefined topic, e.g. "narrative momentum"
 EmergingThemeCandidate                 (named SignalDefinition, per company)
        |                                        |
        v                                        |
 theme time series (relevance, velocity,         |
 action_score per period)                        |
        |                                        |
        v                                        |
 company exposure (company_exposure.py,          |
 universe builder) -> company-level score        |
        \_______________________  _______________/
                                \/
   3  Bridge: ordinal scores, sector-relative, frozen, effective-dated, lagged
                                |
              #11 deterministic backtest (IS / OOS declared first)
                                |
        2  Ledger: count the trial in this family (+ global)
                                |
   Gate: HLZ hurdle(ledger count) + DSR + PBO + 1  incremental alpha
                                |
        PROVISIONAL until forward data  ->  human ratifies  ->  1 registry
                                |
                    4 allocation (optional, reads registry)
```

- **A (theme level)** asks whether a theme predicts returns; its company exposures set the long and short legs.
- **B (company level)** asks whether a company-level narrative signal predicts returns.
- Variants share a **family id**, so the ledger counts them together and the hurdle rises honestly.

## Orchestration

A **study** is one manifest (`studies/<id>/study.json`) listing stages, each stage a normal ARP run (`JobManager`, `RunStore`, resumable batches). Stages hand off by `run_id` + content hash; a stage whose input hash is unchanged is skipped, which is the resume mechanism. A new study-level status `awaiting_review` pauses at human gates. Standing agents may *propose* a study (for example when #12 promotes a theme); a person approves before any LLM spend. The ledger entry is written when the backtest **starts**, so crashed or abandoned attempts still count.

## Rules that carry over from ARP

1. **Zero LLM in the numbers.** The LLM only labels text. Scores enter as frozen snapshots; the backtest is deterministic.
2. **Point-in-time.** A theme or taxonomy applies only at the version in force on the date. Today's definition on past dates is look-ahead and is rejected.
3. **Propose, never apply.** Registry entry needs a recorded human ratification with a reason.
4. **Ledger is append-only.** Rejected and failed attempts stay.
5. **Incremental alpha is a real regression** of long-short returns on actual price momentum, standard factor series and registry returns. Fewer than 36 monthly observations returns INSUFFICIENT_DATA, never a pass.
6. **Pre-committed split.** IS/OOS dates are fixed in the snapshot before the backtest runs and never changed (as in Huang & Fan).
7. **Provisional until forward.** Both papers admit LLM training data can postdate the test window, and this cannot be removed from a historical backtest. A candidate stays `PROVISIONAL` until it has a set number of forward quarters; only then can it be ratified.
8. **Costs are modelled, not assumed.** Turnover-dependent costs plus borrow where shorting; a flat 3 bps is not accepted (Huang & Fan report ~110% daily turnover at that cost).

## Evidence from the papers that shapes the gates

- Huang & Fan: of 12 factors that passed their in-sample gate, only 5 clear their own |t| > 3 out of sample (CAPM alpha, Exhibit 8). A gate that cannot be re-tested out of sample is not enough, so idea 1 and rule 7 apply to discovered factors too.
- They claim the gate approximates DSR but report no DSR and no trial count. ARP already has both; the ledger supplies the count.
- All 12 of their factors are turnover or flow variants, with no reported pairwise correlation. The registry reports it.
- STOXX: all results are simulated, no t-stats, prompt tuned over "several iterations" on the same sample. Treat as a design reference, not as evidence of alpha.

## Phasing

| Phase | Scope | Effort | Depends on |
|---|---|---|---|
| P1 | Study manifest + ledger + registry + incremental-alpha gate, wired into `compare.py`; CLI `arp alpha ...`; one test per gate | 4-5 days | nothing |
| P2 | Bridge, entry B first (narrative momentum per STOXX definition, over stored documents), then entry A | ~1 week | P1, dated document history |
| P3 | Allocation track with IPS schema | 2+ weeks | P1, macro data, a user-defined IPS |
| P4 (optional) | Factor discovery over a **bounded grammar** of whitelisted operators, evaluated deterministically (no code execution, so no sandbox) | 1-2 weeks | P1; only if novel-factor discovery is wanted |

Ship P1 alone and it already improves #11.

## Reproducing the STOXX test

Their real-world setup (maximise signal exposure, long-only, 1% tracking error, 5% one-way turnover, sector +/-2%, beta 0.98-1.02) is a convex programme that `index/optimize.py` already solves. Once P2 gives a score panel, the comparison against a price-momentum index is a configuration, not new code.

## Open questions

1. **History.** Backtesting needs dated documents for several years. Filings and EDGAR full-text give history; news archives (GDELT) are noisier. Is filings-plus-archives coverage acceptable, given it is narrower than STOXX's web search?
2. **Benchmark factors.** Is a vendor factor series (for example Fama-French) available, or is the registry plus price momentum the only reference at first?
3. **Forward window.** How many forward quarters before a provisional candidate can be ratified?
4. **Registry storage.** Files under `alpha/` like `indices/`, or Postgres via the existing optional extra?
5. **Is P3 or P4 in scope?** P3 needs a user-defined IPS; P4 is only worth it if new-factor discovery is a goal.
