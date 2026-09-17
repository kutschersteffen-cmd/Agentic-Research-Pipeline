# Decision Mechanism (Scoring, Ranking & Tiering) — Integration Plan

Source artefact:
[`docs/prototypes/decision-mechanism-studio.html`](prototypes/decision-mechanism-studio.html)
— a ~1,590-line single-file browser tool ("Decision Mechanism Studio").
It reads a table, derives a scoring and tiering mechanism from the data,
lets a user tune every rule, and writes an audit log of which rules came
from the data and which came from the human.

This document proposes how that tool becomes a pillar of this codebase
rather than a page pasted into it. Read
[`docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md`](PORTFOLIO_RISK_EXPOSURE_PLAN.md)
for the analogous precedent — a deterministic, zero-LLM engine behind a
thin UI, with the numbers computed server-side and every choice logged.

---

## 1. Why this is worth integrating

Eight pillars of this system each end in a **table of per-company
numbers**:

| Pillar | Produces |
| --- | --- |
| Thematic Universe Builder | verdict, exposure estimate, confidence per company |
| Data-Point Extraction | schema-defined field values + confidence + grounding |
| Company Financials | segment revenue, CapEx, R&D |
| Transition Plan Assessment | `disclosed_count` / 64, walk vs. talk split, per-category breakdown |
| Document Discovery | document counts, recency, change events |
| Indirect Exposure | input-output propagated structural exposure |
| Portfolio Risk | holdings, market value, weights |
| Climate Analytics | WACI, financed emissions, coverage per issuer |

What the system does **not** have is a shared, auditable way of turning
those numbers into a **decision**: which companies to engage first, which
to exclude, which to park. Today every pillar hard-codes its own
thresholds in its own module — the engagement module's severity ladder
(`arp/engagement/triggers.py`), extraction's 0.3/1.0 confidence
convention (`arp/extraction/aggregator.py`), the transition-plan
completeness metric (`arp/transition_plan/company_assessment.py`). Each
is defensible in isolation; none of them is inspectable, versionable, or
comparable against the others, and none of them can be re-tuned by an
analyst without a code change.

The Studio is exactly that missing layer, and it is the right shape for
this codebase: **entirely deterministic, zero LLM calls in the
computation**, with an audit entry behind every automated choice. It
becomes pillar 9: **Decision Mechanism**.

The tool's real contribution is not the scoring arithmetic — that part is
ordinary — but the set of guards it puts around the arithmetic. Those
guards are the thing to preserve exactly:

1. **Correlated indicators are clustered before weighting**, so three
   ways of saying the same thing do not earn three times the weight.
2. **Gates are decided before averaging.** A knockout is a decision, not
   a deduction — an excluded entity never reaches the score at all.
3. **A sufficiency gate precedes scoring.** An entity below a minimum
   share of weight covered is routed to a data-collection outcome rather
   than being scored on a third of its criteria.
4. **No value is invented by default** — the default missing-data policy
   re-weights over what is present.
5. **Direction is a flagged guess.** The direction of an indicator
   (higher-is-better vs. lower-is-better) is inferred from its name, and
   the inference marks itself for review when it is ambiguous or absent.
   A wrong direction silently inverts a ranking; this is the single most
   valuable flag in the tool.
6. **Rank stability is reported, not assumed.** Every entity is scored
   under four specifications and carries the rank *range* across them.
7. **Cut-points are derived over the eligible field**, after gates and
   sufficiency have removed who should not be in it.
8. **A dimension floor ("veto") applies only to dimensions measured by
   two or more criteria**, so a single yes/no answer cannot demote an
   entity on its own.

---

## 2. What the artefact actually contains

Mapping the prototype's six tabs to what each one is worth porting.

### 2a. Data (tab 01) — parsing

`sniffDelim`, `parseDelimited`, `detectNumLocale`, `toNum`, `toBool`.
Handles comma/semicolon/tab delimiters, quoted fields, German decimal
commas and thousands separators, and a wide set of boolean spellings
(`yes/ja/wahr/x/1`). Excel is read via `xlsx.full.min.js` **loaded from
cdnjs** — see §5.

