# Stewardship priority workbench: every company in one table, by house, fund or subgroup, with the score as one column

Slug: `stewardship-priority-worklist`. Risk: normal (no migration, no new database schema, no stored score
history). Size L, 7 PRs. Spec 1 of 2; the consolidated overlap view and uploads are spec 2 (see Non-goals).

Status: **approved by the owner on 13 Nov 2026** (buttons in the spec session, revision 2 of the review page).

Owner decisions so far:

- 13 Nov 2026 (intake, buttons): build the prioritisation feature from the AI-native stewardship paper now.
- Owner's words: "For prioritization I want this priority score to be just one indicator based on which I can
  select besides of many." The score never gates, hides or selects anything. It is one column among many that
  a person can sort, filter and select on.
- Intake scope: one worklist, indicators as columns, a code-computed weighted score with each component's
  contribution shown, weights in an editable versioned policy, a person selects rows into the cycle's
  engagement selection and a person confirms, everything computed on read.
- 13 Nov 2026, owner in the spec session: "Overall this priority section must provide a proper workbench for the
  analyst. Which allows not only filtering but also uploading additional data and also manually adding comments and
  remarks. Additionally it should have a large sidepanel that allows to dive into more detailed information such as
  vote and engagement record, existing company facts etc. The workbench should also allow to build certain portfolio
  subgroups and select within these subgroups. Idea is to select companies for engagement on Aggregate holding level
  (e.g all holdings of all funds) and on fund level. Plus the consolidates view to see dependencies and overlaps."
- 13 Nov 2026, buttons: **two specs** (this one: table, scopes, side panel, comments, selection per scope; spec 2:
  consolidated overlap view and uploads); **one selection list per scope** (house aggregate, each fund, each saved
  subgroup); **comments per company, kept** across quarters, add-only; uploads are "Information per company like
  Feedback or so" (spec 2).

- 13 Nov 2026, owner comment on the spec page (thread f41bd1da): "first step is the definition of the in scope
  holdings: all, subgroupds or single funds. after that the user should be able to narrow down/filter ny using toggle
  bars (for minimum holdings size, minimum equity holding size, and other numeric indicators) and check-boxes
  etc..this means the user needs to get a drop down with all available indicators to chose from and automatically the
  right selection mechanism shall appear.the companies in the list shall always show name, sector, isin/identifier,
  whether already engaged and when the last time, the last engagement topics, whether it is part of the climate
  engagement program, nature engagement programme, AI engagement programme, Corporate governance engagement
  programme, or involved in normviolations etc. please also consider that this workbench may also be used to derive
  and define the thematic engagement programs such as climate related matters. so the user should be able to give the
  selection a name such as "climate engagement program""
- 13 Nov 2026, buttons after that comment: a programme is a **standing named list** (not tied to a quarter; members
  proposed, then confirmed by a person; a company can be in several); membership **starts empty, with a suggestion**
  from current engagement themes; "minimum equity holding size" **could be any of** ownership share, equity-only EUR
  held, or weight in the scope, so all three are indicators; everything stays **in spec 1** (7 PRs).

**Decisions assumed, the owner can change any at approval:**

- Q1 Next meeting: estimated as the last vote-ledger meeting rolled forward by whole years to today or later, labelled `(est.)`, empty without a ledger
  meeting. Alternatives: leave the column out of v1; show the last meeting date instead.
- Q2 Cycle: the calendar quarter, e.g. `2026-Q4`. Alternatives: the monthly run month; the calendar year.
- Q3 Who confirms a selection: any analyst, name recorded, may be the person who proposed. Alternative: four-eyes
  (a different person confirms).

## Why

Today the steward sees the companies in scope only through separate screens: coverage tiers (Selection), stored
triggers (Monitoring), engagements and commitments (Tracking), simulated ESG (Transition Intelligence). Deciding
which companies to engage this cycle means holding all of them in one's head. The Workbench puts them side by side,
one row per company, so the steward can sort and filter on whatever matters this cycle and pick the companies.

The owner wants more than a list: a workbench where the analyst works at house level (all holdings of all funds), at
fund level, or on a subgroup of funds or companies they build; reads a company's votes, engagements, facts and
triggers without leaving the page; and leaves comments that stay with the company.

The score helps, but is not the decision. A company with score 12 can be picked over one with score 80, and the
tool records the pick the same way.

## Goals

1. `GET /api/stewardship/worklist?scope=…`: one row per company in the chosen scope (house aggregate, one fund, or a
   saved subgroup), with the indicator columns below, computed from stored values on every request.
2. A priority score from 0 to 100: a weighted sum, computed by code, with each component's contribution returned.
3. The weights live in a versioned house policy `priority_weights`, edited, previewed and activated like the
   coverage rules.
4. A new Steward Workflow tab **Workbench** (`#/stewardship/workbench`): a scope picker (house, fund, subgroup, and
   building a new subgroup), sort on up to three columns, filter on every column, `Simulated` labels, and selecting
   rows into the scope's engagement selection for the cycle, which a person then confirms.
5. One engagement selection per scope and cycle, and each row shows where else the company is selected this cycle.
6. Comments: add-only notes per company, kept across quarters, shown in the table and the side panel.
7. A large side panel per company with tabs: Why (the score), Company (facts), Engagements, Votes, Triggers,
   Holdings (which funds hold it) and Notes.
8. In PR 7: the commitment loop's broken commitments as a column and score component, and a new-trigger refresh
   check.
9. A three-step flow: **1 Holdings in scope** (all, subgroup, single fund) → **2 Narrow down** (filter builder) →
   **3 Select** (quarterly selection or a programme).
10. A filter builder: one dropdown of every available indicator; picking one adds the control that fits its type
    (range slider, at-least slider, checkboxes, checklist).
11. Columns that always show, whatever else is hidden: name, sector, ISIN or identifier, engaged (and when last),
    last engagement topics, programme membership, norm violation.
12. Engagement programmes: standing named lists (Climate, Nature, AI, Corporate governance ready-made; more by name),
    filled from the workbench, confirmed by a person, with a suggestion from current engagement themes.

## Non-goals (later specs)

- **Spec 2 (working slug `stewardship-workbench-overlap`), next:** the consolidated view of dependencies and overlaps
  across funds (fund × company matrix, overlap between fund pairs, where selections of different scopes share
  companies), and uploading extra per-company information ("Information per company like Feedback or so", owner,
  13 Nov 2026). This spec only gives the per-company Holdings tab, the Funds column and "Also selected in".

- The three queues (e.g. "must engage / should consider / monitor"), batch confirmation and the random audit sample.
- Weights set or suggested by a model. The score is plain arithmetic in code.
- New data sources: no meeting calendar feed, no new ESG data, no uploads (spec 2).
- Editing or deleting notes, notes on a single engagement or objective (the engagement record has its own fields).
- Weighting the score per scope: one active `priority_weights` applies to every scope.
- Programme objectives, targets, budgets or reporting; opening engagements from a programme. A programme here is a
  named, confirmed company list. Programme membership is not a score component in v1.
- Changing the logic of `tiers.py`, `monitoring.py` or `program.py`. `worklist.py` reads them.
- Opening engagements from the selection. A confirmed selection is a list; opening engagements stays where it is
  today (Monitoring → open engagement, `POST /api/engagement/records/{id}/issues`).
- A stored score history, score snapshots or a score table (that would make the risk high).

## Anti-goals

- The score deciding anything: no default filter on the score, no hidden rows, no pre-ticked rows, no "auto-select
  top N" button.
- A simulated value read as real. Every simulated value carries `Simulated`, in the cell, in the column header and in
  the why panel (AC-21, AC-22, AC-39, AC-40).
- A score nobody can explain. Each row's points add up to its score, component by component, in the panel.
- Stale numbers. No cache: a trigger or overdue commitment stored a second ago shows on the next request (AC-13).

## Constraints

- Computed on read from what the app already stores. No migration, no new Postgres table, no change to
  `postgres_schema.py`. The selection logs and the notes log are append-only JSONL files under
  `stewardship_streams_dir`, like `tier_assignments.jsonl` and the trigger log. Subgroups are the existing saved
  portfolio groups (`PortfolioGroup`, `POST /api/portfolio/groups`), not a new store.
- Engagements are read through the engagement store interface (`EngagementStore.list_all()`, the store the factory
  from `stewardship-data-foundation` returns), never from the files directly.
- Request and response models are new, so `scripts/export_openapi.py` and `npm run gen:api` run in PR 1, PR 2, PR 3 and
  PR 7, and both generated files are committed; each new `request<T>()` gets a line in `frontend/src/api/contract.ts`.
