# Company-level theme exposure: revenue share, momentum, tier and value-chain role

Status: Draft, for owner approval
Slug: `theme-company-exposure`
Risk: `risk:normal` (one read-only API endpoint, three settings, one optional field on two models stored as JSON; no
migration, no auth, money, UI or `risk:high` path)
Size: two slices, `M` then `S` (see `## Slices`). R&D Lab plan items 8 (8a rollup + API, 8b tier thresholds as
settings) and 9 (value-chain role). Fixes the "one row per company × activity" half of findings P5 and U2.

## Decisions for the owner

None needed a question. Every choice is under "Defaults taken"; approving the spec approves them. Two change what a
user will see, so say "Not approved" if either is wrong:

- D1 tier thresholds: **Pure play ≥ 70 %**, **Majority ≥ 50 %**, **Partial ≥ 5 %**, below that **Ecosystem**
  (settings, so they can be changed without code).
- D3 a company with no revenue number gets its tier from the debate's label: `pure_play` → Pure play,
  `significant` → Partial, `minor` or `none` → Ecosystem.

## Why

A theme run stores one `CompanyMatch` per company × activity. Nothing rolls those up to the company, so:

- There is no "how much of this company is in the theme": a company with 71 % of revenue in stacks and 11 % in
  services shows as two unrelated rows.
- There is no tier. The market (FTSE Russell / LSEG, MSCI, Bloomberg Intelligence; plan "What the leaders do")
  sorts companies into classes such as Pure play, Majority, Partial and lets the analyst build baskets from them.
  Mock-up screens 6 (Theme Workbench) and 8 (Exposure map and baskets) need a tier, a revenue share, a momentum
  score and a role per company.
- `CompanyRole` (`arp/research/company_role.py`) says pure player / diversified / innovator, but nothing says whether
  a company **makes** the thing or **buys** it. "Makes electrolysers" and "buys electrolysers" look the same today.

## What the user can do afterwards that they cannot do today

1. Call `GET /api/themes/runs/{run_id}/exposure` and get one row per company of the run: revenue share in the theme
   (with its source label and, for modelled shares, a range), a momentum score from signals the run already holds,
   a tier, a value-chain role, and a "needs check" flag. The Theme Workbench (plan item 13) draws screens 6 and 8
   from it.
2. Change the tier thresholds through `ARP_THEME_TIER_PURE_PLAY`, `ARP_THEME_TIER_MAJORITY`, `ARP_THEME_TIER_PARTIAL`.
3. After slice 2, see in each new match whether the judge found that the company makes, develops, operates or buys
   the activity, and get the role Developer / Maker / Supplier / Operator / Adopter from it.

## What exists today (main `e4cb8c3`)

- Results: `RunStore` (`arp/db/runs.py`) keeps one result row per company, `{"_key": company_id,
  "company_matches": [<CompanyMatch as JSON>, ...]}`; `read_results(run_id)` returns those dicts and
  `load_companies(run_id)` the run's `CompanyRef`s. `create_theme_run` (`arp/research/pipeline.py`) writes the
  run's `ThemeDefinition` to `<run_store.run_dir(run_id)>/theme.json`.
- `CompanyMatch` (`arp/schemas/thematic.py`): `verdict` (`include` / `exclude` / `uncertain`), `exposure_estimate`
  (`pure_play` / `significant` / `minor` / `none`), `revenue_exposure.revenue` and `.capex` (`MetricExposure`:
  `value_pct` 0–1, `source`), `rd_exposure.rd_intensity` and `.news_mentions` (`MetricExposure`),
  `arbitration.methods_disagree`, `company_role` (`pure_player` / `diversified` / `innovator`),
  `flagged_for_review`.
- `ActivityDefinition.tier` is `core`, `enabling` or `critical_input`.
- `AdjudicatorOutput` (`arp/research/matcher_agents.py`): `verdict`, `exposure_estimate`, `confidence`,
  `adjudicator_rationale`, `citations`. The model fills it as structured output, so field descriptions reach it as
  part of the schema.
- Exposure layers (`arp/research/exposure_layers.py`, `GET /api/themes/runs/{run_id}/layers`, spec
  `2026-10-18-themes-exposure-layers-design.md`) are computed on read from the stored results; this spec follows the
  same pattern and does not change them.
