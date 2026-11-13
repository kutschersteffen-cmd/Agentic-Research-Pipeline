# Stewardship priority worklist: one sortable list of every company, with the score as one column

Slug: `stewardship-priority-worklist`. Risk: normal (no migration, no new database schema, no stored score
history). Size M, 3 PRs.

Status: **draft for owner approval**.

Owner decisions so far:

- 13 Nov 2026 (intake, buttons): build the prioritisation feature from the AI-native stewardship paper now.
- Owner's words: "For prioritization I want this priority score to be just one indicator based on which I can
  select besides of many." The score never gates, hides or selects anything. It is one column among many that
  a person can sort, filter and select on.
- Intake scope: one worklist, indicators as columns, a code-computed weighted score with each component's
  contribution shown, weights in an editable versioned policy, a person selects rows into the cycle's
  engagement selection and a person confirms, everything computed on read.
- Q1 to Q3 below: <pending; filled in from the owner's buttons>.

## Why

Today the steward sees the companies in scope only through separate screens: coverage tiers (Selection), stored
triggers (Monitoring), engagements and commitments (Tracking), simulated ESG (Transition Intelligence). Deciding
which companies to engage this cycle means holding all of them in one's head. The worklist puts them side by side,
one row per company, so the steward can sort and filter on whatever matters this cycle and pick the companies.

The score helps, but is not the decision. A company with score 12 can be picked over one with score 80, and the
tool records the pick the same way.

## Goals

1. `GET /api/stewardship/worklist`: one row per company in the house universe, with the indicator columns below,
   computed from stored values on every request.
2. A priority score from 0 to 100: a weighted sum, computed by code, with each component's contribution returned.
3. The weights live in a versioned house policy `priority_weights`, edited, previewed and activated like the
   coverage rules.
4. A new Steward Workflow tab **Worklist** (`#/stewardship/worklist`): sort on up to three columns, filter on every
   column, a "Why is this here" panel per row, `Simulated` labels, and selecting rows into the cycle's engagement
   selection, which a person then confirms.
5. In PR 3: the commitment loop's broken commitments as a column and score component, and a new-trigger refresh
   check.

## Non-goals (later specs)

- The three queues (e.g. "must engage / should consider / monitor"), batch confirmation and the random audit sample.
- Weights set or suggested by a model. The score is plain arithmetic in code.
- New data sources: no meeting calendar feed, no new ESG data.
- Changing the logic of `tiers.py`, `monitoring.py` or `program.py`. The worklist reads them.
- Opening engagements from the selection. A confirmed selection is a list; opening engagements stays where it is
  today (Monitoring → open engagement, `POST /api/engagement/records/{id}/issues`).
- A stored score history, score snapshots or a score table (that would make the risk high).

## Anti-goals

- The score deciding anything: no default filter on the score, no hidden rows, no pre-ticked rows, no "auto-select
  top N" button.
- A simulated value read as real. Every simulated value carries `Simulated`, in the cell, in the column header and in
  the why panel (AC-21, AC-22).
- A score nobody can explain. Each row's points add up to its score, component by component, in the panel.
- Stale numbers. No cache: a trigger or overdue commitment stored a second ago shows on the next request (AC-13).

## Constraints

- Computed on read from what the app already stores. No migration, no new Postgres table, no change to
  `postgres_schema.py`. The selection log is an append-only JSONL file under `stewardship_streams_dir`, like
  `tier_assignments.jsonl` and the trigger log.
- Engagements are read through the engagement store interface (`EngagementStore.list_all()`, the store the factory
  from `stewardship-data-foundation` returns), never from the files directly.
- Request and response models are new, so `scripts/export_openapi.py` and `npm run gen:api` run in PR 1 (and PR 3
  for the new field) and both generated files are committed; each new `request<T>()` gets a line in
  `frontend/src/api/contract.ts`.
- Reads need role `viewer`; selecting, confirming and saving weights need `analyst` or above; activating a weights
  version follows the existing four-eyes rule of `PolicyStore.activate`.
- Frontend rules: the PR 2 screen is checked with impeccable and ui-ux-pro-max, and the PR carries a Playwright
  screenshot of `#/stewardship/worklist` with 400 seeded companies.
