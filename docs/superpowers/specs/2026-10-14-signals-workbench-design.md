# Signals workbench (R&D Lab, Signals lane)

Date: 2026-10-14
Status: approved by the owner, 2026-10-14

## Intent

The R&D Lab is the internal workspace where ideas are tested with honest evidence and then
graduated into production scoring or shelved. It holds two different kinds of things:

- **Themes / topics**: what the world is talking about and doing (emerging themes, taxonomies,
  verified-exposure universes). Out of scope here, see "Not in this design".
- **Signals**: can text and market data predict returns, honestly?

This design covers the **Signals workbench**: a research environment in which a user designs,
builds and tests signals using several machine-learning and statistical techniques. The
foundation the lab needs (point-in-time text store, training-cutoff map, evidence checks,
experiment registry) is built inside this project, not before it.

The owner's two anti-goals drive everything: a signal ranked wrongly, and a backtest run on
leaked data. Where a feature and these anti-goals conflict, the anti-goals win.

## Signal categories (all five in the first release)

1. **Sentiment and narrative momentum.** First member is the STOXX / ISS STOXX whitepaper
   "From narrative to signal: Agentic AI for systematic indexing" (June 2026). See "Reference
   signal" below.
2. **Earnings-call tone.**
3. **Fundamental.** Exists today only as the generic value signal (any single characteristic).
4. **Price momentum.** Exists today (`SignalType.MOMENTUM`).
5. **Analyst revisions.** Does not exist today.

Categories 3 to 5 are baselines and building blocks: every new signal is checked for overlap
with them, and any of the five can enter a composite. Categories 1 and 2 are the research
frontier.

### Reference signal (what the STOXX paper defines)

Facts from the paper, not interpretations:

- Issuer-level, quarterly. The agent starts from a ticker, quarter and year (and peer group),
  searches the web, and returns a strict JSON payload: ordinal scores from -2 to +2, a confidence
  level, a rationale and verifiable citations. The paper says there are five scoring categories
  combined with equal weight and fixed thresholds; it does not name them.
- Design principles: point-in-time cutoff on every search, leakage detection with automatic
  retry, grounded outputs with sparse sources allowed, repeatability (identical inputs rerun 20
  to 30 times, ordinal scoring), an optional critic agent, and an LLM-as-judge calibrated on human
  pass/fail decisions.
- Leakage measured on tickers across the sample: about 40-60% with no protection, about 15% with
  a before-date filter, about 7% with the filter plus one retry (their Table 5).
- Reported results are backtests on simulated data (STOXX USA 900, Q4 2014 to Q4 2025): annual
  return rises monotonically from 1.1% (score -2) to 12.2% (score +2); an optimised long-only
  version had an information ratio of 1.01 against 0.33 for price momentum. Correlation with price
  momentum and analyst revisions is positive but moderate, with book yield negative and with size
  near zero.
- The authors state two limits: they cannot know the inputs were the only ones used, and the LLM
  may have been trained on the evaluation window. They call a live track record the real test.

## Goals

1. A user can define a signal as a **recipe**, run it over a universe and period, and see
   evidence for it, from the app or from a notebook, with identical results.
2. Several method families sit behind one interface so they can be compared on equal terms:
   - grounded LLM scoring of supplied text (ordinal, with a verbatim quote);
   - issuer-first search scoring as in the STOXX paper;
   - embeddings with a supervised head (ridge or logistic) on forward returns;
   - topic and narrative-attention measures (coverage intensity, change in attention);
   - a learned-lexicon baseline fitted to forward returns (SESTM-style, Ke, Kelly and Xiu), so
     it needs no labelled data and no licensed dictionary;
   - statistical transforms (change, decay, z-score, rank, momentum of a signal);
   - composites of the above.
3. Every experiment is recorded (recipe, data version, model and its training cutoff, results,
   decision) so rankings can be compared and the number of trials is known.
4. Each component also works on its own: a user can run a single method, a single evidence
   check, or the text store without the rest.
5. A signal can be marked **graduate** (becomes eligible as an input to the shared scoring
   stage) or **shelve** (kept with its evidence).

## Non-goals

- Intraday or daily news trading.
- Fine-tuning LLMs.
- Agentic alpha mining (an LLM writing factor formulas).
- Selling or distributing any signal or code. The lab is internal only.

## Anti-goals (a failure even if everything runs)

- A contaminated period presented as evidence.
- A signal ranked above another when the data cannot separate them.
- A notebook run that bypasses the guardrails or hides a trial from the count.

## Guardrails (non-negotiable for every method)

Leakage:
- Every text item stores event time (when the market could first read it) and knowledge time
  (when this system saw it). Backtests use event time only.