- Reads need role `viewer`; selecting, confirming, adding notes and saving weights need `analyst` or above; activating a weights
  version follows the existing four-eyes rule of `PolicyStore.activate`.
- Frontend rules: PRs 4, 5 and 6 are checked with impeccable and ui-ux-pro-max, and each carries a Playwright
  screenshot of `#/stewardship/workbench` with the showcase data (PR 6: with the side panel open).
- Works for 400 companies (MSCI World demo) and for 2,500 (the full house universe once more portfolios load).

## Approaches considered

1. **Compute on read, one endpoint, sort and filter in the browser (picked).** The backend joins the stores it
   already has into rows and scores them; the browser holds all rows (2,500 rows ≈ 1 MB JSON before gzip) and sorts
   and filters them in memory. Simple, always current, no schema. Cost: every page load recomputes.
2. Server-side sort, filter and paging. Scales past 10,000 rows, but every sort or filter is a round trip and the
   API grows a query language. Not needed at 2,500.
3. A nightly score table. Fast reads, but stale between runs and it is a stored score history, which the intake rules
   out (risk high).

## Flow

The Workbench opens on three numbered steps across the top; all three stay visible and editable:

1. **Holdings in scope:** the scope picker below (all house holdings, a fund, a subgroup; build a subgroup).
2. **Narrow down:** the filter builder (see Filter builder). "Showing x of n" counts what is left.
3. **Select:** tick rows, then **Add to <scope> selection <cycle>** (quarterly, see Selection) or **Add to programme ▾**
   (standing, see Programmes).

## Scopes

Step 1. A scope decides which companies are rows and what Holdings weight and AUM held mean. Every other column is about the
company and is the same in every scope. Percentile ranks and the rank are computed among the scope's rows.

| Scope key | Rows | Holdings weight % / AUM held | Needs |
|---|---|---|---|
| `house` (default) | every issuer in `house_universe()` (as `load_sample()` returns it, so coverage rules and the workbench see the same companies) | share of all house holdings / its market value across them | — |
| `portfolio:<portfolio_id>` | companies held in that portfolio as of the global latest snapshot date (each portfolio's newest snapshot on or before it, as `load_holdings_as_of` returns for `house_universe()`) | company's market value in it ÷ the sum of the portfolio's holdings that resolve to a company (as `from_portfolio` does for the house) × 100 / that market value | portfolio universe |
| `group:<group_id>`, kind `portfolios` | companies held in any member portfolio | share of the members' combined value of holdings that resolve to a company / market value across the members | portfolio universe |
| `group:<group_id>`, kind `companies` | house rows whose `issuer_id` is a member | as `house` | — |

- `GET /api/stewardship/worklist/scopes` (viewer) returns `{"scopes": [{"key", "label", "kind", "companies"}]}`:
  `house` (label `All house holdings`, kind `house`), every portfolio with company holdings as of the global latest snapshot date
  (label = portfolio name, kind `portfolio`; portfolios without holdings on that date are left out), and every saved
  group of kind `portfolios` or `companies`, latest version (label = group `name`, kind `group`). With the sample
  universe only `house` and `companies` groups are listed.
- With the sample universe, `portfolio:` scopes and `portfolios` groups return 422
  `Fund scopes need the portfolio universe`. A group of kind `securities` returns 422
  `Groups of securities are not a workbench scope`. An unknown portfolio or group id returns 404.
- **Building a subgroup** uses the existing `POST /api/portfolio/groups` (`name`, `kind`, `members`). The picker offers
  **New fund subgroup** (name, tick funds) and **Save ticked companies as subgroup** (name; the ticked rows become a
  `companies` group). Saving under an existing group id makes a new version, as today; the latest wins.
- **Funds column** (all scopes): `held_in` = the house portfolios that hold the company at the latest snapshot; the
  column shows their count, the tooltip their names.

## Always-shown columns

These columns are pinned at the left of every row and cannot be hidden. Sorting and filtering work on them too.

| Column | Source | Shows | Unknown shows |
|---|---|---|---|
| Name | `issuer.name` | text | never empty |
| Sector | `issuer.sector` | text | `Unknown` |
| ISIN / identifier | the ISIN from a `isin_<ISIN>` company id; else the company id itself | `US0378331005` or `SYN03` | never empty |
| Engaged | engagement store: any issue, any status | `Yes · <date of last engagement>` or `No` | `No` |
| Last engagement topics | issues ordered newest first by their own last activity (else `opened_at`); each issue's FIR theme label if `fir_theme` is set, else its free-text `theme`; distinct labels only, at most 3 | `Climate Mitigation & Paris Alignment; board_governance` | `—` |
| Programmes | the programme log (see Programmes) | one chip per programme, labelled with the programme name minus a trailing ` engagement programme` (any case): `Climate ✓` confirmed, `Climate ?` proposed | `—` |
| Norm violation | observation `norms_violation` (bool) | `Yes` / `No`, with `Simulated` when its source is `simulated` | `—` |

"Date of last engagement" (`engaged.last`) = the UTC date part (YYYY-MM-DD) of the latest `correspondence[].date` across the company's issues (stored as `stw_activities`
on the Postgres store), else the latest issue `opened_at`; shown as `12 Sep 2026`.

## Indicator columns (version 1)

One row per company in the scope (see Scopes). Columns 1 and 2 are the pinned Name and Sector. "Score part" is the
component id in `priority_weights`; only the columns with a Score part can carry a weight. Empty cells show `—` and add 0 points; the why panel says `no data`.

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
| 9 | Overdue commitments | commitments with status `open` and `target_date` before today, on issues with status `open` or `stalled` (the commitment loop's `overdue` rule; PR 7 reads it from `commitment_flags_by_company`) | count | never | `overdue_commitments`: min(1, n / 2) |
| 10 | Next meeting | `vote_meetings` (vote ledger): newest `meeting_date` for the `company_id`; Q1, see below | days from today, shown `≈ 42 d (est.)` | no meeting in the vote ledger | `next_meeting`: max(0, 1 − days / 90) |
| 11 | Transition grade | observation `transition_grade` (portfolio store, latest) | `A`..`F` with the fixed label map of `showcase-portfolio-data` (A Leader, B Credible, C Gaps, D Emerging, E Not credible, F Disqualified), e.g. `D Emerging` | no observation | `transition_grade`: A 0, B 0.2, C 0.4, D 0.6, E 0.8, F 1 |
| 12 | ESG score | observation `esg_score` | 0 to 10, 1 decimal | no observation | `esg_score`: (10 − value) / 10 |
| 13 | Controversy | observation `controversy_level` | integer 0 to 5 | no observation | `controversy`: value / 5 |
| 14 | Carbon intensity | observation `ghg_intensity` | tCO2e per EUR m revenue, 0 decimals | no observation | `carbon_intensity`: percentile rank |
| 15 | Priority score | computed | 0 to 100, 1 decimal | never | — |
| 16 | Selected | this scope's selection log for the cycle | `Proposed` / `Confirmed` / empty | not selected | — |
| 17 (PR 7) | Broken commitments | `tracking.commitment_flags_by_company(store.list_all())` from `stewardship-commitment-loop`, flags with `kind` `broken` (status `missed`, set by a person, on an open or stalled issue) | count | never (0 shows `0`) | `broken_commitments`: min(1, n / 2) |
| 18 | Funds | `held_in` (see Scopes) | count; tooltip lists fund names | 0 shows `0` (sample universe) | — |
| 19 | Also selected in | the other scopes' selection logs for the cycle | count; tooltip lists `<scope label>: Proposed/Confirmed` | 0 shows `—` | — |
| 20 | Notes | the notes log | count and the latest note's date; tooltip shows its first 120 characters | 0 shows `—` | — |
| 21 | Equity held (EUR m) | market value of the scope's holdings whose security has `asset_class` `equity` | EUR million, 1 decimal | 0 shows `0.0` | — |
| 22 | Ownership share % | AUM held in the scope (EUR m) ÷ observation `climate_evic_eur_m` (EUR m) × 100 | percent, 4 decimals; `Simulated` when EVIC's source is `simulated` | no EVIC observation | — |

Holdings weight % (column 3), Equity held (21) and Ownership share (22) are the three readings of "minimum equity
holding size"; all three are in the filter builder. Rows carry every other `simulated_esg` field (revenue shares, Controversial weapons, Severe controversy, …) as
`"esg_extra": {"<field_id>": {"value", "simulated"}}`, built in PR 2 from the latest observations. Columns 21 and 22 and every `simulated_esg` field not already a
column can be shown through **Columns ▾** (hidden by default) and used as filters; none of them is scored in v1.

Notes:

- **Holdings weight, not index weight.** In the portfolio universe (the default), `holding.index_weight_pct` is the
  company's share of all house holdings (see `universe.from_portfolio`), not a benchmark weight. The header says
  "Holdings weight %" and its tooltip says so. With the synthetic sample universe it is the sample's index weight.
- **Percentile rank** for value v among the n rows that have a value: (number of those rows with a value < v) / (n − 1);
  the smallest gets 0, ties share a value (so a tied top value gets less than 1), n = 1 gives 1.
- **Simulated** applies to columns 11 to 14 when the observation's source is `simulated` (see
  `showcase-portfolio-data`, "Where each field is stored and shown"). Columns 3 and 4 come from holdings that may
  carry the tag `history:simulated`; they are not labelled, as on every other holdings screen.
