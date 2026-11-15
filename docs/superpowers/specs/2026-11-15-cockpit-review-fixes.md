# Cockpit review fixes

Slug: `cockpit-review-fixes`

Risk: PR A `risk:normal`, PR B `risk:normal` (reason under "PR plan"). Size M, 2 PRs.
Status: **approved by the owner on 15 Nov 2026** (buttons in the spec session).
Starts after: PR #490 (cockpit PR 2, financed emissions) is merged. Both PRs branch from `main` after that merge.

## Intent

The owner asked on 15 Nov 2026 for the open review findings on the StewardIQ Cockpit (`stewardship-cockpit`) to be
fixed before the cockpit is shown live to senior management on about 27 Nov 2026. Each fix makes a number or a
label on the page (or in the client report) say what it claims: a tier count that counts only the house's
companies, a declined ballot that does not look settled, a demo seed that selects only companies the house really
holds, a theme grid whose bars can be read, and an emissions panel that hides itself when there is nothing to
show.

Who it is for: the stewardship lead presenting the cockpit, and the managers watching. A wrong-looking number in
front of them costs more than a missing feature.

## Evidence (read on `main` b53ad65 and on the #490 branch `stewardship-cockpit-pr2` fe98697)

1. **Client report tier counts include companies outside the house universe.** `process.py:712`
   `current_tiers` returns the sample issuers' proposals merged with *every* confirmed tier in the `TierStore`.
   `client_report.py:61` counts that whole union, so tier rows confirmed for companies the house universe does
   not contain (seeded demo tiers, older universes) inflate the "Coverage tiers" chart and table (about 2,600
   extra on the showcase data; not verified). The other callers of `current_tiers` (`worklist.py:237`,
   `program.py:180`, `escalation_contexts`) look tiers up by issuer and do not count them; they stay as they are.
2. **A declined ballot reads as settled.** `voting_feed.py:56` gives an item status `declined` when a reviewer
   rejected the policy recommendation without a vote. `cockpit.py:58` `ballot_state_of_run` knows only `cast` and
   `awaiting`, so a ballot with a declined item and nothing awaiting returns `decided`, and `action_due` stays
   false. The page then reads "Decided, not cast" although no vote exists for that item.
3. **The demo seed selects companies the house does not hold.** `cockpit_demo.py:117` adds
   `market_value_eur or 0.0`, so a company whose holdings are all worth 0 still gets a key in `held_values`, a
   Monitor proposal in step 3 (`tiers`), a confirmed tier, and counts as selected on the cockpit.
4. **The theme grid's bars are unreadable.** `cockpit.py:184-193` puts every selected company without an open
   engagement and without a themed tier rule into the `Other` row; on the showcase data that is about 2,181
   companies. `StewardCockpit.tsx:211` scales every bar to one `max`, so the named-theme bars shrink to 2-11 px.
   The `Other` row and its numbers are fixed by `stewardship-cockpit` (spec lines 202 and 465, rows AC-28, AC-82).