- Each model has a recorded training cutoff. Only periods after it count as evidence. Earlier
  periods are shown, labelled contaminated, and the in-window versus post-cutoff gap is
  reported as the contamination estimate.
- Search-based methods apply a hard before-date, run a leakage check and retry once, and
  report the residual leakage rate beside the score.
- Long-history text signals use time-consistent models only (ChronoBERT vintages).

Ranking:
- All signals are compared on the same universe, window and cost assumptions, net of costs.
- Every prompt, model or parameter variant tried counts as a trial in the deflated Sharpe and
  PBO.
- Rerun stability is measured, as in the STOXX paper.
- Overlap with the other four categories is shown before a signal is ranked.
- If two signals cannot be separated statistically, the result is "insufficient data", not a
  forced order.
- Significance uses errors robust to autocorrelation (Newey-West or clustered).

## Components

Architecture picture: `docs/superpowers/specs/assets/signals-workbench-architecture.html`.

1. **Recipe.** A versioned JSON document: category, text source, method, parameters,
   aggregation (per issuer and period), horizon, lag, universe. Stored once, usable from the app
   and from notebooks.
2. **Point-in-time text store.** Event time and knowledge time per item, content hash, entity
   link. Sources: Thomson Reuters news (licensed history, full text to be ingested; today it is
   headlines only), a transcript vendor, SEC EDGAR filings with `acceptanceDateTime`.
3. **Methods.** One interface, the families listed under Goals.
4. **Evidence harness.** Rank-IC (mean, robust t-statistic, rolling window), quantile and
   long-short returns, in-window versus post-cutoff split, leakage report, turnover and cost,
   deflated Sharpe and PBO with trial counting, rerun stability, redundancy (correlation) against
   the four other categories, size and sector neutral views, equal-weighted and value-weighted.
5. **Experiment registry.** Records every run and the decision. Holds the trial counter.
6. **Notebook library.** A Python module exposing the components above. A signal built in a
   notebook is saved as a recipe and appears in the app.
7. **App screens.** A Signals workspace with menus and selection: build a recipe, run it,
   compare experiments, view evidence, decide.

## Data already available (owner decisions of 2026-10-13, recorded in the research doc)

- Thomson Reuters news history with full text is licensed. The current pull is headlines only
  with an empty excerpt, so full-text ingestion is part of this project.
- A transcript vendor is available (name not yet given).
- Point-in-time prices and universe membership are available, so backtests use point-in-time
  membership.
- Local open-weight models may run on the owner's machines (ChronoBERT).

## Already done (on branch `ccr-255c3bd3-0eqx1j`)

- Point-in-time fixes: news uses first-publication time, the sentiment prompt is dated by
  `published_at`, EDGAR keeps `acceptanceDateTime`.
- `build_manifest_from_store`, per-cell averaging of grounded scores in `build_sentiment_panel`,
  and `arp replicate news-manifest`.
- Background and source review: `docs/LLM_TEXT_SIGNALS_RESEARCH.md`.

## Existing code to reuse

`backend/arp/replication/` (signals, backtest engine, deflated Sharpe, PBO via CSCV, comparison
report, regime analysis), `sentiment_scoring.py` (grounded scorer), `backend/arp/grounding.py`,
the run store (`backend/arp/db/runs.py`), `backend/arp/index/risk.py` (factor risk model that
could provide residualisation), the emerging-themes extraction (`ExtractedTag`s) for narrative
attention over themes.

## Libraries

Internal-only use. Checked online on 2026-10-14 (licence from PyPI metadata and project pages;
not legal advice).

- **Adopt:** scikit-learn (BSD), statsmodels (BSD), sentence-transformers or the existing
  fastembed, ChronoBERT `manelalab/chrono-bert-v1-*` (MIT), BERTopic (MIT).
- **Optional:** skfolio (BSD), MLflow (Apache-2.0; the existing run store may make it
  unnecessary), Optuna (MIT; every trial still counts), Jupyter as an optional dependency group.
- **Reimplement, do not adopt:** alphalens-style evidence in the numpy-based engine (adopting
  alphalens-reloaded would add pandas); Qlib (own data format; borrow ideas only).
- **Owner decision 2026-10-16: use FinBERT** for internal research. Its licence is CC BY-NC-SA 4.0
  (non-commercial, share-alike), so it stays internal: no output or model derived from it is
  sold or distributed. Recheck before any commercial use.
- **Do not use pending a licensing check:** Financial PhraseBank (CC BY-NC-SA 4.0),
  Loughran-McDonald dictionary (free for academic research, commercial use needs a licence).
- **Fine for internal use:** vectorbt (Apache-2.0 with Commons Clause), gensim (LGPL), but
  neither is needed.
- **Version caution:** shap and scipy now require Python 3.12 or later; the repo requires 3.11
  or later.

