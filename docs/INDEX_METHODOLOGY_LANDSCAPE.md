# Index Construction Methodology Landscape — MSCI, ISS STOXX, Solactive

Status: **research input for `docs/EQUITY_INDEX_CONSTRUCTION_PLAN.md`** -- and
now partly implemented. The catalogue in section 6 is the menu the rule
engine in `backend/arp/index/` offers: families A (screening and selection),
B (closed-form tilts) and D (path-dependent) are built, and so is **all of
family C bar the licence**: C3 (the least-squares projection), C1 (score
maximisation under a tracking-error budget), C2 (minimum tracking error) and
C4's constraint vocabulary, as an opt-in path (`arp/index/optimize.py` and
`risk.py`, the `optimize` extra) selected per calibration. C6 -- the risk
model itself -- ships as three estimators rather than a licensed factor
model, with `supplied_factor_model()` as the slot a vendor file drops into.

The **default path still deploys no solver at all**, and meets the
decarbonisation target by *exponential (entropy) tilting*: `w_i ∝ w_i^base · exp(-lambda · x_i)` is the analytic
minimum-relative-entropy reweighting subject to a linear constraint on the
weighted average, so only the multiplier `lambda` is found numerically, by
bisection. It is adjacent to C3 in spirit -- risk-model-free,
distortion-minimising, reproducible -- but it is a different objective from
Solactive's least-squares programme and is not solved as a quadratic
programme over the weight vector. With the cap projection composed inside
the search it carries **no optimality certificate**: it provably reaches the
target and respects every cap, but it is not the minimum-distortion point of
the feasible set. That certificate is exactly what the C3 path now adds, at
the cost of an optional dependency and of the cross-machine reproducibility
the tilt gets for free. A tracking-error *budget* still needs C1/C2 and a
covariance matrix, and remains unbuilt -- section 7.2 explains why that
ordering is deliberate rather than a shortcut.

The rest of this document remains research.

It exists to answer the plan's open decision #3 — single index
or a family, and with what weighting machinery — with evidence rather than
preference, and to size §7 of the plan (weighting and constraints) against
what the three providers actually do.

**Verification caveat, stated up front.** This session's egress policy blocks
`msci.com`, `stoxx.com`, `solactive.com`, `eur-lex.europa.eu` and
`legislation.gov.uk`, so the primary methodology PDFs and the regulation text
could not be fetched directly. Everything below comes from search-engine
retrieval over those same documents. The *structure* of each approach is
reliable; **individual numeric thresholds must be re-checked against the
primary methodology document and the Official Journal text before they enter
a methodology document or a config file.** §7 flags which numbers carry the
most risk.

---

## 1. The five-layer stack

Every index from all three providers decomposes into the same five layers.
Keeping them separate is what makes a methodology family tractable, and it is
already the package boundary in the build plan.

| Layer | Question | Varies by |
|---|---|---|
| **1. Parent universe** | What is investable at all? | Region, size segment, liquidity |
| **2. Eligibility / exclusion** | Who is disqualified regardless of score? | Norms, product involvement, controversies, fossil thresholds |
| **3. Selection** | Who is in the index? | Best-in-class, rank+buffer, relevance threshold, category |
| **4. Weighting** | How much of each? | Cap-weight, tilt, optimiser |
| **5. Constraints & schedule** | What bounds the result, and when? | Caps, TE, turnover, trajectory, review calendar |

The three families the question asks about — simple over/underweight rules,
optimisation, path dependence — are all layer 4/5 choices. Layers 2 and 3 are
shared across all of them, which is the single most important architectural
observation in this document: **exclusion and selection logic is common
infrastructure; only the weighting engine forks.**

---

## 2. MSCI

MSCI's families are best read as a ladder of increasing machinery, from pure
exclusion to constrained optimisation with a time-dependent target.

### 2.1 Exclusion only — MSCI ESG Screened

Parent index minus companies in weapons, tobacco, thermal coal, oil sands, and
UN Global Compact violators. Weights are parent weights renormalised. No
selection, no tilt, no optimiser. This is the cheapest thing to build and the
most common institutional starting point.

### 2.2 Simple tilt — MSCI ESG Universal

The canonical closed-form over/underweight rule:

```
Combined ESG Score = ESG Rating Score × ESG Trend Score
Security Weight    = Combined ESG Score × parent float-adjusted market-cap weight
                   → normalised to 100%
```

Worst-ESG names are dropped first ("minimal exclusions"), then everything else
is reweighted by a multiplier reflecting both the current rating and its
*direction of travel*. Deterministic, explainable in one line, no risk model.
Tracking error is an output, not an input.

*Unverified:* the exact numeric mapping from rating letter to rating score and
from trend to trend multiplier. The multiplicative structure is confirmed; the
lookup table is not.

### 2.3 Relative best-in-class — MSCI ESG Leaders and MSCI SRI

Selection by sector-relative ESG rank, to a **market-cap coverage target**:

- **ESG Leaders** — target 50% of the free-float market cap of each GICS sector
  of the parent, selecting highest-rated first, with a **10% buffer on the
  coverage target** (i.e. a sector is only rebalanced outside roughly 45–55%
  coverage) to damp turnover.
- **SRI** — the same mechanic at a **25%** coverage target, plus the strictest
  exclusion set of the MSCI ESG range (weapons, adult entertainment, alcohol,
  tobacco, gambling, GMO, nuclear power, thermal coal, UNGC violators).

Weighting within the selection is parent market-cap weight, renormalised. Note
the buffer is applied to a *coverage percentage*, not a rank — a variant of the
rank buffer in the build plan's §6.2 and slightly harder to implement, because
the hysteresis band is on a cumulative quantity.

### 2.4 Optimised ESG — MSCI ESG Focus / ESG Enhanced Focus (and its CTB variant)

Exclusions, then an optimisation that **maximises the index-weighted ESG score
subject to a tracking-error budget**, with a simultaneous constraint of at
least a 30% reduction in index-weighted carbon intensity versus the parent.
Realised TE on the ACWI version has been around 0.6%. Built on MSCI's Barra
risk model and Open Optimizer.

This is the archetype of objective family C1 in §6.

### 2.5 Category tilt — MSCI Climate Change (CTB)

Uses the **Low Carbon Transition (LCT) score** (0–10) and its five **LCT
categories**: Asset Stranding, Product Transition, Operational Transition,
Neutral, Solutions. Constituents are reweighted *between and within*
categories:

```
Relative Tilt Score = LCT score normalised against the max LCT score
                      of that LCT category in the parent, floored at 0.5
Security Weight     = Combined Score × parent weight → normalised
```

Two details worth stealing: the **floor on the multiplier** (0.5), which stops
a tilt from becoming a de facto exclusion, and normalisation **within category
rather than globally**, which prevents the tilt from collapsing into a sector
bet. Related selection rule in the same family: no security in the Neutral or
Solutions category is removed even if it sits in the bottom quartile by LCT
score — a category override on a rank screen.

### 2.6 Category selection by count — MSCI Climate Action

Selects the **top 50% of companies in each GICS sector by count** (not by
market cap — an important and easily-missed distinction from ESG Leaders) on a
four-part transition-readiness assessment: current emission intensity,
reduction commitments, track record of actual reductions, green revenue share,
and climate risk management. Reported to deliver a near-50% WACI reduction on
ACWI purely through selection.

### 2.7 Optimised + path-dependent — MSCI Climate Paris Aligned

The most machinery of any equity family here. Barra Open Optimizer, semi-annual
reviews (last business day of May and November), with:

- a **self-decarbonisation trajectory** measured from a fixed **base date**:
  the target weighted-average GHG intensity at each review is the base-date
  intensity decayed at the self-decarbonisation rate. MSCI ran this at **10%**
  p.a. and consulted on moving to **7%** to match the EU PAB requirement
  exactly;
- an **aggregated Climate Value-at-Risk** constraint, applied in recent reviews
  as `≥ max(-10%, Aggregated Climate VaR of the parent index)` — note the
  `max()` form, which makes the constraint relative to the parent when the
  parent is itself worse than the absolute floor;
- country bounds: for countries below 2.5% of the parent, the index weight
  upper bound is **3× the parent weight**;