- **Observations (columns 11 to 14)** are read per company with the portfolio store's
  `latest_observation(company_id, field_id, <latest holdings snapshot date>)`, any source. `from_portfolio` keeps only
  numeric values, so the grade (a letter) is read here, not from `load_sample()`. The sample universe's `SYN..` ids have
  no observations: these columns are empty there.
- **Next meeting (Q1, recommended answer A):** the only source is the `vote_meetings` table (already created by
  data-foundation PR 1): the newest `meeting_date` among rows with this `company_id`, plus whole years until the date is today or later; days = that date − today. The cell shows `≈ <days> d (est.)`
  and the tooltip `Estimated: last meeting <date> + <k> year(s). No meeting calendar is connected.` Empty when the company has
  no ledger meeting. The sample universe's own `meetings` list and `vote.last_meeting_date` are not used, so the sample
  universe shows this column empty until ledger rows exist. <If the owner picks B, the column and its score part are dropped; if C, the column shows the last
  meeting date and has no score part.>

**Commitment flags (PR 7).** The sibling spec `stewardship-commitment-loop` (merges first) adds to
`arp/stewardship/tracking.py`: `commitment_flags_by_company(records, today=None) -> dict[str, list[CommitmentFlag]]`
(only companies with a flag are keys) and `CommitmentFlag` in `arp/schemas/engagement.py` with `commitment_id`,
`engagement_id`, `kind` (`overdue` | `broken`), `text`, `target_date`, `since`, `message`. PR 7 calls it once per
request and counts each company's flags by `kind`; Overdue commitments then comes from it too, with the same rule as
PR 1, so the column does not change. The why panel shows each flag's `message` under the Value of that row. Pending
Argus suggestions never create a flag.

## Priority score

Each component's points = weight × normalised value, rounded to 1 decimal, where the weights are the active
`priority_weights` version's integers (0 to 100, summing to 100) and the normalised value is the 0..1 value from the
table above (0 when empty). **score = the sum of the rounded points**, so the points add up to the score exactly.

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
| `broken_commitments` (PR 7) | 0 | Added with weight 0 so no saved version changes meaning |

**The policy.** `priority_weights` is a new entry in `policies.POLICIES`, so it gets everything the other house
policies have: version 0 = the bundled draft in `arp/stewardship/data/priority_weights.json`, saved versions are
immutable files, activation needs `approved_by` who is not the person who saved it (four-eyes), and the existing
`/api/stewardship/policies/priority_weights` routes list, read, save and activate it. Content:

```json
{"policy_id": "priority_weights", "version": "v0",
 "components": [{"id": "open_triggers", "weight": 30}, {"id": "holdings_weight", "weight": 20}, ...]}
```

Validation (nothing invalid is saved): a version lists every component of the bundled file, no other id and no id
twice (422 `Missing components: <ids>` / `Unknown components: <ids>`); each weight is an integer 0..100; weights sum to
100 (422 `Weights must add up to 100 (now <sum>)`). When PR 7 adds `broken_commitments` to the bundled file, a version
saved earlier lacks it and reads it as weight 0; that is the only case of a missing component. A row's `parts` always
lists the bundled file's components, in its order.

**Rank.** A row's rank = 1 + the number of rows with a strictly higher score (ties share a rank). "Top 25" = rows
with rank ≤ 25, ordered by score descending, then company name ascending.

**Preview.** `POST /api/stewardship/studio/priority/preview` (analyst) with body `{"content": <candidate policy>}`
always ranks the `house` scope. It validates the candidate like a save (422 with the same messages) and returns, against the active version:

```json
{"companies": 400,
 "top_active": [{"issuer_id": "...", "company": "...", "score": 71.3, "rank": 1}],
 "top_candidate": [{"issuer_id": "...", "company": "...", "score": 68.0, "rank": 1}],
 "entering_top": [{"issuer_id": "...", "company": "...", "rank_active": 31, "rank_candidate": 12}],
 "leaving_top": [{"issuer_id": "...", "company": "...", "rank_active": 20, "rank_candidate": 44}],
 "score_change": [{"issuer_id": "...", "company": "...", "active": 41.7, "candidate": 38.2, "change": -3.5}]}
```

`score_change` lists every company, largest absolute change first. The Weights section shows it like the coverage
preview, so the editor sees what a weight change does before anyone saves it.

**Editing.** On the Workbench tab, a collapsed section **Weights** holds the same `RuleEditor` and `VersionsPanel`
the Selection studio uses for coverage rules, with a plain table in place of the decision-table canvas: one row per
component, its label and a number input. A running total shows `Total 100` (or `Total 95 — must be 100`, save
disabled).

## API

`GET /api/stewardship/worklist?scope=house` (viewer; `scope` defaults to `house`):

```json
{"as_of": "2026-11-13", "universe_note": "<house_universe note>",
 "scope": {"key": "house", "label": "All house holdings", "kind": "house", "companies": 400},
 "weights": {"version": 2, "activated_by": "<approved_by>", "activated_at": "<approved_at>"},
 "cycle": "2026-Q4",
 "rows": [{"issuer_id": "isin_US0378331005", "company": "Apple Inc.", "sector": "Information Technology",
           "identifier": "US0378331005", "engaged": {"yes": true, "last": "2026-09-12"},
           "last_topics": ["Climate Mitigation & Paris Alignment", "board_governance"],
           "programmes": [{"programme_id": "climate", "name": "Climate engagement programme", "status": "confirmed"}],
           "norms_violation": {"value": false, "simulated": true},
           "equity_held_eur_m": 412.3, "ownership_pct": {"value": 0.0121, "simulated": true},
           "holdings_weight_pct": 4.812, "aum_held_eur_m": 412.3,
           "coverage_tier": "priority_bilateral", "coverage_tier_confirmed": true,
           "triggers": {"high": 1, "medium": 0, "low": 2},
           "open_engagements": 2, "escalated": 0, "overdue_commitments": 1,
           "next_meeting": {"days": 128, "estimated": true, "last_meeting": "2026-02-24"},
           "transition_grade": {"value": "C", "label": "Gaps", "simulated": true},
           "esg_score": {"value": 6.1, "simulated": true}, "controversy": {"value": 1, "simulated": true},
           "carbon_intensity": {"value": 12.0, "simulated": true},
           "score": 41.7,
           "parts": [{"id": "open_triggers", "weight": 30, "normalised": 0.8, "points": 24.0, "empty": false}, ...],
           "selection": null,
           "held_in": [{"portfolio_id": "portfolio_msci_world", "name": "MSCI World (public ETF holdings, 2026-11-02)",
                        "weight_pct": 1.204, "market_value_eur_m": 60.0, "selection_status": "proposed" | "confirmed" | null}],
           "selected_elsewhere": [{"scope": "portfolio:portfolio_dax", "label": "DAX (...)", "status": "proposed"}],
           "notes": {"count": 2, "latest": {"text": "<first 120 characters>", "by": "...", "at": "..."}}}]}
```

`weights.activated_by` and `activated_at` are the last activation row's `approved_by` and `approved_at`; both `null`
for v0. `parts` lists every component of the bundled file in its order, weight 0 included. PR 7 adds
`"new_high_trigger": true | false` to each row. `selection` is `null` or
the selection object defined under `GET /selection`.

Programmes (standing named lists; see Programmes for the rules):

- `GET /api/stewardship/programmes` (viewer): `{"programmes": [{"programme_id", "name", "built_in", "created_by",
  "created_at", "confirmed": n, "proposed": n}]}`, the four built-in ones first.
- `POST /api/stewardship/programmes` (analyst) `{"name": "Water engagement programme"}` → 200 with the new programme;
  `programme_id` = the name lower-cased, runs of non-alphanumerics → `_`, trimmed of `_`. A name whose id already
  exists (e.g. `AI` → `ai`): 422 `A programme with id <id> exists`. Empty name or over 80 characters: 422
  `A programme name needs 1 to 80 characters`; a name equal to an existing one (any case): 422
  `A programme named <name> exists`.