Worth porting: the locale and boolean detection, which is the part that
makes a raw German-locale Excel export usable without cleaning. The CDN
dependency is not portable and is not needed server-side.

### 2b. Profile (tab 02) — column typing

`profile()` assigns each column one of `numeric | ordinal | boolean |
categorical | identifier | text` from the *values*, not the header, plus
coverage, cardinality, quantile statistics and a `spread` flag.
`proposeRoles()` then assigns each column a job — `label`, `reference`,
`size`, `gate`, `criterion`, `segment`, `excluded` — and a direction,
from keyword dictionaries (`KW_HIGH`, `KW_LOW`, `KW_GATE`, `KW_SEVERE`,
`KW_SIZE`, `KW_ID`), each with the reason recorded in the audit log.

The dictionaries are bilingual (English/German) and currently inline
constants. In the port they belong in data, not code — see §4.

### 2c. Mechanism (tab 03) — normalisation, clustering, weighting

- **Normalisation**: percentile rank (default), min–max, z-score, each
  with winsorised tails; direction applied as `100 − v`.
- **Dimension discovery**: pairwise Spearman on direction-adjusted
  normalised values, then **complete-linkage** agglomerative clustering
  at ρ ≥ 0.72. Complete rather than single linkage deliberately: every
  pair inside a dimension must clear the threshold, so a chain of
  moderate correlations cannot swallow the whole framework.
- **Dimension naming**: longest common token set across members, falling
  back to the *medoid* member (the one most typical of the rest).
- **Weighting presets**: breadth-adjusted (dimension weight = √(criteria
  count), split evenly within), equal-per-criterion, and an
  entropy/"discriminating power" weight.

### 2d. Decision tree (tab 04)

A fixed evaluation order — sufficiency → hard gates → score band →
modifiers — with gate rules (`is/isnot/lt/gt/eq` per column, outcome
`exclude | demote | flag`), three cut-point modes (quantile, natural
breaks on the largest gaps subject to a minimum band width, fixed), and
the dimension-floor veto.

### 2e. Results (tab 05)

Tier KPIs, a score histogram with the cut-points drawn on it, a ranked
table, a per-entity drawer showing each criterion's contribution
(`(w / wUsed) × (score − 50)`), and two orderings: by score, and by
**leverage** = `size × (100 − score) / 100` — position size times the gap
to a perfect score, which is the ordering a stewardship team actually
wants for "where does engagement move the most".

### 2f. Audit (tab 06)

The derivation log (stage / item / decision / why), a plain-text export
for a methodology annex, and a copy-pasteable configuration JSON.

---

## 3. What must change — the artefact does not fit as-is

None of these are cosmetic. Each is a reason the HTML file cannot simply
be served from `frontend/public/`.

1. **The numbers are computed in the browser.** Nothing about a result
   is reproducible, citable, reviewable or regression-testable. This
   codebase's central commitment is the opposite: a deterministic engine
   computes, and the decision trail is permanent and append-only. The
   scoring must move to Python.
2. **Persistence is `localStorage`, keyed by a truncated column list.**
   `sig()` is `"dms:" + columns.join("|").slice(0, 200)` — two datasets
   sharing a 200-character column prefix collide and silently load each
   other's framework. Frameworks need real IDs and server-side versions.
3. **A derived framework overwrites itself.** In quantile or natural-breaks
   mode, `recompute()` writes the freshly derived cut-points back into the
   saved configuration on every pass. A saved framework therefore carries
   cut-points belonging to whatever dataset was last loaded — acceptable
   in a scratchpad, wrong for a versioned artefact that is supposed to
   mean the same thing next quarter. The port must keep *pinned* and
   *derived* cut-points as separate fields.
4. **The audit log misstates its own threshold.** The clustering constant
   is `TH = 0.72`, but the log line for an unclustered criterion reads
   "no rank correlation at or above 0.60 with any other criterion". The
   audit log is the product here; a stale number in it is a real defect.
   Fix on port, and have the log render the threshold from the constant
   rather than repeating it in prose.