- Works for 400 companies (MSCI World demo) and for 2,500 (the full house universe once more portfolios load).

## Approaches considered

1. **Compute on read, one endpoint, sort and filter in the browser (picked).** The backend joins the stores it
   already has into rows and scores them; the browser holds all rows (2,500 rows ≈ 1 MB JSON before gzip) and sorts
   and filters them in memory. Simple, always current, no schema. Cost: every page load recomputes.
2. Server-side sort, filter and paging. Scales past 10,000 rows, but every sort or filter is a round trip and the
   API grows a query language. Not needed at 2,500.
3. A nightly score table. Fast reads, but stale between runs and it is a stored score history, which the intake rules
   out (risk high).

## Indicator columns (version 1)

One row per issuer in `house_universe()` (as `load_sample()` returns it, so the coverage rules and the worklist see
the same companies). "Score part" is the component id in `priority_weights`; every column except Company and Sector
can carry a weight. Empty cells show `—` and add 0 points; the why panel says `no data`.

| # | Column (header) | Source | Unit, format | Empty when | Score part: value → 0..1 |
|---|---|---|---|---|---|
| 1 | Company | `issuer.name`, `issuer_id` | text | never | — |
| 2 | Sector | `issuer.sector` | text, filter by list | `unknown` shows `Unknown` | — |
| 3 | Holdings weight % | `holding.index_weight_pct` | percent, 3 decimals | no holding value | `holdings_weight`: percentile rank (below) |
| 4 | AUM held (EUR m) | `holding.aum_held_eur_m` | EUR million, 1 decimal | no holding value | `aum_held`: percentile rank |
| 5 | Coverage tier | `TierStore.latest()` confirmed tier; else the active `coverage_rules` proposal, shown with ` (proposed)` | tier label | never (rules always propose one) | `coverage_tier`: Priority Bilateral 1, Thematic & Collaborative 0.67, Scaled Baseline 0.33, Systemic / Market-Level 0 |
| 6 | Open triggers | `TriggerStore.list_triggers()` for the issuer, status `open` or `acknowledged` | three counts, shown `H 1 · M 2 · L 0` | never (all zero shows `—`) | `open_triggers`: min(1, (H × 1.0 + M × 0.6 + L × 0.3) / 2) |
| 7 | Open engagements | engagement store, issues with status `open` or `stalled` (`tracking.OPEN`) | count | never (0 shows `0`) | `open_engagements`: min(1, n / 3) |
| 8 | Escalated | open issues whose `escalation_stage` is not `private_engagement` | count | never | `escalated`: 1 if n ≥ 1, else 0 |
| 9 | Overdue commitments | `tracking.commitments(records)` rows with `overdue` true | count | never | `overdue_commitments`: min(1, n / 2) |
| 10 | Next meeting | Q1, see below | days from today, shown `≈ 42 d (est.)` | no meeting in the vote ledger | `next_meeting`: max(0, 1 − days / 90) |
| 11 | Transition grade | observation `transition_grade` (portfolio store, latest) | `A`..`F` with label, e.g. `D Emerging` | no observation | `transition_grade`: A 0, B 0.2, C 0.4, D 0.6, E 0.8, F 1 |
| 12 | ESG score | observation `esg_score` | 0 to 10, 1 decimal | no observation | `esg_score`: (10 − value) / 10 |
| 13 | Controversy | observation `controversy_level` | integer 0 to 5 | no observation | `controversy`: value / 5 |
| 14 | Carbon intensity | observation `ghg_intensity` | tCO2e per EUR m revenue, 0 decimals | no observation | `carbon_intensity`: percentile rank |
| 15 | Priority score | computed | 0 to 100, 1 decimal | never | — |
| 16 | Selected | the cycle's selection log | `Proposed` / `Confirmed` / empty | not selected | — |
| 17 (PR 3) | Broken commitments | `commitment_flags(company_id)` from `stewardship-commitment-loop` | <pending from the sibling spec> | <pending> | `broken_commitments`: min(1, n / 2) |