- turnover and active sector weight constraints — and, critically, a documented
  **relaxation ladder**: the one-way turnover constraint and the active sector
  weight constraint are *alternately relaxed* when no optimal solution is
  found.

That relaxation ladder is the single most important implementation detail in
this whole document. See §6 C5 and §7.

### 2.8 Thematic — MSCI Thematic Relevance Score

- Start from MSCI ACWI IMI.
- Compute a **Relevance Score** per company per theme, from revenue mapped to
  the theme by two routes: direct (NLP/keyword analysis over business segment
  names, business descriptions, filings) and indirect (SIC-code mapping). The
  score is the share of company revenue attributable to the theme.
- Filter to **relevance ≥ 25%**; drop companies in unrelated GICS
  sub-industries (a sanity overlay on the NLP).
- Weight by **relevance score × float-adjusted market cap**, normalise, then
  **cap each issuer at 5%**.
- "Pure play" is the ≥50% relevance bucket, reported as an index characteristic.

---

## 3. ISS STOXX

ISS STOXX splits cleanly: **ISS ESG supplies the data layer**, STOXX supplies
the index mechanics, and the optimiser is **Axioma's** (all three now sit
inside the same group, which is why the pairing is so tight).

### 3.1 The ISS ESG data layer

| Dataset | What it produces | Typical index use |
|---|---|---|
| **Corporate Rating** | Letter grade + **decile rank** (1 best, 10 worst) vs industry peers; **Prime status** where the grade meets an industry-specific threshold (C+ for most industries, **B−** for high-risk, **C** for low-risk) | Absolute best-in-class selection |
| **ESG Performance Score** | 0–100, standardised for cross-sector comparison, 50 = standard | Tilt and optimisation objective |
| **Norms-Based Research** | UNGC / OECD / UNGP compliance verdict | Hard exclusion |
| **Carbon Risk Rating** | Carbon Risk Classification (exposure) + Carbon Performance Score (management), 100+ indicators | Climate selection and tilt |
| **SDG Solutions Assessment** | Positive/negative contribution across 15 objectives | Thematic/impact screens, PAB SDG obstruction screens |
| **Climate Impact / scenario data** | Emissions, scenario alignment | Trajectory constraints |

**Prime status is the notable structural difference from MSCI.** MSCI's ESG
Leaders/SRI selection is *relative* (top X% of a sector). ISS Prime is an
*absolute* threshold that varies by industry. A relative rule always fills the
index; an absolute rule can leave a sector empty — which is a real edge case a
weighting engine has to handle, and a good reason the threshold table itself
must be versioned config.

### 3.2 Exclusion only — STOXX ESG-X

Norm- and product-based exclusionary screens over an existing STOXX parent
(controversial weapons, thermal coal, tobacco, and related), weights otherwise
unchanged. Deliberately designed as a drop-in replacement for the standard
benchmark — the "minimum viable ESG index".

### 3.3 Rank-and-count selection — STOXX ESG Broad Market

Screens, then securities are ranked by ISS ESG score **within each of the 11
ICB Industries**, selecting top-ranked names until the count reaches **80% of
the number of securities** in the underlying index. Note: a **count** target
within industry, not a market-cap target — the third variant of the same
best-in-class idea, and each variant gives a different turnover profile.

### 3.4 Optimised tilt — STOXX ESG Target

Axioma risk model and optimiser. Objective: **maximise the portfolio ESG
score**, subject to an **ex-ante tracking-error constraint** (documented around
**<1.5%** versus the parent on published variants) and carbon-reduction goals,
on top of the ESG-X exclusion set extended with tobacco, thermal coal, small
arms, military contracting, unconventional oil and gas, high ESG risk and
controversies.

### 3.5 PAB / CTB — STOXX Paris-Aligned Benchmark

ISS ESG screens (norms, controversial weapons, fossil revenue thresholds, plus
**SDG obstruction screens on SDGs 12, 13, 14 and 15** — an ISS-specific overlay
beyond the regulation), then an optimisation targeting **tracking error ≤
1.5%** versus the parent while meeting the EU PAB minimums (≥50% intensity
reduction and the 7% annual trajectory).

Also relevant as a design reference: the STOXX Willis Towers Watson Climate
Transition index family, which uses a forward-looking climate transition
value-at-risk rather than a point-in-time intensity.