5. **`xlsx.full.min.js` comes from cdnjs.** The frontend has exactly two
   runtime dependencies (`react`, `react-dom`) and no CDN script tags;
   outbound fetches elsewhere in the system go through
   `arp/net_safety.py`. The backend already depends on `openpyxl`, which
   this codebase uses for Excel parsing in `arp/ingestion/local_files.py`.
   Excel parsing belongs server-side.
6. **A different design system.** Source Serif 4 / Carlito / teal, a
   sticky tab shell, a slide-in drawer. The app is `app-shell` /
   `nav-tab` / `card` / `data-table` / `sub-nav` with the existing
   palette in `frontend/src/index.css`. The prototype is a UX
   specification to re-implement, not markup to paste.
7. **It only reads a file a user drops on it.** It has no access to the
   eight tables listed in §1 — which is the entire reason to integrate it
   here rather than keep using it standalone.

Two further behaviours are correct but undocumented, and need tests to
stay correct: percentile normalisation maps a lone present value to 50
rather than 0 or 100, and boolean columns bypass winsorisation entirely
(mapped straight to 0/100).

---

## 4. Proposed backend layout (new)

```
backend/arp/decision/
  __init__.py
  parsing.py       delimiter sniffing, numeric-locale + boolean detection,
                   CSV/TSV/XLSX -> a row matrix (openpyxl, no CDN)
  profiling.py     per-column type, coverage, cardinality, quantiles, spread
  roles.py         role + direction proposal; dictionaries loaded from data/
  normalise.py     percentile / min-max / z-score, winsorising, direction flip
  cluster.py       Spearman + complete-linkage grouping, dimension naming
  weighting.py     breadth-adjusted / equal / entropy effective weights
  scoring.py       weighted score, coverage, per-criterion contribution
  tree.py          gates, sufficiency, cut derivation, veto, tier assignment
  stability.py     the four alternative specifications -> rank range
  mechanism.py     derive_mechanism(dataset) / apply_mechanism(dataset, cfg)
  sources.py       build a decision table from in-repo run results (§6)
  data/
    role_keywords.json     KW_HIGH/KW_LOW/KW_GATE/KW_SEVERE/KW_SIZE/KW_ID
  sample_data/
    example_transition_universe.csv   the prototype's bundled dataset
```

`mechanism.py` exposes exactly two pure functions, both free of I/O and
both emitting `AuditEntry` rows:

```python
def derive_mechanism(dataset: Dataset) -> tuple[MechanismConfig, list[AuditEntry]]
def apply_mechanism(dataset: Dataset, config: MechanismConfig) -> DecisionResult
```

Keeping derivation and application separate is what makes a framework
reusable: derive once against a reference dataset, ratify it, then apply
the ratified version to next quarter's data unchanged.

Pulling the keyword dictionaries into `data/role_keywords.json` means a
house that reports in a third language, or that has its own naming
convention for exclusion flags, extends the tool with a data change
rather than a patch — the same reasoning behind
`arp/transition_plan/data/indicators.json`.

### Schemas — `backend/arp/schemas/decision.py`