Notes:

- **Holdings weight, not index weight.** In the portfolio universe (the default), `holding.index_weight_pct` is the
  company's share of all house holdings (see `universe.from_portfolio`), not a benchmark weight. The header says
  "Holdings weight %" and its tooltip says so. With the synthetic sample universe it is the sample's index weight.
- **Percentile rank** for value v among the n rows that have a value: (number of those rows with a value < v) / (n − 1);
  the largest gets 1, the smallest 0, ties share a rank, n = 1 gives 1.
- **Simulated** applies to columns 11 to 14 when the observation's source is `simulated` (see
  `showcase-portfolio-data`, "Where each field is stored and shown"). Columns 3 and 4 come from holdings that may
  carry the tag `history:simulated`; they are not labelled, as on every other holdings screen.
- **Next meeting (Q1, recommended answer A):** the newest `vote_meetings.meeting_date` for the company in the vote
  ledger, plus whole years until the date is today or later; days = that date − today. The cell shows `≈ <days> d (est.)`
  and the tooltip `Estimated: last meeting <date> + 1 year. No meeting calendar is connected.` Empty when the company has
  no ledger meeting. <If the owner picks B, the column and its score part are dropped; if C, the column shows the last
  meeting date and has no score part.>

## Priority score

score = Σ over components of weight × normalised value, where the weights are the active `priority_weights`
version's integers (0 to 100, summing to 100) and the normalised value is the 0..1 value from the table above
(0 when empty). Rounded to 1 decimal. Each component's points (weight × value, 1 decimal) are returned, so the row's
points add up to its score within 0.1 (rounding).

**Default weights (`priority_weights` version 0, the bundled draft):**

| Component | Weight | Why this default |
|---|---|---|
| `open_triggers` | 30 | A live signal that something needs a conversation |
| `holdings_weight` | 20 | Leverage: how much the house holds relative to the rest |
| `overdue_commitments` | 15 | A company not doing what it said |
| `escalated` | 10 | Already past private engagement |
| `transition_grade` | 10 | Climate laggards (simulated today) |
| `aum_held` | 10 | Absolute money at stake |
| `next_meeting` | 5 | A vote coming up soon |
| `coverage_tier`, `open_engagements`, `esg_score`, `controversy`, `carbon_intensity` | 0 | Shown as columns; available to weight |
| `broken_commitments` (PR 3) | 0 | Added with weight 0 so no saved version changes meaning |

**The policy.** `priority_weights` is a new entry in `policies.POLICIES`, so it gets everything the other house
policies have: version 0 = the bundled draft in `arp/stewardship/data/priority_weights.json`, saved versions are
immutable files, activation needs `approved_by` who is not the person who saved it (four-eyes), and the existing
`/api/stewardship/policies/priority_weights` routes list, read, save and activate it. Content:

```json
{"policy_id": "priority_weights", "version": "v0",
 "components": [{"id": "open_triggers", "weight": 30}, {"id": "holdings_weight", "weight": 20}, ...]}
```

Validation (nothing invalid is saved): every component id known, each weight an integer 0..100, weights sum to 100,
no id twice. A saved version without a component that a later PR adds reads that component as weight 0. Error text
for a wrong sum: `Weights must add up to 100 (now <sum>)`.

**Preview.** `POST /api/stewardship/studio/priority/preview` with a candidate content returns, against the active
version: the top 25 by score under each, the companies entering and leaving the top 25, and each company's score
change, so the editor shows what a weight change does before anyone saves it (like the coverage preview).

**Editing.** On the Worklist tab, a collapsed section **Weights** holds the same `RuleEditor` and `VersionsPanel`
the Selection studio uses for coverage rules, with a plain table in place of the decision-table canvas: one row per
component, its label and a number input. A running total shows `Total 100` (or `Total 95 — must be 100`, save
disabled).

## API

`GET /api/stewardship/worklist` (viewer):