### 3.6 Thematic — STOXX revenue-based

Selection and weighting driven by **FactSet RBICS** revenue segmentation rather
than an in-house NLP score: a granular revenue taxonomy is used to compute
thematic exposure, names are selected on exposure, and the portfolio is tilted
toward the highest aggregate thematic exposure and the largest market caps,
with a trading-value liquidity filter and ESG screens layered in.

This is the "buy the taxonomy" alternative to MSCI's and Solactive's "build the
NLP" approach — a genuine build-vs-licence choice for us, and one where this
repo already has the NLP side.

---

## 4. Solactive

Solactive's market position is transparent, rules-based, white-label
construction — usually the simplest machinery that satisfies the constraint.

### 4.1 Thematic — ARTIS

An in-house NLP engine that scans large volumes of company reports, filings and
news, resolving company–theme references via keyword association and assigning
a **thematic relevance score per company per theme**. Explicitly
multi-dimensional: unlike a sector classification, a company can carry exposure
to several themes at once. Source reliability is weighted — a financial report
counts for more than a news article.

Typical index rules on top: **pure-play selection at ≥50% of revenue** from one
or more thematic categories, plus market-cap (e.g. >$500m) and ADV (e.g. >$1m)
filters. Over 100 ETF-underlying indices are built on it.

### 4.2 Climate — Solactive ISS ESG PAB / CTB and Net Zero Pathway

ISS ESG screens (Norms-Based Research, controversial weapons, fixed revenue
thresholds for fossil activities), then a weighting step that is the third
distinct optimisation formulation in this document:

```
minimise   Σ_i ( w_i − w_i^parent )²          (cumulative squared weight deviation)
subject to carbon intensity ≤ target, exclusions, weight bounds, …
```

**No risk model.** Minimising squared weight deviation is a proxy for tracking
error that needs no covariance matrix — a pure quadratic program. It is far
more reproducible than a risk-model optimisation (no model vintage to pin, no
factor data to license) at the cost of not actually controlling *risk*, only
weight distance.

Alongside it, a documented **iterative heuristic**: weight is increased in
**0.25% steps until a feasible solution is found**. That is a deterministic
search, not a solver — and it is exactly the kind of rule that is trivially
reproducible and trivially auditable.

The trajectory is the EU one: **7% annual minimum carbon-intensity reduction
measured against the index's intensity on its base day**, plus the 50%
(PAB) / 30% (CTB) reduction versus the benchmark.

The **Net Zero Pathway** series goes further, implementing the IIGCC Net Zero
Investment Framework on top of PAB compliance — i.e. a forward pathway rather
than a backward-looking intensity cut.

---

## 5. The EU PAB / CTB regime

Commission Delegated Regulation **(EU) 2020/1818** sets the minimum standards;
**2020/1816** governs the benchmark statement ESG disclosures and **2020/1817**
the methodology explanation. What the regulation actually requires:

| Requirement | CTB | PAB |
|---|---|---|
| GHG intensity reduction vs. **investable universe** | **≥ 30%** | **≥ 50%** |
| Year-on-year self-decarbonisation | **7%**, geometric progression from the base year | **7%**, same |
| Exposure to high-climate-impact sectors (NACE A–H and L) | **≥** that of the investable universe | **≥** same |
| Green share / brown share ratio | — | **≥** that of the investable universe |
| Exclusions | Controversial weapons; tobacco cultivation and production; UNGC / OECD Guidelines violators | All CTB exclusions **plus** fossil revenue thresholds and DNSH |
| Fossil revenue exclusions | **none** | coal **>1%**; oil **>10%**; gas **>50%**; electricity generation with lifecycle intensity **>100 gCO2e/kWh** at **>50%** of revenue |
| Significant harm to a Taxonomy environmental objective | — | Excluded |
| Sovereign issuance | Not eligible | Not eligible |
| Scope 3 | Phased in — energy and mining first (NACE divisions 05–09, 19–20), transport/construction/buildings within two years, broadening thereafter | Same |

Four mechanics matter more than the headline percentages:

1. **The trajectory is geometric from a fixed base year.** The year-*n* target
   is computed from year *n−1* in a geometric progression anchored on the base
   year — not from wherever the index happens to sit today. An index that
   overshoots does not get to coast.