5. **(#490) A near-zero emissions total shows an empty panel.** `emissions_of` (`cockpit.py:107` on #490)
   returns `None` only when the unrounded total is exactly 0. A scope with under 0.005 t returns
   `total_tco2e` 0.0 with contributors, so the page shows "0 of 0 t" and an empty panel instead of hiding it.
   Contributors are sorted on raw floats (line 118), so two contributors that both read 10.00 t in the response
   are ordered by an invisible difference instead of by name.

Moved out to the sibling item `vote-abstain-and-seed-fixes`: a ballot cast twice counting twice in the voting
statistics. That item owns the "Voting, season to date" section and the vote counting in `cockpit.py`; this spec
does not touch either.

## Owner decisions (15 Nov 2026, buttons in the dispatcher session; not reopened here)

1. **Declined ballot:** it reads "Declined" and is flagged as action due, like a ballot still awaiting a decision,
   because no vote has been cast.
2. **Theme grid:** fixed on the page. Named themes get their own bar scale so their bars are readable. The row
   `Other` is renamed "No theme yet" on the page (copy only). The `themes` payload stays as it is and no theme
   data is invented, so `stewardship-cockpit` AC-28 and AC-82 are untouched.
3. **Declined ballot text when due** (15 Nov 2026, button in the spec session): keep the word, e.g.
   `Declined · decision due in 3 days`, rather than the plain awaiting text.
4. **Emissions unit** (decided on #490): the page shows whole tonnes; the API keeps tonnes rounded to 0.01 t.

## Goals

- G1. The client report's tier counts cover only the house universe's issuers (finding 1).
- G2. A run ballot with a declined item and none awaiting has `ballot_state` `declined`, reads "Declined", and is
  action due on the same 7-day rule as an awaiting ballot (finding 2, decision 1).
- G3. `seed-cockpit-demo` step 3 proposes and confirms tiers only for companies held with a total market value
  above 0 (finding 3).
- G4. The theme grid draws named-theme rows on their own scale, labels the `Other` row "No theme yet", and says on
  the page which scale each row uses (finding 4, decision 2).
- G5. (PR B) `emissions` is `null` when the total rounds to 0.00 t, and contributors with equal rounded tonnes are
  ordered by name, then company key (finding 5).

## Non-goals

- Any change to the `themes` payload, `summary`, or how companies are attributed to themes.
- Programme-based themes (feature B, `stewardship-cockpit-programmes`).
- The voting statistics section and vote counting (sibling item `vote-abstain-and-seed-fixes`).
- Removing tier rows already confirmed in a tier log. The seed never removes rows; see "Showcase setup".
- Changing `current_tiers` or its other callers.
- Changing `financed_emissions_by_company` or `compute_financed_emissions`.
- The start-page entry and polish (cockpit PR 3, separate).

## Anti-goals (a failure even if it works)

- A bar scale a viewer cannot tell apart from the other: two scales in one grid without a visible note saying
  which rows use which.
- A declined ballot that looks settled (neutral "Decided, not cast") while no vote exists.
- The signal colour on anything new except a declined ballot that is action due (`DESIGN.md`, One Signal Rule).

## Constraints

- `DESIGN.md`: monochrome, the one signal colour only where a person must act, hand-built SVG/CSS.
- The tests of `stewardship-cockpit` run unchanged. Hidden tests: AC-28, AC-30, AC-47 to AC-50, AC-53, AC-54,
  AC-56 to AC-59, AC-82, AC-83. Unit rows: AC-36 to AC-39.
- `ballot_state` is a plain `str` in `schemas/cockpit.py`, so a new value needs no API regeneration.

## Approaches

**Theme grid (the only part with real alternatives):**

1. **Two scales, said on the page (chosen, per decision 2).** Named-theme rows share one scale: the largest
   named-theme `selected` fills the bar. The "All themes" row and the "No theme yet" row share the total scale
   (`summary.selected`). A heavier rule sets "No theme yet" apart from the named rows, and one muted line under the
   legend states both scales with their numbers.
2. **Each cell as a share of its own row** (track always full, fill = engaged / selected). Rejected: it hides
   size, so a theme with 3 companies looks like one with 300.
3. **Drop the "No theme yet" row from the grid.** Rejected: the payload keeps it (AC-28), and hiding 2,000
   selected companies would make "Engaged vs selected" read better than it is.

**Client report:** filter the count in `client_report.py` to the sample's issuer ids (chosen). Changing
`current_tiers` itself was rejected: three other callers use it as a lookup and would lose confirmed tiers for
engaged companies outside the sample.

**Demo seed:** filter in step 3 (`step_tiers`) only (*my call*). Filtering in `held_values` would also change
which 14 companies step 4 picks for meetings, and with it AC-48's fixture outcomes.

## Changes

### PR A: findings 1 to 4

1. **Client report** (`client_report.py`): `tiers` counts `current_tiers(...)` only for issuer ids in
   `sample["issuers"]`. A sample issuer with a confirmed tier still counts under its confirmed tier; one without
   counts under its proposal. Applies to the report JSON, the studio page table and the deck chart (all read
   `report["tiers"]`).
2. **Declined ballot** (`cockpit.py` `ballot_state_of_run`, `lib/cockpit.ts`):
   - `ballot_state` for a run ballot, the first that applies: `awaiting` when the ballot has no items or any item
     is `awaiting`; `cast` when every item is `cast`; `declined` when any item is `declined`; else `decided`.
   - `action_due` = `ballot_state` is `awaiting`, `not_started` or `declined`, and `days_to_meeting` ≤ 7.
   - Page text: `declined` reads `Declined` (neutral) when not action due. When action due it reads
     `Declined · decision due today`, `Declined · decision due in 1 day` or `Declined · decision due in <n> days`,
     in the signal style. (Owner decision 3; the plain awaiting text
     `Decision due in <n> days` was not chosen.)
   - Ledger meetings are unchanged (the ledger has no declined state).
3. **Demo seed** (`cockpit_demo.py` step 3 `tiers`): a held company whose summed `market_value_eur` across the
   holdings of `load_holdings_as_of(as_of, None)` is not above 0 gets no proposal and no confirmation. *My call:*
   "not above 0" rather than "equal to 0", so a net short position is skipped too. Steps 1, 2 and 4 do not change.
   `total` (the share base) is the sum over the companies kept.
4. **Theme grid** (`StewardCockpit.tsx` `ThemeGrid`, `index.css`):
   - `themeMax` = max(1, the largest `selected` among `themes` rows whose `theme` is not `Other`).
     `totalMax` = max(1, `summary.selected`).
   - Named-theme rows: every cell (tiers and Total) draws track `s / themeMax` and fill `e / themeMax`.
   - "All themes" row and the `Other` row: track `s / totalMax`, fill `e / totalMax`.
   - The `Other` row is labelled `No theme yet`, stays last, and has a 2 px top rule in the `--panel-border`
     token (the other rows keep 1 px).
   - Under the legend, one muted line (`--text-xs`, `--muted`): `Theme rows: a full bar is <themeMax>
     companies. All themes and No theme yet: a full bar is <summary.selected> companies.` The first sentence is
     left out when no named-theme row has `selected` above 0; the "No theme yet" part (`All themes and No theme
     yet` becomes `All themes`) when there is no `Other` row.
   - Counts use thousands separators, as elsewhere on the page.
   - Only the grid row label changes: `theme` values elsewhere on the page (engagement meetings, control gaps) keep
     reading "Other".
5. **Spec amendment** in the same PR: `stewardship-cockpit` gets the new ballot rule (its `ballot_state`,
   `action_due` and ballot-text lines), the theme-grid paragraph, and seed step 3, each marked
   "amended by `cockpit-review-fixes`, 15 Nov 2026".

Mockup (illustrative numbers, before → after):

```
BEFORE (one scale, max 2,300)            AFTER (named themes: max 120; totals: max 2,300)
Theme            Total                   Theme            Total
All themes       119 / 2,300 ██████████  All themes       119 / 2,300 ██████████
Climate           58 /   120 ▌           Climate           58 /   120 ████▌░░░░░
Corp. governance  31 /    64 ▏           Corp. governance  31 /    64 ██▌░░
Nature            12 /    25 ▏           Nature            12 /    25 █░
AI and digital     4 /     9 ▏           AI and digital     4 /     9 ▍
Norm violations    9 /    18 ▏           Norm violations    9 /    18 ▋░
Other             17 / 2,181 █████████▌  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                         No theme yet      17 / 2,181 █████████▌
                                         Theme rows: a full bar is 120 companies.
                                         All themes and No theme yet: a full bar is 2,300 companies.
```

### PR B: finding 5 (after #490 is on `main`)

1. `emissions_of`: returns `None` when the total, rounded as the API rounds tonnes (`round(x, 2)` on #490's head
   fe98697; if the merged code rounds differently, that same rounding), is 0.
2. `contributors`: the top 6 by the rounded `tco2e`, ties by `company` name, then `company_id`.
3. Spec amendment: `stewardship-cockpit`'s `emissions` rules ("`null` when … `total_tco2e` is 0", "ties by name")
   are amended the same way.

No page change: the page already hides the emissions figure and panel when `emissions` is null (AC-61).

## PR plan

| PR | Content | Risk | Holdout `Rows:` |
|---|---|---|---|
| A | Findings 1 to 4, spec amendment, tests | normal | `Rows: AC-1, AC-6` |
| B | Finding 5, spec amendment, tests | normal | AC-9, AC-10 (last slice, no `Rows:` line) |

PR B is `risk:normal`, not high (*my call*): it changes when the `emissions` section is hidden and the order of
contributors, not how financed emissions are computed. `financed_emissions_by_company`,
`compute_financed_emissions` and the bucket sums do not change, and `stewardship-cockpit` AC-53, AC-56 and AC-57
guard them. #490 was high because it added that maths. The owner can raise it to high when the PR opens.

Both PRs carry `Spec: cockpit-review-fixes`.

## What is left to the builder

- Helper names, and whether the scale maths lives in `lib/cockpit.ts` or the component.
- The exact element for the 2 px rule (a row class or a `tbody` split).

## Showcase setup (no code)

The seed never removes tier rows, so a showcase stack seeded before PR A keeps its zero-value Monitor tiers.
Before the showcase run, start from an empty tier log (`<ARP_STEWARDSHIP_STREAMS_DIR>/tier_assignments.jsonl`
moved aside), then run the four steps of `stewardship-cockpit` "Showcase setup".

## Rows of `stewardship-cockpit` this spec touches

- **Amended (wording only, evaluator):** AC-84: the `Other` entry's row is labelled `No theme yet`; its counts are
  checked as before. AC-66, AC-67: unchanged on the demo stack (it has no declined ballots); a declined ballot that
  is action due joins the due ballot texts allowed the signal colour.
- **Unchanged, must still pass.** Hidden tests: AC-28, AC-30, AC-47 to AC-50, AC-53, AC-54, AC-56 to AC-59,
  AC-82, AC-83. Unit rows: AC-36 to AC-39. Evaluator: AC-61.
- **Superseded:** none. No existing row's expected value changes.

## Acceptance

`holdout` rows run on the e2e stack (`backend/scripts/e2e_stack.sh up`; Postgres, `ARP_ENGAGEMENT_STORE=postgres`)
with the fixture rules and helpers of `stewardship-cockpit`'s Acceptance section (empty `stw_*`, `vote_*`, tier
log, no runs; portfolios through the portfolio store; climate values through `append_observation`). "Cockpit"
means `GET /api/stewardship/cockpit`. "Client report" means `GET /api/stewardship/streams/{stream_id}/report`
for a stream created with `POST /api/stewardship/streams` `{name: "Client S"}`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | house universe setting at its default (`portfolio`); stream S; the Client report read once and its `tiers` kept as T0; then `TierStore(settings.stewardship_streams_dir).confirm({issuer_id: "isin_ZZ0000000099", tier: "monitor", rule: "top_weight"}, "test")`, a key held by no portfolio | Client report | `tiers` equals T0 (same labels, same `companies` per tier) | holdout |
| AC-2 | the house universe holds issuer I with proposed tier `letter`; I confirmed as `bilateral` | Client report | I counts under Bilateral and not under Letter (must not change) | unit |
| AC-3 | a `proxy_voting` run ballot for H, meeting 2026-11-19, 4 items: 1 `declined`, 3 `cast` | Cockpit `?as_of=2026-11-17` | H's row: `ballot_state` `"declined"`, `action_due` `true` | unit |
| AC-4 | AC-3 with the meeting on 2026-11-26 | same | `ballot_state` `"declined"`, `days_to_meeting` 9, `action_due` `false` | unit |
| AC-5 | AC-3 with items 1 `awaiting`, 1 `declined`, 2 `cast` | same | `ballot_state` `"awaiting"`, `action_due` `true` | unit |
| AC-6 | AC-47's fixture of `stewardship-cockpit`, plus company `isin_XZ0000000001` (no `stw_companies` row) held in the same portfolio only through holdings with `market_value_eur` 0.0 | `arp stewardship seed-cockpit-demo --as-of 2026-11-27` | exits 0; the tier log has no row with `issuer_id` `isin_XZ0000000001`; every company held with a value above 0 in any portfolio on 2026-11-27 (the test's portfolio and the stack's demo portfolios) has a tier-log row | holdout |
| AC-7 | a cockpit with ballot texts for: `declined` not due; `declined` due in 0, 1 and 3 days | the shareholder-meetings rows render | texts are exactly `Declined`, `Declined · decision due today`, `Declined · decision due in 1 day`, `Declined · decision due in 3 days`; the three due ones carry the signal style, the first does not | unit |
| AC-8 | a cockpit with `summary.selected` 2,300, Climate `{selected: 120, engaged: 58}`, Nature `{selected: 25, engaged: 12}`, Other `{selected: 2181, engaged: 17}` | the theme grid renders | Total-column track widths: Climate 100 %, Nature 20.8 % (25/120), All themes 100 %, No theme yet 94.8 % (2181/2300), each ±0.1 %; the row label reads `No theme yet` | unit |
| AC-9 | (PR B) portfolio P: one holding of company A, 1 EUR, EVIC 100 EUR m, Scope 1 1, Scope 2 0, climate observations dated 2026-11-01 | Cockpit `?portfolio_id=P&as_of=2026-11-17` | `emissions` is `null` | holdout |
| AC-10 | (PR B) portfolio P: companies A "Alpha AG" and C "Beta SE" (names on the portfolio store's companies), each 1,000,000 EUR, EVIC 100 EUR m, Scope 2 0; A Scope 1 1000.1, C Scope 1 1000.4; observations dated 2026-11-01 | Cockpit `?portfolio_id=P&as_of=2026-11-17` | `contributors` `company_id` order is `[A, C]`, both `tco2e` 10.0 | holdout |
| AC-11 | (PR B) two contributors with equal rounded `tco2e` and equal `company` names, keys `k2` and `k1` | `emissions_of` | contributors order `[k1, k2]` | unit |
| AC-12 | the demo stack (`stewardship-cockpit` "Showcase setup") | open `#/stewardiq/cockpit`, the theme grid | the last row reads `No theme yet` below a heavier rule; the line under the legend reads `Theme rows: a full bar is <n> companies. All themes and No theme yet: a full bar is <N> companies.` with n = the largest named-theme `selected` and N = `summary.selected` from the API, both with thousands separators (e.g. `2,300`) | evaluator |
| AC-13 | the demo stack | the theme grid, named-theme rows | the named theme with the largest `selected` has a Total track as wide as the All themes Total track; every other named row's Total track is that width × its `selected` / n, ±2 px | evaluator |
| AC-14 | the demo stack | look for the signal colour on the page | same places as `stewardship-cockpit` AC-67; the theme grid has none (must not change) | evaluator |
| AC-15 | a cockpit with `summary.selected` 40, Climate `{selected: 10}`, the other named themes 0, and no `Other` row | the theme grid renders | the line under the legend reads exactly `Theme rows: a full bar is 10 companies. All themes: a full bar is 40 companies.` | unit |
| AC-16 | a cockpit with `summary.selected` 40, every named theme `selected` 0, Other `{selected: 40}` | same | the line reads exactly `All themes and No theme yet: a full bar is 40 companies.` | unit |

Must not change: the client report's per-tier attribution of house issuers (AC-2), the theme-grid payload
(`stewardship-cockpit` AC-28, AC-82, AC-83), ballots without a declined item (AC-36 to AC-39), seed steps 1, 2 and
4 (AC-47 to AC-50), the emissions maths (AC-53, AC-56, AC-57), and the signal colour's places (AC-14).

PR slices: PR A delivers AC-1 to AC-8 and AC-12 to AC-16; its `Rows:` line lists the holdout rows AC-1 and AC-6.
PR B delivers AC-9 to AC-11.
