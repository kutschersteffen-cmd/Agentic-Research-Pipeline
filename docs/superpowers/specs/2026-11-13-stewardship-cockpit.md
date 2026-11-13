# StewardIQ Cockpit

Slug: stewardship-cockpit

Risk: PR 1 `risk:normal`, PR 2 `risk:high` (financed-emissions maths), PR 3 `risk:low` (optional). Size M, 3 PRs.
Status: draft for owner approval, 13 Nov 2026.

## Intent

The owner, in their words: "I need a cool looking Cockpit for stewardship IQ that gives the user a very strong and
detailed but also easy to read dashboard overview of current and upcoming/planned engagement and voting
activities/meetings." It must show engaged vs selected companies, the financed emissions driven by companies in
engagement, planned engagement meetings by date, engagements with control gaps, running voting statistics,
upcoming shareholder meetings and companies in escalation.

Who it is for: the stewardship lead opening StewardIQ, who wants one page that says what is happening, what is
coming in the next 30 days, and where a person has to act. First use: the live showcase on **17 Nov 2026**, so
version 1 must be on `main` by **16 Nov 2026**.

Target look: the mockup the owner approved, <https://claude.ai/artifact/J3ryTPULk2Q3fR7D5ruCqE>
(`project/Main.dc.html`). Its numbers are sample numbers; the layout, sections and wording are the target.

## Owner decisions (13 Nov 2026, buttons; not reopened here)

