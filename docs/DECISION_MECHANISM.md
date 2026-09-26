# Decision Mechanism — Scoring, Ranking & Tiering

A deterministic layer that turns any per-entity table this system produces
into a **decision**: which companies to engage, exclude, prioritise or
park — with every automated choice and every human edit recorded.

**Zero LLM calls anywhere in the computation.** The same commitment
`arp/portfolio/aggregation.py` makes: the engine computes, and the trail
is permanent.

Implementation index at the end of this document.

---

## 1. Why this is a pillar rather than a page

Almost every function in this system ends in a **table of per-entity
numbers** — thematic exposure and confidence, extracted data points,
segment financials, transition-plan disclosure counts, transition-barrier
scores per sector and region, emerging-theme action scores, discovery
recency, indirect exposure, holdings and weights, WACI and financed
emissions.

What the system lacked was a shared, auditable way of turning those
numbers into a decision. Thresholds were hard-coded per module: the
engagement severity ladder (`arp/engagement/triggers.py`), extraction's
0.3/1.0 confidence convention (`arp/extraction/aggregator.py`), the
transition-plan completeness metric
(`arp/transition_plan/company_assessment.py`). Each is defensible in
isolation; none is inspectable, versionable, or comparable against the
others, and none can be re-tuned by an analyst without a code change.

The arithmetic of scoring is ordinary. The value is in the guards around
it, and those are what this layer exists to enforce:

1. **Correlated indicators are clustered before weighting**, so three
   ways of saying the same thing do not earn three times the weight.
2. **Gates resolve before the average.** A knockout is a decision, not a
   deduction — an excluded entity never reaches the score, where a
   strong dimension could dilute it.
3. **Sufficiency precedes scoring.** An entity below a minimum share of
   weight covered is routed to data collection rather than ranked on a
   third of its criteria.
4. **Nothing is invented by default.** The default missing-data policy
   re-weights over what is present.
5. **Direction is a flagged guess.** Higher-is-better vs.
   lower-is-better is inferred from the column name, and the inference
   flags itself when ambiguous or absent. A wrong direction silently
   inverts a ranking and nothing on screen looks wrong.
6. **Rank stability is reported, not assumed.** Every entity is scored
   under four specifications and carries the rank *range* across them.
7. **Cut-points are drawn over the eligible field**, after gates and
   sufficiency have removed who should not be in it.
8. **The dimension floor applies only to dimensions with ≥2 criteria**,
   so one yes/no answer cannot demote an entity on its own.
9. **Peer-relative scoring.** Criteria are normalised within a cohort
   (sector, region) rather than across an unlike field.
10. **Every rule records where it came from** — the data (`derived`) or
    a person (`human`).

---

## 2. The two entry points

```python
derive_mechanism(dataset)          -> MechanismConfig + audit trail
apply_mechanism(dataset, config)   -> DecisionResult
```

Derivation looks at data and proposes rules. Application takes rules and
produces decisions. They are deliberately separate: a **ratified**
framework can be applied to next quarter's snapshot unchanged, which is
the only way `compare_results` means anything.

Applying a framework never mutates it (asserted in the test suite).

---

## 3. What the engine does, step by step

### 3·0. Rules: calculated columns (`rules.py`)

A framework may carry a `rule_graph`: a GoRules JSON Decision Model,
drawn on a drag-and-drop canvas (the JDM editor) and evaluated per row by
the ZEN engine before anything else in `apply_mechanism` runs. Every
output key that is not already a column becomes a **calculated column**:

- **Formulas** in an Expression box: `capex / revenue * 100`. Earlier
  outputs in the same box are `$.name`.
- **AND/OR conditions**: `coal_expansion_flag and not sbti_validated_target`
  in an Expression box, or a Decision table (columns AND, rows OR, first
  hit wins), or a Switch.

A calculated column is profiled, proposed a role and scored like any
other. A compound gate needs no second gate system: the condition is a
yes/no column, and an ordinary `is Yes` gate acts on it.

Rows are typed from the profile before evaluation (numbers, booleans,
blanks as null) and every column is also addressable by its slug
(`Scope 1 (t)` → `scope_1_t`). Three rules keep the source data in charge:

1. **A rule never overwrites a source column.** Such an output is dropped
   and logged.
2. **A row the graph cannot evaluate gets blanks**, not an error: null
   arithmetic or division by zero leaves that row's calculated values
   empty for the missing-data policy to handle, and the count plus the
   first error are logged with `needs_check`.