2. **Missed targets must be compensated in the following year.** Article 8
   requires administrators to make up any year in which the target was not met.
   This is explicit, regulated state carry-forward: the index's obligation next
   year depends on its realised history.
3. **Two reductions bind simultaneously and one of them moves.** The 30%/50%
   cut is measured against the *investable universe as it is at that review*,
   which itself decarbonises over time; the 7% trajectory is measured against a
   *fixed base*. The binding constraint is whichever is tighter, and which one
   that is changes over the index's life.
4. **The high-climate-impact exposure floor is deliberately anti-divestment.**
   It exists so equity holders keep the engagement and voting leverage that
   divestment would forfeit — which is why it is an equity-only requirement.

The activity-exposure and green/brown ratios are both **relative to the
investable universe and recomputed each review**, so neither can be
precomputed into a static config.

---

## 6. The catalogue

The comprehensive list, grouped as asked. The last column is the engineering
cost in our architecture, and it is the point of the exercise.

### A. Screening and selection rules (layer 2–3, no weighting machinery)

| # | Approach | Mechanic | Seen in | Cost |
|---|---|---|---|---|
| A1 | **Norms-based exclusion** | Binary verdict on UNGC / OECD / UNGP compliance | All three | Trivial — a join and a filter |
| A2 | **Product-involvement exclusion** | Revenue share above a threshold in a named activity | All three; the PAB fossil thresholds are the regulated case | Trivial, *if* the revenue data exists per activity |
| A3 | **Controversy screen** | Severity flag from a ratings provider | MSCI SRI, STOXX ESG-X | Trivial |
| A4 | **Relative best-in-class to a market-cap coverage target** | Rank within sector, select until X% of sector float cap | MSCI ESG Leaders (50%), SRI (25%) | Low — cumulative-sum selection |
| A5 | **Relative best-in-class to a count target** | Rank within industry, select until X% of the *count* | STOXX ESG Broad Market (80%) | Low |
| A6 | **Top-N% by count per sector** | Select the best half of each sector by count | MSCI Climate Action (50%) | Low |
| A7 | **Absolute best-in-class threshold** | Grade must clear an industry-specific bar | ISS **Prime** (C+/B−/C) | Low — but can empty a sector; needs a documented fallback |
| A8 | **Coverage-target buffer** | Hysteresis band around a cumulative coverage target | MSCI ESG Leaders (±10% on the 50% target) | Medium — hysteresis on a cumulative quantity, not a rank |
| A9 | **Relevance / revenue threshold selection** | In if thematic revenue share ≥ threshold | MSCI (≥25%, pure play ≥50%), Solactive ARTIS (≥50%) | Low |
| A10 | **Classification sanity overlay** | Drop NLP hits in unrelated GICS sub-industries | MSCI thematic | Low — and a good precedent for our LLM boundary |
| A11 | **Category-based override** | Never drop a name in a protected category regardless of rank | MSCI Climate Change (Neutral, Solutions) | Low |
| A12 | **DNSH / Taxonomy harm exclusion** | Exclude significant harm to a Taxonomy objective | PAB requirement | Data-bound, not logic-bound |
| A13 | **SDG obstruction screen** | Exclude significant obstruction of named SDGs | STOXX PAB (SDG 12/13/14/15) | Low |

### B. Simple over/underweight (tilt) rules — closed form, layer 4