1. **Showcase version first.** v1 reads what the app has today plus demo engagements, planned meetings, shareholder
   meetings and votes written by a separate showcase-loader module. Switching to the engagement ledger (PR #440)
   and the priority workbench's named programmes is a later feature.
2. **Control gap** = an open engagement with no objective set, or with no planned next meeting date. Nothing else
   counts.
3. **The mockup** above is the target layout and look.
4. Scope selector: all portfolios, or one portfolio. Nothing else.

## Goals

- G1. A new page at `#/stewardiq/cockpit` with the mockup's sections: six key figures, a 30-day strip, engaged vs
  selected by programme, financed emissions in engagement, upcoming engagement meetings, upcoming shareholder
  meetings with ballot state, control gaps, escalation ladder, voting season to date, scope selector.
- G2. One backend read, `GET /api/stewardship/cockpit`, that computes every number on the page.
- G3. An optional, additive `planned_meeting_date` on an engagement issue, so "planned meetings" and the
  "no next meeting" gap have a source.
- G4. Demo data for the showcase via `arp showcase load-stewardship`, labelled as demo on the page.
- G5. A "Cockpit" link on the StewardIQ workspace overview (`#/stewardiq`), next to the existing screens.
- G6. Per-company financed emissions (PR 2), split engaged / selected not engaged / not selected, plus the
  largest contributors.

## Non-goals

- The engagement ledger (#440), named programmes from the priority workbench, commitments, the ballot banner.
- Any scope other than "all portfolios" or one portfolio (no region, sector or fund-family filter).
- Editing anything from the cockpit. It is read-only; rows link out only where noted.
- A screen or API to edit `planned_meeting_date` (it arrives through the demo loader and, later, #440's intake).
- Changing the StewardIQ overview page beyond adding one link, or the start page (except optional PR 3).
- A chart library. Charts are hand-built SVG/CSS per `DESIGN.md`.

## Anti-goals (a failure even if it works)

- The signal colour (Signal Orange / Signal Lime) on anything other than control gaps and ballots due. When there
  is no gap and no ballot due in scope, no signal colour appears on the page (`DESIGN.md`, One Signal Rule).
- Demo numbers that a viewer could take for real: whenever any demo row is in scope, the header shows `Demo data`.
- A financed-emissions total on the cockpit that differs from the climate module's figure for the same holdings.
- PR 1 depending on PR 2: PR 1 alone is a complete, demonstrable page.

## Constraints

- Deadline: holdout takes about 2 h 15 per PR. If PR 2 slips, PR 1 ships alone; the emissions panel and the
  "Financed emissions covered" figure are hidden while `emissions` is `null`.
- Overlap with #440 (engagement models, generated API files, showcase load): `planned_meeting_date` is additive
  and nullable; expect a rebase on whichever merges second. The demo loader is its own module and command, so
  `arp showcase load` (and `backend/arp/showcase/load.py`) is not touched.
- The commitment-loop and priority-workbench features touch the ballot page and the workbench; the cockpit touches
  neither.
- Both engagement stores (`ARP_ENGAGEMENT_STORE=file` and `postgres`) must work. Vote-ledger tables
  (`vote_meetings`, `vote_items`, `vote_decisions`) exist only in Postgres; without `ARP_POSTGRES_DSN` the
  ledger part of the voting sections is empty, never an error.

## Approaches

1. **One aggregate read endpoint, computed on request (chosen).** A backend module reads the engagement store,
   confirmed tiers, proxy-voting runs, the vote ledger and (PR 2) holdings + climate data, and returns one JSON
   for the page. All rules (control gap, escalation, ballot state, topics) live in one testable place; the page
   only draws. Data sizes are small (hundreds of companies, low thousands of vote items).
2. **Superset / BI views.** Rejected: the owner approved a hand-built page in the house style, and new BI views
   would not be ready by 16 Nov.
3. **The page stitches existing endpoints.** Rejected: there is no read API for the vote ledger, portfolio scope
   needs holdings on the server, and the emissions maths must stay in the backend next to
   `compute_financed_emissions`.

## Definitions (all as of the request's `as_of`, default today UTC)

- **Open issue**: an engagement issue whose `status` is `open` or `stalled` (`arp.stewardship.tracking.OPEN`).
- **Engaged company**: a company with at least one open issue.
- **Selected company**: a company whose latest confirmed tier (`TierStore(...).latest()`, `tiers.py`) is
  `priority_bilateral` or `thematic_collaborative`. *My call:* `scaled_baseline` (a baseline letter plus the
  voting policy) and `systemic` (market-level work) are coverage, not company selection for engagement.
- **Programme** of an issue, from its `fir_theme` (*my call, the smallest mapping*):

  | Programme | `fir_theme` values |
  |---|---|
  | Climate | `climate_mitigation`, `climate_adaptation` |
  | Corporate governance | `governance_board_pay`, `business_ethics`, `tax_accounting`, `shareholder_rights` |
  | Nature | `natural_capital`, `resources_circular`, `pollution` |
  | AI | `digital_responsibility` |
  | Norm violations | `human_rights`, `human_capital`, `consumer_protection`, `communities` |
  | Other | `other`, or `fir_theme` null |

  A selected company with no open issue gets its programme from its confirmed tier's `rule`: `high_emitter` →
  Climate, `nature_impact` → Nature, anything else → Other. The free-text `theme` is not read.
- **Current objective** of an issue: its last objective (list order) whose `status` is `initiated` or
  `in_progress`. None when there is no such objective.
- **Control gap** (owner decision 2): an open issue with no current objective (`no_objective`), or whose
  `planned_meeting_date` is null or earlier than `as_of` (`no_next_meeting`). *My call:* a date in the past is not a
  planned *next* meeting. One issue can have both gaps; it is one gap row listing both.
- **Window**: the 30 days `as_of` to `as_of + 29`, both included.
- **Escalation step**: the 1-based position of `escalation_stage` in `ESCALATION_ORDER`. A company's step is the
  highest step among its open issues. **In escalation**: a company whose step is 2 or more.
- **Season**: calendar year of `as_of`; a vote counts when its meeting date is in that year and on or before `as_of`.
- **Scope**: `portfolio_id` absent = all portfolios: every engagement record, every confirmed tier, every meeting
  and vote, unfiltered. `portfolio_id` given = only companies held in that portfolio per
  `load_holdings_as_of(as_of, [portfolio_id])` applied to every section.
- **Company key**: `securities[h.security_id].company_id` (the universe id, e.g. `isin_DE0007037129`), as
  `compute_financed_emissions` uses it. It is compared with `EngagementRecord.company_id`, the tier row's
  `issuer_id`, `vote_meetings.company_id` and the run ballot's `company_id`. The registry UUID on `holdings` is
  not used.

## Data sources

| Section | Source |
|---|---|
| Engagements, meetings, gaps, ladder | the active engagement store's `list_all()` |
| Selected | `TierStore(stewardship streams root).latest()` |
| Shareholder meetings, votes (runs) | `arp.stewardship.voting_feed.items()` over `proxy_voting` runs (`CompanyBallot.meeting_date`) |
| Shareholder meetings, votes (ledger) | Postgres `vote_meetings`, `vote_items`, `vote_decisions` |
| Financed emissions (PR 2) | holdings in scope + the climate fields EVIC, Scope 1, Scope 2, as `compute_financed_emissions` reads them |

## Model change: `planned_meeting_date`

- `EngagementIssue.planned_meeting_date: str | None = None` (ISO date `YYYY-MM-DD`). Records without the key load
  with `null`.
- Postgres: nullable column `stw_engagements.planned_meeting_date` (added by the existing additive column
  reconciliation), read and written by `PostgresEngagementStore`.
- Both stores gain a public `save_record(record: EngagementRecord) -> EngagementRecord` that writes a whole record
  (issues, objectives, stages, the new field) as given. The demo loader and tests use it. No API route calls it.

## API: `GET /api/stewardship/cockpit`

Query: `portfolio_id` (optional), `as_of` (optional `YYYY-MM-DD`, default today UTC). Unknown `portfolio_id` → 404
with detail `Unknown portfolio <id>`; a malformed `as_of` → 422. Response model `CockpitResponse` (exported to
`openapi.json` / `schema.gen.ts`, with a line in `frontend/src/api/contract.ts`):

```
as_of: "2026-11-17"
scope: {portfolio_id: str | null, label: str}       # "All portfolios (7)" or the portfolio name
portfolios: [{portfolio_id, name}]                    # for the selector, sorted by name
demo: bool                                            # any demo row in scope (see Demo data)
summary: {selected: int, engaged_selected: int, engaged_outside_selection: int}
days: [{date, engagement_meetings: int, shareholder_meetings: int}]          # exactly 30, the window in order
programmes: [{programme, selected: int, engaged: int}]
engagement_meetings: [{date, company_id, company, issue_id, programme, objective: str|null, step: int, stage}]
shareholder_meetings: [{date, company_id, company, items: int, flagged: int|null, ballot_state,
                        action_due: bool, days_to_meeting: int, run_id: str|null}]
control_gaps: [{company_id, company, issue_id, programme, open_days: int, gaps: [str]}]
ladder: [{step: int, stage, label, companies: [{company_id, company}]}]       # exactly 7, steps 1..7
voting: {season: int, meetings: int, items: int, for: int, against: int, abstain: int, other: int,
         against_management: int, topics: [{topic, items: int, against_management: int}]}
emissions: null                                       # PR 1; filled in PR 2 (below)
```

Rules:

- `summary.selected` = selected companies in scope; `engaged_selected` = of those, engaged;
  `engaged_outside_selection` = engaged companies in scope that are not selected.
- `programmes`: fixed order Climate, Corporate governance, Nature, AI, Norm violations, Other; Other is omitted
  when both its numbers are 0. `engaged` = selected companies with an open issue in that programme; `selected` =
  selected companies attributed to it (an engaged company counts once in each programme of its open issues; a
  non-engaged one once, by tier rule). A company may appear in several rows; `summary` counts it once.
- `engagement_meetings`: open issues whose `planned_meeting_date` is in the window, sorted by date.
- Ties in `engagement_meetings`, `shareholder_meetings` and `control_gaps` sort by company name, then `issue_id`
  (meetings: `company_id`).
- `shareholder_meetings`: meetings in the window, sorted by date. One row per company and meeting
  date. From runs: the latest `proxy_voting` run with a ballot for that company and date; `items` = its ballot
  items; `flagged` = items whose policy recommendation is `against` or `withhold` while management recommends
  `for`; `ballot_state` = `cast` when every item is cast, `decided` when no item is `awaiting` but not every item is
  cast, else `awaiting`. From the ledger, only when no run row exists for that company and date (meeting date = UTC date part of
  `meeting_date`; meetings with null `company_id` are skipped; `company` = `stw_companies.name`, else `issuer_name`): `items` = its
  `vote_items`; `flagged` = null; `ballot_state` = `cast` when every item has a decision, `awaiting` when some do,
  `not_started` when none do; `run_id` null. `days_to_meeting` = meeting date − `as_of` in days. `action_due` =
  `ballot_state` is `awaiting` or `not_started` and `days_to_meeting` ≤ 7.
- `days[i].engagement_meetings` / `shareholder_meetings` = rows of the two lists above on that date.
- `control_gaps`: one row per open issue with a gap; `gaps` ⊆ `["no_objective", "no_next_meeting"]` in that order;
  `open_days` = `as_of` − date part of `opened_at`; sorted by `open_days` descending.
- `ladder`: each engaged company listed once, at its step, sorted by company name; `label` per step: 1 Private
  dialogue, 2 Joint engagement, 3 Letter to the board, 4 Meeting with the chair, 5 Vote against management, 6 File
  a resolution, 7 Public statement.
- `voting` (season, in scope): ledger decisions (the latest `decided_at` per item) plus run items with status
  `cast`; a run item and a ledger item with the same company, meeting date and item number count once (ledger).
  `for`/`against`/`abstain` from the vote value, compared lower-cased and trimmed (`withhold` counts as
  `against`); anything else is `other`.
  `against_management`: the ledger's `against_management` flag, or the run feed's `against_management`.
  `meetings` = distinct (company, meeting date) among the counted items. Topics, fixed order, each item in exactly one: **Shareholder
  proposals** (ledger `proponent` contains `holder`, case-insensitive, nothing else compared; run type
  `shareholder_resolution`),
  **Remuneration** (category contains "SAY-ON-PAY" or "COMPENSATION"; run type `say_on_pay`), **Director
  elections** (category contains "DIRECTOR"; run type `director_election`), **Auditors** (category contains
  "AUDIT"; run type `auditor_ratification`), **Capital and other** (everything else). A ledger item matches a
  category rule when any element of its `categories` array contains the text, case-insensitive; rules are tried
  in the order listed and the first match wins.

### `emissions` (PR 2)

```
emissions: {total_tco2e: float, engaged_tco2e: float, selected_not_engaged_tco2e: float,
            not_selected_tco2e: float, uncovered_holding_count: int,
            contributors: [{company_id, company, sector, tco2e: float, share: float, status}]}   # top 6
```

- A new function next to `compute_financed_emissions` (`arp/portfolio/climate/metrics.py`) returns financed
  emissions **per company** with the same formula: Σ over the company's holdings in scope of
  `(market_value_eur / 1e6) / EVIC_eur_m × (Scope 1 + Scope 2)`, holdings without EVIC or Scope 1/2 excluded and
  counted in `uncovered_holding_count`. `total_tco2e` equals `compute_financed_emissions(...)["financed_emissions_tco2e"]`
  for the same holdings and `as_of` (±0.1 t, rounding). `compute_financed_emissions` itself does not change.
- Holdings: `store.load_holdings_as_of(as_of, <portfolio ids in scope, or None for all>)`, exactly as
  `arp climate financed-emissions` selects them.
- Buckets: engaged companies; selected and not engaged; the rest. The three sum to `total_tco2e` (±0.1 t).
- `contributors`: the 6 largest companies by `tco2e`, `share` = `tco2e / total_tco2e` (0..1, 4 decimals),
  `status` one of `in_escalation`, `engaged`, `selected`, `not_selected`.
- `emissions` is `null` when no holdings are in scope or `total_tco2e` is 0.

## The page (`#/stewardiq/cockpit`)

New page `frontend/src/pages/StewardCockpit.tsx`, routed in `App.tsx` when the tab is `stewardiq` and the first
param is `cockpit` (`#/stewardiq` keeps showing `WorkspaceOverview`). Layout and copy follow the mockup:

- Header: "StewardIQ" crumb, title "Cockpit", scope selector (`All portfolios (N)` then each portfolio; changing it
  refetches with `portfolio_id`), "As of <d MMM yyyy>", a `Demo data` pill when `demo` is true.
- Six key figures: **Companies engaged** `engaged_selected / selected` with "<p>% of selected companies";
  **Financed emissions covered** (PR 2, hidden while `emissions` is null) `engaged_tco2e / total_tco2e` as % with
  "<a> of <b> Mt CO₂e in engagement"; **Next 30 days** = both meeting lists' counts, with the split; **Control
  gaps** = gap rows, "<x> without objective · <y> without next meeting"; **In escalation** = companies at step ≥ 2,
  "Highest step: <label>"; **Votes cast, <season>** = `voting.items`, "<meetings> meetings · <p>% against
  management".
- 30-day strip: one column per `days` entry, weekends shaded, two bar series (engagement / shareholder meetings).
- Engaged vs selected, by programme: two bars per programme row (selected track, engaged fill), "<e> / <s>".
- Financed emissions in engagement (PR 2): one stacked bar (engaged / selected not engaged / not selected) and the
  contributors table (Company · sector, Share, Status).
- Upcoming engagement meetings: Date, Company + programme, Objective (or "No objective"), Step. Up to 6 rows, then
  a button `All <n>` that shows the rest in place.
- Upcoming shareholder meetings: Date, Company, Items, Flagged (`–` when null), Ballot. Ballot text: `Cast`,
  `Decided, not cast`, `Awaiting decision`, `Not started`; when `action_due`, the text is exactly `Decision due today` (0),
  `Decision due in 1 day` (1) or `Decision due in <n> days` (2–7), in the signal style. A row with `run_id` links to `#/voting/<run_id>`. Up to 6 rows,
  then `All <n>`. Footnote: "Flagged: items where the voting policy recommends a vote against management."
- Control gaps: header count "<n> need you" in the signal style; each row Company, programme · "open <d> days", gap
  text `No objective`, `No next meeting`, or both joined by ` · `. Footnote: "A gap is an open engagement with no
  objective or no planned next meeting." With no gaps: "No control gaps." and no signal colour.
- Escalation ladder: 7 rows, step number, label, count, company names (step 1 shows only the count).
- Voting, season to date: one stacked bar for / against / abstain (other only if > 0) with counts, and "Against
  management, by topic": one bar per topic, "<rate>% · <a> of <n>".
- Percentages on the page are whole numbers, rounded half up; Mt CO₂e to two decimals; counts with thousands
  separators.
- `as_of`: the page reads an optional `?as_of=YYYY-MM-DD` from the hash (`#/stewardiq/cockpit?as_of=2026-11-17`)
  and passes it to the API; without it the API's default (today UTC) applies. The header shows the response's
  `as_of`.
- Empty sections say so in one line (e.g. "No engagement meetings in the next 30 days."), never a blank card.
- Load failure: one `role="alert"` line "The cockpit could not be loaded: <message>".
- House style per `DESIGN.md`: both themes, tokens not hex, tabular numbers, hand-built SVG/CSS. Signal colour only
  on control gaps and `action_due` ballots. Escalation steps use status colours (not the signal) as the builder sees
  fit within `DESIGN.md`. The page stacks to one column below 900 px with no horizontal page scroll.

Link: `frontend/src/lib/processes.ts`, StewardIQ `screens` gains `["#/stewardiq/cockpit", "Cockpit"]` as the
first entry; the other four stay in their order.

## Demo data: `arp showcase load-stewardship`

New module `backend/arp/showcase/stewardship_demo.py` and command `arp showcase load-stewardship
[--dataset data/simulated/esg_simulated.csv]`. It does not need `arp showcase load` to have run: companies are
taken from the dataset (`company_id`, `name`, `sector`), preferring the names in the mockup where the dataset has
them. It prints one line per step `ok|FAIL <step>: <detail>` (steps `engagements`, `tiers`, `votes`) and exits 1 on
the first FAIL. Needs `ARP_POSTGRES_DSN` for the `votes` step. A second run writes nothing new.

Markers: demo issues have `data_source = "showcase_demo"`; demo tier rows have `confirmed_by = "showcase demo"`;
demo ledger rows (`stw_companies` rows it adds, `vote_meetings`, `vote_items`, `vote_decisions`) have
`source = "showcase_demo"`. `demo` in the response is true when any such row is in scope. It adds a demo issue to an
existing record only when that record has no `showcase_demo` issue; it never edits or removes other issues.

Content (fixed dates, chosen so the showcase on 17 Nov 2026 shows the mockup's shape):

- 34 companies with one open issue each. Programmes: Climate 17, Corporate governance 7, Nature 5, AI 4, Norm
  violations 1. Steps: 29 at 1, 2 at 2, 1 at 3, 1 at 4, 1 at 5.
- 9 issues with `planned_meeting_date` from 2026-11-18 to 2026-12-16; 4 issues with no date; the other 21 dated
  2026-12-17 or later. 3 issues (all with a date, none of the 4 undated) have no objective; the other 31 have one
  `in_progress` objective with a one-sentence description. So 7 control gaps: 3 `no_objective`, 4 `no_next_meeting`.
- 120 confirmed tiers, all `priority_bilateral` or `thematic_collaborative`: the 34 engaged companies, plus 86 more
  with rule `high_emitter` (31), `nature_impact` (17) and `top_weight` (38).
- 14 upcoming `vote_meetings` from 2026-11-18 to 2026-12-16, 4 of them on or before 2026-11-24, each with 10–22
  `vote_items` and no decisions.
- 96 past 2026 meetings (2026-01-15 to 2026-11-14) with 1,284 decided items: 1,062 for, 171 against, 51 abstain;
  152 against management. Topics: Shareholder proposals 40 of 87, Remuneration 31 of 148, Director elections 59 of
  742, Auditors 3 of 96, Capital and other 19 of 211.

## PR plan

| PR | Content | Risk | Holdout `Rows:` | Ships alone? |
|---|---|---|---|---|
| 1 | `planned_meeting_date` + `save_record` (both stores); `GET /api/stewardship/cockpit` with every field except `emissions` (always `null`); `arp showcase load-stewardship`; the page with every section except the emissions panel and figure; the overview link; regenerated API files | normal | AC-1 to AC-60 and AC-70 to AC-72: PR body line `Rows: AC-1, AC-2, …, AC-60, AC-70, AC-71, AC-72` (every ID listed) | Yes: complete page |
| 2 | Per-company financed emissions; `emissions` in the response; the emissions panel and key figure | high | AC-61 to AC-69 (last slice: no `Rows:` line) | — |
| 3 (optional, droppable) | Cockpit entry on the start page (`#/home`), visual polish after `/impeccable:impeccable audit` | low | none | — |

*My call:* "engaged vs selected" moves to PR 1 (it needs only tiers, no emissions maths), so PR 1 alone carries five
of six key figures and every section but one. If PR 2 is not merged by 16 Nov, PR 1 is the showcase version.

## What is left to the builder

Function and file names inside the backend module; how the store reads are composed; demo company choice and
objective wording within the counts above; exact spacing, typography and status colours within `DESIGN.md` and the
mockup.

## Showcase setup (no code)

On the showcase stack: `arp showcase load` (portfolios, needed for the scope selector and PR 2), then
`arp showcase load-stewardship`.

## Acceptance

All `holdout` rows run on the e2e stack (`ARP_ENGAGEMENT_STORE=postgres`, Postgres set). A test starts from empty
`stw_*` / `vote_*` tables, an empty tier log (`<settings.stewardship_streams_dir>/tier_assignments.jsonl`, env
`ARP_STEWARDSHIP_STREAMS_DIR`) and no `proxy_voting` runs. It builds fixtures with `save_record` on the active
engagement store, `TierStore(settings.stewardship_streams_dir).confirm`, direct inserts into the vote tables, and,
for portfolios, the portfolio store's `save_portfolio`, `save_security` and `save_snapshot` (securities carry the
company key, see Definitions). `as_of` is always passed. "Cockpit" below
means `GET /api/stewardship/cockpit`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | no engagement records, tiers, runs or votes | Cockpit `?as_of=2026-11-17` | 200; `summary` is `{selected: 0, engaged_selected: 0, engaged_outside_selection: 0}`; `engagement_meetings`, `shareholder_meetings`, `control_gaps` are `[]`; `voting.items` is 0; `emissions` is `null`; `demo` is `false` | holdout |
| AC-2 | same | same | `days` has 30 entries, the first `date` `"2026-11-17"`, the last `"2026-12-16"`, every count 0 | holdout |
| AC-3 | same | same | `ladder` has 7 entries with `step` 1..7 and `label` exactly "Private dialogue", "Joint engagement", "Letter to the board", "Meeting with the chair", "Vote against management", "File a resolution", "Public statement", each `companies` `[]` | holdout |
| AC-4 | any | Cockpit `?as_of=2026-13-01` | 422 | holdout |
| AC-5 | no portfolio `nope` | Cockpit `?portfolio_id=nope&as_of=2026-11-17` | 404, detail `"Unknown portfolio nope"` | holdout |
| AC-6 | a record saved with `save_record` whose issue has `planned_meeting_date` `"2026-11-20"` | `GET /api/engagement/records/{id}` | that issue's `planned_meeting_date` is `"2026-11-20"` | holdout |
| AC-7 | an engagement record file written before this change (no `planned_meeting_date` key), `ARP_ENGAGEMENT_STORE=file` | `GET /api/engagement/records/{id}` | 200; every issue has `planned_meeting_date` `null`; all other fields as before (must not change) | unit |
| AC-8 | company A: open issue, `fir_theme` `climate_mitigation`, one `in_progress` objective "Cut coal", `planned_meeting_date` `2026-11-20`, `escalation_stage` `private_engagement` | Cockpit `?as_of=2026-11-17` | `engagement_meetings` is exactly one row: `date` `"2026-11-20"`, `company_id` A, `programme` `"Climate"`, `objective` `"Cut coal"`, `step` 1 | holdout |
| AC-9 | after AC-8 | same | `days[3]` is `{date: "2026-11-20", engagement_meetings: 1, shareholder_meetings: 0}`; `control_gaps` is `[]` | holdout |
| AC-10 | A as in AC-8 but `planned_meeting_date` `2026-12-17` | same | `engagement_meetings` is `[]` (outside the window) and `control_gaps` is `[]` | holdout |
| AC-11 | A as in AC-8 but `planned_meeting_date` `2026-11-17` | same | `engagement_meetings` has A on `"2026-11-17"`; `control_gaps` is `[]` | holdout |
| AC-12 | A as in AC-8 but `planned_meeting_date` null | same | `control_gaps` is one row for A with `gaps` `["no_next_meeting"]` | holdout |
| AC-13 | A as in AC-8 but `planned_meeting_date` `2026-11-16` | same | `control_gaps` is one row for A with `gaps` `["no_next_meeting"]` | holdout |
| AC-14 | A as in AC-8 but no objectives | same | `control_gaps` is one row for A with `gaps` `["no_objective"]`; A's `engagement_meetings` row has `objective` `null` | holdout |
| AC-15 | A as in AC-8 but its only objective has status `closed`, and no `planned_meeting_date` | same | `control_gaps` is one row for A with `gaps` `["no_objective", "no_next_meeting"]` | holdout |
| AC-16 | A as in AC-12 but issue status `resolved` | same | `control_gaps` is `[]` and `engagement_meetings` is `[]` | holdout |
| AC-17 | A as in AC-12, issue `opened_at` `2026-10-03T09:00:00Z` | same | A's gap row has `open_days` 45 | holdout |
| AC-18 | A as in AC-8 with status `stalled` | same | `engagement_meetings` has A (stalled counts as open) | holdout |
| AC-19 | A with two open issues at `private_engagement` and `escalation_to_chair` | same | `ladder[3].companies` is `[{company_id: A, company: <A's name>}]` and A is in no other ladder step | holdout |
| AC-20 | A with one open issue at `vote_against_management` and one resolved issue at `public_statement` | same | A is listed only in `ladder[4]` | holdout |
| AC-21 | confirmed tiers: B `priority_bilateral`, C `thematic_collaborative`, D `scaled_baseline`, E `systemic`; B has an open issue; F has an open issue and no tier | same | `summary` is `{selected: 2, engaged_selected: 1, engaged_outside_selection: 1}` | holdout |
| AC-22 | B confirmed `priority_bilateral`, later confirmed `scaled_baseline` | same | `summary.selected` is 0 (latest tier counts) | holdout |
| AC-23 | B selected with an open issue `fir_theme` `governance_board_pay`; C selected, rule `high_emitter`, no issue; D selected, rule `top_weight`, no issue | same | `programmes` is exactly `[{Climate,1,0},{Corporate governance,1,1},{Nature,0,0},{AI,0,0},{Norm violations,0,0},{Other,1,0}]` as `{programme, selected, engaged}` | holdout |
| AC-24 | B selected, open issues in `climate_mitigation` and `digital_responsibility` | same | Climate and AI rows both have `selected` 1 and `engaged` 1; `summary.engaged_selected` is 1 | holdout |
| AC-25 | only C selected with rule `nature_impact` | same | `programmes` has 5 rows (no `Other`) and Nature is `{selected: 1, engaged: 0}` | holdout |
| AC-26 | a ledger meeting for company G on 2026-11-20 with 3 `vote_items` and no decisions | same | `shareholder_meetings` is one row: `date` `"2026-11-20"`, `items` 3, `flagged` `null`, `ballot_state` `"not_started"`, `days_to_meeting` 3, `action_due` `true`, `run_id` `null` | holdout |
| AC-27 | same meeting on 2026-11-25 | same | `days_to_meeting` 8 and `action_due` `false` | holdout |
| AC-28 | AC-26 with decisions on 2 of 3 items | same | `ballot_state` `"awaiting"`, `action_due` `true` | holdout |
| AC-29 | AC-26 with decisions on all 3 items | same | `ballot_state` `"cast"`, `action_due` `false` | holdout |
| AC-30 | a ledger meeting on 2026-12-17 | same | `shareholder_meetings` is `[]` | holdout |
| AC-31 | a `proxy_voting` run ballot for H, meeting 2026-11-19, 4 items: policy `against` / management `for` on 2, none decided | same | H's row: `items` 4, `flagged` 2, `ballot_state` `"awaiting"`, `action_due` `true`, `run_id` the run id | unit |
| AC-32 | AC-31 with every item decided, 1 cast | same | `ballot_state` `"decided"`, `action_due` `false` | unit |
| AC-33 | AC-31 with every item cast | same | `ballot_state` `"cast"` | unit |
| AC-34 | AC-31 plus a ledger meeting for H on 2026-11-19 | same | exactly one row for H on that date, with the run's `run_id` | unit |
| AC-35 | ledger, company G: meeting 2026-03-10 with four decided items: category `DIRECTOR ELECTIONS` `for` (`against_management` false), category `SECTION 14A SAY-ON-PAY VOTES` `against` (true), category `AUDIT-RELATED` `abstain` (false), proponent `Security holder` `for` (true); a meeting 2025-12-01 with one decided item; a meeting 2026-11-20 with one decided item | Cockpit `?as_of=2026-11-17` | `voting` is `{season: 2026, meetings: 1, items: 4, for: 2, against: 1, abstain: 1, other: 0, against_management: 2}` | holdout |
| AC-36 | AC-35 | same | `voting.topics` is exactly `[{Shareholder proposals,1,1},{Remuneration,1,1},{Director elections,1,0},{Auditors,1,0},{Capital and other,0,0}]` as `{topic, items, against_management}` | holdout |
| AC-37 | ledger only: a 2026-03-10 meeting for G with two decided items, votes `Withhold` and `1 Year` | Cockpit `?as_of=2026-11-17` | `voting` has `items` 2, `for` 0, `against` 1, `abstain` 0, `other` 1 | holdout |
| AC-38 | portfolio P holds company A only; A and B both engaged, selected, with meetings and gaps | Cockpit `?portfolio_id=P&as_of=2026-11-17` | every list holds only A; `summary.selected` is 1; `scope` is `{portfolio_id: P, label: <P's name>}` | holdout |
| AC-39 | 7 portfolios exist | Cockpit `?as_of=2026-11-17` | `scope` is `{portfolio_id: null, label: "All portfolios (7)"}`; `portfolios` has 7 entries sorted by `name` | holdout |
| AC-40 | empty tables, then `arp showcase load-stewardship` | run it twice | first run exits 0 and prints exactly three lines starting `ok engagements:`, `ok tiers:`, `ok votes:`; the second run exits 0 and the row counts of `stw_engagements`, `vote_meetings`, `vote_items`, `vote_decisions` and the tier log are unchanged | holdout |
| AC-41 | after AC-40 | Cockpit `?as_of=2026-11-17` | `demo` is `true`; `summary` is `{selected: 120, engaged_selected: 34, engaged_outside_selection: 0}`; `len(engagement_meetings)` 9; `len(shareholder_meetings)` 14; 4 of them `action_due` | holdout |
| AC-42 | after AC-40 | same | `control_gaps` has 7 rows: 3 with `["no_objective"]`, 4 with `["no_next_meeting"]`; ladder company counts by step are 29, 2, 1, 1, 1, 0, 0 | holdout |
| AC-43 | after AC-40 | same | `programmes` is Climate 48/17, Corporate governance 7/7, Nature 22/5, AI 4/4, Norm violations 1/1, Other 38/0 (`selected`/`engaged`) | holdout |
| AC-44 | after AC-40 | same | `voting` has `meetings` 96, `items` 1284, `for` 1062, `against` 171, `abstain` 51, `against_management` 152, and the topics of the Demo data section | holdout |
| AC-45 | a company record with a non-demo open issue, then `arp showcase load-stewardship` picks that company | after the load | the non-demo issue is unchanged (same `issue_id`, `status`, `escalation_stage`) | unit |
| AC-46 | `ARP_POSTGRES_DSN` unset, `ARP_ENGAGEMENT_STORE=file`, no `proxy_voting` runs | Cockpit `?as_of=2026-11-17` | 200; `shareholder_meetings` is `[]` and `voting.items` is 0 | unit |
| AC-47 | (PR 1 build only; retired by PR 2, superseded by AC-68 and AC-69) the demo stack (`arp showcase load`, then `arp showcase load-stewardship`) | open `#/stewardiq/cockpit?as_of=2026-11-17` | no "Financed emissions covered" figure and no emissions panel; no empty card in their place | evaluator |
| AC-48 | the demo stack (`arp showcase load`, then `arp showcase load-stewardship`) | open `#/stewardiq` | the screens row shows `Cockpit` first, then Steward Workflow, Engagement, Proxy Voting, RFP Answers; the processes are unchanged (must not change) | evaluator |
| AC-49 | same | click `Cockpit`, then open `#/stewardiq/cockpit?as_of=2026-11-17` | title "Cockpit"; "As of 17 Nov 2026"; `Demo data` pill; key figures "34 / 120" with "28% of selected companies", "23" (9 + 14), "7", "5", "1,284" with "96 meetings · 12% against management" | evaluator |
| AC-50 | same | look at the page | sections in mockup order: key figures, 30-day strip, engaged vs selected by programme, (emissions, PR 2), upcoming engagement meetings, upcoming shareholder meetings, control gaps, escalation ladder, voting season to date | evaluator |
| AC-51 | same | read the 30-day strip | 30 day columns 17 Nov to 16 Dec, weekends shaded, bars on the 9 engagement and 14 shareholder meeting dates | evaluator |
| AC-52 | same | Upcoming engagement meetings | 6 rows, then `All 9`; clicking it shows 9 rows | evaluator |
| AC-53 | same | Upcoming shareholder meetings, `All 14` opened | the 4 meetings on or before 24 Nov read `Decision due in <n> days` / `Decision due in 1 day` in the signal style; the other 10 read `Not started` in neutral style; Flagged shows `–` | evaluator |
| AC-54 | same | look for the signal colour (Signal Orange in Graphite, Signal Lime in Night) | it appears only on the control-gaps count/rows and the 4 due ballots | evaluator |
| AC-55 | the stack after `arp showcase load` only (no `load-stewardship`), all portfolios | open `#/stewardiq/cockpit?as_of=2026-11-17` | no signal colour anywhere; Control gaps reads "No control gaps." | evaluator |
| AC-56 | same as AC-49 | select portfolio `DAX` in the scope selector | the scope label reads its name; the key figures and list lengths equal those of `GET /api/stewardship/cockpit?portfolio_id=<its id>&as_of=2026-11-17` | evaluator |
| AC-57 | same | switch to the Night theme, then back to Graphite | every chart and text stays readable in both; no hard-coded light-only colours | evaluator |
| AC-58 | same | 390 px wide viewport | one column, no horizontal page scroll | evaluator |
| AC-59 | the backend stopped | open the page | one alert line starting "The cockpit could not be loaded:" | evaluator |
| AC-60 | an empty stack | `arp showcase load` | exits 0; stdout has lines starting `ok import:`, `ok history:`, `ok esg:`, `ok scores:` and no line starting `FAIL` (must not change) | holdout |
| AC-61 | (PR 2) portfolio P: A 1,000,000 EUR, EVIC 100 EUR m, Scope 1 800, Scope 2 200; B 2,000,000 EUR, EVIC 100, Scope 1 300, Scope 2 200; C 1,000,000 EUR held without EVIC; A engaged, B selected not engaged | Cockpit `?portfolio_id=P&as_of=2026-11-17`, climate observations dated 2026-11-01 | `emissions.total_tco2e` 20.0, `engaged_tco2e` 10.0, `selected_not_engaged_tco2e` 10.0, `not_selected_tco2e` 0.0, `uncovered_holding_count` 1 | holdout |
| AC-62 | AC-61 | same | `contributors` is `[A share 0.5, B share 0.5]` in `tco2e` order (ties by name), statuses `engaged`, `selected` | holdout |
| AC-63 | AC-61 with A's open issue at `joint_engagement` | same | A's contributor `status` is `in_escalation` | holdout |
| AC-64 | the showcase portfolios loaded (`arp showcase load`) | Cockpit for each portfolio, `as_of=2026-11-02` | `emissions.total_tco2e` equals `financed_emissions_tco2e` printed by `arp climate financed-emissions --portfolio <id> --as-of 2026-11-02` within 0.1 t | holdout |
| AC-65 | AC-61's holdings and data | `compute_financed_emissions(..., as_of="2026-11-17", portfolio_filter=[P])` | returns exactly `{as_of: "2026-11-17", financed_emissions_tco2e: 20.0, covered_market_value_eur: 3000000.0, uncovered_market_value_eur: 1000000.0, coverage_pct: 0.75, uncovered_holding_count: 1}` (must not change) | holdout |
| AC-66 | the showcase data + demo loaded | Cockpit `?as_of=2026-11-17` | `engaged_tco2e + selected_not_engaged_tco2e + not_selected_tco2e` = `total_tco2e` within 0.1 t; `len(contributors)` 6 | holdout |
| AC-67 | no holdings in scope | Cockpit | `emissions` is `null` | holdout |
| AC-68 | (PR 2) the demo stack | open `#/stewardiq/cockpit` | the "Financed emissions covered" figure shows the % and "<a> of <b> Mt CO₂e in engagement" matching the API; the emissions panel shows the three-part bar and 6 contributors | evaluator |
| AC-69 | (PR 2) `emissions` null for a scope | open the page in that scope | the emissions figure and panel are hidden | evaluator |
| AC-70 | a record saved with `save_record`, open issue with `planned_meeting_date` `"2026-11-20"` | `POST /api/engagement/records/{id}/issues/{issue_id}/escalate` with `{stage: "joint_engagement"}`, then `GET /api/engagement/records/{id}` | the issue's `planned_meeting_date` is still `"2026-11-20"` (must not change) | holdout |
| AC-71 | `ARP_ENGAGEMENT_STORE=file`, a record saved with `save_record` with `planned_meeting_date` `"2026-11-20"` | `GET /api/engagement/records/{id}` | the issue's `planned_meeting_date` is `"2026-11-20"` | unit |
| AC-72 | the cockpit page | open `#/stewardiq/cockpit?as_of=2026-11-17`, then `#/stewardiq/cockpit` | the first request carries `as_of=2026-11-17`; the second carries no `as_of` | unit |

Must not change: record reads without the new field (AC-7), the StewardIQ overview apart from the link (AC-48),
`compute_financed_emissions` (AC-65), `arp showcase load` (AC-60), `planned_meeting_date` kept by existing writes
(AC-70).