```python
ColumnRole = Literal["label","reference","size","gate","criterion","segment","excluded"]
Direction  = Literal["higher","lower"]
NormMethod = Literal["percentile","minmax","zscore"]
MissingPolicy = Literal["renormalise","neutral","mean","penalise"]
WeightPreset  = Literal["balanced","equal","entropy","manual"]
CutMode    = Literal["quantile","breaks","absolute"]
GateOutcome = Literal["exclude","demote","flag"]

class ColumnProfile(BaseModel): ...      # type, coverage, unique, stats, spread, locale
class Criterion(BaseModel): ...          # column, dimension_id, weight, enabled, direction
class Dimension(BaseModel): ...          # id, name, weight, derived_from (audit trail)
class GateRule(BaseModel): ...           # column, op, value, outcome
class TierDefinition(BaseModel): ...     # name, action, rank
class MechanismConfig(BaseModel):        # the versioned, ratifiable artefact
    framework_id: str
    version: int
    norm: NormMethod; winsor_pct: float; missing: MissingPolicy
    weighting: WeightPreset; min_coverage_pct: float
    dimensions: list[Dimension]; criteria: list[Criterion]; gates: list[GateRule]
    cut_mode: CutMode
    pinned_cuts: list[float] | None      # explicit, survives a re-run
    derived_cuts: list[float] | None     # informational; recomputed per dataset
    veto: VetoRule; tiers: list[TierDefinition]
    label_column: str | None; size_column: str | None; segment_column: str | None
class CriterionContribution(BaseModel): ...   # column, normalised, weight, contribution, imputed
class EntityDecision(BaseModel):         # one row of the result
    entity_key: str; name: str; segment: str | None
    score: float | None; coverage: float
    status: Literal["scored","excluded","insufficient"]
    tier: int | None; notes: list[str]
    rank: int | None; rank_min: int | None; rank_max: int | None
    size: float | None; leverage: float | None; leverage_rank: int | None
    dimension_scores: dict[str, float | None]
    contributions: list[CriterionContribution]
class AuditEntry(BaseModel):             # stage, item, decision, why, needs_check,
                                         # origin: "derived" | "human", at, by
class DecisionRunRecord(BaseModel): ...  # dataset ref + framework ref + results + audit
```

`AuditEntry.origin` is the one field the prototype implies but does not
model explicitly. It is what lets a reviewer answer the question the tool
is built to answer: which rules came from the data, and which came from a
person.

### Storage — `backend/arp/storage/decision_store.py`

A direct copy of `TaxonomyStore`'s shape and philosophy:
`frameworks/<framework_id>/v<N>.json` plus a `latest.json` pointer, with
`create` / `new_version` / `ratify`, never an in-place edit. A ratified
framework is exactly what was ratified even after later edits — the same
guarantee the taxonomy library already gives.

Applying a framework is a **run**, not a store write: it goes through the
existing `RunStore` (manifest + `results.jsonl` + review queue), so Run
History, the Review Queue and the export endpoints pick it up with no new
plumbing. `runs/` gains nothing new structurally; `frameworks/` joins
`taxonomies/` and `portfolios/` in `.gitignore`.