```json
{"as_of": "2026-11-13", "universe_note": "<house_universe note>",
 "weights": {"version": 2, "activated_by": "...", "activated_at": "..."},
 "cycle": "2026-Q4",
 "rows": [{"issuer_id": "isin_US0378331005", "company": "Apple Inc.", "sector": "Information Technology",
           "holdings_weight_pct": 4.812, "aum_held_eur_m": 412.3,
           "coverage_tier": "priority_bilateral", "coverage_tier_confirmed": true,
           "triggers": {"high": 1, "medium": 0, "low": 2}, "new_high_trigger": false,
           "open_engagements": 2, "escalated": 0, "overdue_commitments": 1,
           "next_meeting": {"days": 128, "estimated": true, "last_meeting": "2026-02-24"},
           "transition_grade": {"value": "C", "label": "Gaps", "simulated": true},
           "esg_score": {"value": 6.1, "simulated": true}, "controversy": {"value": 1, "simulated": true},
           "carbon_intensity": {"value": 12.0, "simulated": true},
           "score": 41.7,
           "parts": [{"id": "open_triggers", "weight": 30, "normalised": 0.8, "points": 24.0, "empty": false}, ...],
           "selection": null}]}
```

`parts` lists every component in the active version in policy order, weight 0 included. `selection` is `null`,
`{"status": "proposed", "by": "...", "at": "..."}` or `{"status": "confirmed", ...}`.

Selection (Q2 and Q3, recommended answers):

- `GET /api/stewardship/selection?cycle=2026-Q4` (viewer): the cycle's rows, folded from the log.
- `POST /api/stewardship/selection` (analyst) `{"cycle": "2026-Q4", "add": ["isin_..."], "remove": ["isin_..."]}`:
  adds rows as `proposed`, removes `proposed` rows. Removing a `confirmed` row is a 422
  `confirmed selections cannot be removed`. Only the current cycle can be changed (422 `only <cycle> can be changed`).
  Unknown issuer ids are a 422 listing them.
- `POST /api/stewardship/selection/confirm` (analyst) `{"cycle": "2026-Q4"}`: every `proposed` row becomes `confirmed`,
  with the signed-in user as `confirmed_by`. Returns `{"confirmed": n}`.

The log is `<stewardship_streams_dir>/selection/<cycle>.jsonl`, append-only, events `added`, `removed`, `confirmed`,
each with `issuer_id`, `by`, `at` and the active `priority_weights` version. It stores no score.

**The cycle.** <Q2, recommended: the calendar quarter of today's date, `YYYY-Qn`. A new quarter starts empty; earlier
cycles stay readable through `?cycle=`.>

**Who confirms.** <Q3, recommended: any analyst, recorded by name, may be the person who proposed (as with coverage
tiers). If the owner picks four-eyes, confirm refuses rows the confirming user added, with 422
`Four-eyes rule: <n> rows were proposed by you`.>

## Screen

Steward Workflow gets a tab **Worklist** after **Selection** (`STAGE_TABS`, no stage number). Layout, top to bottom:

```
Worklist · 400 companies in scope · Cycle 2026-Q4 · Weights v2 (activated 12 Nov by A. Analyst)
The priority score is one column. It does not hide, order or select anything unless you sort or filter by it.

[ Search company… ]  Filters: Tier ▾  Triggers ▾  Grade ▾  Score ▾  …   Clear filters
Sorted by: 1 Score ↓  ✕   2 Holdings weight ↓  ✕          Showing 37 of 400 · Selected 5 (2 confirmed)

 ☐ Company          Sector   Wt %   AUM m  Tier             Triggers      Eng Esc Overdue  Next mtg       Grade        Score  Sel
 ☐ Shell plc        Energy   1.204  103.5  Priority Bil.    H 1·M 1·L 0    2   1    1      ≈ 141 d (est.) E Simulated   78.6 ⓘ
 ☑ Nestlé SA        Staples  0.981   84.2  Thematic (prop.) H 0·M 2·L 0    1   0    0      ≈ 133 d (est.) C Simulated   38.0 ⓘ Proposed
 …
[ Add 3 to 2026-Q4 selection ]   [ Confirm 2026-Q4 selection (5 proposed) ]           ‹ 1 2 3 4 ›  100 per page

▸ Weights (edit, preview, save, activate)
```