- Momentum-type signals a theme run already holds per match: R&D intensity (`rd_exposure.rd_intensity`, source
  `extracted`), news mentions (`rd_exposure.news_mentions`, source `news`) and the capex share
  (`revenue_exposure.capex`). Orders and a mention *trend* exist only on Theme Radar candidates
  (`emerging_themes`: `ActionType.ORDERS` claims, `CompanyActionEvidence`), not in theme runs.

### Labels from `theme-revenue-share` (written in parallel)

This spec reads these names and does not depend on that spec's build order (agreed with its author 2026-11-26):

- `revenue_exposure.revenue.source` gains `reported` and `modelled` beside `catalogue`, `extracted`, `qualitative`,
  `unresolved` (and `news`, which revenue never uses).
- `MetricExposure` gains `low_pct` and `high_pct` (0–1), set only when `source` is `modelled`; then `value_pct` is
  their midpoint.

Until that spec is built, stored matches simply never carry `reported` or `modelled`, and everything below still
works with `catalogue` and `extracted`. The rollup reads the stored JSON dicts (as the layers do), not
`CompanyMatch`, so a stored `reported` / `modelled` value or a `relation` key is read even before the models accept
it.

## Goals

- G1 One row per company of a theme run, with revenue share summed over the activities it is in.
- G2 The share's source label and, when any part is modelled, a low–high range.
- G3 A momentum score and band from the signals the run already holds, no new source.
- G4 A tier Pure play / Majority / Partial / Ecosystem / Out, computed on read, with thresholds as settings.
- G5 A value-chain role Developer / Maker / Supplier / Operator / Adopter from the activity tier and the debate.
- G6 A "needs check" flag when the run already says the signals disagree or a match needs review.
- G7 The judge states whether the company makes, develops, operates or buys the activity (slice 2).

## Non-goals

- Any screen. The Theme Workbench, the exposure map and baskets are plan item 13.
- New momentum sources: orders, hiring, a mention trend over time, SEC capex / R&D year-on-year. A later item can add
  them to the signal list below.
- Changing how a revenue share is found or labelled (`theme-revenue-share`) or how matching works
  (`matcher-shared-retrieval`); this spec adds one optional judge field and reads the rest.