### API — `backend/arp/api/routers/decision.py`, prefix `/api/decision`

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/datasets` | upload CSV/TSV/XLSX → `dataset_id` + profile (`safe_filename`, as `universe.py` does) |
| POST | `/datasets/from-source` | build the table from in-repo results — §6 |
| GET | `/datasets/{id}/profile` | column profiles + proposed roles/directions + the flagged guesses |
| POST | `/mechanisms/derive` | derive a `MechanismConfig` + audit log from a dataset |
| POST/GET/PUT | `/mechanisms[/{id}]` | create, list, show, new version |
| POST | `/mechanisms/{id}/ratify` | freeze a version |
| POST | `/score` | apply a framework to a dataset → `EntityDecision` rows, KPIs, histogram bins |
| GET | `/runs/{id}/results` | paged, matching the other routers' `offset`/`limit` convention |
| GET | `/runs/{id}/export.csv` | the ranked outcome as CSV |

Registered in `arp/api/main.py` alongside the existing sixteen routers.
No endpoint on this router calls an LLM, so none of them needs
`schedule_llm_run`; scoring is synchronous and fast.

### CLI — `arp decision`

`profile`, `derive`, `score`, `list`, `show`, `new-version`, `ratify`,
`export` — mirroring `arp taxonomy` command-for-command, so a framework
is manageable from the terminal exactly as a taxonomy is.

---

## 5. Frontend

`frontend/src/pages/DecisionStudio.tsx`, added to `TABS` in `App.tsx` as
"Decision Studio", with six sub-tabs via the existing `sub-nav` pattern
(as `PortfolioRisk.tsx` does): **Data / Profile / Mechanism / Decision
tree / Results / Audit**.

Reuse rather than re-create:

| Prototype element | Existing component |
| --- | --- |
| score histogram | `components/BarChart.tsx` |
| per-entity drawer | `components/InspectorModal.tsx` |
| coverage badge | `components/ConfidenceBadge.tsx` |
| ranked table | `.data-table` + `.clickable-row` in `index.css` |
| KPI row | `.card` grid, as in `ClimateAnalytics.tsx` |

New components, kept small: `MechanismEditor.tsx` (dimensions, criteria,
weights), `DecisionTreeEditor.tsx` (gates, cut-points, veto),
`ColumnProfileTable.tsx`, `AuditLogView.tsx`.

Rules for the port: **no new npm dependencies, no CDN script tags.** File
upload posts to `/api/decision/datasets` and the server parses it —
which is also what removes the `xlsx` dependency. The client renders
what the engine returns and never recomputes a score locally, so what a
reviewer sees on screen is byte-for-byte what the audit trail records.

---

## 6. The integration that makes this more than a port

`POST /api/decision/datasets/from-source` builds the decision table from
data this system already produced, instead of from an upload. Four
sources, in the order they are worth building:

1. **`transition_plan_run`** — one row per company; columns
   `disclosed_count`, `walk_disclosed_count`, `talk_disclosed_count`,
   per-category breakdowns, `overall_confidence`. This turns the paper's
   completeness metric into a tiered engagement decision, which is what
   an investor does with it.
2. **`portfolio_snapshot` + `climate`** — holdings joined to WACI,
   financed emissions and coverage per issuer. `market_value_eur` maps
   straight onto the `size` role, which makes the **leverage** ordering
   (`size × (100 − score)`) a real portfolio-weighted engagement
   priority list rather than a demo.
3. **`theme_run`** — exposure estimate, confidence, verdict, flagged
   status per matched company, for prioritising a newly built thematic
   universe.
4. **`extraction_run`** — a schema's fields pivoted to one row per
   company, so any extraction schema becomes a scoreable table without
   new code.

A `sources.py` adapter per source, each returning the same `Dataset`, is
enough. The column names each adapter emits should keep the conventions
the keyword dictionaries already recognise (`*_coverage`,
`*_intensity`, `*_flag`), so role and direction inference works on
in-repo tables as well as it does on an uploaded one.

**Closing the loop (phase 5):** a Tier-1-or-leverage-ranked result can be
posted into the engagement module as `TriggerEvent`s via
`arp/engagement/triggers.py`, which already accepts externally supplied
signals through `StaticControversySource`. The path from *"these are the
numbers"* to *"these are the companies we engage, in this order, for
this recorded reason"* then runs end to end inside the system, with the
scoring framework version attached to the trigger as its justification.

---

## 7. Precision controls to add to `docs/METHODOLOGY.md`

The existing "precision controls, concretely" section gains a
decision-mechanism block, stating each guard from §1 in the repo's terms
and, for each, what it catches:

- *Direction inference is flagged, never silent* — catches an inverted
  ranking, the failure mode that looks completely normal on screen.
- *Correlated criteria are clustered before weighting* — catches a theme
  measured seven ways outweighing one measured once by 7:1.
- *Gates resolve before the average* — catches a knockout being diluted
  into a deduction by a strong score elsewhere.
- *Sufficiency precedes scoring* — catches a company ranked first on a
  third of the criteria.
- *Missing data is re-weighted, not imputed, by default* — catches an
  invented value entering a published ranking.
- *Rank stability across four specifications* — catches a ranking that
  only holds under one arbitrary weighting choice.
- *The dimension floor applies only to dimensions with ≥2 criteria* —
  catches a single binary answer demoting a company on its own.
- *Every automated choice and every human edit is logged with its basis*
  — makes the framework defensible to a client, a regulator or a
  committee.

The entropy weighting's formula in particular should be written out
there rather than left implicit in code: it is a CRITIC/entropy-weight
variant computed over the min–max normalised values across entities, with
a `+1` offset before normalisation to a probability distribution.

---

## 8. Reuse map

| Need | Already exists | New |
| --- | --- | --- |
| Excel parsing | `openpyxl` (`arp/ingestion/local_files.py`) | — |
| CSV variant handling | `arp/research/taxonomy_sources/etf_holdings.py` | locale/boolean detection |
| Upload endpoint + safe paths | `arp/api/routers/universe.py`, `arp/storage/safe_path.py` | — |
| Versioned, ratifiable artefact store | `arp/storage/taxonomy_store.py` | `decision_store.py` (same shape) |
| Run manifest, results, review queue | `arp/storage/run_store.py` | — |
| Charts, tables, modal, badges | `frontend/src/components/*` | 4 small editors |
| Deterministic engine precedent | `arp/portfolio/aggregation.py` | `arp/decision/*` |
| Statistics | `numpy` (already a dependency) | — |

No new backend or frontend dependency is required.

---

## 9. Phased roadmap

**Phase 1 — engine + regression fixture (no UI).**
`arp/decision/*`, `arp/schemas/decision.py`, `arp decision derive|score`
against a CSV. Ship the prototype's bundled dataset as
`backend/arp/decision/sample_data/example_transition_universe.csv` and
assert that the Python port reproduces the prototype's numbers on it —
scores, dimension groupings, cut-points, tiers and rank ranges. This is
the phase that matters: the port is only worth having if it is provably
the same mechanism. Fix the §3 defects here (the 0.72/0.60 audit-log
mismatch, pinned vs. derived cut-points), and add tests for the two
undocumented behaviours (lone-value percentile → 50, booleans bypass
winsorising).

**Phase 2 — persistence + API.** `decision_store.py`, the
`/api/decision` router, `RunStore` integration so results appear in Run
History.

**Phase 3 — frontend.** `DecisionStudio.tsx` and the four editors,
re-implemented in the app's design system.

**Phase 4 — in-repo sources.** `sources.py` adapters, starting with
`transition_plan_run` and `portfolio_snapshot + climate`.

**Phase 5 — close the loop.** Ranked results into the engagement queue
as trigger events, carrying the framework version as justification.

Phases 1 and 2 are independently useful — the CLI alone makes every
existing run result scoreable and auditable, before any UI exists.

---

## 10. Open questions

1. **Does a framework belong to a dataset shape or to a decision?** The
   prototype implicitly binds one to a column signature. Binding a
   framework to a *named decision* ("climate engagement prioritisation")
   and letting it declare required columns is more useful, but needs a
   column-mapping step when the source table's names differ.
2. **Should tier assignments enter the review queue?** Consistent with
   the rest of the codebase, a tier that flips between quarters, or an
   entity whose rank range spans more than one tier, is a strong
   review-queue candidate. It also adds queue volume; worth deciding
   before phase 2.
3. **Clustering threshold as policy.** ρ ≥ 0.72 is a judgement call baked
   into a constant. It should be a framework field with the default
   documented, not a code constant — but then two frameworks with
   different thresholds are not directly comparable, which needs saying
   in the audit log.
4. **Where do gate rules on numeric columns come from?** The prototype
   auto-derives gates only from boolean flag columns; numeric gates
   ("intensity above X") are manual-only. Auto-proposing numeric gates
   from distribution shape is possible but is a much weaker inference
   than the boolean case, and probably should stay manual.
5. **Cross-framework comparison.** Once several frameworks exist, "how
   differently would framework B have ranked this universe" is an
   obvious question, and the rank-stability machinery in `stability.py`
   already computes exactly that kind of comparison. Not phase 1.

---

## 11. The prototype file itself

`docs/prototypes/decision-mechanism-studio.html` is kept in the
repository as the **UX and behaviour specification** for phases 1 and 3 —
not built, not served, and not linked from the app. It loads a script
from a CDN (§3.5), which is on its own sufficient reason not to ship it.
Open it directly in a browser to see the interaction the React page
should reproduce; read it alongside §2 for what each tab is doing
underneath.