- `GET /api/stewardship/programmes/{id}` (viewer): the programme and `members: [{"issuer_id", "company", "status":
  "proposed" | "confirmed" | "ended", "proposed_by", "proposed_at", "confirmed_by", "confirmed_at", "ended_by",
  "ended_at", "end_reason"}]`.
- `POST /api/stewardship/programmes/{id}/members` (analyst) `{"add": [...], "remove": [...], "end": [...],
  "reason": "..."}`: `add` proposes companies of the house universe (422 `unknown company: <ids>` otherwise; a company
  already proposed or confirmed is left as it is); `remove` drops proposed members (422 `confirmed members are ended,
  not removed` for a confirmed one); `end` ends confirmed members and needs a `reason` (422 `Ending a membership needs a
  reason`). An ended company can be proposed again.
- `POST /api/stewardship/programmes/{id}/confirm` (analyst) `{}` → `{"confirmed": n}`: every proposed member becomes
  confirmed, recorded with the signed-in user (Q3 as assumed: any analyst, may be the proposer).
- `GET /api/stewardship/programmes/{id}/suggestions` (viewer): `{"suggestions": [{"issuer_id", "company", "issues":
  [{"issue_id", "fir_theme"}]}]}`: house-universe companies with an issue whose status is `open` or `stalled` and whose
  `fir_theme` maps to the programme, leaving out current proposed or confirmed members. Mapping: `climate` ←
  `climate_mitigation`; `nature` ← `natural_capital`; `ai` ← `digital_responsibility`; `governance` ←
  `governance_board_pay`. Other programmes have no mapping and return `[]`. Suggestions write nothing.
- Unknown programme id: 404. Worklist rows gain `programmes: [{"programme_id", "name", "status"}]` (proposed and
  confirmed only).

Selection (one list per scope and cycle; Q2 and Q3 as assumed). Every selection route takes `scope` (body or query,
default `house`), with the same 404 and 422 rules as the worklist.

- `GET /api/stewardship/selection?cycle=2026-Q4` (viewer, `cycle` defaults to the current one): the cycle's rows,
  folded from the log: `{"cycle": "2026-Q4", "current": true, "rows": [{"issuer_id": "...", "company": "...",
  "status": "proposed" | "confirmed", "proposed_by": "...", "proposed_at": "...", "confirmed_by": null | "...",
  "confirmed_at": null | "...", "weights_version": 2}]}`. A worklist row's `selection` is the same object without
  `issuer_id` and `company`, or `null`.
- `POST /api/stewardship/selection` (analyst) `{"cycle": "2026-Q4", "scope": "house", "add": ["isin_..."], "remove":
  ["isin_..."]}`: adds rows as `proposed`, removes `proposed` rows. A company not among the scope's rows is a 422
  `not in scope <scope>: <ids>`. Removing a `confirmed` row is a 422
  `confirmed selections cannot be removed`. Only the current cycle can be changed (422 `only <cycle> can be changed`).
  Unknown issuer ids are a 422 listing them.
- `POST /api/stewardship/selection/confirm` (analyst) `{"cycle": "2026-Q4", "scope": "house"}`: every `proposed` row
  of that scope becomes `confirmed`,
  with the signed-in user as `confirmed_by`. Returns `{"confirmed": n}`.

The log is `<stewardship_streams_dir>/selection/<cycle>/<scope file>.jsonl` (`house`, `portfolio__<id>`,
`group__<id>`), append-only, events `added`, `removed`, `confirmed`, each with `issuer_id`, `by`, `at` and the active
`priority_weights` version. It stores no score. A company that left a group after it was selected stays in that
selection; its row is then missing from the scope. `GET /selection` rows carry `"in_scope": true | false`, and the
Workbench lists such companies below the table under the heading `Selected but no longer in this scope`.

Notes (comments and remarks, per company, kept across quarters, add-only):

- `POST /api/stewardship/notes` (analyst) `{"company_id": "isin_...", "text": "...", "scope": "house"}` (`scope`
  optional, default `house`, validated like the worklist scope) → 200 with
  `{"note_id", "company_id", "text", "by", "at", "scope"}`. `text` is trimmed; empty or over 2,000 characters is a 422
  `A note needs 1 to 2,000 characters`. A company not in the house universe is a 422 `unknown company`. `scope` only
  records where the note was written.
- `GET /api/stewardship/notes?company_id=…` (viewer): `{"notes": [...]}`, that company's notes, newest first by log
  order (last appended first).
- No route edits or deletes a note. The log is `<stewardship_streams_dir>/notes/notes.jsonl`. Notes never change a
  score.

Votes (for the side panel; reads the vote ledger of `stewardship-data-foundation`):

- `GET /api/stewardship/votes?company_id=…` (viewer): every `vote_decisions` row whose meeting has that `company_id`,
  newest `meeting_date` first, then `item_number`: `{"meeting_date", "meeting_type", "item_number", "description",
  "proponent", "management_recommendation", "vote", "vote_label", "against_management", "rationale", "source",
  "demo"}`, where `demo` is true for `mock_voice_seed` and `npx_urth_demo`. Body `{"votes": [... at most 500],
  "total": n}`.

**The cycle.** <Q2, recommended: the calendar quarter of today's date, `YYYY-Qn`. A new quarter starts empty; earlier
cycles stay readable through `?cycle=`.>

**Who confirms.** <Q3, recommended: any analyst, recorded by name, may be the person who proposed (as with coverage
tiers). If the owner picks four-eyes, confirm refuses rows the confirming user added, with 422
`Four-eyes rule: <n> rows were proposed by you`.>

## Programmes

A programme is a standing, named list of companies for a thematic engagement programme, for example "Climate
engagement programme". It is not tied to a quarter or a scope.

- Four built-in programmes always exist and cannot be renamed or deleted: `climate` "Climate engagement programme",
  `nature` "Nature engagement programme", `ai` "AI engagement programme", `governance` "Corporate governance engagement
  programme". They start with no members. Analysts add more by name (step 3, **Add to programme ▾ → New programme…**).
- A company can be in any number of programmes. Members are proposed (from ticked rows or from **Suggest**), then a
  person confirms them; confirmed members stay until someone ends them with a reason. The history is kept.