| # | Approach | Mechanic | Seen in | Cost |
|---|---|---|---|---|
| B1 | **Score × market cap** | `w = score × w_parent`, renormalised | MSCI ESG Universal | **Trivial** — the highest value-per-line rule in this document |
| B2 | **Multiplicative composite score** | `score = rating × trend` before the tilt | MSCI ESG Universal | Trivial |
| B3 | **Relevance × market cap** | Thematic exposure as the multiplier | MSCI thematic | Trivial |
| B4 | **Floored multiplier** | Clamp the tilt factor (e.g. ≥ 0.5) so a tilt can't become an exclusion | MSCI Climate Change | Trivial, and prevents a real failure mode |
| B5 | **Within-category normalisation** | Normalise the score against the max *within its category*, then tilt between categories too | MSCI Climate Change LCT | Low |
| B6 | **Bucket multiplier table** | Fixed over/underweight per rating bucket, from config | Common in custom mandates | Trivial — and the most auditable of all |
| B7 | **Issuer capping** | Hard cap per issuer post-tilt (e.g. 5%) | MSCI thematic | Low — the waterfall already in the plan |
| B8 | **Regulatory capping** | UCITS 5/10/40 as a second pass | UCITS-backing indices | Low–medium; interacts with B7 |
| B9 | **Equal weight / tiered weight** | Ignore market cap entirely, or in bands | Widespread in thematic | Trivial |
| B10 | **Iterative step heuristic** | Shift weight in fixed increments until a constraint is met | Solactive (0.25% steps) | Low — deterministic by construction |
| B11 | **Inverse-intensity weighting** | Weight ∝ market cap / carbon intensity | Low-carbon families | Trivial; degenerate for near-zero intensities, needs a floor |

**Property of the whole B family:** closed-form, deterministic, explainable in
a sentence, no solver, no risk model, byte-identical across machines. The cost
is that tracking error, sector drift and concentration are *outputs* — you
discover them after the fact and correct with caps, not constraints.

### C. Portfolio optimisation approaches — layer 4–5

| # | Formulation | Objective / constraints | Seen in | Cost |
|---|---|---|---|---|
| C1 | **Max score s.t. TE budget** | `max Σ wᵢsᵢ` s.t. `TE ≤ τ`, plus carbon and exclusion constraints | MSCI ESG Focus / Enhanced Focus; STOXX ESG Target (TE <1.5%) | **High** — needs a risk model and a licensed factor covariance matrix |
| C2 | **Min TE s.t. climate constraints** | `min TE` s.t. trajectory, Climate VaR, green/brown, sector floors | MSCI Climate Paris Aligned (Barra Open Optimizer) | High |
| C3 | **Min squared weight deviation s.t. constraints** | `min Σ(wᵢ − wᵢᵖᵃʳᵉⁿᵗ)²` s.t. intensity target and bounds | Solactive PAB family | **Medium** — a plain QP, *no risk model*, far more reproducible |
| C4 | **Constraint vocabulary** | Active sector/country bounds; security bounds as a multiple of parent (e.g. **3×** for countries <2.5%); turnover cap; min holdings; liquidity/ADV; factor neutrality | All optimised families | Each constraint is cheap; the *set* is the methodology |
| C5 | **Infeasibility relaxation ladder** | A defined order in which constraints are loosened when no solution exists — MSCI alternately relaxes one-way turnover and active sector weight | MSCI PAB | **This is methodology, not error handling.** See §7 |
| C6 | **Risk model choice** | Barra (MSCI) vs Axioma (STOXX) vs none (Solactive C3) | — | Determines licence cost, and whether "byte-identical" is even attainable |

See [`OPTIMIZATION_TOOLING.md`](OPTIMIZATION_TOOLING.md) for the modeling
layers and solvers that implement this family, which problem class each
constraint actually generates, and the staged recommendation for adopting
one.

**Property of the whole C family:** tracking error becomes an *input* you
control rather than an output you observe — which is the entire reason
providers pay for it. The costs are a licensed risk model, solver-version
sensitivity that fights the reproducibility requirement, and the fact that
infeasibility is not an exception but a routine event with a methodology-level
answer.

### D. Path-dependent approaches — layer 5, and the hard one

These are the approaches where **this review's output depends on prior
reviews**, not only on today's data. They are what force an index *state store*.