- Storing the rollup, a CLI command, or Decision Studio / Portfolio Builder export.
- A tier override with a reason (screen 7's "Change tier"); a later item.
- Changing `CompanyRole`, the layers, or `GET /api/themes/runs/{run_id}/results`.

## Anti-goals (must stay true)

- No model call to compute the rollup; it is a pure function of the stored results, `theme.json` and the settings.
- The layers endpoint, the results endpoint and every existing theme-run test behave as on `main`.
- A stored match without `relation`, `low_pct` or `high_pct` is read as if they were null.

## Design

### Slice 1: `GET /api/themes/runs/{run_id}/exposure` (items 8a, 8b, and the role rule of item 9)

New module `arp/research/company_exposure.py` (pure functions over the stored dicts) and one route in
`arp/api/routers/themes.py` with a response model. Any signed-in user (`viewer` and up), as the layers.

**Order of checks:** authentication (401), run exists and `run_type` is `theme` (else 404, `detail` =
`unknown theme run '<run_id>'`), tier settings (503).

**Settings** (`arp/config.py`, read when the request is served, as the layers do with `Settings()`):

| Setting | Env | Default |
|---|---|---|
| `theme_tier_pure_play` | `ARP_THEME_TIER_PURE_PLAY` | 0.70 |
| `theme_tier_majority` | `ARP_THEME_TIER_MAJORITY` | 0.50 |
| `theme_tier_partial` | `ARP_THEME_TIER_PARTIAL` | 0.05 |

Valid when each is greater than 0 and at most 1 and `partial < majority < pure_play`. Otherwise 503 with `detail`:
`<ENV NAME> must be greater than 0 and at most 1` for the first out-of-range one in the order pure play, majority,
partial; else `ARP_THEME_TIER_PARTIAL < ARP_THEME_TIER_MAJORITY < ARP_THEME_TIER_PURE_PLAY is required`.

**Inputs.** Companies = `load_companies(run_id)` in their order (none stored → no rows). A company's matches = the
`company_matches` of every result row whose `_key` is its `company_id`, in stored order. Activity tiers =
`activities[*].tier` by `activity_id` from `<run_dir>/theme.json`; an activity not found there, or no
`theme.json`, counts as `core`.

**Per match** (`m` a stored dict; "included" = `m["verdict"] == "include"`; `rev` = `m["revenue_exposure"]["revenue"]`
when `revenue_exposure` is set):

- `share`: when included and `rev.source` is `reported`, `catalogue`, `extracted` or `modelled` and
  `rev.value_pct` is not null: `rev.value_pct`. Otherwise null.
- `share_low` / `share_high`: `rev.low_pct` / `rev.high_pct` when `share` is set and `rev.source` is `modelled`;
  otherwise null.
- `basis`: `rev.source` when `share` is set; `label` when included and `share` is null; null when not included.
- `relation`: `m.get("relation")` (one of `makes`, `develops`, `operates`, `buys`, or null).
- `role` (null when not included), first rule that applies:
  1. `relation` `buys` → `adopter`; `operates` → `operator`; `develops` → `developer`.
  2. `relation` null and `company_role` `innovator` → `developer`.
  3. Otherwise (`makes`, or null and not innovator): activity tier `core` → `maker`; `enabling` or
     `critical_input` → `supplier`.

**Per company:**

- `share`: the sum of its matches' `share`, capped at 1; null when no match has one.
- `share_low` / `share_high`: null unless some match has `basis` `modelled`; then the sum over matches with a `share`
  of (`share_low` if it is not null, else `share`), and likewise with `share_high`, each capped at 1. So a
  modelled match stored without `low_pct` / `high_pct` adds its `share` to both sums.
- `share_basis`: when `share` is set, the weakest `basis` among matches with a `share`, strongest first:
  `reported`, `catalogue`, `extracted`, `modelled`. Else `label` when the company has an included match. Else null.
- `tier`:
  - `out` when no match is included (exclude, uncertain, or no matches).
  - Else the higher of (a) the tier of `share` — `pure_play` if `share ≥ pure_play`, `majority` if
    `≥ majority`, `partial` if `≥ partial`, else `ecosystem`; none when `share` is null — and (b) for each included
    match with `basis` `label`, its `exposure_estimate`: `pure_play` → `pure_play`, `significant` → `partial`,
    `minor` or `none` → `ecosystem`. Higher means earlier in `pure_play`, `majority`, `partial`, `ecosystem`.
- Momentum signals, each over included matches only, the largest value, null when none:
  `rd` = `rd_exposure.rd_intensity.value_pct` where its `source` is `extracted`; `mentions` =
  `rd_exposure.news_mentions.value_pct` where its `source` is `news`; `capex` = `revenue_exposure.capex.value_pct`
  where its `source` is `reported`, `catalogue`, `extracted` or `modelled`.
- `momentum`: the mean of the non-null signals; null when all three are null.
- `momentum_band`: `high` when `momentum ≥ 0.5`, `medium` when `≥ 0.2`, `low` otherwise, null when `momentum` is null.
- `role`: the `role` of its lead match, null when `tier` is `out`. Lead = among included matches, the one with the
  largest `share` (null counts as below any number); tie → higher `exposure_estimate` (`pure_play`, `significant`,
  `minor`, `none`); tie → `activity_name` ascending.
- `needs_check`: true when an included match has `flagged_for_review` true or `arbitration.methods_disagree` true.

**Order of rows:** `tier` in the order `pure_play`, `majority`, `partial`, `ecosystem`, `out`; then `share`
descending (null last); then `momentum` descending (null last); then `name` ascending; then `company_id` ascending.

**Response** (numbers rounded to 4 decimals with Python's `round`, computed from unrounded values):

```
{"run_id": str,
 "thresholds": {"pure_play": float, "majority": float, "partial": float},
 "rows": [{"company_id", "name", "tier", "share", "share_low", "share_high", "share_basis",
           "momentum", "momentum_band", "momentum_signals": {"rd", "capex", "mentions"},
           "role", "needs_check",
           "activities": [{"activity_id", "activity_name", "verdict", "share", "share_low", "share_high",
                           "basis", "relation", "role"}]}]}
```

`activities` holds every match of the company, in stored order. Run `backend/scripts/export_openapi.py` and
`npm run gen:api` and commit both generated files (`.claude/CLAUDE.md`, Checks); no frontend call is added, so no
`contract.ts` line.

### Slice 2: the judge states the relation (item 9)

- `AdjudicatorOutput` and `CompanyMatch` each get
  `relation: Literal["makes", "develops", "operates", "buys"] | None = None`, on `AdjudicatorOutput` with
  `Field(default=None, description=...)`, the description exactly:
  `How the company relates to the activity: makes (it makes and sells it, or a part of it), develops (R&D, pilots or
  prototypes, not yet selling), operates (it runs assets that use it to sell something else), buys (it buys or uses
  it). Null if the evidence does not say.`
- `_run_adjudicator_node` (`arp/research/match_graph.py`) copies `adjudication.relation` into the match. Every other
  path (revenue-resolved, no evidence, screened out by the funnel) leaves it null. No prompt text changes.
- Old stand-in files without `relation` stay valid (default null). Regenerate the OpenAPI types (`CompanyMatch`
  changed).

## Defaults taken

1. **D1 tier thresholds 70 / 50 / 5 %.** "Majority" has to mean at least half, so Pure play sits above it; 70 % keeps
   the mock-up's pure plays (82 %, 91 %) apart from its majority names (54 %, 61 %). 5 % equals today's
   `revenue_exposure_minor_threshold`. The layers' `pure_play` flag (≥ 50 %, `ARP_REVENUE_EXPOSURE_PURE_PLAY_THRESHOLD`)
   and `CompanyRole.pure_player` are separate and unchanged.
2. **D2 share = sum over included activities, capped at 1.** Screen 7 adds stacks 71 % and services 11 % to 82 % "in
   the theme". Excluded activities add nothing, even with a number.
3. **D3 label fallback** as listed at the top. `significant` is "material but not primary", so not Majority.
4. **D4 mixed numbers and labels:** the higher tier wins, so a strong label on an activity without a number is not
   hidden by a small number on another.
5. **D5 the weakest source labels the company**, so a share is never shown as `reported` when part of it is modelled.
6. **D6 momentum = plain mean of R&D intensity, capex share and news mentions**, largest per company. Each is already
   0–1 on the match. Orders and a mention trend have no per-company signal in a theme run today (Non-goals). Bands
   0.5 / 0.2 are constants, not settings (only the tiers were asked for as settings).
7. **D7 role** from the judge's relation first, then `CompanyRole.innovator`, then the activity tier. Operator =
   uses it to sell something else (a gas company running electrolysers); Adopter = buys or uses it.
8. **D8 one role per company**, from the activity with the largest share; every activity's own role is in
   `activities`.
9. **D9 `needs_check`** reuses `flagged_for_review` and `arbitration.methods_disagree` (screen 8's "signals
   disagree").
10. **D10 computed on read**, like the layers: no stored rollup, no recompute step, no migration.

## Acceptance

Setup notes for the test-writer:

- A theme run is created through `RunStore(dsn, runs_dir)` on the app's `ARP_POSTGRES_DSN` and `ARP_RUNS_DIR`:
  `save_manifest(RunManifest(run_id=R, run_type="theme"))`, `save_companies(R, [CompanyRef(company_id=..., name=...)])`,
  one `append_result(R, {"_key": <company_id>, "company_matches": [...]})` per company that has matches, and
  `<run_store.run_dir(R)>/theme.json` = a `ThemeDefinition` JSON. Settings are read from the environment when the
  request is served; tests set them before building the app. Holdout tests run the app with `ARP_AUTH_MODE=local`.
- A match is a dict: `CompanyMatch(company_id=..., name=..., activity_id=..., activity_name=..., verdict=...,
  exposure_estimate=..., confidence=0.9, adjudicator_rationale="r").model_dump(mode="json")`, then the keys the
  fixture lists are set on the dict (so `reported`, `modelled`, `low_pct`, `high_pct` and `relation` can be stored
  before the models accept them). `rev(x, src)` = `revenue_exposure` set to `{"activity_id": <its activity>,
  "revenue": {"value_pct": x, "source": src}, "capex": {"value_pct": null, "source": "unresolved"},
  "sector_relevant": true}`. `rd(r, n)` = `rd_exposure` set to `{"activity_id": <its activity>, "rd_intensity":
  {"value_pct": r, "source": "extracted" if r is not null else "unresolved"}, "news_mentions": {"value_pct": n,
  "source": "news" if n is not null else "unresolved"}, "sector_relevant": true}`. Unlisted keys keep the dict's
  values (`revenue_exposure` and `rd_exposure` null, `relation` absent, `flagged_for_review` false).
- "X's row" is the element of `rows` whose `name` is X. "Order" is `[r["name"] for r in rows]`.

**Fixture G.** `theme.json` = `ThemeDefinition(name="Electrolysers", description="d", activities=[...])` with three
`ActivityDefinition`s (`in_scope_description` `i`, `out_of_scope_description` `o`): `act_stacks` "Stacks" tier
`core`, `act_bop` "Balance of plant" tier `enabling`, `act_svc` "Services" tier `core`. Companies, in this order:

| company | matches (stored order) |
|---|---|
| Alpha | `act_stacks` include, `pure_play`, `rev(0.71, "reported")`, `relation` `makes`, `rd(0.14, 0.60)`; `act_svc` include, `significant`, `rev(0.11, "extracted")`; `act_bop` exclude, `none` |
| Beta | `act_bop` include, `minor`, `rev(0.08, "modelled")` with `revenue.low_pct` 0.05 and `revenue.high_pct` 0.11 and `capex` = `{"value_pct": 0.30, "source": "extracted"}`, `relation` `makes` |
| Gamma | `act_stacks` include, `significant`, `relation` `operates` |
| Delta | `act_stacks` exclude, `none`, `rd(0.90, null)` |
| Epsilon | `act_stacks` include, `pure_play`, `rev(0.55, "catalogue")`, `flagged_for_review` true, `company_role` `pure_player` |
| Zeta | `act_stacks` include, `minor`, `company_role` `innovator`, `rd(0.80, null)` |
| Omega | no result row |

Default settings unless a row says otherwise. Requests are `GET /api/themes/runs/R/exposure` signed in as a `viewer`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture G | request | 200; body keys exactly `run_id`, `thresholds`, `rows`; `thresholds` = `{"pure_play": 0.7, "majority": 0.5, "partial": 0.05}` | holdout |
| AC-2 | Fixture G | request | Order = `["Alpha", "Epsilon", "Beta", "Gamma", "Zeta", "Delta", "Omega"]` | holdout |
| AC-3 | Fixture G | request | Every row has exactly the keys `company_id`, `name`, `tier`, `share`, `share_low`, `share_high`, `share_basis`, `momentum`, `momentum_band`, `momentum_signals`, `role`, `needs_check`, `activities`; every element of `activities` exactly `activity_id`, `activity_name`, `verdict`, `share`, `share_low`, `share_high`, `basis`, `relation`, `role` | holdout |
| AC-4 | Fixture G | request | Alpha's row: `tier` `pure_play`, `share` 0.82, `share_low` null, `share_high` null, `share_basis` `extracted`, `momentum` 0.37, `momentum_band` `medium`, `momentum_signals` `{"rd": 0.14, "capex": null, "mentions": 0.6}`, `role` `maker`, `needs_check` false | holdout |
| AC-5 | Fixture G | request | Alpha's `activities` = `[{"activity_id": "act_stacks", "activity_name": "Stacks", "verdict": "include", "share": 0.71, "share_low": null, "share_high": null, "basis": "reported", "relation": "makes", "role": "maker"}, {"activity_id": "act_svc", "activity_name": "Services", "verdict": "include", "share": 0.11, "share_low": null, "share_high": null, "basis": "extracted", "relation": null, "role": "maker"}, {"activity_id": "act_bop", "activity_name": "Balance of plant", "verdict": "exclude", "share": null, "share_low": null, "share_high": null, "basis": null, "relation": null, "role": null}]` | holdout |
| AC-6 | Fixture G | request | Beta's row: `tier` `partial`, `share` 0.08, `share_low` 0.05, `share_high` 0.11, `share_basis` `modelled`, `momentum` 0.3, `momentum_band` `medium`, `role` `supplier` | holdout |
| AC-7 | Fixture G | request | Gamma's row: `tier` `partial`, `share` null, `share_basis` `label`, `momentum` null, `momentum_band` null, `role` `operator` | holdout |
| AC-8 | Fixture G | request | Delta's row: `tier` `out`, `share` null, `share_basis` null, `momentum` null, `momentum_signals` `{"rd": null, "capex": null, "mentions": null}`, `role` null, `needs_check` false | holdout |
| AC-9 | Fixture G | request | Epsilon's row: `tier` `majority`, `share` 0.55, `share_basis` `catalogue`, `role` `maker`, `needs_check` true | holdout |
| AC-10 | Fixture G | request | Zeta's row: `tier` `ecosystem`, `share_basis` `label`, `momentum` 0.8, `momentum_band` `high`, `role` `developer` | holdout |
| AC-11 | Fixture G | request | Omega's row: `tier` `out`, `share` null, `role` null, `activities` `[]` | holdout |
| AC-12 | Fixture G with `ARP_THEME_TIER_PURE_PLAY=0.9` | request | `thresholds.pure_play` 0.9; Alpha's `tier` `majority`; order starts `["Alpha", "Epsilon", "Beta"]` | holdout |
| AC-13 | Fixture G with `ARP_THEME_TIER_PARTIAL=0.1` | request | Beta's `tier` `ecosystem`; Gamma's `tier` `partial` | holdout |
| AC-14 | Fixture G with `ARP_THEME_TIER_MAJORITY=0.8` | request | 503; `detail` = `ARP_THEME_TIER_PARTIAL < ARP_THEME_TIER_MAJORITY < ARP_THEME_TIER_PURE_PLAY is required` | holdout |
| AC-15 | Fixture G with `ARP_THEME_TIER_PURE_PLAY=1.5` | request | 503; `detail` = `ARP_THEME_TIER_PURE_PLAY must be greater than 0 and at most 1` | holdout |
| AC-16 | Fixture G with `ARP_THEME_TIER_PARTIAL=0` | request | 503; `detail` = `ARP_THEME_TIER_PARTIAL must be greater than 0 and at most 1` | holdout |
| AC-17 | Fixture G plus a Beta match `act_stacks` include, `minor`, `rev(0.20, "reported")` stored after its `act_bop` match | request | Beta's row: `share` 0.28, `share_low` 0.25, `share_high` 0.31, `share_basis` `modelled`, `role` `maker` (lead is `act_stacks`, the larger share) | holdout |
| AC-18 | A run with company Eta: `act_stacks` include, `minor`, `rev(0.10, "extracted")`; `act_svc` include, `pure_play`, no `revenue_exposure` | request | Eta's row: `tier` `pure_play`, `share` 0.1, `share_basis` `extracted` | holdout |
| AC-19 | A run with company Theta: `act_stacks` include `rev(0.70, "reported")`, `act_svc` include `rev(0.60, "reported")`, both `significant` | request | Theta's row: `share` 1.0, `tier` `pure_play`, `share_basis` `reported` | holdout |
| AC-20 | Fixture G with Gamma's `relation` `buys` | request | Gamma's `role` `adopter` | holdout |
| AC-21 | Fixture G with Gamma's `relation` `develops` | request | Gamma's `role` `developer` | holdout |
| AC-22 | Fixture G with Zeta's `relation` `makes` | request | Zeta's `role` `maker` (the judge's relation wins over `innovator`) | holdout |
| AC-23 | Fixture G without `theme.json` | request | 200; Beta's `role` `maker` (unknown activity tier counts as `core`) | holdout |
| AC-24 | A run with companies Pa and Qa, each `act_stacks` include, `significant`, `rev(0.10, "reported")`; Pa `rd(0.20, null)`, Qa `rd(null, 0.60)` | request | Order = `["Qa", "Pa"]` (same tier and share, higher momentum first); Pa's `momentum_band` `medium` | holdout |
| AC-25 | A run with company Iota: `act_stacks` include, `minor`, `rd(0.50, null)`; and company Kappa: `act_stacks` include, `minor`, `rd(0.19, null)` | request | Iota's `momentum_band` `high`; Kappa's `momentum_band` `low` | holdout |
| AC-26 | A run with company Lambda: `act_stacks` include, `minor`, `rev(0.30, "qualitative")` with `arbitration` = `{"composite_score": 0.3, "methods_disagree": true, "disagreement_spread": 0.5, "mid_band": true, "contributions": [], "rationale": ""}` | request | Lambda's row: `needs_check` true, `share` null, `share_basis` `label`, `tier` `ecosystem` | holdout |
| AC-27 | A run with company Mu: `act_stacks` uncertain, `none`, `rev(0.40, "extracted")` | request | Mu's row: `tier` `out`, `share` null, its activity's `share` null and `basis` null | holdout |
| AC-28 | No run `nope` | `GET /api/themes/runs/nope/exposure` | 404; `detail` = `unknown theme run 'nope'` | holdout |
| AC-29 | An existing run whose `run_type` is `extraction` | `GET /api/themes/runs/<its id>/exposure` | 404; `detail` = `unknown theme run '<its id>'` | holdout |
| AC-30 | Fixture G; no `Authorization` header | request | 401; `detail` = `Missing or invalid bearer token` | holdout |
| AC-39 | A run with company Xi: `act_stacks` include, `minor`, `rev(0.20, "modelled")` with no `low_pct` / `high_pct` | request | Xi's row: `share` 0.2, `share_low` 0.2, `share_high` 0.2, `share_basis` `modelled`; its activity's `share_low` null | holdout |
| AC-40 | Fixture G; the app's `ARP_STANDINS_DIR` an empty directory | request | 200, Alpha's row as in AC-4, and no `calls.jsonl` exists in that directory (no model call) | holdout |

Slice 2 rows call `arp.research.match_graph.match_company_activity` directly for one company and one activity
(seed keyword `electrolyser`, tier `core`), as in `theme-precision-scorecard` AC-23: default settings with
`hybrid_retrieval_enabled=False`, an LLM built by `build_llm_client` under `ARP_STANDINS_DIR`, one document `doc_1`
with text `We manufacture electrolyser stacks.` (`documents_by_id` = `{"doc_1": <it>}`). Stand-in `AgentOpinion` =
one entry (`stance` `s`, `rationale` `r`, no citations, `exposure_estimate` `pure_play`); stand-in
`AdjudicatorOutput` = include, `pure_play`, confidence 0.9, rationale `r`, one citation (`doc_id` `doc_1`,
`doc_type` `annual_report`, quote `We manufacture electrolyser stacks.`), plus what the row says; every entry
wrapped as `{"output": …}`. "Then" reads the returned match.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-31 | Stand-in `AdjudicatorOutput` with `"relation": "buys"` | Call it | `match.relation == "buys"` | holdout |
| AC-32 | Stand-in `AdjudicatorOutput` without a `relation` key | Call it | `match.relation is None`; `verdict` `include` | holdout |
| AC-33 | The document's text is `We make cement.` (no keyword hit) | Call it | `match.relation is None`; `verdict` `exclude` | holdout |
| AC-34 | AC-31's match stored as company Nu's only match in a run whose `theme.json` gives its activity tier `core` | `GET /api/themes/runs/<run>/exposure` | Nu's row: `role` `adopter`; its activity's `relation` `buys` | holdout |
| AC-35 | The repository | `AdjudicatorOutput.model_json_schema()["properties"]["relation"]` | Its `description` is the text under "Slice 2", and its allowed values are exactly `makes`, `develops`, `operates`, `buys` and null | unit |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-36 | Fixture G | `GET /api/themes/runs/R/results` | `results` equals the stored matches of fixture G in stored order, except that each non-null `revenue_exposure` also has `opex` = `{"value_pct": null, "source": "unresolved", "confidence": 1.0, "matched_catalogue_labels": [], "citation": null, "notes": ""}` (as on `main`); no other key is added or changed | holdout |
| AC-37 | The existing layers, theme-run, matcher and precision-scorecard tests under `backend/tests/` | Run on this branch | All pass with no edits to those test files | unit |
| AC-38 | The existing backend and frontend test suites on `main` | Run on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

## Slices

Two PRs, each `risk:normal` with `Spec: theme-company-exposure` and its `Rows:` line. Order: 1, then 2.
Slice 2 touches `matcher_agents.py`, `match_graph.py` and `schemas/thematic.py`, which `matcher-shared-retrieval`
and `theme-precision-scorecard` slice 2 also change: it starts after `matcher-shared-retrieval` merges and merges
`origin/main` first. Neither slice waits for `theme-revenue-share`.

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | M | `arp/research/company_exposure.py`, the `/exposure` route and response model in `arp/api/routers/themes.py`, three tier settings in `arp/config.py`, OpenAPI + generated types, tests | AC-1 to AC-30, AC-36 to AC-40 |
| 2 | S | `relation` on `AdjudicatorOutput` and `CompanyMatch`, copied in `_run_adjudicator_node`, OpenAPI + generated types, tests | AC-31 to AC-35, AC-37, AC-38 |