3. **Only declarative nodes** (input, output, expression, decision table,
   switch). Function nodes run JavaScript and decision nodes load other
   graphs; the schema refuses both, since a framework arrives inline from
   the UI.

The browser runs the same engine build (ZEN 2.0.2 as threaded WASM,
`frontend/src/lib/zenEngine.ts`) for a live preview while a rule is being
edited; the backend pins `zen-engine==2.0.2` in lockstep so the two cannot
drift. The preview never becomes the score: `POST
/api/decision/datasets/{id}/calculated` evaluates the whole table
server-side, and scoring always re-runs the rules. Threaded WASM needs
`SharedArrayBuffer`, hence the COOP/COEP headers in `vite.config.ts` and
`nginx.conf`. If those headers are missing, the preview falls back to the
server's values.

Editing the graph is diffed node by node into a human-origin audit entry;
dragging a node is not an edit.

### 3a. Parsing (`parsing.py`)

Delimiter sniffing that picks the delimiter yielding the most *consistent*
column count rather than the most frequent character — a free-text column
full of commas otherwise beats the semicolons actually separating fields.
Numeric locale is detected per column from the values, so a German-locale
export (`1.234,5`) parses correctly without cleaning; `1.234,5` silently
read as `1.234` is a plausible-looking number, not an error. Booleans are
bilingual (`yes/ja/wahr/x/1`). Excel goes through `openpyxl`, already a
dependency of this codebase.

### 3b. Profiling (`profiling.py`)

Each column gets a type from its **values, not its header** — a header can
lie, or be in another language — plus coverage, cardinality, quantile
statistics and a `spread` flag that catches a column carrying one value
across every row.

### 3c. Roles and direction (`roles.py`)

Two traps this caught, both recorded because a column name is the only
thing standing between a correct ranking and a silently inverted one:

- The Transition Barrier matrix rates **feasibility**, where `HIGH` means
  *fewer* barriers. Emitting it as `..._Barrier_...` would have matched the
  lower-is-better dictionary and inverted the ranking, so `sources.py`
  names those columns for feasibility instead.
- A replication's out-of-sample decay figure cannot be called a *gap*:
  `gap` is a lower-is-better key, and the number's sign already means
  higher-is-better. It is `Out_Of_Sample_Persistence_pp`.


Each column is assigned a job (`label`, `reference`, `size`, `gate`,
`criterion`, `segment`, `excluded`) and a direction, from keyword
dictionaries held in `arp/decision/data/role_keywords.json` — **data, not
code**, so a house reporting in a third language or with its own
flag-naming convention extends this with an edit rather than a patch.

A column whose name signals position size (`weight`, `bps`, `aum`) becomes
the size column, never a criterion: how much you own is not a measure of
how good the company is.

### 3d. Normalisation (`normalise.py`)

Percentile rank (default), min–max or z-score, with winsorised tails, and
the direction applied as `100 − v`. Booleans map straight to 0/100 and
bypass winsorising — a two-valued column has no tails to trim. A lone
present value maps to the neutral midpoint: with nothing to compare
against, neither extreme is defensible.

**Peer cohorts.** With `normalise_within` set, each criterion is
normalised inside its cohort. An emissions-intensity percentile computed
across utilities and software companies together is close to meaningless,
and whole-table normalisation is the default that produces it. Cohorts
below `min_cohort_size` fall back to the whole table, because a percentile
rank over three peers is noise dressed as a score.

### 3e. Dimensions (`cluster.py`)

Pairwise Spearman on direction-adjusted values, then **complete-linkage**
agglomerative clustering at `cluster_threshold` (default 0.72). Complete,
not single, linkage: every pair inside a dimension must clear the
threshold. Under single linkage a chain of moderate correlations merges
into one dimension whose members may be unrelated to each other, which
quietly collapses a framework into a single weight.

Dimensions are named after the tokens their members share, falling back to
the **medoid** — the member most typical of the rest — which beats naming
a group after whichever column sorted first.

### 3f. Weighting (`weighting.py`)

- **Breadth-adjusted** (default): a dimension weighs `√(criteria count)`,
  shared among its members. A theme measured seven ways counts for more
  than one measured once, but not seven times more.
- **Equal**: every criterion counts the same.
- **Discriminating power**: Shannon-entropy weights over each criterion's
  min–max normalised values treated as a distribution across entities,
  with a `+1` offset so a zero value does not vanish from the log. Stated
  here because it is the one preset whose result cannot be read off the
  config.

### 3g. Scoring (`scoring.py`)

The weighted score, plus the two coverage figures that decide whether it
may stand:

- **coverage** — the share of total weight backed by a present value.
- **grounded coverage** — the share backed by a value whose confidence
  clears `grounded_confidence_min`. `None` when the source supplied no
  confidence at all, because *unknown* and *unverified* are not the same
  claim.

With `require_grounded_coverage`, the sufficiency gate keys off the
grounded figure, so a score resting on values the verifier could not
ground is routed to review instead of published. Asking for it against a
table that carries no confidence produces an audit entry saying so rather
than silently passing.

### 3h. The decision tree (`tree.py`)

A fixed evaluation order, which is what makes results reproducible:

1. **Sufficiency** → below `min_coverage_pct`, routed to data collection.
2. **Hard gates** → `exclude` settles it; the entity never reaches a score.
3. **Score band** → cut-points by quantile, natural breaks (widest gaps,
   subject to a minimum band width so one outlier cannot claim a tier), or
   fixed.
4. **Modifiers** → demote-gates and the dimension floor.

`derive_cuts` returns the mode that *actually* produced the cuts: a
`breaks` request with too few distinct scores falls back to quantiles and
says so rather than claiming natural breaks.

### 3i. Rank stability (`stability.py`)

Every entity is scored under four specifications — the framework's own,
equal weights, entropy weights, and the contrasting normalisation — and
carries the best and worst rank across them. A ranking that only survives
one arbitrary weighting choice is not a ranking, it is an artefact of that
choice.

### 3j. Leverage

`size × (100 − score) / 100` — position size times the gap to a perfect
score. The ordering a stewardship team actually wants: not who scores
worst, but where engagement moves the most.

---

## 4. Sensitivity: how much do the weights matter (`sensitivity.py`)

For each dimension, the weight is swept across a range and the entity's
tier recorded at each step, giving the smallest weight change that flips
it. This converts *"the framework says Tier 1"* into *"the framework says
Tier 1, and it takes a 14-point weight change to say otherwise"* — the
question a committee reliably asks. A tier that survives every weight in
the range is reported as robust.

Cost is (dimensions × steps) applications, so it is requested per entity
on demand and the rank-stability band is switched off for the intermediate
runs.

---

## 5. Period-on-period movement (`compare.py`)

The same framework applied to two snapshots: tier transitions, score and
rank deltas, and the criteria whose contribution moved most. A movement
with no named driver is the shape of a data problem rather than progress,
and the empty driver list says so.

Two guards:

- **Framework mismatch is refused, not silently compared.** A tier change
  under two different frameworks says nothing about the company, only
  about the frameworks.
- **A rank-based score cannot show absolute improvement.** Comparing two
  percentile-scored snapshots returns a caveat: an entity that improved in
  absolute terms shows no movement unless its ordering changed, and one
  that stood still can move because its peers did. For period-on-period
  work, score on min–max or z-score with pinned cut-points so the scale
  means the same thing in both snapshots.

---

## 6. Frameworks are versioned artefacts (`arp/storage/decision_store.py`)

`frameworks/<framework_id>/v<N>.json`, a `latest.json` pointer, and
`v<N>.audit.json` carrying the derivation and edit trail for that exact
version. Modelled on `TaxonomyStore`, with the same append-don't-mutate
rule — and it matters more here: a ratified framework is the justification
attached to a decision about a company, and a justification that can be
rewritten afterwards is not one. Saving over a ratified version is
refused; editing produces a new version.

**The audit log's two halves.** Derivation entries (`origin="derived"`)
say what the data proposed. `describe_changes` diffs a submitted framework
against the version it was based on and emits `origin="human"` entries for
every difference — the direction overrides, reweightings, regroupings and
gate changes a person made. Without that half, a reviewer cannot tell
which of the rules in front of them came from a person, which is the
distinction the log exists to draw.

---

## 7. Building the table from this system's own data (`sources.py`)

Nothing in the engine assumes an entity is a company — it scores rows. Three
of these seven sources prove it.

| Source | Entity | Produces |
| --- | --- | --- |
| `transition_plan_run` | company | disclosed count, walk/talk split, per-category disclosure %, assessment confidence — carried per cell |
| `extraction_run` | company | one column per schema field, each cell's confidence carried, and **zero** where the citation did not ground |
| `theme_run` | company | aggregate of the per-activity matches: activities included, best and mean exposure, adjudicator confidence |
| `portfolio_snapshot` | company | holdings as of one date joined to climate data-point observations, with `market_value_eur` as the size column |
| `transition_barrier` | **sector × region** | the shipped matrix, one row per cell: per-pillar feasibility, confidence, staleness. Needs no run — it is reference data |
| `emerging_themes_run` | **theme** | velocity, breadth, persistence, novelty, action score, materiality, contradiction, grounded-source share, status |
| `replication_runs` | **strategy** | in/out-of-sample Sharpe and return, out-of-sample persistence, max drawdown, deflated Sharpe, verdict. Spans runs, because one run replicates one spec |

