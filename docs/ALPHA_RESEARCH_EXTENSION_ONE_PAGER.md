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

## Three entry points, one object

All three start a `SignalCandidate` (family id, origin, signal definition, snapshot ref). Everything after the bridge is identical.

```
 A. THEME LEVEL            B. COMPANY LEVEL            C. PAPER LEVEL
 ratified Taxonomy theme   predefined topic, e.g.      paper -> paper_discovery ->
 or EmergingThemeCandidate "narrative momentum"        spec extractor + verifier
        |                  (named SignalDefinition)    -> StrategySpec + reported
        v                           |                    performance
 theme time series                  |                         |
 (relevance, velocity,              |                         |
 action_score per period)           |                         |
        v                           |                         |
 company exposure -> company        |                         |
 score (company_exposure.py,        |                         |
 universe builder)                  |                         |
        \__________________  _______/                         |
                           \/                                  |
   3  Bridge: ordinal scores, sector-relative, frozen,          |
      effective-dated, lagged  (builds the spec)                |
                           \___________________  ______________/
                                               \/
              #11 run_replication: deterministic backtest (IS / OOS declared first)
                C also gets the REPLICATED / NOT_REPLICATED verdict vs the paper
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
- **C (paper level)** is the existing #11 flow: a published strategy becomes a spec, is replicated, and its result enters the ledger and registry. Its family is the paper, so a paper's variants are counted together.
- **#11 is also the engine for A and B** (stage S5), and the **source of the benchmark factors**: replicate momentum, value and size first and store them as the first registry entries, so the incremental-alpha gate uses ARP's own universe and calendar instead of a vendor series.
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
8. **Verdict without a paper.** `compare.py` currently needs the paper's reported performance. For A and B it becomes optional: the verdict then rests on the hurdle, DSR and PBO alone.
9. **Costs are modelled, not assumed.** Turnover-dependent costs plus borrow where shorting; a flat 3 bps is not accepted (Huang & Fan report ~110% daily turnover at that cost).

## Frontend: one "Alpha Research" page

One sidebar item (under **Research**), one page, tabs that follow the process. It reuses the tab pattern of Decision Studio and the review controls of the Review Queue; the existing Strategy Replication page stays as the paper-level workbench and is linked from here. A header above the tabs always shows the selected **study**: entry (A/B/C), family, stage stepper, status, LLM cost so far.

| Tab | Shows | Reuses | Phase |
|---|---|---|---|
| **Studies** | List and start: pick entry A (theme), B (topic), C (paper); status, cost, family, pending items | `FlowRuns`, `DateSelector` | P1 |
| **Signal** | Narrative-momentum config, score distribution by sector, burst-consistency result, sampled judge QA with grounded citations | `BarChart`, `CitationList`, `ConfidenceBadge` | P2 |
| **Backtest** | Declared IS/OOS split, bucket returns, regime split, costs and turnover; for C, replication verdict vs the paper | `LineChart`, StrategyReplication result views | P1 |
| **Gate** | Hurdle and the trial count behind it, DSR, PBO, incremental-alpha table, verdict, PROVISIONAL status and forward-quarter counter | `ConfidenceBadge`, tables | P1 |
| **Ledger** | Append-only attempts per family, filters by verdict and reason; rejected attempts stay visible | `AuditLogView` | P1 |
| **Registry** | Ratified factors, pairwise correlation matrix, ratify / reject with a required reason | `ReviewControls`, `ConfirmDecision`, `LevelOverrides` pattern | P1 |
| **Allocation** | IPS constraints and verified weights | `PersistentSelectionPane` | P3, hidden until built |

Rules for the page, from `PRODUCT.md`: it is screen-shared in committees, so the Gate and Registry tabs must read cleanly on a wide screen; it is also checked on phones, so **Studies** (status, pending items) and ratification work at phone width, while dense tables may scroll. Nothing flagged is shown as final until a person ratifies it. API: one new router `api/routers/alpha.py` (studies, ledger, registry, ratify), registered like the others.

## Evidence from the papers that shapes the gates

- Huang & Fan: of 12 factors that passed their in-sample gate, only 5 clear their own |t| > 3 out of sample (CAPM alpha, Exhibit 8). A gate that cannot be re-tested out of sample is not enough, so idea 1 and rule 7 apply to discovered factors too.
- They claim the gate approximates DSR but report no DSR and no trial count. ARP already has both; the ledger supplies the count.
- All 12 of their factors are turnover or flow variants, with no reported pairwise correlation. The registry reports it.
- STOXX: all results are simulated, no t-stats, prompt tuned over "several iterations" on the same sample. Treat as a design reference, not as evidence of alpha.

## Phasing

| Phase | Scope | Effort | Depends on |
|---|---|---|---|
| P1 | Replicate momentum / value / size and seed the registry; study manifest + ledger + incremental-alpha gate wired into `compare.py` (paper optional); CLI `arp alpha ...`; page with Studies, Backtest, Gate, Ledger, Registry tabs; one test per gate | ~9 days (5 backend, 4 frontend) | nothing |
| P2 | Bridge and Signal tab, entry B first (narrative momentum per STOXX definition, over stored documents), then entry A | ~1.5 weeks | P1, dated document history |
| P3 | Allocation track with IPS schema, plus Allocation tab | 2+ weeks | P1, macro data, a user-defined IPS |
| P4 (optional) | Factor discovery over a **bounded grammar** of whitelisted operators, evaluated deterministically (no code execution, so no sandbox) | 1-2 weeks | P1; only if novel-factor discovery is wanted |

Ship P1 alone and it already improves #11.

## Reproducing the STOXX test

Their real-world setup (maximise signal exposure, long-only, 1% tracking error, 5% one-way turnover, sector +/-2%, beta 0.98-1.02) is a convex programme that `index/optimize.py` already solves. Once P2 gives a score panel, the comparison against a price-momentum index is a configuration, not new code.

## Open questions

1. **History.** Backtesting needs dated documents for several years. Filings and EDGAR full-text give history; news archives (GDELT) are noisier. Is filings-plus-archives coverage acceptable, given it is narrower than STOXX's web search?
2. **Benchmark factors.** Plan: replicate momentum, value and size with #11 and seed the registry. Is a vendor series (for example Fama-French) also available to cross-check them?
3. **Forward window.** How many forward quarters before a provisional candidate can be ratified?
4. **Registry storage.** Files under `alpha/` like `indices/`, or Postgres via the existing optional extra?
5. **Is P3 or P4 in scope?** P3 needs a user-defined IPS; P4 is only worth it if new-factor discovery is a goal.
