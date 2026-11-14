# StewardIQ Cockpit

Slug: stewardship-cockpit

Risk: high (PR 2 changes financed-emissions maths; PR 1 extends the engagement intake). Size M, 3 PRs.
Status: draft for owner approval, 13 Nov 2026.
Starts after: PR 2 (#440, engagement and vote intake) and PR 3 (`arp stewardship seed-demo`, `arp stewardship
load-npx`) of `stewardship-data-foundation` are on `main`, and so is the three-tier change (owner decision 6). PR 1's
evaluator pass runs on that demo data.

## Intent

The owner, in their words: "I need a cool looking Cockpit for stewardship IQ that gives the user a very strong and
detailed but also easy to read dashboard overview of current and upcoming/planned engagement and voting
activities/meetings." It must show engaged vs selected companies, the financed emissions driven by companies in
engagement, planned engagement meetings by date, engagements with control gaps, running voting statistics,
upcoming shareholder meetings and companies in escalation.

Who it is for: the stewardship lead opening StewardIQ. They want one page that shows what is happening, what is
coming in the next 30 days, and where a person has to act. First use: the live showcase, now about 27 Nov 2026.

Target look: the mockup the owner approved, <https://claude.ai/artifact/J3ryTPULk2Q3fR7D5ruCqE>
(`project/Main.dc.html`). Its numbers are sample numbers; the layout, sections and wording are the target.

## Owner decisions (13 Nov 2026, buttons; not reopened here)

1. **Control gap** = an open engagement with no objective set, or with no planned next meeting date. Nothing else
   counts.
2. **The mockup** above is the target layout and look; house style per `DESIGN.md`.
3. Scope selector: all portfolios, or one portfolio. Nothing else.
4. **Build on the ledger** (22:28 UTC, intake session: "Deadline is moves by 10 days. So we can make it perfect",
   then "Build all"). The showcase-first version on today's data is void. The cockpit reads the engagement and
   vote ledger of `stewardship-data-foundation`; the planned meeting date lives in the ledger. There is no field on
   the file-based `EngagementIssue`.
5. **Split:** this spec is feature A, `stewardship-cockpit`: every section of the mockup including financed
   emissions, with "selected" taken from confirmed tiers. Feature B, `stewardship-cockpit-programmes`, comes later.
   It covers engaged vs selected by *named programme* and programme-based "selected", and waits on the
   priority-workbench spec (#448).
6. **Three coverage tiers** (14 Nov 2026, buttons, at spec approval): "Only change: tier: bilateral, letter,
   monitor" and "Delete collaborative everywhere. We don't do that". The tiers are `bilateral`, `letter` and
   `monitor`; Thematic & Collaborative goes everywhere. Changing the tier model itself (`tiers.py`, the coverage and
   escalation rule graphs, the Selection screen, docs) is a separate feature that lands first. This spec only reads
   its result.

## Goals

- G1. A new page at `#/stewardiq/cockpit` with the mockup's sections: six key figures, a 30-day strip, engaged vs
  selected by theme (see the panel note below), financed emissions in engagement, upcoming engagement meetings,
  upcoming shareholder meetings with ballot state, control gaps, the escalation ladder, voting season to date, and
  the scope selector.
- G2. One backend read, `GET /api/stewardship/cockpit`, that computes every number on the page from the ledger,
  confirmed tiers, proxy-voting runs and (PR 2) holdings and climate data.
- G3. A planned meeting date on each ledger engagement, `stw_engagements.planned_meeting_date`, loaded through the
  existing engagement intake (API and Excel).
- G4. `arp stewardship seed-cockpit-demo`: on top of the foundation's demo data, it adds planned meeting dates,
  some escalations, confirmed tiers and upcoming shareholder meetings, so the showcase shows every section filled.
  The page labels all of it as demo data.
- G5. A "Cockpit" link on the StewardIQ workspace overview (`#/stewardiq`), next to the existing screens.
- G6. Per-company financed emissions (PR 2), split into engaged / selected not engaged / not selected, plus the
  largest contributors.

## Non-goals

- Named programmes and programme-based selection (feature B).
- Commitments, the ballot banner, the priority workbench.
- Any scope other than "all portfolios" or one portfolio (no region, sector or fund-family filter).
- Editing anything from the cockpit. It is read-only; rows link out only where noted.
- A screen to edit `planned_meeting_date`. It arrives through intake (API, Excel) and the demo step.
- Showing `planned_meeting_date` on the Engagement page, or adding it to `EngagementIssue` / the file store.
- Changing the StewardIQ overview beyond adding one link.
- A chart library. Charts are hand-built SVG/CSS per `DESIGN.md`.

## Anti-goals (a failure even if it works)

- The signal colour (Signal Orange / Signal Lime) on anything other than control gaps and ballots due. When there
  is no gap and no ballot due in scope, no signal colour appears on the page (`DESIGN.md`, One Signal Rule).
- Demo numbers a viewer could take for real: whenever a demo row is in scope, the header shows `Demo data`.
- A financed-emissions total on the cockpit that differs from the climate module's figure for the same holdings.
- A cockpit figure that disagrees with the API: every number on the page comes from the response, the page
  computes nothing beyond sums and percentages of it.

## Constraints

- Postgres is the system of record (`postgres_schema.py`). The cockpit reads `stw_*` and `vote_*` tables directly,
  whatever `ARP_ENGAGEMENT_STORE` says. Engagements kept only in `engagements/*/record.json` are not shown
  (`arp stewardship migrate-files` moves them).
- `planned_meeting_date` is one nullable column, added by the existing additive column reconciliation. Existing
  store writes (`PostgresEngagementStore` sets attributes in place) must leave it as it is.
- The commitment-loop and priority-workbench features touch the ballot page and the workbench; the cockpit touches
  neither. Feature B will replace only the grouping of the "by theme" panel.

## Approaches

1. **One aggregate read endpoint, computed on request (chosen).** A backend module reads the ledger, confirmed
   tiers, proxy-voting runs and (PR 2) holdings and climate data, and returns one JSON for the page. All rules
   (control gap, escalation, ballot state, topics) live in one testable place, and the page only draws. Data sizes
   are small: hundreds of companies, tens of thousands of vote decisions, aggregated in SQL.
2. **Superset / BI views.** Rejected: the owner approved a hand-built page in the house style. The BI layer also
   publishes per month, while the cockpit is about today and the next 30 days.
3. **The page stitches existing endpoints.** Rejected: there is no read API for the ledger, portfolio scope needs
   holdings on the server, and the emissions maths must stay in the backend next to `compute_financed_emissions`.

Where the planned meeting date lives (owner decision 4 says "in the ledger"; the form is my call):

- **Chosen: a column `stw_engagements.planned_meeting_date`.** One value per engagement is what the control gap
  asks ("no planned next meeting"). It also loads through the intake as one more engagement column.
- Rejected: a future-dated `stw_activities` row of type `meeting`. Activities are VOICE evidence, counted per
  objective in Table 2, so a planned meeting would inflate those counts.
- Rejected: a separate planned-meetings table. It would add a table, an intake sheet and ids for one date.

## Definitions (all as of the request's `as_of`, default today UTC)

- **Engagement**: a `stw_engagements` row. **Open**: `status` is `open` or `stalled`.
- **Company key**: `stw_companies.company_id` (for held companies `isin_<ISIN>`, as the foundation spec keys
  them). It is compared with `securities[h.security_id].company_id` (as `compute_financed_emissions` uses it), the
  tier row's `issuer_id`, `vote_meetings.company_id` and the run ballot's `company_id`. The registry UUID on
  `holdings` is not used. Company name: `stw_companies.name`; for an unmatched vote meeting, `issuer_name`.
- **Engaged company**: a company with at least one open engagement.
- **Selected company** (owner decision 6): a company whose latest confirmed tier
  (`TierStore(settings.stewardship_streams_dir).latest()`, `tiers.py`) is `bilateral`, `letter` or `monitor`. A
  tier row with any other value (an old tier name) does not count.
- **Theme group** of an engagement, from its `fir_theme` (*my call*, the stand-in until feature B's programmes):

  | Theme group | `fir_theme` values |
  |---|---|
  | Climate | `climate_mitigation`, `climate_adaptation` |
  | Corporate governance | `governance_board_pay`, `business_ethics`, `tax_accounting`, `shareholder_rights` |
  | Nature | `natural_capital`, `resources_circular`, `pollution` |
  | AI and digital | `digital_responsibility` |
  | Norm violations | `human_rights`, `human_capital`, `consumer_protection`, `communities` |
  | Other | `other`, or `fir_theme` null |

  A selected company with no open engagement gets its group from its confirmed tier's `rule`: `high_emitter` →
  Climate, `nature_impact` → Nature, anything else → Other. The free-text `theme` is not read.
- **Current objective** of an engagement: its `stw_objectives` row with status `initiated` or `in_progress` and the
  latest `started_at` (ties: `objective_id`). None when there is no such row.
- **Control gap** (owner decision 1): an open engagement with no current objective (`no_objective`), or whose
  `planned_meeting_date` is null or earlier than `as_of` (`no_next_meeting`). *My calls:* an objective that is
  closed or abandoned is not "set"; a date in the past is not a planned *next* meeting. One engagement can have
  both gaps; it is one gap row listing both. Migrated engagements without objectives show as `no_objective`, which
  matches the foundation's "not yet a VOICE engagement".
- **Window**: the 30 days `as_of` to `as_of + 29`, both included.
- **Escalation step**: the 1-based position of `escalation_stage` in `ESCALATION_ORDER` (null counts as step 1). A
  company's step is the highest step among its open engagements. **In escalation**: a company at step 2 or more.
- **Season**: the calendar year of `as_of`. A vote counts when its meeting date (UTC date part) is in that year and
  on or before `as_of`.
- **Scope**: `portfolio_id` absent means all portfolios: every engagement, confirmed tier, meeting and vote, with no
  filter. `portfolio_id` given means only companies held in that portfolio per
  `load_holdings_as_of(as_of, [portfolio_id])`, applied to every section.
- **Demo row**: an engagement, meeting or decision whose `source` is `mock_voice_seed`, `npx_urth_demo` or
  `cockpit_demo`, or a tier row with `confirmed_by` `showcase demo`.

## Ledger change: `planned_meeting_date`

- `stw_engagements.planned_meeting_date` (`date`, nullable), on `StwEngagementModel`; `ensure_schema` adds it to
  existing databases.
- Engagement intake (API and Excel): the `engagements` sheet gains an optional last column `planned_meeting_date`
  (ISO date; an Excel date cell is accepted like `started_at`). An empty cell stores null. A malformed value
  rejects the row with one rejection `{sheet: "engagements", row: <n>, field: "planned_meeting_date", reason: "not a date"}`. It counts in the unchanged/updated comparison like
  every other column. The template lists it last on the `engagements` sheet.
- This supersedes `stewardship-data-foundation` AC-20 for the `engagements` sheet only: its header row is the
  foundation's list followed by `planned_meeting_date` (AC-6 here). The holdout test for that AC-20 is updated in
  the same change.

## API: `GET /api/stewardship/cockpit`

Query: `portfolio_id` (optional), `as_of` (optional `YYYY-MM-DD`, default today UTC). Unknown `portfolio_id` gives
404 with detail `Unknown portfolio <id>`; a malformed `as_of` gives 422. Same `authorize` dependency as the other
`/api/stewardship` routes. Response model `CockpitResponse`, exported to `openapi.json` / `schema.gen.ts`, with a
line in `frontend/src/api/contract.ts`:

```
as_of: "2026-11-27"
scope: {portfolio_id: str | null, label: str}       # "All portfolios (7)" or the portfolio name
portfolios: [{portfolio_id, name}]                    # for the selector, sorted by name
demo: bool                                            # any demo row in scope
summary: {selected: int, engaged_selected: int, engaged_outside_selection: int}
days: [{date, engagement_meetings: int, shareholder_meetings: int}]          # exactly 30, the window in order
themes: [{theme, selected: int, engaged: int}]
engagement_meetings: [{date, company_id, company, engagement_id, theme, objective: str|null, step: int, stage}]
shareholder_meetings: [{date, company_id, company, items: int, flagged: int|null, ballot_state,
                        action_due: bool, days_to_meeting: int, run_id: str|null}]
control_gaps: [{company_id, company, engagement_id, theme, open_days: int|null, gaps: [str]}]
ladder: [{step: int, stage, label, companies: [{company_id, company}]}]       # exactly 7, steps 1..7
voting: {season: int, meetings: int, votes: int, for: int, against: int, abstain: int, other: int,
         against_management: int, topics: [{topic, votes: int, against_management: int}]}
emissions: null | {...}                               # PR 2, below; null in PR 1
```

Rules:

- `summary.selected` = selected companies in scope; `engaged_selected` = those of them that are engaged;
  `engaged_outside_selection` = engaged companies in scope that are not selected.
- `themes`: fixed order Climate, Corporate governance, Nature, AI and digital, Norm violations, Other. Other is
  omitted when both its numbers are 0. `engaged` = selected companies with an open engagement in that group.
  `selected` = selected companies attributed to the group: an engaged company counts once in each group of its open
  engagements, a non-engaged one once, by tier rule. A company may appear in several rows; `summary` counts it once.
- `engagement_meetings`: open engagements whose `planned_meeting_date` is in the window, sorted by date.
- `shareholder_meetings`: meetings in the window, sorted by date, one row per company and meeting date.
  - **From runs:** the latest `proxy_voting` run with a ballot for that company and date
    (`voting_feed.items()`). `items` = its ballot items. `flagged` = items where the policy recommends `against` or
    `withhold` and management recommends `for`. `ballot_state` = `cast` when every item is cast, `decided` when
    no item is `awaiting` but not every item is cast, else `awaiting`.
  - **From the ledger,** only when no run row exists for that company and date. Meeting date = UTC date part of
    `meeting_date`; meetings with null `company_id` are skipped. `items` = its `vote_items`; `flagged` = null.
    `ballot_state` = `cast` when every item has a decision, `awaiting` when some do, `not_started` when none do.
    `run_id` is null.
  - `days_to_meeting` = meeting date − `as_of` in days. `action_due` = `ballot_state` is `awaiting` or
    `not_started` and `days_to_meeting` ≤ 7.
- `days[i].engagement_meetings` / `shareholder_meetings` = rows of the two lists above on that date.
- `control_gaps`: one row per open engagement with a gap. `gaps` ⊆ `["no_objective", "no_next_meeting"]`, in that
  order. `open_days` = `as_of` − the date part of `started_at`, or null when `started_at` is null. Sorted by
  `open_days` descending, nulls last.
- Ties in `engagement_meetings`, `shareholder_meetings` and `control_gaps` sort by company name, then
  `engagement_id` (meetings: `company_id`).
- `ladder`: each engaged company listed once, at its step, sorted by company name. `label` per step: 1 Private
  dialogue, 2 Joint engagement, 3 Letter to the board, 4 Meeting with the chair, 5 Vote against management, 6 File
  a resolution, 7 Public statement.
- `voting` (season, in scope). The unit is one vote:
  - Votes counted: each `vote_decisions` row (a split vote counts once per decision row), plus each run item with
    status `cast` that has no ledger decision with the same `run_id`.
  - `for` / `against` / `abstain` come from the vote value; `withhold` counts as `against`. Every other value
    (`do_not_vote`, `one_year`, `two_years`, `three_years`, `other`) is `other`.
  - `against_management`: the decision's `against_management` is true, or the run feed's `against_management`.
  - `meetings` = distinct (company or issuer, meeting date) among the counted votes.
  - Topics, in this fixed order; each vote falls in exactly one, the first that matches:
    1. **Shareholder proposals**: ledger `proponent` is `shareholder` (case-insensitive); run type
       `shareholder_resolution`.
    2. **Remuneration**: an element of `categories` contains `SAY-ON-PAY` or `COMPENSATION`; run type `say_on_pay`.
    3. **Director elections**: an element contains `DIRECTOR`; run type `director_election`.
    4. **Auditors**: an element contains `AUDIT`; run type `auditor_ratification`.
    5. **Capital and other**: everything else.

    Category text is matched case-insensitively against any element of the item's `categories` array.

### `emissions` (PR 2)

```
emissions: {total_tco2e: float, engaged_tco2e: float, selected_not_engaged_tco2e: float,
            not_selected_tco2e: float, uncovered_holding_count: int,
            contributors: [{company_id, company, sector, tco2e: float, share: float, status}]}   # top 6
```

- A new function next to `compute_financed_emissions` (`arp/portfolio/climate/metrics.py`) returns financed
  emissions **per company**, with the same formula: the sum over the company's holdings in scope of
  `(market_value_eur / 1e6) / EVIC_eur_m × (Scope 1 + Scope 2)`. Holdings without EVIC or Scope 1/2 are left out
  and counted in `uncovered_holding_count`. `total_tco2e` equals
  `compute_financed_emissions(...)["financed_emissions_tco2e"]` for the same holdings and `as_of`, ±0.1 t
  (rounding). `compute_financed_emissions` itself does not change.
- Holdings: `store.load_holdings_as_of(as_of, <portfolio ids in scope, or None for all>)`, exactly as
  `arp climate financed-emissions` selects them.
- Buckets: engaged companies, selected but not engaged, and the rest. The three sum to `total_tco2e` (±0.1 t).
- `contributors`: the 6 largest companies by `tco2e`, ties by name. `share` = `tco2e / total_tco2e`, 0 to 1, 4
  decimals. `status` is the first that applies: `in_escalation`, `engaged`, `selected`, `not_selected`. `company` and `sector` come
  from the security's company.
- `emissions` is `null` when no holdings are in scope or `total_tco2e` is 0.

## The page (`#/stewardiq/cockpit`)

New page `frontend/src/pages/StewardCockpit.tsx`, routed in `App.tsx` when the tab is `stewardiq` and the first
param is `cockpit`. Today line 403 renders `WorkspaceOverview` for every `stewardiq` route; `#/stewardiq` keeps
showing it. Layout and copy follow the mockup:

- **Header:** a "StewardIQ" crumb, the title "Cockpit", and the scope selector (`All portfolios (N)`, then each
  portfolio; changing it refetches with `portfolio_id`). Then "As of <d MMM yyyy>" from the response's `as_of`,
  and a `Demo data` pill when `demo` is true.
- **`as_of`:** an optional second path segment, `#/stewardiq/cockpit/2026-11-27` (route `params[1]`), is passed
  to the API as `as_of`. Without it, the API's default (today UTC) applies. `parseHash` does not change.
- **Six key figures:**
  - **Companies engaged**: `engaged_selected / selected`, with "<p>% of selected companies".
  - **Financed emissions covered** (PR 2; hidden while `emissions` is null): `engaged_tco2e / total_tco2e` as a %,
    with "<a> of <b> Mt CO₂e in engagement".
  - **Next 30 days**: the two meeting lists' counts added up, with the split.
  - **Control gaps**: the number of gap rows, with "<x> without objective · <y> without next meeting".
  - **In escalation**: companies at step 2 or higher, with "Highest step: <label>".
  - **Votes cast, <season>**: `voting.votes`, with "<meetings> meetings · <p>% against management".
- **30-day strip:** one column per `days` entry, weekends shaded, two bar series (engagement meetings, shareholder
  meetings).
- **Engaged vs selected, by theme** (*my call* until feature B): the panel shows the `themes` rows, titled "by
  theme" so it does not claim named programmes. Each row has two bars, a selected track and an engaged fill, and
  "<e> / <s>". Feature B renames the panel and swaps its grouping; nothing else on the page changes.
- **Financed emissions in engagement** (PR 2): one stacked bar (engaged / selected not engaged / not selected) and
  the contributors table (Company · sector, Share, Status).
- **Upcoming engagement meetings:** Date, Company + theme, Objective (or "No objective"), Step. Up to 6 rows, then
  a button `All <n>` that shows the rest in place.
- **Upcoming shareholder meetings:** Date, Company, Items, Flagged (`–` when null), Ballot.
  - Ballot text is `Cast`, `Decided, not cast`, `Awaiting decision` or `Not started`.
  - When `action_due`, the text is exactly `Decision due today` (0 days), `Decision due in 1 day` (1) or
    `Decision due in <n> days` (2–7), in the signal style.
  - A row with a `run_id` links to `#/voting/<run_id>`.
  - Up to 6 rows, then `All <n>`.
  - Footnote: "Flagged: items where the voting policy recommends a vote against management."
- **Control gaps:**
  - Header count "<n> need you" in the signal style.
  - Each row shows the company, "<theme> · open <d> days", and the gap text: `No objective`, `No next meeting`,
    or both joined by ` · `.
  - Footnote: "A gap is an open engagement with no objective or no planned next meeting."
  - With no gaps it reads "No control gaps." and uses no signal colour.
- **Escalation ladder:** 7 rows, each with the step number, label, count and company names. Step 1 shows only the
  count.
- **Voting, season to date:** one stacked bar for / against / abstain (plus other, only when it is above 0) with
  counts. Under it, "Against management, by topic": one bar per topic, "<rate>% · <a> of <n>".
- **Zero cases:** `selected` 0 shows `0 / 0` and "– of selected companies"; `voting.votes` 0 shows "0 meetings · –
  against management"; no company in escalation shows `0` and "Highest step: –"; a topic with 0 votes shows
  "– · 0 of 0".
- **Numbers:** percentages are whole numbers, rounded half up. Mt CO₂e has two decimals. Counts use thousands
  separators.
- **Empty and error states:** an empty section says so in one line (e.g. "No engagement meetings in the next 30
  days."), never a blank card. A load failure shows one `role="alert"` line, "The cockpit could not be loaded:
  <message>".
- **House style** per `DESIGN.md`: both themes, colour tokens rather than hex values, tabular numbers, hand-built
  SVG/CSS.
  - The signal colour appears only on control gaps and on `action_due` ballots.
  - Escalation steps use status colours, never the signal colour.
  - Below 900 px the page stacks to one column, with no horizontal page scroll.

Link: in `frontend/src/lib/processes.ts`, the StewardIQ `screens` list gains `["#/stewardiq/cockpit", "Cockpit"]`
as its first entry; the other four keep their order.

## Demo data: `arp stewardship seed-cockpit-demo`

New module `backend/arp/stewardship/cockpit_demo.py` and command `arp stewardship seed-cockpit-demo [--as-of
YYYY-MM-DD]` (default today UTC). Showcase order: `arp showcase load`, `arp stewardship seed-demo`, `arp stewardship
load-npx data/voting/npx_urth/`, then this. It prints one line per step, `ok|FAIL <step>: <detail>`, and exits 1
on the first FAIL. It never changes a row whose `source` is not `mock_voice_seed` or `cockpit_demo`, and never
removes a row. Let `h(x)` = `int(hashlib.sha256(x.encode("utf-8")).hexdigest(), 16)`; in `"items:" + k`, k is written in decimal.

1. `planned`: for every open `mock_voice_seed` engagement `e`, with `b = h(engagement_id) mod 20` and
   `k = (h(engagement_id) div 20)`, it sets `planned_meeting_date` as follows:
   - `b` 0–5: `as_of + (k mod 30)` days, inside the window.
   - `b` 6–16: `as_of + 30 + (k mod 90)` days, later.
   - `b` 17–19: null, which makes a `no_next_meeting` gap.

   Prints `ok planned: <n> engagements`.
2. `escalation`: for every open `mock_voice_seed` engagement still at `private_engagement`, with `c =
   h("esc:" + engagement_id) mod 100`, it moves the engagement to step 2 (`c` 0–1), 3 (`c` 2), 4 (`c` 3) or 5 (`c`
   4). Each move writes `escalation_stage` plus one `stw_transitions` row (`kind` `escalation`, `decided_by`
   `showcase demo`, `source` `cockpit_demo`). Prints `ok escalation: <n> engagements`.
3. `tiers`: it proposes tiers with the active coverage rules (`tier_contexts` + `evaluate` over `load_sample()` and
   the engagement records) and confirms every proposal whose issuer has no confirmed tier yet, with `decided_by`
   `showcase demo`. Prints `ok tiers: <n> confirmed`.
4. `meetings`: it upserts 14 `vote_meetings` (`source` `cockpit_demo`, `external_id` `cockpit_demo:meeting:<k>`, k
   = 0–13) for 14 held companies that have `stw_companies` rows (held = the company key of any holding in
   `load_holdings_as_of(as_of, None)`). The companies are the 14 with the smallest `h(company_id)`.
   - Meeting k is dated `as_of + [1, 2, 4, 6, 9, 11, 13, 15, 18, 20, 22, 24, 27, 29][k]` days, with `meeting_type`
     `annual`.
   - Each meeting has `10 + h("items:" + k) mod 13` `vote_items` (10–22), with N-PX-style categories,
     `management_recommendation` `for`, and proponent `issuer`, except one `shareholder` item in meetings with odd k.
   - No decisions.

   Prints `ok meetings: 14 upcoming`.

A second run with the same `--as-of` writes nothing. A run with a later `--as-of` moves the demo dates (steps 1
and 4). Escalations and tier confirmations stay as they are.

Expected showcase shape (not an acceptance figure; the counts follow the seed): about 30 % of open demo
engagements have a meeting in the next 30 days and about 15 % have no date, about 5 % are escalated, 14 shareholder
meetings fall in the window and 4 of them are due, and the 2026 season shows the N-PX votes cast from January to
June 2026.

## PR plan

| PR | Content | Risk | Holdout `Rows:` |
|---|---|---|---|
| 1 | `planned_meeting_date` (column, intake, template); `GET /api/stewardship/cockpit` with every field except `emissions` (always `null`); `arp stewardship seed-cockpit-demo`; the page with every section except the emissions panel and figure; the overview link; regenerated API files | normal | AC-1 to AC-52 and AC-73 to AC-78, listed one by one: `Rows: AC-1, AC-2, …, AC-52, AC-73, …, AC-78` |
| 2 | Per-company financed emissions; `emissions` in the response; the emissions panel and key figure | high | AC-53 to AC-63 (last slice, no `Rows:` line) |
| 3 | A Cockpit entry on the start page (`#/home`), and polish after `/impeccable:impeccable audit` on the demo stack | low | none |

PR 1 alone is a complete page with five of the six key figures.

## What is left to the builder

- Function and file names inside the backend module, and how the SQL is composed.
- The wording of the demo items.
- Exact spacing, typography and status colours, within `DESIGN.md` and the mockup.

## Showcase setup (no code)

On the showcase stack, with `ARP_ENGAGEMENT_STORE=postgres`, run:

1. `arp showcase load`
2. `arp stewardship seed-demo`
3. `arp stewardship load-npx data/voting/npx_urth/`
4. `arp stewardship seed-cockpit-demo`, on the morning of the showcase, so the dates count from that day.

To show a live ballot state, run one proxy vote on a company with a demo meeting before the showcase.

## Acceptance

All `holdout` rows run on the e2e stack (`backend/scripts/e2e_stack.sh up`; Postgres, `ARP_ENGAGEMENT_STORE=postgres`).
Each test starts from:

- empty `stw_*` and `vote_*` tables;
- an empty tier log (`<settings.stewardship_streams_dir>/tier_assignments.jsonl`, env `ARP_STEWARDSHIP_STREAMS_DIR`);
- no `proxy_voting` runs.

It builds fixtures with:

- direct inserts into `stw_companies` (intake accepts only known companies), and into `stw_engagements` /
  `stw_objectives` where a row needs a `source` other than `api`;
- the engagement intake (`POST /api/stewardship/intake/engagements`, JSON);
- the escalate route (`POST /api/engagement/records/{company_id}/issues/{engagement_id}/escalate`);
- `TierStore(settings.stewardship_streams_dir).confirm`;
- direct inserts into `vote_meetings`, `vote_items` and `vote_decisions`;
- for portfolios, the portfolio store's `save_portfolio`, `save_security` and `save_snapshot`. Securities carry
  the company key (see Definitions). Climate values via `append_observation` (`climate_evic_eur_m`,
  `climate_scope1_tco2e`, `climate_scope2_tco2e`).

The stack already holds the portfolios `arp portfolio seed-demo` writes (`e2e_stack.sh up`); rows that need an
exact portfolio set use `portfolio_id`.

"Cockpit" below means `GET /api/stewardship/cockpit`. "Engagement A" means an engagement taken in by intake for
company `isin_XA0000000001` ("Alpha AG", its `stw_companies` row inserted first), `status` `open`, `fir_theme` `climate_mitigation`, `started_at`
`2026-10-03`, with one objective, `status` `in_progress`, `objective_type` `strategic`, description "Cut coal", and `planned_meeting_date`
`2026-11-20`, unless the row says otherwise.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | no engagements, tiers, runs or votes | Cockpit `?as_of=2026-11-17` | 200; `summary` is `{selected: 0, engaged_selected: 0, engaged_outside_selection: 0}`; `engagement_meetings`, `shareholder_meetings`, `control_gaps` are `[]`; `voting.votes` is 0; `demo` is `false` | holdout |
| AC-2 | same | same | `days` has 30 entries, the first `date` `"2026-11-17"`, the last `"2026-12-16"`, every count 0 | holdout |
| AC-3 | same | same | `ladder` has 7 entries with `step` 1..7 and `label` exactly "Private dialogue", "Joint engagement", "Letter to the board", "Meeting with the chair", "Vote against management", "File a resolution", "Public statement", each `companies` `[]` | holdout |
| AC-4 | any | Cockpit `?as_of=2026-13-01` | 422 | holdout |
| AC-5 | no portfolio `nope` | Cockpit `?portfolio_id=nope&as_of=2026-11-17` | 404, detail `"Unknown portfolio nope"` | holdout |
| AC-6 | — | `GET /api/stewardship/intake/template?kind=engagements`, opened in openpyxl | the `engagements` sheet's header row is `external_id, company_id, isin, company_name, theme, fir_theme, esg_pillars, rationale, engager_role, started_at, status, severity, planned_meeting_date` (supersedes `stewardship-data-foundation` AC-20 for this sheet) | holdout |
| AC-7 | engagement A taken in by intake | the same batch is sent again | 200 with `created` 0 and `updated` 0; the stored `planned_meeting_date` is `2026-11-20` | holdout |
| AC-8 | engagement A taken in by intake | the batch is sent again with `planned_meeting_date` `2026-11-25` | 200 with `updated` 1; the stored value is `2026-11-25` | holdout |
| AC-9 | company A's `stw_companies` row | intake of engagement A with `planned_meeting_date` `"20.11.2026"` | 422; `rejected` is exactly `[{sheet: "engagements", row: 1, field: "planned_meeting_date", reason: "not a date"}]`; no `stw_engagements` row is stored | holdout |
| AC-10 | engagement A taken in by intake | `POST …/escalate` with `{stage: "joint_engagement"}` | the stored `planned_meeting_date` is still `2026-11-20` (must not change) | holdout |
| AC-11 | engagement A | Cockpit `?as_of=2026-11-17` | `engagement_meetings` is exactly one row: `date` `"2026-11-20"`, `company_id` `isin_XA0000000001`, `company` `"Alpha AG"`, `theme` `"Climate"`, `objective` `"Cut coal"`, `step` 1 | holdout |
| AC-12 | engagement A | same | `days[3]` is `{date: "2026-11-20", engagement_meetings: 1, shareholder_meetings: 0}` | holdout |
| AC-13 | engagement A | same | `control_gaps` is `[]` | holdout |
| AC-14 | engagement A with `planned_meeting_date` `2026-12-17` | same | `engagement_meetings` is `[]` | holdout |
| AC-15 | engagement A with `planned_meeting_date` `2026-11-17` | same | `engagement_meetings` has A on `"2026-11-17"` | holdout |
| AC-16 | engagement A with `planned_meeting_date` empty | same | `control_gaps` is one row for A with `gaps` `["no_next_meeting"]` and `open_days` 45 | holdout |
| AC-17 | engagement A with `planned_meeting_date` `2026-11-16` | same | `control_gaps` is one row for A with `gaps` `["no_next_meeting"]` | holdout |
| AC-18 | engagement A without objectives | same | `control_gaps` is one row for A with `gaps` `["no_objective"]` | holdout |
| AC-19 | engagement A without objectives | same | A's `engagement_meetings` row has `objective` `null` | holdout |
| AC-20 | engagement A whose only objective has `status` `closed`, and no `planned_meeting_date` | same | `control_gaps` is one row for A with `gaps` `["no_objective", "no_next_meeting"]` | holdout |
| AC-21 | engagement A with two objectives, both `in_progress`: "Old aim" `started_at` 2026-01-10 and "New aim" `started_at` 2026-09-01 | same | A's `engagement_meetings` row has `objective` `"New aim"` | holdout |
| AC-22 | engagement A with `status` `resolved` and no `planned_meeting_date` | same | `control_gaps` is `[]` | holdout |
| AC-23 | engagement A with `status` `stalled` | same | `engagement_meetings` has one row for A | holdout |
| AC-24 | company A with two open engagements, escalated to `joint_engagement` and `escalation_to_chair` | same | `ladder[3].companies` is `[{company_id: "isin_XA0000000001", company: "Alpha AG"}]` and A is in no other ladder step | holdout |
| AC-25 | company A with one open engagement escalated to `vote_against_management`, and a second engagement escalated to `public_statement` while open, then sent again through intake with `status` `resolved` | Cockpit `?as_of=2026-11-17` | A is listed only in `ladder[4]` | holdout |
| AC-26 | confirmed tiers B `bilateral`, C `letter`, D `monitor`, E `thematic_collaborative` (an old row); B has an open engagement; F has an open engagement and no tier | same | `summary` is `{selected: 3, engaged_selected: 1, engaged_outside_selection: 1}` | holdout |
| AC-27 | B confirmed `bilateral`, later confirmed `monitor` | same | `summary.selected` is 1 | holdout |
| AC-28 | B selected, open engagement `fir_theme` `governance_board_pay`; C selected, rule `high_emitter`, no engagement; D selected, rule `top_weight`, no engagement | same | `themes` as `{theme, selected, engaged}` is exactly `[{Climate,1,0},{Corporate governance,1,1},{Nature,0,0},{AI and digital,0,0},{Norm violations,0,0},{Other,1,0}]` | holdout |
| AC-29 | B selected, open engagements with `climate_mitigation` and `digital_responsibility` | same | the Climate and AI and digital rows both have `selected` 1 and `engaged` 1; `summary.engaged_selected` is 1 | holdout |
| AC-30 | only C selected, rule `nature_impact` | same | `themes` has 5 rows (no `Other`) and Nature is `{selected: 1, engaged: 0}` | holdout |
| AC-31 | a ledger meeting for company G (`stw_companies` row "Gamma SE") on 2026-11-20 with 3 `vote_items` and no decisions | same | `shareholder_meetings` is one row: `date` `"2026-11-20"`, `company` `"Gamma SE"`, `items` 3, `flagged` `null`, `ballot_state` `"not_started"`, `days_to_meeting` 3, `action_due` `true`, `run_id` `null` | holdout |
| AC-32 | the meeting of AC-31 dated 2026-11-25 | same | `days_to_meeting` 8 and `action_due` `false` | holdout |
| AC-33 | AC-31 with decisions on 2 of 3 items | same | `ballot_state` `"awaiting"` and `action_due` `true` | holdout |
| AC-34 | AC-31 with decisions on all 3 items | same | `ballot_state` `"cast"` and `action_due` `false` | holdout |
| AC-35 | AC-31 dated 2026-12-17; another with null `company_id` dated 2026-11-20 | same | `shareholder_meetings` is `[]` | holdout |
| AC-36 | a `proxy_voting` run ballot for H, meeting 2026-11-19, 4 items, policy `against` / management `for` on 2, none decided | same | H's row: `items` 4, `flagged` 2, `ballot_state` `"awaiting"`, `action_due` `true`, `run_id` the run id | unit |
| AC-37 | AC-36 with every item decided, 1 cast | same | `ballot_state` `"decided"`, `action_due` `false` | unit |
| AC-38 | AC-36 with every item cast | same | `ballot_state` `"cast"` | unit |
| AC-39 | AC-36 plus a ledger meeting for H on 2026-11-19 | same | exactly one row for H on that date, with the run's `run_id` | unit |
| AC-40 | ledger, company G: a 2026-03-10 meeting with four decisions: categories `{DIRECTOR ELECTIONS}` `for` (`against_management` false); `{SECTION 14A SAY-ON-PAY VOTES}` `against` (true); `{AUDIT-RELATED}` `abstain` (null); proponent `shareholder`, categories `{OTHER SOCIAL MATTERS}`, `for` (true). Also a 2025-12-01 meeting with one decision and a 2026-11-20 meeting with one decision | Cockpit `?as_of=2026-11-17` | `voting` is `{season: 2026, meetings: 1, votes: 4, for: 2, against: 1, abstain: 1, other: 0, against_management: 2, …}` | holdout |
| AC-41 | AC-40 | same | `voting.topics` as `{topic, votes, against_management}` is exactly `[{Shareholder proposals,1,1},{Remuneration,1,1},{Director elections,1,0},{Auditors,1,0},{Capital and other,0,0}]` | holdout |
| AC-42 | ledger only: a 2026-03-10 meeting for G with three decisions `withhold`, `one_year`, `do_not_vote` | same | `voting` has `votes` 3, `for` 0, `against` 1, `abstain` 0, `other` 2 | holdout |
| AC-43 | a 2026-03-10 ledger meeting for G, one item with two decisions (a split vote), both `for` | Cockpit `?as_of=2026-11-17` | `voting.votes` is 2 and `voting.meetings` is 1 | holdout |
| AC-44 | portfolio P holds company A only; A and B are both engaged and selected, each with a planned meeting in the window, one `no_objective` gap and a ledger meeting in the window | Cockpit `?portfolio_id=P&as_of=2026-11-17` | `engagement_meetings`, `shareholder_meetings`, `control_gaps` and every `ladder[].companies` hold only A; `summary.selected` is 1; `scope` is `{portfolio_id: P, label: <P's name>}` | holdout |
| AC-45 | the stack's portfolios plus 3 saved by the test; N = the number of portfolios in the store | Cockpit `?as_of=2026-11-17` | `scope` is `{portfolio_id: null, label: "All portfolios (N)"}`; `portfolios` has N entries sorted by `name` | holdout |
| AC-46 | engagement A inserted directly into `stw_engagements` with `source` `mock_voice_seed` | Cockpit `?as_of=2026-11-17` | `demo` is `true` | holdout |
| AC-47 | a portfolio with snapshots dated on or before 2026-11-27 holding at least 14 companies with `stw_companies` rows; 40 open engagements inserted directly with `source` `mock_voice_seed` at `private_engagement` | `arp stewardship seed-cockpit-demo --as-of 2026-11-27` | exits 0; stdout is exactly four lines starting `ok planned: 40 engagements`, `ok escalation:`, `ok tiers:`, `ok meetings: 14 upcoming` | holdout |
| AC-48 | after AC-47 | Cockpit `?as_of=2026-11-27` | `shareholder_meetings` has 14 rows, all `ballot_state` `"not_started"`, with `days_to_meeting` exactly `[1, 2, 4, 6, 9, 11, 13, 15, 18, 20, 22, 24, 27, 29]` | holdout |
| AC-49 | after AC-47 | read `stw_engagements` | every open `mock_voice_seed` engagement's `planned_meeting_date` is null or between 2026-11-27 and 2027-03-26, and each one equals the rule of step 1 | holdout |
| AC-50 | after AC-47 | run it again with `--as-of 2026-11-27` | row counts of `stw_engagements`, `stw_transitions`, `vote_meetings`, `vote_items` and the tier log are unchanged; no `planned_meeting_date` changes | holdout |
| AC-51 | after AC-47, plus one open engagement with `source` `api` and no `planned_meeting_date` | `seed-cockpit-demo --as-of 2026-12-01` | the `api` engagement is unchanged: `planned_meeting_date` null, `escalation_stage` as before | holdout |
| AC-52 | the demo stack of "Showcase setup" | open `#/stewardiq` | the screens row shows `Cockpit` first, then Steward Workflow, Engagement, Proxy Voting, RFP Answers; the processes are unchanged (must not change) | evaluator |
| AC-53 | (PR 2) portfolio P: A 1,000,000 EUR, EVIC 100 EUR m, Scope 1 800, Scope 2 200; B 2,000,000 EUR, EVIC 100, Scope 1 300, Scope 2 200; C 1,000,000 EUR without EVIC; climate observations dated 2026-11-01; A engaged; B selected and not engaged | Cockpit `?portfolio_id=P&as_of=2026-11-17` | `emissions` has `total_tco2e` 20.0, `engaged_tco2e` 10.0, `selected_not_engaged_tco2e` 10.0, `not_selected_tco2e` 0.0, `uncovered_holding_count` 1 | holdout |
| AC-54 | AC-53 | same | `contributors` is `[A, B]` (equal `tco2e`, so by name), `share` 0.5 each, `status` `engaged` and `selected` | holdout |
| AC-55 | AC-53, with A's engagement escalated to `joint_engagement` | same | A's contributor `status` is `in_escalation` | holdout |
| AC-56 | AC-53's holdings and data | `compute_financed_emissions(..., as_of="2026-11-17", portfolio_filter=[P])` | returns exactly `{as_of: "2026-11-17", financed_emissions_tco2e: 20.0, covered_market_value_eur: 3000000.0, uncovered_market_value_eur: 1000000.0, coverage_pct: 0.75, uncovered_holding_count: 1}` (must not change) | holdout |
| AC-57 | the showcase portfolios loaded (`arp showcase load`) | Cockpit for each portfolio, `as_of=2026-11-02` | `emissions.total_tco2e` equals `financed_emissions_tco2e` from `arp climate financed-emissions --portfolio <id> --as-of 2026-11-02`, within 0.1 t | holdout |
| AC-58 | same, plus `seed-cockpit-demo --as-of 2026-11-02` | Cockpit `?as_of=2026-11-02` | `engaged_tco2e + selected_not_engaged_tco2e + not_selected_tco2e` equals `total_tco2e` within 0.1 t; `contributors` has 6 entries | holdout |
| AC-59 | portfolio Q saved with no snapshot on or before 2026-11-17 | Cockpit `?portfolio_id=Q&as_of=2026-11-17` | `emissions` is `null` | holdout |
| AC-60 | (PR 2) the demo stack | open `#/stewardiq/cockpit` | the "Financed emissions covered" figure shows the % and "<a> of <b> Mt CO₂e in engagement", matching the API; the emissions panel shows the three-part bar and 6 contributors | evaluator |
| AC-61 | (PR 2) a scope where `emissions` is null | open the page in that scope | the emissions figure and panel are hidden, with no empty card in their place | evaluator |
| AC-62 | the demo stack | open `#/stewardiq/cockpit` | sections in mockup order: key figures, 30-day strip, engaged vs selected by theme, financed emissions, upcoming engagement meetings, upcoming shareholder meetings, control gaps, escalation ladder, voting season to date | evaluator |
| AC-63 | the demo stack | read the six key figures | each equals the value computed from `GET /api/stewardship/cockpit` for the same `as_of` and scope, with whole-number percentages and Mt to two decimals | evaluator |
| AC-64 | the demo stack | the 30-day strip | 30 day columns from the `as_of` date, weekends shaded, bars on exactly the dates in `days` with counts above 0 | evaluator |
| AC-65 | the demo stack | Upcoming engagement meetings | at most 6 rows, then `All <n>` with n = `len(engagement_meetings)`; clicking it shows n rows | evaluator |
| AC-66 | the demo stack, `#/stewardiq/cockpit/<seed as_of>` | Upcoming shareholder meetings, `All 14` opened | the 4 meetings within 7 days read `Decision due in 1 day` / `Decision due in <n> days` in the signal style; the other 10 read `Not started` in the neutral style; Flagged shows `–` | evaluator |
| AC-67 | the demo stack | look for the signal colour (Signal Orange in Graphite, Signal Lime in Night) inside the cockpit page's main area | it appears only on: the Control gaps key-figure value, the Control gaps panel's "<n> need you" header and its gap texts, and the 4 due ballot texts | evaluator |
| AC-68 | the stack after `arp showcase load` only | open `#/stewardiq/cockpit` | no signal colour inside the page's main area; Control gaps reads "No control gaps."; every empty section shows its one-line message | evaluator |
| AC-69 | the demo stack | select portfolio `DAX` in the scope selector | the scope label reads its name; the key figures and list lengths equal those of `GET /api/stewardship/cockpit?portfolio_id=<its id>` for the same `as_of` | evaluator |
| AC-70 | the demo stack | switch to the Night theme, then back to Graphite | in both themes body text contrast is at least 4.5:1 against its ground, and every colour on the page comes from a `DESIGN.md` token | evaluator |
| AC-71 | the demo stack | 390 px wide viewport | one column, no horizontal page scroll | evaluator |
| AC-72 | the backend stopped | open the page | one alert line starting "The cockpit could not be loaded:" | evaluator |
| AC-73 | the cockpit page | open `#/stewardiq/cockpit/2026-11-17`, then `#/stewardiq/cockpit` | the first request carries `as_of=2026-11-17`; the second carries no `as_of` | unit |
| AC-74 | engagement A with `planned_meeting_date` `2026-11-17` | Cockpit `?as_of=2026-11-17` | `control_gaps` is `[]` | holdout |
| AC-75 | engagement A with `status` `resolved` and no `planned_meeting_date` | same | `engagement_meetings` is `[]` | holdout |
| AC-76 | after AC-47 | Cockpit `?as_of=2026-11-27` | exactly 4 `shareholder_meetings` rows have `action_due` `true` | holdout |
| AC-77 | after AC-47 | Cockpit `?as_of=2026-11-27` | `demo` is `true` | holdout |
| AC-78 | after AC-47 | `seed-cockpit-demo --as-of 2026-12-01`, then Cockpit `?as_of=2026-12-01` | `shareholder_meetings` `days_to_meeting` is still exactly `[1, 2, 4, 6, 9, 11, 13, 15, 18, 20, 22, 24, 27, 29]` | holdout |
| AC-79 | the demo stack | open `#/stewardiq/cockpit` | the header shows the `Demo data` pill | evaluator |
| AC-80 | the stack after `arp showcase load` only | open `#/stewardiq/cockpit` | no `Demo data` pill | evaluator |
| AC-81 | a voting run `R` exists | open `#/voting/R` | the run opens as before (must not change: routing) | evaluator |

PR slices: PR 1 delivers AC-1 to AC-52 and AC-62 to AC-81, except the emissions parts of AC-62 and AC-63, which
come with PR 2. PR 2 delivers AC-53 to AC-61. PR 1's `Rows:` line lists AC-1 to AC-52 and AC-73 to AC-78; the
evaluator checks AC-62 to AC-72 and AC-79 to AC-81 on PR 1 without the emissions section, and again on PR 2.

Must not change: the intake's other columns and its unchanged/updated behaviour (AC-7), `planned_meeting_date`
kept by existing store writes (AC-10), the StewardIQ overview apart from the link (AC-52),
`compute_financed_emissions` (AC-56), and routing of existing hash routes (AC-81). Supersedes: `stewardship-data-foundation` AC-20, for the `engagements`
sheet only (AC-6).