- **Suggest** (in the programme's menu) lists the suggestions above with their matching issue themes; the user ticks
  some and adds them as proposed.
- The quarterly selection (per scope) and programmes are separate: a programme says which companies belong to a theme;
  the quarterly selection says whom to engage this quarter. The Programmes filter lets the analyst build a quarterly
  selection from a programme's members.
- Log: `<stewardship_streams_dir>/programmes/events.jsonl`, append-only, events `created`, `proposed`, `removed`,
  `confirmed`, `ended`, each with `programme_id`, `by`, `at` and, for member events, `issuer_id` (and `reason` for
  `ended`). Built-in programmes need no `created` event.

## Screen

Steward Workflow gets a tab **Workbench** after **Selection** (`STAGE_TABS`, no stage number). Layout, top to bottom:

```
Workbench   ① Holdings in scope   ② Narrow down   ③ Select
① Scope: [ All house holdings ▾ ]  (funds: MSCI World, S&P 500, DAX …; subgroups; + New fund subgroup)
② [ Add filter ▾ ]  Ownership share ≥ 0.0100 % ✕   Norm violation: Yes ✕   Sector: Energy, Utilities ✕   Clear filters
400 companies in scope · Cycle 2026-Q4 · Weights v2 (activated 12 Nov by A. Analyst)
The priority score is one column. It does not hide, order or select anything unless you sort or filter by it.

Sorted by: 1 Score ↓  ✕   2 Holdings weight ↓  ✕          Showing 37 of 400 · Selected 5 (2 confirmed)

   Name ‖ Sector ‖ ISIN ‖ Engaged ‖ Last topics ‖ Programmes ‖ Norm viol. ║ Funds Wt % … Triggers … Grade … Notes  Score  Sel
 ☐ Shell plc ‖ Energy ‖ GB00BP6MXD84 ‖ Yes · 12 Sep 2026 ‖ Climate Mitigation… ‖ Climate ✓ ‖ No Simulated ║ 4 1.204 … 78.6 ⓘ
 ☑ Nestlé SA ‖ Staples ‖ CH0038863350 ‖ No ‖ — ‖ Nature ? ‖ No Simulated ║ 3 0.981 … 38.0 ⓘ Proposed
 …
③ [ Add 3 to All house holdings selection 2026-Q4 ] [ Confirm selection (5 proposed) ] [ Add to programme ▾ ] [ Save ticked as subgroup ]

▸ Weights (edit, preview, save, activate)
```

**Sorting.** Click a header: sort by it, descending first for numbers, ascending for text; click again to flip.
Shift-click (or the header menu's "Add as next sort") adds it as the next key, up to three keys; a fourth replaces the
third. Empty values sort last in both directions. Default: Score descending, then Company ascending. The sort chips
above the table show the keys in order, each removable. Text columns sort case-insensitively. Triggers sort by
(high, medium, low) counts, high first; Coverage tier in tier order, Priority Bilateral → Systemic / Market-Level (the
proposed and confirmed tier sort together); Grade A → F; Selected: Confirmed, Proposed, empty.

**Filter builder (step 2).** One button **Add filter ▾** opens a searchable dropdown of every available indicator:
every column of the table (always-shown, indicator and Workbench columns) plus every `simulated_esg` field of
`GET /api/climate/simulated-schema` that is not already a column (labelled `Simulated`). Picking one adds a filter
chip with the control that fits the indicator's type, opened at once:

| Type | Indicators (examples) | Control | Default when added |
|---|---|---|---|
| amount, percent, score | Holdings weight %, AUM held, Equity held, Ownership share, ESG score, Carbon intensity, Priority score, revenue shares | a two-handle range slider from the scope's minimum to maximum value, with number boxes for exact values | the full range (filters nothing until moved) |
| count | Open triggers (any / high), Open engagements, Escalated, Overdue commitments, Notes, Funds | an "at least n" slider from 0 to the scope's maximum | 1 |
| days | Next meeting | an "at most n days" slider | 90 |
| yes/no | Norm violation, Engaged, Controversial weapons, Severe controversy, Has notes | checkboxes `Yes` and `No` | `Yes` ticked |
| category | Sector, Coverage tier, Transition grade, Programmes (with status), Selected | a checklist of the values present in the scope | nothing ticked (filters nothing) |
| text | Name, ISIN / identifier, Last engagement topics | a contains box, any case | empty |

Rules: filters combine with AND; picking an indicator that already has a filter opens that chip instead of adding a
second; each chip shows its condition in words (`Ownership share ≥ 0.0100 %`, values with the column's decimals, `Norm violation: Yes`, `Sector: Energy,
Utilities`) and has ✕ to remove it; **Clear filters** removes all. A row with no value for a filtered indicator is
left out, unless the chip's **Include empty** box is ticked (off by default). Filters stay when the scope changes (slider values outside the new bounds are clamped to them, and the chip text
updates);
slider bounds follow the new scope. Filters and sort never change the score, the selection or a programme.

**Size.** All rows load once; sorting and filtering run in the browser. 100 rows per page with page controls; the
header row stays visible while scrolling. With 2,500 companies building the rows takes under 1 s (AC-26) and a sort or
filter change redraws within 200 ms (AC-27). The page with 400 seeded companies shows its rows within 5 s of opening
(AC-44).

**Selecting.** Ticking rows and pressing **Add n to 2026-Q4 selection** proposes them; a proposed row has an ✕ to
remove it. **Confirm 2026-Q4 selection** opens a dialog: "Confirm 5 companies for the 2026-Q4 engagement selection?
Confirmed rows cannot be removed. Recorded as <your name>." with **Confirm** and **Cancel**. Rows can be added at any
rank; there is no "select top N" and no select-all box: each row is ticked by hand.

**Side panel.** A click on a row opens a large panel on the right: at least half the window width from 1,280 px
wide, full screen below that, closed with ✕ or Esc. The table stays usable beside it, and ↑/↓ move to the previous or
next row with the same tab open. Tabs, in this order:

| Tab | Shows | Source |
|---|---|---|
| Why | the score breakdown below; above it, the company's programme chips with status | the worklist row |
| Company | name, ISIN, sector, country, then its facts (field, value, period, source; simulated ones labelled `Simulated`) | `GET /api/companies/{ref}`, `GET /api/companies/{ref}/facts` |
| Engagements | each issue (theme, status, escalation stage), its objectives (as on `#/engagement`, with `Demo data` labels), commitments with status, the last 10 activities | `GET /api/engagement/records/{company_id}` |
| Votes | the vote ledger, newest meeting first: date, item, management recommendation, vote, against management; `Demo data` on demo rows; "Showing 500 of n" when cut | `GET /api/stewardship/votes` |
| Triggers | the company's stored triggers, every status, with severity, rule, reason, first seen | `GET /api/stewardship/triggers` filtered to the issuer |
| Holdings | one line per house portfolio that holds it: fund, weight in that fund %, market value EUR m, and its selection status in that fund's scope this cycle | the row's `held_in` (no extra request) |
| Notes | all notes, newest first, with author and time, and a box **Add note** (analyst) | `GET/POST /api/stewardship/notes` |

An empty tab says what is missing, e.g. `No votes in the ledger for this company.`

**Why is this here** (the Why tab, also opened by the ⓘ on the score):

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

**New-trigger refresh check (PR 7).** No cache anywhere. The page refetches when the browser tab regains focus. A row
whose issuer has a stored `high` trigger with `is_new` true shows the tag `New high trigger` next to its trigger counts,
and the trigger filter offers "new high trigger".

## PR split

1. **Backend core (house scope):** `arp/stewardship/worklist.py` (rows, normalisation, score, parts),
   `priority_weights` policy with its bundled draft and validation, the preview, the house selection log and its
   routes, `GET /worklist`; openapi export and `gen:api`; unit tests. Can start now: reads engagements through the
   store interface. `vote_meetings` exists since data-foundation PR 1; it holds rows once that spec's PR 3 has run
   `load-npx`, and the column is empty before that.
2. **Backend workbench:** scopes and `GET /worklist/scopes`, selection per scope, `held_in`, `selected_elsewhere`,
   the always-shown fields (identifier, engaged, last topics, norm violation), Equity held and Ownership share, the
   notes log and routes, `GET /votes`; openapi and `gen:api`. Starts only after data-foundation PR 3 merges.
3. **Backend programmes:** the programme log, routes, suggestions, `programmes` on rows; openapi and `gen:api`.
4. **Screen:** the Workbench tab with the three steps, scope picker and subgroup building, pinned columns, sort,
   paging, **Columns ▾**, select and confirm, Add to programme and New programme, `Simulated` labels, the Weights
   section. Screenshot, impeccable audit.
5. **Filter builder:** Add filter, the type-fitting controls, chips, Include empty, Clear filters. Screenshot.
6. **Side panel:** the seven tabs, notes entry, ↑/↓ navigation, programme chips. Screenshot with the panel open.
7. **Commitments and refresh:** `broken_commitments` from `commitment_flags_by_company` (after the commitment loop
   merges), the `New high trigger` tag and refetch on focus.

## Left to the builder

- How `worklist.py` batches store reads to meet AC-26 (the per-company observation lookups in `from_portfolio` are the
  likely cost; the worklist may read observations in one pass but must not change what `load_sample` returns).
- Column widths, the exact filter widgets, keyboard handling beyond the rows below.
- Component labels in the Weights table (plain English, matching the column headers).

## Acceptance

Holdout rows run on the e2e stack with `ARP_ENGAGEMENT_STORE=postgres`. Words used below:

- **Fixture W:** house universe source `sample` (`PUT /api/stewardship/universe` `{"source": "sample"}`, 12 issuers
  `SYN01`..`SYN12`), `priority_weights` with no saved versions (v0 active), the trigger log
  `<stewardship_streams_dir>/triggers/events.jsonl`, the `selection/` and `notes/` directories and the
  `policies/priority_weights/` directory removed, and the `stw_*` and `vote_*` tables truncated in one `TRUNCATE … CASCADE` (no engagement records, no ledger), as
  data-foundation's holdout rows do.
- **PR tags:** a row whose Given starts `PR n;` applies from that PR on; other rows apply from PR 1.
  Rows that use Showcase data need data-foundation PR 3 (`seed-demo`, `load-npx`), which PRs 2 and 4 wait for.
- **Trigger run T(issuer, severity, rule):** one line appended to that trigger log:
  `{"event": "run", "month": "<current YYYY-MM>", "at": "<now>", "triggers": [{"issuer_id": <issuer>, "rule": <rule>,
  "type": "controversy", "theme": "climate", "severity": <severity>, "reason": "test"}]}` (the format
  `TriggerStore.record_run` writes). Several triggers may share one line.
- **Q:** the current calendar quarter of the server's date, e.g. `2026-Q4`. **Today:** the server's date.
- **Showcase data:** `arp showcase load`, `arp stewardship seed-demo`, `arp stewardship load-npx data/voting/npx_urth/`,
  then `PUT /api/stewardship/universe` `{"source": "portfolio"}`; the universe then holds the held MSCI World companies
  (about 400; "n" below is the number the page shows).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture W | `GET /api/stewardship/worklist` | Status 200; `rows` holds 12 rows, one per `SYN01`..`SYN12`, no `issuer_id` twice | holdout |
| AC-2 | Fixture W | `GET /api/stewardship/worklist` | Every row's `parts` lists the component ids of `arp/stewardship/data/priority_weights.json`, in that file's order | holdout |
| AC-33 | Fixture W | `GET /api/stewardship/worklist` | On every row, the sum of `parts[].points` equals `score` (to 1 decimal) | holdout |
| AC-3 | Fixture W | `GET /api/stewardship/worklist` | The `open_triggers`, `overdue_commitments` and `escalated` parts have `points` 0 on every row | holdout |
| AC-4 | Fixture W plus T(`SYN03`, high, `t_high`) and T(`SYN03`, medium, `t_med`) in one line | `GET /api/stewardship/worklist` | `SYN03`'s `triggers` = `{"high": 1, "medium": 1, "low": 0}` | holdout |
| AC-34 | AC-4 | `GET /api/stewardship/worklist` | `SYN03`'s `open_triggers` part has `normalised` 0.8 and `points` 24.0 | holdout |
| AC-5 | AC-4, then `POST /api/stewardship/triggers/<id of SYN03 t_high>/transition` `{"status": "resolved", "decided_by": "tester"}` | `GET /api/stewardship/worklist` | `SYN03`'s `triggers` = `{"high": 0, "medium": 1, "low": 0}` | holdout |
| AC-55 | AC-5 | `GET /api/stewardship/worklist` | `SYN03`'s `open_triggers` part has `points` 9.0 | holdout |
| AC-6 | Fixture W; `POST /api/engagement/records` for `SYN05`, an issue on it, and `POST /api/stewardship/tracking/commitments` with `target_date` = today − 30 days | `GET /api/stewardship/worklist` | `SYN05`'s `overdue_commitments` = 1 | holdout |
| AC-56 | AC-6 | `GET /api/stewardship/worklist` | `SYN05`'s `overdue_commitments` part has `points` 7.5 | holdout |
| AC-7 | Fixture W; a record and one issue for `SYN06`, escalated through `POST /api/engagement/records/SYN06/issues/{id}/escalate` with `{"stage": "joint_engagement"}` | `GET /api/stewardship/worklist` | `SYN06`'s `escalated` = 1 | holdout |
| AC-35 | AC-7 | `GET /api/stewardship/worklist` | `SYN06`'s `open_engagements` = 1 | holdout |
| AC-36 | AC-7 | `GET /api/stewardship/worklist` | `SYN06`'s `escalated` part has `points` 10.0 | holdout |
| AC-8 | Fixture W | `GET /api/stewardship/worklist` | `SYN03` (largest holding, 3.1 %) has `holdings_weight` `normalised` 1.0 and `SYN10` (smallest, 0.02 %) has 0.0 | holdout |
| AC-9 | Fixture W | `GET /api/stewardship/worklist` | `SYN01`'s `transition_grade` is `null` | holdout |
| AC-57 | Fixture W | `GET /api/stewardship/worklist` | `SYN01`'s `transition_grade` part has `empty` true and `points` 0 | holdout |
| AC-10 | `priority_weights` v1 saved by user A with `open_triggers` 0, `holdings_weight` 50, the rest as v0 (sum 100), activated by user B | `worklist.build()` runs on the sample | It reports weights version 1, and every row's `open_triggers` part has `weight` 0 | unit |
| AC-11 | Fixture W | `POST /api/stewardship/policies/priority_weights/versions` with weights summing to 95 | Status 422 with detail `Weights must add up to 100 (now 95)` | holdout |
| AC-37 | AC-11 | `GET /api/stewardship/policies/priority_weights` | Its versions list holds only version 0 | holdout |
| AC-12 | v1 saved by user A | User A activates v1 | `ValueError` with the four-eyes message | unit |
| AC-58 | AC-12 | The active version is read | It is 0 | unit |
| AC-13 | Fixture W and one `GET /worklist` done | T(`SYN07`, high, `t_new`) is appended, then `GET /worklist` again, with no restart | The second response has `SYN07`'s `triggers.high` = 1 | holdout |
| AC-14 | Fixture W | `POST /api/stewardship/studio/priority/preview` with the v0 content | `entering_top` and `leaving_top` are `[]` | holdout |
| AC-59 | AC-14 | — | Every `score_change[].change` is 0 | holdout |
| AC-15 | Fixture W | `POST /api/stewardship/selection` `{"cycle": Q, "add": ["SYN02", "SYN09"]}`, then `GET /worklist` | `SYN02` and `SYN09` have `selection.status` `proposed`; the other 10 rows have `selection` `null` | holdout |
| AC-16 | AC-15 | `POST /api/stewardship/selection/confirm` `{"cycle": Q}` | Body `{"confirmed": 2}` | holdout |
| AC-38 | AC-16 | `GET /api/stewardship/selection?cycle=Q` | Both rows have `status` `confirmed` and `confirmed_by` = the signed-in user's name | holdout |
| AC-17 | AC-16 | `POST /api/stewardship/selection` `{"cycle": Q, "remove": ["SYN02"]}` | Status 422 with detail `confirmed selections cannot be removed` | holdout |
| AC-60 | AC-17 | `GET /api/stewardship/selection?cycle=Q` | `SYN02` has `status` `confirmed` | holdout |
| AC-18 | Fixture W | `POST /api/stewardship/selection` with `cycle` = the quarter before Q | Status 422 with detail `only <Q> can be changed` | holdout |
| AC-19 | A `viewer` user (non-dev auth) | `POST /api/stewardship/selection` | Status 403 | unit |
| AC-20 | Fixture W | Rows are read before and after `POST /selection` adds `SYN04` | Every row's `score` and `parts` are identical | holdout |
| AC-21 | PR 2; Showcase data | `GET /worklist` | Every row whose `transition_grade`, `esg_score`, `controversy` or `carbon_intensity` is not `null` has `simulated` true on that field | holdout |
| AC-22 | PR 4; Showcase data on the e2e stack | A user opens `#/stewardship/workbench` | Each non-empty grade, ESG score, controversy and carbon intensity cell shows its value followed by `Simulated` | evaluator |
| AC-39 | PR 4; AC-22 | — | The Grade, ESG score, Controversy and Carbon intensity headers each show `Simulated` | evaluator |
| AC-40 | PR 6; Showcase data | The user opens "Why is this here" on a row with a transition grade | In the panel's Value column, the grade and every other simulated value are followed by `Simulated` | evaluator |
| AC-23 | PR 6; Showcase data | The user clicks the Score ⓘ on any row | A panel titled `Why is this here` opens. Its first line reads `<company> — priority score <score> of 100, rank <r> of <n>.` | evaluator |
| AC-41 | PR 6; AC-23 | — | The panel's `Total` equals the row's score | evaluator |
| AC-61 | PR 6; AC-23 | — | The panel's last line reads `This score is one indicator. Sorting, filtering and selecting are your call.` | evaluator |
| AC-24 | PR 4; Showcase data | The user clicks the Score header once, then shift-clicks Holdings weight | The sort chips read `1 Score ↓` and `2 Holdings weight ↓` | evaluator |
| AC-42 | PR 4; AC-24 | — | Rows with equal score are ordered by holdings weight, largest first | evaluator |
| AC-43 | PR 4; Showcase data | The user sorts by Next meeting, ascending and then descending | Rows with an empty Next meeting are last both times | evaluator |
| AC-25 | PR 5; Showcase data plus T(X, high, `t_e`) for a company X with grade E | With **Add filter** the user adds Transition grade (ticks `E` and `F`) and Open triggers – high (at least 1) | Every visible row has grade E or F and at least one high trigger, and X is among them | evaluator |
| AC-136 | AC-25 | — | "Showing x of n" equals the number of rows across all pages | evaluator |
| AC-26 | 2,500 synthetic issuers, 1,000 stored triggers, 500 engagement records (unit fixture, in-memory stores) | `worklist.build()` runs | It returns 2,500 rows in under 1.0 s on the CI runner | unit |
| AC-27 | PR 4; 2,500 rows in the screen (component test with a fixture response) | Sort by Score, then by Company | Each re-render finishes in under 200 ms | unit |
| AC-139 | PR 5; 2,500 rows in the screen (component test) | A range filter on Holdings weight is added and moved | Each re-render finishes in under 200 ms | unit |
| AC-44 | PR 4; Showcase data | A user opens `#/stewardship/workbench` | The first rows show within 5 s; the page shows 100 rows and page controls | evaluator |
| AC-28 | PR 4; Showcase data | The user ticks the first row on page 1, page 2 and page 4 of the default sort, presses Add, then Confirm, then Confirm in the dialog | Those three rows show `Confirmed`; no other row shows a selection | evaluator |
| AC-45 | PR 4; Showcase data, one row added as proposed | The user presses that row's ✕ | The row's `Proposed` badge disappears and the "Confirm" button counts one fewer | evaluator |
| AC-46 | PR 4; Showcase data, 2 rows proposed | The user presses Confirm | A dialog reads `Confirm 2 companies for the <Q> engagement selection? Confirmed rows cannot be removed. Recorded as <your name>.` with buttons `Confirm` and `Cancel` | evaluator |
| AC-47 | PR 5; Showcase data | **Add filter** → Name, then the user types part of a company's name | Only rows whose Name contains it (any case) are shown | evaluator |
| AC-29 | PR 4; Fixture W | The screen loads | No row is ticked | evaluator |
| AC-62 | PR 4; Fixture W | The screen loads | No filter is set and "Showing 12 of 12" shows | evaluator |
| AC-63 | PR 4; Fixture W | The screen loads | There is no select-all box and no control that selects rows by score or rank | evaluator |
| AC-48 | PR 4; Showcase data | The user opens Weights and sets `open_triggers` to 25 (total 95) | The total reads `Total 95 — must be 100` and Save is disabled | evaluator |
| AC-49 | PR 4; AC-48, then `holdings_weight` raised by 5 | The user presses Preview | The lists `Entering top 25` and `Leaving top 25` equal `entering_top` and `leaving_top` of `POST /studio/priority/preview` for the same content | evaluator |
| AC-64 | PR 4; Showcase data | The user clicks Score, then shift-clicks Holdings weight, AUM held and Grade | The chips show three keys: `1 Score`, `2 Holdings weight`, `3 Grade` | evaluator |
| ~~AC-65~~ | Retired before approval: the filter builder replaced per-column "empty" filters; see AC-116. | | | |
| AC-30 | PR 7, Fixture W; a record and open issue for `SYN08` with two commitments set to `missed` through `POST /api/stewardship/tracking/commitments/{id}` | `GET /worklist` | `SYN08`'s `broken_commitments` = 2 | holdout |
| AC-53 | AC-30 | `GET /worklist` | `SYN08`'s `broken_commitments` part has `weight` 0 and `points` 0 | holdout |
| AC-54 | Fixture W; a record and issue for `SYN11`, one commitment with `target_date` = today − 30 days added, then the issue closed through `POST /api/stewardship/tracking/close` | `GET /worklist` | `SYN11`'s `overdue_commitments` = 0 | holdout |
| AC-31 | PR 7; T(X, high, `t_x`) stored for a company X, so its trigger has `is_new` true | A user opens `#/stewardship/workbench` | X's row shows the tag `New high trigger` | evaluator |
| AC-50 | PR 7; `#/stewardship/workbench` open in one tab | T(X, high, `t_y`) is stored, the user switches to another tab and back | X's row shows `New high trigger` without a page reload | evaluator |
| AC-32 | Fixture W | The backend suite runs | The existing tests of `tiers.py`, `monitoring.py`, `program.py` and `policies.py` pass unchanged | unit |
| AC-51 | Fixture W | `GET /api/stewardship/tiers` and `GET /api/stewardship/studio/monitoring/triggers` on `main` and on the PR build | The responses are equal (a snapshot recorded from `main` in the PR's test) | unit |
| AC-52 | Fixture W | `GET /api/stewardship/universe` and `GET /api/stewardship/policies/coverage_rules` on `main` and on the PR build | The responses are equal (a snapshot recorded from `main` in the PR's test) | unit |
| AC-66 | PR 2; Showcase data | `GET /api/stewardship/worklist/scopes` | Exactly one entry has key `house`, and the 7 showcase portfolio ids each appear as a `portfolio:<id>` entry with `companies` ≥ 1 | holdout |
| AC-67 | PR 2; Fixture W | `GET /api/stewardship/worklist?scope=portfolio:anything` | Status 422 with detail `Fund scopes need the portfolio universe` | holdout |
| AC-68 | PR 2; Showcase data, any portfolio P | `GET /worklist?scope=portfolio:P` | The rows' `holdings_weight_pct` add up to 100 within 0.1 | holdout |
| AC-69 | AC-68 | — | Every row's `held_in` contains P | holdout |
| AC-70 | PR 2; Showcase data, P | `GET /worklist?scope=portfolio:P` and `GET /worklist?scope=house` | For a company in both, the `open_triggers`, `overdue_commitments`, `escalated` and `transition_grade` parts have equal `normalised` values | holdout |
| AC-71 | PR 2; Fixture W; `POST /api/portfolio/groups` `{"name": "g", "kind": "companies", "members": ["SYN01", "SYN02"]}` → id G | `GET /worklist?scope=group:G` | Exactly 2 rows, `SYN01` and `SYN02` | holdout |
| AC-72 | PR 2; Fixture W; a group of kind `securities` → id S | `GET /worklist?scope=group:S` | Status 422 with detail `Groups of securities are not a workbench scope` | holdout |
| AC-73 | PR 2; AC-71 | `POST /selection` `{"cycle": Q, "scope": "group:G", "add": ["SYN05"]}` | Status 422 with detail `not in scope group:G: SYN05` | holdout |
| AC-74 | PR 2; AC-71; `POST /selection` `{"cycle": Q, "scope": "group:G", "add": ["SYN01"]}` | `GET /worklist?scope=house` | `SYN01`'s `selected_elsewhere` = `[{"scope": "group:G", "label": "g", "status": "proposed"}]` | holdout |
| AC-97 | AC-74 | `GET /worklist?scope=house` | `SYN01`'s `selection` is `null` | holdout |
| AC-75 | PR 2; AC-74, then `POST /selection` `{"cycle": Q, "scope": "house", "add": ["SYN02"]}` | `POST /selection/confirm` `{"cycle": Q, "scope": "house"}` | Body `{"confirmed": 1}` | holdout |
| AC-76 | AC-75 | `GET /selection?cycle=Q&scope=group:G` | `SYN01` still has `status` `proposed` | holdout |
| AC-77 | PR 2; Fixture W | `POST /api/stewardship/notes` `{"company_id": "SYN04", "text": "  Board change expected  "}` | Status 200; `text` = `Board change expected`, `by` = the signed-in user's name | holdout |
| AC-78 | PR 2; Fixture W | `POST /notes` with `text` `"   "` | Status 422 with detail `A note needs 1 to 2,000 characters` | holdout |
| AC-79 | PR 2; Fixture W | `POST /notes` with a 2,001-character `text` | Status 422 with detail `A note needs 1 to 2,000 characters` | holdout |
| AC-80 | PR 2; Fixture W; notes "first" then "second" on `SYN04` | `GET /api/stewardship/notes?company_id=SYN04` | Two notes, `second` first | holdout |
| AC-81 | AC-80 | `GET /worklist` | `SYN04`'s `notes.count` = 2 | holdout |
| AC-98 | AC-80 | `GET /worklist` | `SYN04`'s `notes.latest.text` = `second` | holdout |
| AC-82 | AC-80 | `PUT` and `DELETE` on `/api/stewardship/notes/<note_id>` | Status 404 or 405 for both | holdout |
| AC-101 | AC-82 | `GET /notes?company_id=SYN04` | Both notes are returned with their original `text` | holdout |
| AC-83 | AC-80 | Rows of `GET /worklist` are compared with Fixture W's | Every row's `score` is unchanged | holdout |
| AC-84 | PR 2; a `viewer` user (non-dev auth) | `POST /api/stewardship/notes` | Status 403 | unit |
| AC-85 | PR 2; Showcase data, a company C with ledger meetings | `GET /api/stewardship/votes?company_id=C` | `total` equals the number of `vote_decisions` rows whose meeting has `company_id` C | holdout |
| AC-86 | AC-85 | — | Rows are ordered by `meeting_date` descending | holdout |
| AC-100 | AC-85 | — | Every `npx_urth_demo` row has `demo` true | holdout |
| AC-87 | PR 4; Showcase data | The user picks a fund in the scope picker | The header names the fund | evaluator |
| AC-102 | AC-87 | — | "Showing x of x" equals that fund's `companies` in `GET /worklist/scopes` | evaluator |
| AC-88 | PR 4; Showcase data | The user makes a **New fund subgroup** from 2 funds | It appears in the picker; picking it shows every company held in either fund | evaluator |
| AC-89 | PR 4; Showcase data | The user ticks 3 rows and uses **Save ticked as subgroup** | Picking the new subgroup shows exactly those 3 companies | evaluator |
| AC-90 | PR 4; Showcase data; a company proposed in a fund's scope | The user opens the house scope | That company's Also selected in column shows `1` | evaluator |
| AC-99 | AC-90 | The user hovers that cell | The tooltip reads `<fund name>: Proposed` | evaluator |
| AC-91 | PR 6; Showcase data, window 1440 × 900 | The user clicks a row | A panel opens covering at least half the width, with tabs `Why`, `Company`, `Engagements`, `Votes`, `Triggers`, `Holdings`, `Notes` in that order | evaluator |
| AC-92 | PR 6; AC-91 | The user opens Votes on a company with N-PX rows | Each row shows date, item, management recommendation, vote, against management and `Demo data` | evaluator |
| AC-93 | PR 6; AC-91 | The user opens Holdings | It lists as many funds as the row's Funds column | evaluator |
| AC-94 | PR 6; AC-91 | The user adds a note in the Notes tab | It shows first, with the user's name | evaluator |
| AC-103 | AC-94 | — | The row's Notes count has risen by 1 without a page reload | evaluator |
| AC-104 | PR 6; Fixture W plus T(`SYN03`, high, `t_x`) | The user opens Triggers for `SYN03` | A line shows severity `high`, rule `t_x`, reason `test` | evaluator |
| AC-105 | PR 6; Showcase data | The user opens Company for any row | It shows the company's ISIN and sector, and each simulated fact is followed by `Simulated` | evaluator |
| AC-106 | A ledger meeting for company C on today − 400 days, none later (unit fixture) | `worklist.build()` runs | C's `next_meeting.days` = 330 and its `next_meeting` part has `normalised` 0 | unit |
| AC-107 | PR 2; Fixture W | `GET /worklist` | `SYN03`'s `identifier` = `SYN03`, `engaged` = `{"yes": false, "last": null}`, `last_topics` = `[]` | holdout |
| AC-108 | PR 2; Fixture W; `POST /api/engagement/records` for `SYN06`, then `POST /api/stewardship/intake/engagements` with one engagement for `SYN06` (`theme` `board_governance`, no `fir_theme`) and one activity with `occurred_at` `2026-09-12T10:00:00Z` | `GET /worklist` | `SYN06`'s `engaged` = `{"yes": true, "last": "2026-09-12"}` | holdout |
| AC-109 | AC-108 | `GET /worklist` | `SYN06`'s `last_topics` = `["board_governance"]` | holdout |
| AC-110 | PR 2; Showcase data | `GET /worklist` | Every row whose ISIN-keyed id is `isin_<X>` has `identifier` `<X>`, and every non-null `norms_violation` has `simulated` true | holdout |
| AC-111 | PR 2 (unit fixture): company C held for EUR 50 m in the scope, `climate_evic_eur_m` = 10,000 | `worklist.build()` runs | C's `ownership_pct` = 0.5 | unit |
| AC-112 | PR 2 (unit fixture): C held through one equity security worth EUR 30 m and one bond worth EUR 20 m | `worklist.build()` runs | C's `equity_held_eur_m` = 30.0 and `aum_held_eur_m` = 50.0 | unit |
| AC-113 | PR 3; Fixture W, programme log removed | `GET /api/stewardship/programmes` | The first four `programme_id`s are `climate`, `nature`, `ai`, `governance`, each with `confirmed` 0 and `proposed` 0 | holdout |
| AC-114 | PR 3; AC-113 | `POST /programmes` `{"name": "Water engagement programme"}`, then the same name in upper case | First status 200 with `programme_id` `water_engagement_programme`; second status 422 with detail `A programme named WATER ENGAGEMENT PROGRAMME exists` | holdout |
| AC-115 | PR 3; AC-113 | `POST /programmes/climate/members` `{"add": ["SYN03"]}`, then `POST /programmes/nature/members` `{"add": ["SYN03"]}` | `GET /worklist` shows `SYN03`'s `programmes` with both, each `status` `proposed` | holdout |
| AC-117 | AC-115 | `POST /programmes/climate/confirm` `{}` | Body `{"confirmed": 1}`; `GET /programmes/climate` shows `SYN03` `confirmed` with `confirmed_by` the signed-in user | holdout |
| AC-118 | AC-117 | `POST /programmes/climate/members` `{"remove": ["SYN03"]}` | Status 422 with detail `confirmed members are ended, not removed` | holdout |
| AC-119 | AC-117 | `POST /programmes/climate/members` `{"end": ["SYN03"]}` with no `reason` | Status 422 with detail `Ending a membership needs a reason` | holdout |
| AC-120 | AC-117 | `POST /programmes/climate/members` `{"end": ["SYN03"], "reason": "objective achieved"}` | `GET /programmes/climate` shows `SYN03` `ended` with `end_reason` `objective achieved`; `GET /worklist` no longer lists `climate` in `SYN03`'s `programmes` | holdout |
| AC-121 | PR 3; AC-113; `POST /api/engagement/records` for `SYN07` and `SYN08`, then `POST /api/stewardship/intake/engagements` with an engagement for `SYN07` (`fir_theme` `climate_mitigation`, `status` `open`) and one for `SYN08` (`fir_theme` `climate_mitigation`, `status` `closed`) | `GET /programmes/climate/suggestions` | Exactly one suggestion, `SYN07` | holdout |
| AC-122 | AC-121 | `GET /programmes/climate` | It has no members (suggestions write nothing) | holdout |
| AC-123 | AC-117 | Rows of `GET /worklist` are compared with Fixture W's | Every row's `score` is unchanged | holdout |
| AC-124 | PR 4; Showcase data | The user opens `#/stewardship/workbench` | Steps `① Holdings in scope`, `② Narrow down`, `③ Select` show in that order, and Name, Sector, ISIN, Engaged, Last engagement topics, Programmes and Norm violation are the first seven columns | evaluator |
| AC-125 | PR 4; AC-124 | The user opens **Columns ▾** and hides every column it offers | The seven always-shown columns are still there | evaluator |
| AC-126 | PR 4; Showcase data | The user ticks 2 rows, opens **Add to programme ▾** and picks **New programme…**, named `Water engagement programme` | The two rows' Programmes cells show `Water ?` | evaluator |
| AC-137 | PR 3; AC-113 | `POST /programmes` `{"name": "AI"}` | Status 422 with detail `A programme with id ai exists` | holdout |
| AC-127 | PR 5; Showcase data | The user opens **Add filter ▾** | It lists every table column and the `simulated_esg` fields, the latter labelled `Simulated` | evaluator |
| AC-128 | PR 5; AC-127 | The user picks Ownership share | A chip with a two-handle range slider and two number boxes opens, spanning the scope's minimum and maximum | evaluator |
| AC-129 | PR 5; AC-127 | The user picks Norm violation | A chip with checkboxes `Yes` (ticked) and `No` opens, and every visible row shows `Yes` in Norm violation | evaluator |
| AC-130 | PR 5; AC-127 | The user picks Sector | A chip with a checklist of the sectors present in the scope opens, nothing ticked, and the row count is unchanged | evaluator |
| AC-131 | PR 5; AC-128 | The user moves the lower handle to a value v between the scope's minimum and maximum | The chip reads `Ownership share ≥ <v with 4 decimals> %`, and every visible row's Ownership share is ≥ v | evaluator |
| AC-132 | PR 5; AC-131 and AC-129 both set | The user presses ✕ on the Norm violation chip | The Norm violation chip is gone and the Ownership share chip remains | evaluator |
| AC-133 | PR 5; AC-131 | The user picks Ownership share again in **Add filter ▾** | No second chip appears; the existing chip opens | evaluator |
| AC-116 | PR 5; Fixture W (no grades) | **Add filter** → Transition grade, tick `E` | The page reads `Showing 0 of 12` | evaluator |
| AC-138 | AC-116 | The user ticks **Include empty** on that chip | The page reads `Showing 12 of 12` | evaluator |
| AC-134 | PR 5; filters set in the house scope | The user switches scope to a fund | The same chips stay, and the range sliders' bounds follow the fund's rows | evaluator |
| AC-135 | PR 3; a `viewer` user (non-dev auth) | `POST /api/stewardship/programmes` | Status 403 | unit |
| AC-95 | PR 6; AC-91 | The user presses ↓ | The panel shows the next row's company in the same tab | evaluator |
| AC-96 | PR 6; AC-91 | The user opens Engagements on a seeded company | Each objective shows description, type, status, result and `Demo data` | evaluator |

Must not change: coverage tiers, monitoring triggers, the universe and the existing policies (AC-32, AC-51, AC-52);
selecting, notes and programmes change no score (AC-20, AC-83, AC-123); nothing is pre-selected or filtered by score (AC-29).