| # | Approach | The state it carries | Seen in |
|---|---|---|---|
| D1 | **Fixed-base decarbonisation trajectory** | Base-date intensity + base date; target = base × (1−r)^n in geometric progression | EU PAB/CTB (7%); MSCI PAB self-decarbonisation (10%, consulted to 7%); Solactive (7% vs base day) |
| D2 | **Missed-target compensation** | Realised vs. required reduction per year, and the shortfall owed | EU 2020/1818 Art. 8 — a *regulated* carry-forward |
| D3 | **Moving relative floor** | The investable universe's own intensity, recomputed each review, against which the 30%/50% cut is measured | EU PAB/CTB |
| D4 | **Dual binding constraint** | Which of D1 and D3 binds, and when that switches | EU PAB/CTB |
| D5 | **Relative ratio floors** | Activity exposure ratio and green/brown ratio vs. the current universe | EU PAB (green/brown), both (activity exposure) |
| D6 | **Net-zero pathway frameworks** | A forward alignment pathway per issuer and portfolio, carried and reassessed | Solactive ISS ESG Net Zero Pathway (IIGCC NZIF) |
| D7 | **Turnover-constrained optimisation** | The previous index's weights enter this review's constraint set | MSCI PAB, STOXX ESG Target, any optimised family |
| D8 | **Membership hysteresis** | Which names were in last review (rank buffers, coverage buffers, Prime status buffers) | MSCI ESG Leaders, standard across providers |
| D9 | **Capping factor carry** | Prior capping factors as the starting point for this review's waterfall | Capped families generally |
| D10 | **Forward-looking risk carried as a constraint** | Aggregated Climate VaR relative to parent, e.g. `≥ max(−10%, parent)` | MSCI PAB; STOXX WTW Climate Transition |

**Property of the whole D family:** the index is a **state machine**, not a
pure function of today's data. This breaks the most convenient assumption in
the build plan — that a review is `f(data at knowledge_date, config)` — and
replaces it with `f(data, config, index_state[t−1])`. Everything in §7 follows
from that.

---

## 7. What this means for our build

### 7.1 The single largest finding

The build plan's §7.2 warned that a CTB/PAB ambition "makes weighting
path-dependent across reviews, which requires explicit state carry-forward" and
should be declared before the weighting engine is written. This research
confirms it and makes it concrete: **path dependence is not one feature, it is
ten** (§6 D), and two of them (D1, D2) are *regulated* rather than chosen.

Concretely, the plan needs a new first-class, bitemporal artifact alongside
levels, shares and divisors:

```
indices/<index_id>/state/<review_date>.json
  base_date, base_intensity, base_universe_intensity
  required_intensity[n], achieved_intensity[n]
  shortfall_carried_forward          # EU Art. 8 compensation
  binding_constraint                 # trajectory vs universe-relative floor
  activity_exposure_ratio, green_brown_ratio
  prior_weights, prior_capping_factors, prior_membership
  constraints_relaxed[]              # see 7.3
```

It is append-only and bitemporal for the same reason everything else is: a
restatement of a past year's emissions data changes what the trajectory *should
have been*, and both versions must remain recoverable.

### 7.2 Build order for the weighting engine

The catalogue gives a clean, cheap-first sequence, and it maps onto the plan's
phases without moving them:

1. **Exclusion + renormalise** (A1–A3, A12–A13) — Phase 2, near-free once the
   data is there. Covers ESG Screened / ESG-X entirely.
2. **Tilt engine** (B1–B6, B11) — Phase 4, roughly a day of work. One function:
   `w = clip(f(score), floor, ceil) × w_parent`, normalised. Covers ESG
   Universal, Climate Change, and MSCI-style thematic weighting. **This is by
   far the best value-per-line in the whole landscape.**
3. **Selection engine** (A4–A11) — Phase 2/4. Three variants of best-in-class
   (cap-coverage, count-coverage, top-N-by-count) plus absolute thresholds;
   they share one ranked-selection primitive with different stopping rules.
4. **Capping waterfall** (B7–B8, B10) — Phase 4, already in the plan.
5. **Index state + trajectory** (D1–D5, D8–D9) — **new, and it belongs in
   Phase 4, not later**, because the state schema constrains the calculation
   layer above it.
6. **Optimiser** (C1–C6) — a distinct subsystem, genuinely the A+ track. Still
   opt-in, still pinned, still determinism-tested per the plan's §7.1.

Note that steps 1–5 cover **every family in this document except the optimised
ones** — including full EU PAB/CTB compliance, reachable either by the
Solactive-style C3 quadratic programme or, as the engine actually does it, by
an entropy tilt whose multiplier is found by bisection. Both are materially
cheaper than the MSCI/STOXX route, and either is the one to take unless a
tracking-error *guarantee* or a provable optimum is a client requirement —
that requirement, and only that, is what buys family C.

