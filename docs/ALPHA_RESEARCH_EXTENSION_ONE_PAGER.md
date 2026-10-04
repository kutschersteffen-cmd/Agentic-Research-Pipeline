# Alpha Research Extension: one-pager

**Status:** proposal, nothing built. **Extends:** #11 Strategy Replication, #12 Emerging Themes, #2 Taxonomy Library, #16 Index Construction.
**Origin:** review of the "Agentic Quant Research Pipeline" spec. Its code is unusable (fake orthogonalization, hard-coded gate), but four ideas fit ARP.

## Problem

ARP proves a result is **real** (HLZ-scaled t-hurdle, DSR, PBO). It cannot yet show a result is **new** (not a repackaged known factor) or **honestly counted** (`num_trials_attempted` is self-reported). Narrative inputs (themes, sentiment) never reach the backtest engine as one flow.

## Four ideas

| # | Idea | What it adds | Reuses |
|---|---|---|---|
| 1 | **Factor Zoo registry + orthogonality gate** | Accepted strategies' return series are stored. A new candidate is regressed on them; the gate is the residual-alpha t-stat. Also reports max pairwise correlation. | `replication/backtest_engine.py` returns, `compare.py` hurdle |
| 2 | **Trial ledger** | Every attempt, including rejected ones, is appended with spec hash, family, verdict, reason. `num_trials_attempted` is read from the ledger, not from the spec. | `StrategySpec.num_trials_attempted`, `deflated_sharpe.py` |
| 3 | **Narrative-to-signal bridge** | Turns theme or company narrative scores into a point-in-time signal panel the #11 engine can backtest. | `sentiment_scoring.py`, `emerging_themes/scoring.py` (velocity, persistence, action_score), `company_exposure.py`, `SignalType.TEXT_SENTIMENT` |
| 4 | **IPS-constrained allocation** (optional) | Return/Risk debate proposes weights across registry factors; cvxpy solves; plain Python re-verifies every IPS constraint. | debate pattern in #1, `index/optimize.py` (never trust the solver's "optimal") |

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
        3  Bridge: frozen, effective-dated snapshot, lagged by disclosure date
                                |
                      #11 deterministic backtest (IS / OOS)
                                |
        2  Ledger: count the trial in this family (+ global)
                                |
   Gate: HLZ hurdle(ledger count) + DSR + PBO + 1  orthogonality vs registry
                                |
                 PROPOSED  ->  human ratifies  ->  1 registry
                                |
                    4 allocation (optional, reads registry)
```

- **A (theme level)** answers "does this theme predict returns?". The theme's company exposures set who is in the long and short legs.
- **B (company level)** answers "does this company-level narrative signal predict returns?". Narrative momentum is the first definition: change in a company's text-sentiment or theme-relevance score over a lookback, mapped onto the existing `TEXT_SENTIMENT` path.
- A theme finding can spawn company-level variants (and the reverse). They share a **family id**, so the ledger counts them together and the hurdle rises honestly.

## Rules that carry over from ARP

1. **Zero LLM in the numbers.** The LLM only labels text. Scores enter as frozen snapshots; the backtest is deterministic.
2. **Point-in-time.** A theme or taxonomy is applied only at the version in force on the date. Using today's theme definition on past dates is look-ahead and is rejected.
3. **Propose, never apply.** Registry entry needs a recorded human ratification with a reason, like a taxonomy.
4. **Ledger is append-only.** Rejected and failed attempts stay, so the trial count cannot be gamed down.
5. **Orthogonality is real regression.** Time-series regression of long-short returns on actual registry returns (and market/size/value/momentum where a vendor series is configured). Fewer than 36 monthly observations returns INSUFFICIENT_DATA, never a pass.

## Phasing

| Phase | Scope | Effort | Depends on |
|---|---|---|---|
| P1 | Ledger + registry + orthogonality gate, wired into `compare.py`; CLI `arp alpha ...`; one test per gate | 3-4 days | nothing |
| P2 | Bridge: entry B (company topic, narrative momentum) first, then entry A (theme level) | ~1 week | P1, point-in-time text history |
| P3 | Allocation track with IPS schema | 2+ weeks | P1, macro data source, an IPS definition from users |

Ship P1 alone and it already improves #11.

## Open questions

1. **History for narrative signals.** Backtesting needs dated text back several years. EDGAR full-text search and GDELT give history; theme labels must be re-derived under the taxonomy version of each date. Is that acceptable cost?
2. **Benchmark factors.** Is a vendor factor series (e.g. Fama-French) available, or is the registry the only reference at first?
3. **Registry storage.** Files under `alpha/` like `indices/`, or Postgres via the existing optional extra?
4. **Is P3 in scope?** Allocation needs a user-defined IPS; without one, skip it.