Emitted column names follow the conventions the keyword dictionaries
already recognise (`*_Coverage_pct`, `*_Intensity_*`, `*_Flag`), so role
and direction inference works as well on an in-repo table as on an
uploaded one.

The portfolio source is what makes leverage real: position size × the gap
to a perfect score, over actual holdings, is a portfolio-weighted
engagement priority list.

---

## 8. Surfaces

**API** — `/api/decision` (`arp/api/routers/decision.py`). Datasets
(upload or from-source), mechanisms (derive, save, version, ratify),
`score`, `export.csv`, `sensitivity`, `compare`. No endpoint calls an
LLM, so none needs `schedule_llm_run`: scoring is synchronous.

**CLI** — `arp decision profile | derive | score | sensitivity | compare |
list | show | audit | new-version | ratify` (`arp/cli/decision.py`),
mirroring `arp taxonomy`.

**UI** — `frontend/src/pages/DecisionStudio.tsx`, eight sub-tabs: Data,
Profile, Rules, Mechanism, Decision tree, Results, Movement, Audit. Every number
on the page comes back from the engine, so what a reviewer sees is exactly
what the audit trail records. The one exception is the Rules tab's live
preview: it is computed in the browser, by the same engine build, and it is
never the recorded score (see 3·0).

---

## 9. Implementation index

```
backend/arp/decision/
  parsing.py       delimiter sniffing, numeric-locale + boolean detection, CSV/TSV/XLSX
  dataset.py       Dataset (rows + optional per-cell confidence), build/load
  profiling.py     per-column type, coverage, cardinality, quantiles, spread
  roles.py         role + direction proposal, peer-cohort choice
  data/role_keywords.json   the dictionaries, as data
  normalise.py     percentile / min-max / z-score, winsorising, cohorts, Spearman
  cluster.py       complete-linkage grouping, dimension naming
  weighting.py     breadth-adjusted / equal / entropy
  scoring.py       weighted score, coverage, grounded coverage, contributions
  tree.py          gates, cut-point derivation, tiers, dimension floor
  stability.py     the alternative specifications -> rank range
  sensitivity.py   tipping points: how far a weight must move
  compare.py       period-on-period movement + its caveats
  diffing.py       framework diff -> human-origin audit entries
  mechanism.py     derive_mechanism / apply_mechanism
  sources.py       in-repo tables (transition plan, extraction, theme, portfolio)
  rules.py         rule graph (GoRules JDM) -> calculated columns, via ZEN
  sample_data/example_transition_universe.csv
backend/arp/schemas/decision.py      every type named in this document
backend/arp/storage/decision_store.py  versioned frameworks + datasets
backend/arp/api/routers/decision.py    /api/decision
backend/arp/cli/decision.py            arp decision ...
backend/tests/test_decision_*.py       engine, store, analysis, sources, rules, API
frontend/src/pages/DecisionStudio.tsx
frontend/src/components/{ColumnProfileTable,MechanismEditor,DecisionTreeEditor,
                         DecisionResultsTable,ScoreDistribution,AuditLogView}.tsx
frameworks/                            versioned frameworks + saved datasets (gitignored)
```

---

## 10. Known limits

1. **A framework is bound to column names.** Applying one to a table whose
   columns are named differently needs a mapping step that does not exist
   yet; the practical path is the `sources.py` adapters, which emit stable
   names.
2. **Tier changes do not enter the review queue.** An entity whose rank
   band spans two tiers, or whose tier flipped since last quarter, is a
   strong review-queue candidate. Deliberately not wired yet — it is a
   volume decision as much as a technical one.
3. **Numeric gates are manual.** Gates are auto-derived only from boolean
   flag columns. Proposing numeric gates from distribution shape is
   possible but a far weaker inference than the boolean case.
4. **Ranked results do not yet open engagement issues.** Posting a
   Tier-1-or-leverage-ranked list into `arp/engagement/triggers.py` as
   `TriggerEvent`s — carrying the framework version as the justification —
   is the next step, and the store already keeps what that citation needs.
5. **Seven source adapters exist, not one per function.** Company
   financials, document discovery and indirect exposure have no adapter
   yet; each is a function returning a `Dataset`, and nothing in the
   engine needs to change for them.