**Sorting.** Click a header: sort by it, descending first for numbers, ascending for text; click again to flip.
Shift-click (or the header menu's "Add as next sort") adds it as the next key, up to three keys; a fourth replaces the
third. Empty values sort last in both directions. Default: Score descending, then Company ascending. The sort chips
above the table show the keys in order, each removable. Text columns sort case-insensitively.

**Filtering.** Every column has a filter: numbers a min and max box; counts a "at least n" box; Tier, Grade and Sector a
checklist of values present; Triggers by severity (at least one high, at least one medium or high, any); Selected
(any, proposed, confirmed, not selected). Each filter also offers "has a value / empty". Filters combine with AND; the
search box matches company name or issuer id, case-insensitively. "Showing x of n" counts the filtered rows. Filters
and sort never change the score or the selection.

**Size.** All rows load once; sorting and filtering run in the browser. 100 rows per page with page controls; the
header row stays visible while scrolling. With 2,500 companies the API answers within 3 s on the e2e stack and a sort
or filter change redraws within 200 ms (AC-26, AC-27).

**Selecting.** Ticking rows and pressing **Add n to 2026-Q4 selection** proposes them; a proposed row has an ✕ to
remove it. **Confirm 2026-Q4 selection** opens a dialog: "Confirm 5 companies for the 2026-Q4 engagement selection?
Confirmed rows cannot be removed. Recorded as <your name>." with **Confirm** and **Cancel**. Rows can be added at any
rank; there is no "select top N".

**Why is this here** (the ⓘ on the score, or a click on the row): a side panel:

```
Why is this here
Shell plc — priority score 78.6 of 100, rank 4 of 400.
Weights: priority_weights v2, activated 12 Nov 2026 by A. Analyst.

Indicator             Value                     Counts as   Weight   Points
Open triggers         1 high, 1 medium          0.80        30       24.0
Holdings weight       1.204 %  (rank 12 of 400) 0.97        20       19.5
Overdue commitments   1                         0.50        15        7.5
Escalated             1 engagement              1.00        10       10.0
Transition grade      E Not credible  Simulated 0.80        10        8.0
AUM held              EUR 103.5 m               0.96        10        9.6
Next meeting          ≈ 141 d (est.)            0.00         5        0.0
                                                          Total     78.6

Not weighted (weight 0): Coverage tier Priority Bilateral, Open engagements 2, ESG score 3.9 Simulated, …
No data, 0 points: —
This score is one indicator. Sorting, filtering and selecting are your call.
```

The panel's wording is fixed by this spec: title `Why is this here`; first line `<company> — priority score <score> of 100,
rank <r> of <n>.`; second line `Weights: priority_weights v<k>, activated <date> by <name>.` (version 0: `Weights:
priority_weights v0 (bundled default).`); table headers `Indicator`, `Value`, `Counts as`, `Weight`, `Points`; the
`Total` row equals the score; then `Not weighted (weight 0): …`, `No data, 0 points: …` (or `—`), and the last line
`This score is one indicator. Sorting, filtering and selecting are your call.`

**Simulated label.** The word `Simulated`, as in `showcase-portfolio-data`: a small tag after each simulated value in
columns 11 to 14 and in the panel's Value column, and in the column header when any row in that column is simulated
(`Grade · Simulated`). The page also shows the universe note from `house_universe()`, which already says how many
companies carry simulated values.

**New-trigger refresh check (PR 3).** No cache anywhere. The page refetches when the browser tab regains focus. A row
whose issuer has a stored `high` trigger with `is_new` true shows the tag `New high trigger` next to its trigger counts,
and the trigger filter offers "new high trigger".

## PR split

1. **Backend:** `arp/stewardship/worklist.py` (rows, normalisation, score, parts), `priority_weights` policy with its
   bundled draft and validation, the preview, the selection log and its routes, `GET /worklist`; openapi export and
   `gen:api`; unit tests. Can start now: reads engagements through the store interface. Next meeting reads the vote
   ledger only when `vote_meetings` exists (data-foundation PR 3); before that the column is empty.
2. **Screen:** the Worklist tab, sort, filter, paging, select and confirm, the why panel, `Simulated` labels, the Weights
   section. Starts only after data-foundation PR 3 merges. Playwright screenshot in the PR, impeccable audit.
3. **Commitments and refresh:** `broken_commitments` from `commitment_flags(company_id)` (after the commitment loop
   merges), the `New high trigger` tag and refetch on focus.

## Left to the builder

- How `worklist.py` batches store reads to meet AC-26 (the per-company observation lookups in `from_portfolio` are the
  likely cost; the worklist may read observations in one pass but must not change what `load_sample` returns).
- Column widths, the exact filter widgets, keyboard handling beyond the rows below.
- Component labels in the Weights table (plain English, matching the column headers).

## Acceptance

Holdout rows run on the e2e stack with `ARP_ENGAGEMENT_STORE=postgres` and the sample universe
(`house_universe` source `sample`) unless the row says otherwise. "Fixture W" = the sample universe, the bundled
`priority_weights` v0, no stored triggers, no engagement records, no selection log, today = 2026-11-13.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture W | `GET /api/stewardship/worklist` | Status 200; the number of `rows` equals `GET /api/stewardship/universe`'s `issuers` (12 for the sample), and no `issuer_id` appears twice | holdout |
| AC-2 | Fixture W | `GET /api/stewardship/worklist` | Every row's `parts` lists the 12 v0 component ids in the order of the v0 file, and the sum of `points` is within 0.1 of `score` | holdout |
| AC-3 | Fixture W | `GET /api/stewardship/worklist` | The `parts` of `open_triggers`, `overdue_commitments` and `escalated` have `points` 0 on every row | holdout |
| AC-4 | Fixture W plus one stored trigger run with 1 `high` and 1 `medium` trigger for issuer X | `GET /api/stewardship/worklist` | X's `triggers` = `{"high": 1, "medium": 1, "low": 0}`, its `open_triggers` part has `normalised` 0.8 and `points` 24.0 | holdout |
| AC-5 | AC-4, then the `high` trigger transitioned to `resolved` | `GET /api/stewardship/worklist` | X's `triggers` = `{"high": 0, "medium": 1, "low": 0}`, `open_triggers` points 9.0 | holdout |
| AC-6 | Fixture W plus a record for X with one open issue holding one open commitment whose `target_date` is 2026-10-01 | `GET /api/stewardship/worklist` | X's `overdue_commitments` = 1 and its part has `points` 7.5 | holdout |
| AC-7 | Fixture W plus a record for X with one open issue at escalation stage `joint_engagement` | `GET /api/stewardship/worklist` | X's `escalated` = 1, `open_engagements` = 1, `escalated` points 10.0 | holdout |
| AC-8 | Fixture W | `GET /api/stewardship/worklist` | The row with the largest `holdings_weight_pct` has `holdings_weight` `normalised` 1.0; the smallest has 0.0 | holdout |
| AC-9 | Fixture W, an issuer with no `transition_grade` observation | `GET /api/stewardship/worklist` | Its `transition_grade` is `null`, its part has `empty` true and `points` 0 | holdout |
| AC-10 | `priority_weights` v1 saved by user A with `open_triggers` 0, `holdings_weight` 50 and the other weights as in v0 (sum 100), activated by user B | `GET /api/stewardship/worklist` | `weights.version` = 1, and every row's `open_triggers` part has `weight` 0 | holdout |
| AC-11 | — | `POST /api/stewardship/policies/priority_weights/versions` with weights summing to 95 | Status 422, detail `Weights must add up to 100 (now 95)`; `GET .../priority_weights` lists no new version | holdout |
| AC-12 | v1 saved by user A | User A activates v1 | Status 422 (four-eyes), active version still 0 | holdout |
| AC-13 | Fixture W, a first `GET /worklist` read | A trigger run with a `high` trigger for issuer Y is stored, then `GET /worklist` again | The second response shows Y's `triggers.high` = 1, with no restart in between | holdout |
| AC-14 | Fixture W | `POST /api/stewardship/studio/priority/preview` with v0 content | `entering_top` and `leaving_top` are empty lists, every `score_change` is 0 | holdout |
| AC-15 | Fixture W, cycle `2026-Q4` | `POST /api/stewardship/selection` `{"cycle": "2026-Q4", "add": [X, Y]}` then `GET /worklist` | Status 200; X's and Y's `selection.status` = `proposed`; every other row's `selection` is `null` | holdout |
| AC-16 | AC-15 | `POST /api/stewardship/selection/confirm` `{"cycle": "2026-Q4"}` | Body `{"confirmed": 2}`; `GET /selection?cycle=2026-Q4` shows both `confirmed` with `confirmed_by` the signed-in user | holdout |
| AC-17 | AC-16 | `POST /selection` `{"cycle": "2026-Q4", "remove": [X]}` | Status 422, detail `confirmed selections cannot be removed`; X still `confirmed` | holdout |
| AC-18 | Fixture W, today 2026-11-13 | `POST /selection` with `cycle` `2026-Q3` | Status 422, detail `only 2026-Q4 can be changed` | holdout |
| AC-19 | A `viewer` user (non-dev auth) | `POST /api/stewardship/selection` | Status 403 | unit |
| AC-20 | Fixture W | Rows are compared before and after `POST /selection` adds X | Every row's `score` and `parts` are identical (selecting changes no score) | holdout |
| AC-21 | `arp showcase load` done, portfolio universe | `GET /worklist` | Every row with a `transition_grade` has `simulated` true, and `esg_score`, `controversy`, `carbon_intensity` likewise | holdout |
| AC-22 | AC-21 on the e2e stack | A user opens `#/stewardship/worklist` | Each grade, ESG score, controversy and carbon intensity cell shows its value followed by `Simulated`, and those four headers carry `Simulated` | evaluator |
| AC-23 | Seeded demo data (400 companies) | A user clicks Score's ⓘ on any row | A panel titled `Why is this here` opens; its first line reads `<company> — priority score <score> of 100, rank <r> of 400.`; its `Total` equals the row's score; its last line reads `This score is one indicator. Sorting, filtering and selecting are your call.` | evaluator |
| AC-24 | Seeded demo data | The user sorts by Score, then shift-clicks Holdings weight | The chips read `1 Score ↓` and `2 Holdings weight ↓`; rows with equal score are ordered by holdings weight descending; rows with an empty sort value are last | evaluator |
| AC-25 | Seeded demo data | The user filters Grade to `E` and `F` and Triggers to "at least one high" | "Showing x of 400" matches the number of visible rows across pages, and each visible row has grade E or F and at least one high trigger | evaluator |
| AC-26 | 2,500 synthetic issuers, 1,000 stored triggers, 500 engagement records (unit fixture, in-memory stores) | `worklist.build()` runs | It returns 2,500 rows in under 1.0 s on the CI runner | unit |
| AC-27 | 2,500 rows loaded in the screen (component test with a fixture response) | Sort by Score, then by Company | Each re-render finishes in under 200 ms | unit |
| AC-28 | Seeded demo data | The user ticks 3 rows ranked 1, 150 and 390, presses Add, then Confirm, then Confirm in the dialog | The three rows show `Confirmed`; no other row shows a selection | evaluator |
| AC-29 | Fixture W | The screen loads | No row is ticked, no filter is set, and no control selects rows by score or rank | evaluator |
| AC-30 | PR 3; the commitment loop's `commitment_flags` reports <n> broken commitments for X | `GET /worklist` | X's `broken_commitments` = <n>; its part has `weight` 0 under v0 | holdout |
| AC-31 | PR 3; a stored `high` trigger for X with `is_new` true | A user opens `#/stewardship/worklist` | X's row shows the tag `New high trigger` | evaluator |
| AC-32 | Existing tests | The backend and frontend suites run | `tiers.py`, `monitoring.py` and `program.py` tests pass unchanged, and `GET /api/stewardship/tiers` and `GET /api/stewardship/studio/monitoring/triggers` responses are unchanged for Fixture W | unit |

Must not change: coverage tiers and monitoring triggers (AC-32); scores never change on selection (AC-20); nothing is
pre-selected or filtered by score (AC-29).