### 7.3 The relaxation ladder is methodology

MSCI documents that it alternately relaxes the turnover and active-sector
constraints when the optimiser finds no solution. Solactive documents stepping
weights by 0.25% until feasible. Both are admissions that **infeasibility is
routine**, and both handle it with a *published, ordered* rule.

For us this means three things, and all three are plan amendments:

- The relaxation order is **config, versioned and effective-dated**, exactly
  like a cap threshold — not a `try/except` in the solver wrapper.
- Every relaxation actually applied is **recorded in the run manifest and shown
  on the committee pack**, in the same register as the data-quality exceptions
  in the plan's §11.5.
- The determinism test must cover the **relaxation path**, not just the
  solution: same inputs must produce the same *sequence* of relaxations.

An unlogged relaxation is a silent methodology change, which is precisely what
the audit trail exists to prevent.

### 7.4 Two smaller amendments

- **Tilt floors.** MSCI's 0.5 floor on the relative tilt score is a cheap
  guard against a tilt silently becoming an exclusion. Make a floor and ceiling
  on any tilt multiplier a required config field, not an optional one.
- **Absolute thresholds can empty a sector.** ISS Prime is an absolute bar, so
  a whole industry can fail it. Any absolute-threshold screen needs a declared
  fallback (leave the sector empty, or fall back to relative ranking) — a
  methodology decision that must be made before it happens in production.

### 7.5 Where our existing pipeline already fits

Thematic relevance is the one layer where this codebase is already at provider
parity in kind, if not in coverage:

| Provider | Thematic exposure source | Our equivalent |
|---|---|---|
| MSCI | In-house NLP + SIC mapping → Relevance Score, GICS sanity overlay | Advocate/Opposing/Adjudicator pipeline + `standards_mapping/` |
| Solactive | ARTIS NLP over reports, filings, news, source-reliability weighted | Same shape — plus our grounding check, which ARTIS does not document |
| STOXX | **Licensed** FactSet RBICS revenue taxonomy | `revenue_exposure/` cascade |

Two of the three build it, one licenses it. The plan's §6.4 frozen-snapshot
rule is what makes ours usable in an index at all — and note that MSCI's GICS
sanity overlay (A10) is exactly the same instinct: never let the NLP be the
only thing standing between a company and the index.

---

## 8. Verification status

| Claim | Confidence | Re-check before use |
|---|---|---|
| Five-layer decomposition; which provider uses which family | High | — |
| EU PAB/CTB structural requirements (30/50%, 7% geometric, compensation, exclusion categories, equity-only activity floor) | High | Confirm against the Official Journal text |
| PAB fossil revenue thresholds (1% / 10% / 50% / 50% at 100 gCO2e/kWh) | Medium-high | **Yes** — these are consistently reported but must come from Art. 12 itself |
| Scope 3 phase-in sectors and dates | Medium | **Yes** — Art. 5, and subsequent amendments |
| MSCI coverage targets (50% Leaders, 25% SRI) and the ±10% buffer | Medium-high | Yes |
| MSCI PAB constraint values (Climate VaR `max(−10%, parent)`, 3× country bound, relaxation order) | Medium | **Yes** — review-specific and revised over time |
| MSCI self-decarbonisation 10% → consulted 7% | Medium | **Yes** — confirm the current published rate |
| MSCI tilt formulas (score × parent weight; 0.5 floor; within-category normalisation) | Medium-high | Yes for the exact floor |
| MSCI ESG Universal rating/trend multiplier table | **Low** | **Yes — structure confirmed, values not** |
| MSCI thematic (≥25% relevance, 5% issuer cap, relevance × cap weighting) | Medium-high | Yes |
| STOXX ESG Broad Market 80%-by-count; ESG Target / PAB TE ≤1.5%; Axioma | Medium-high | Yes |
| ISS Prime thresholds (C+ / B− / C) and decile rank | Medium-high | Yes |
| Solactive: min squared weight deviation; 0.25% iterative step; 7% vs base day; ARTIS ≥50% pure play | Medium-high | Yes — and check whether the step size varies by index |

Anything marked **Low** or **Yes** in bold must not enter a config file or a
methodology document on the strength of this document alone.