## Constraints

- Internal use only, no product sold.
- Precision first: "insufficient data" is an acceptable answer. Never a forced ranking.
- Repo conventions: backend checks `ruff` and `pytest`; never delete or weaken a test; every
  test change listed in the PR description; PRs target `main`.
- The grounding rule holds for every LLM output: a score keeps a verbatim quote or is excluded.
- Notebooks run on the user's own machine against the backend and database (the builder's
  default; see "My calls").

## Decisions made by the owner

- Signals and themes are different kinds of things.
- Detect's market test lives in the Themes lane.
- All five signal categories from day one; fundamentals and analyst revisions may come from a
  vendor, price and text from existing data.
- The Signals workbench is built first, with the foundation inside it; the Themes lane gaps and
  the shared build-stage upgrades follow as separate designs.
- Work is a mix: screens and menus in the app, plus notebooks.
- The first release includes the whole workbench and its individual components.
- Internal use only.

## My calls (the owner has not decided these)

- Stored-text scoring and issuer-first search are both built as variants of the same signal, so
  they can be compared.
- Experiments are stored in the existing run store; no new experiment infrastructure until it
  is shown to be needed.
- Notebooks run locally against the backend and database. A hosted notebook server is not built.
- Alphalens-style evidence is reimplemented, not imported.
- A theme can become a signal (for example theme attention); this link is a guess and not in
  the first release unless cheap.
- Backtest of themes uses the same engine (decided in the shared-stage design, not here).

Calls made after a builder read of this document:

- **Universe, window, cost.** Universe and window are recipe parameters, drawn from the
  point-in-time universe data above. Signals are only compared when they share the same
  universe, window and cost model. Cost is a flat basis-point charge per side on traded
  weight, configurable per comparison, reported gross and net. There is no required universe
  such as STOXX USA 900.
- **Trial counting.** A trial is any registered run of a recipe variant (prompt, model, method
  or parameter change). Deflation for a signal uses every registered trial in the same
  category, universe and evaluation window.
- **Enforcement.** Anything that appears in the app, is ranked, or can be graduated must be
  registered, and registration runs the guardrails. A notebook may compute anything ad hoc, but
  unregistered output is labelled "unregistered, not evidence" and cannot be graduated.
- **Insufficient data.** Two signals are ordered only if a paired bootstrap on their
  long-short return differences, corrected for the number of registered comparisons, excludes
  zero at a configurable confidence (default 95%). Otherwise the result is "insufficient data".
- **Unknown training cutoff.** Treated as contaminated: no period counts as evidence until a
  cutoff is recorded. Cutoffs are editable data with a source note, not hard-coded. Embedding
  and ChronoBERT models carry their own cutoff by model name or vintage.
- **Missing vendors.** Fundamentals, analyst revisions and transcripts sit behind adapter
  interfaces with CSV import as the first adapter, so the first release is not blocked on a
  vendor. Point-in-time handling (restatement and revision timestamps) is part of each adapter.
- **LLM spend.** Runs are asynchronous, cached and resumable, using the existing job manager.
  Before a run the app shows the estimated number of calls and cost and asks for confirmation
  above a configurable threshold. Large universes may be sampled.
- **Graduate.** Graduating records who approved it and when, freezes the recipe version, and
  produces a characteristic panel that the shared scoring stage can read. Experiments are
  append-only; shelving never deletes.

## Left to the builder

Storage layout for the text store and registry, exact recipe schema, screen layout, naming,
test plan, the order of components inside the project, and how the notebook library is
packaged.

## Open questions (only the owner can answer)

1. Who maintains the per-model training-cutoff dates, and from which Anthropic source?
2. Which vendor supplies analyst revisions and fundamentals, and which supplies transcripts?
3. Which search tool may supply the hard before-date filter for the issuer-first variant, and
   what is the spend ceiling for a run? (The STOXX paper used Google Search grounding; the repo
   has only an Anthropic client. Without an allowed tool, the issuer-first variant is built
   against an interface only.)
4. Loughran-McDonald dictionary: usable internally? (Needs the licensing owner; stays out until
   answered. FinBERT was approved for internal use by the owner on 2026-10-16.)

## Success

From the app or a notebook, a user can define a narrative-momentum recipe, run it on a defined
universe and period, and see evidence split into in-window and post-cutoff, with the leakage
rate, cost-adjusted results, trial-adjusted significance and overlap with the other four
categories. The same experiment is visible in both places. A contaminated period cannot be shown
as evidence, and a signal that cannot be separated from another is not ranked above it.

## Not in this design

The Themes lane (detect, define, identify, universe), the shared build stage upgrades
(neutralisation, value-weighting in the backtest, cross-signal correlation in construction),
and the UI of the other workspaces. Each gets its own design after this one.
