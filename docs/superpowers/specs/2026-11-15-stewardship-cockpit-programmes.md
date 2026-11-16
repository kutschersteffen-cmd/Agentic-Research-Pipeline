# StewardIQ Cockpit, part 2: engaged vs selected by programme

Slug: stewardship-cockpit-programmes

Risk: normal (one API field, one page panel, one demo-seed step; no stored data changes shape). Size S to M, 1 PR.
Status: **approved by the owner on 15 Nov 2026** (buttons in the spec session, after the spec-critic read "Ready for approval").
Starts after: the build branches from `main` once these are merged, because all of them change `cockpit.py`,
`cockpit_demo.py`, `StewardCockpit.tsx` or the worklist read path:

- `cockpit-review-fixes` (spec PR #500 and its build),
- `vote-abstain-and-seed-fixes` (spec PR #499 and its build),
- cockpit PR 3 (#498),
- workbench PR 4 (#491, which also carries the faster house-universe read path).

## Intent

The owner asked at intake (13 Nov 2026) for a cockpit with, among other things, "a chart showing the number of
engagements vs the selected number of companies for engagement". The approved cockpit mockup
(<https://claude.ai/artifact/J3ryTPULk2Q3fR7D5ruCqE>, `project/Main.dc.html`) has a panel "Engaged vs selected,
by programme": one row per engagement programme, a bar of the selected companies with the engaged ones filled in,
and "<engaged> / <selected>". Part 1 (`stewardship-cockpit`, PRs #481 and #490) built the cockpit and counts
"selected" by coverage tier in a themes × tiers grid. This spec adds the programme view, the piece split off as
feature B (`stewardship-cockpit-programmes`, owner decision 5 of part 1).

Who it is for: the stewardship lead and the managers at the live showcase (about 27 Nov 2026). They want to see,
per named programme (Climate, Nature, AI, Corporate governance, and any the team names), how many of the
companies the team committed to are actually in an open engagement.

The cockpit only monitors (part 1, owner decision 6): programmes are made and changed in the Workbench
(`#/stewardship/workbench`); the cockpit reads them and links there.

## Owner decisions (15 Nov 2026, buttons in this spec session)

1. **Selected** = confirmed members of the programme. Proposed members are not in the bar; the row shows a small
   note "+<n> proposed" next to it. Ended members are left out.
2. **Engaged** = a confirmed member with at least one open engagement in the ledger, whatever its theme. Same rule
   as part 1's "engaged company", and it works for programmes the team names itself (they carry no theme).
3. **Placement:** a new panel directly after the themes × tiers grid. The grid and the six key figures stay as
   they are. (This supersedes part 1's note that feature B would replace the grid's theme rows.)
4. **Showcase data:** `seed-cockpit-demo` fills the four ready-made programmes (Climate, Nature, AI, Corporate
   governance) with confirmed members drawn from held companies, some engaged, two per programme left proposed,
   marked as demo data.
5. **Scope picker:** with one portfolio picked, each programme row counts only members that portfolio holds, like
   every other number on the cockpit. A programme with no member in that portfolio keeps its row and shows `–`.
6. **Meeting and gap lists keep the theme.** The mockup's programme name under each company in "Upcoming
   engagement meetings" and "Control gaps" is not built: a company can be in several programmes.

## Goals

- G1. `GET /api/stewardship/cockpit` returns `programmes` (one row per programme with members) and
  `programme_totals` (distinct companies), computed from the programme log and the ledger, in the request's scope.
- G2. A panel "Engaged vs selected, by programme" on `#/stewardiq/cockpit`, after the themes × tiers grid, with a
  link to the Workbench and an empty state.
- G3. `arp stewardship seed-cockpit-demo` gains a fifth step, `programmes`, that fills the four built-in
  programmes on the showcase stack.
- G4. Programme members marked as demo turn on the page's `Demo data` pill.

## Non-goals

- Creating, editing, confirming or ending programmes or members from the cockpit (the Workbench does that).
- Programme names in the engagement-meeting or control-gap lists (owner decision 6).
- Changing the six key figures, `summary`, `themes`, `tiers` or the themes × tiers grid.
- Programme objectives, targets or a per-programme engagement theme check (decision 2).
- Moving the programme log to Postgres, or changing `ProgrammeLog`'s events or its Workbench routes.
- Any scope other than all portfolios or one portfolio.

## Anti-goals (a failure even if it works)

- The signal colour anywhere in the new panel. Nothing in it asks a person to act (`DESIGN.md`, One Signal Rule).
- A programme figure on the page that differs from the API. The page computes no count; it only scales bars.
- A slower cockpit: the programme figures come from one read of the programme log per request plus data the
  cockpit request already loads (engaged companies, the scope's held companies), never one read per company or
  per programme.
- A row a viewer could take for real data when it is demo data: demo members turn on the `Demo data` pill.

## Constraints

- `DESIGN.md` ("Signal Room"): monochrome, tokens rather than hex, tabular numbers, hand-built SVG/CSS, no chart
  library. The bar follows the mockup: a selected track (outline) with the engaged fill, as in the themes ×
  tiers grid.
- "LLM plans, code computes": every number is computed in `cockpit.py`; no model call.
- The programme log is the file `<settings.stewardship_streams_dir>/programmes/events.jsonl`, read through
  `ProgrammeLog` (`backend/arp/stewardship/programmes.py`). Its member key `issuer_id` is the house-universe
  company key, the same key the cockpit uses (`isin_<ISIN>` for held companies; part 1, "Company key").
- The response model change goes through the API contract steps in `.claude/CLAUDE.md` (export OpenAPI,
  `gen:api`, commit both generated files).

## Approaches

1. **Read the log once inside the cockpit request (chosen).** The route builds `ProgrammeLog(settings.
   stewardship_streams_dir)` once and passes its folded programmes and members to `cockpit.build`, which already
   knows the scope's held companies and the engaged companies. One file read, one fold, set lookups per member.
2. **The page calls the Workbench's programme routes.** Rejected: one request per programme
   (`GET /programmes/{id}`), the scope filter would need holdings on the page, and the distinct total
   (`programme_totals`) cannot be summed from rows, which the "page computes nothing" anti-goal forbids.
3. **Copy programme members into Postgres for the cockpit.** Rejected: a second copy of the log that can drift,
   for a list of tens of companies.

## Definitions

Part 1's definitions hold (`docs/superpowers/specs/2026-11-13-stewardship-cockpit.md`, "Definitions"): company key,
open engagement (`status` `open` or `stalled`), engaged company, scope, `as_of`.

- **Programme** and its order: the entries of `ProgrammeLog.programmes()`, in that order (the four built-ins
  `climate`, `nature`, `ai`, `governance` first, then the others in the order they were created).
- **Member status**: as `ProgrammeLog` folds the log: `proposed`, `confirmed` or `ended`. The cockpit reads the
  status as it is when the request runs; `as_of` does not filter the log (the log has no dates per company
  beyond the event time, and the cockpit's `as_of` is a date in the ledger).
- **Programme selected** (decision 1): a confirmed member whose company key is in scope.
- **Programme engaged** (decision 2): a programme-selected company that is an engaged company (part 1).
- **Programme proposed**: a proposed member whose company key is in scope.
- **In scope**: all portfolios: every member. One portfolio: members whose company key is held in that portfolio
  (part 1's `held` set for the request).
- **Label**: the programme `name` with a trailing ` engagement programme` removed, compared case-insensitively
  (as the Workbench's programme chips do): "Climate engagement programme" → "Climate",
  "Biodiversity ENGAGEMENT PROGRAMME" → "Biodiversity", "Water stewardship" → "Water stewardship".
- **Demo member**: a confirmed member with `confirmed_by` `showcase demo`, or a proposed member with `proposed_by`
  `showcase demo`.

## API: `GET /api/stewardship/cockpit` (two new fields)

```
programmes: [{programme_id: str, name: str, label: str, selected: int, engaged: int, proposed: int}]
programme_totals: {selected: int, engaged: int}
```

- `programmes`: one row per programme that has at least one confirmed or proposed member in the whole log
  (whatever the scope), in programme order. A programme with no confirmed or proposed member is left out. So a
  portfolio scope keeps the same rows as "All portfolios", with counts that may be 0 (decision 5).
- `selected`, `engaged`, `proposed`: counts of companies, per the definitions above.
- `programme_totals.selected`: distinct companies that are programme-selected in any programme;
  `programme_totals.engaged`: those of them that are engaged. A company in two programmes counts once here.
- `demo` (part 1 field) is also `true` when any in-scope demo member exists. Nothing else about `demo` changes.
- Every other field of the response is unchanged. Programme membership changes no count in `summary`, `themes`,
  `tiers`, `emissions` or any list.
- A missing or empty programme log gives `programmes` `[]` and `programme_totals` `{selected: 0, engaged: 0}`.
- The request reads the log; it never writes it.

## The page: panel "Engaged vs selected, by programme"

Placed directly after the "Engaged vs selected, by theme and tier" grid and before "Financed emissions in
engagement". On wide screens it may share a row with the emissions panel as in the mockup; below 900 px the page
stays one column (part 1).

```
Engaged vs selected, by programme                                    34 / 61
Climate                ████████████░░░░░░░░░░░░░░░░░░░░░░    12 / 20  +2 proposed
Corporate governance   ██████░░░░░░░░░░░░░░░░                 6 / 14
Nature                 █████░░░░░░░░░░░░░░                    5 / 12  +2 proposed
AI                     ██░░░░░░░░░                            2 / 7
Water                  –                                              +1 proposed
■ Engaged  □ Selected
Selected: confirmed programme members. Engaged: with an open engagement.
Manage programmes in the Workbench →
```

- **Header:** title "Engaged vs selected, by programme"; on the right "<programme_totals.engaged> /
  <programme_totals.selected>" in the label style.
- **One row per `programmes` entry, in API order:** the `label`; a bar; "<engaged> / <selected>"; and, only when
  `proposed` is above 0, a muted note "+<proposed> proposed".
- **Bar:** the track (outline, the grid's "selected" style) is `selected / max` of the bar width and the fill
  (the grid's "engaged" style) is `engaged / max`, where `max` = the largest `selected` among the rows (at least
  1). A row with `selected` 0 shows `–` and no bar.
- **Legend:** "Engaged" (fill) and "Selected" (track), as in the mockup.
- **Footnote:** "Selected: confirmed programme members. Engaged: with an open engagement."
- **Link:** "Manage programmes in the Workbench →" to `#/stewardship/workbench`.
- **Empty state** (`programmes` is `[]`): one line "No programme has members yet." and the link
  "Open the Workbench →" to `#/stewardship/workbench`; no bars, no legend.
- **Numbers:** counts with thousands separators (part 1 rule).
- No signal colour (anti-goal). Both themes, tokens only, tabular numbers.

## Demo data: step 5 `programmes` of `arp stewardship seed-cockpit-demo`

Runs after part 1's four steps (and after any steps the merged fixes add), with the same `--as-of`. Let
`h(x)` be part 1's hash. For each built-in programme `p` in the order `climate`, `nature`, `ai`, `governance`, with
theme group `G` = Climate, Nature, AI and digital, Corporate governance respectively (part 1's theme groups):

1. If `ProgrammeLog.programme(p)["members"]` is not empty (any status, any author), skip the programme.
2. **Held companies**: company keys with a total held market value above 0 across all portfolios as of `as_of`
   (the same set `cockpit-review-fixes` gives step 3, `tiers`), in ascending order of `h(p + ":" + company_id)`.
   Let `H` be their number.
3. **Chosen**, in this order, up to `n = min(20, H)` companies: first, up to 8 held companies that have an open
   engagement in the ledger whose theme group (part 1's `fir_theme` mapping) is `G`, in hash order; then the
   remaining held companies in hash order until `n` are chosen.
4. With `ProgrammeLog.change`, propose the first `n − 2` chosen (all `n` when `n` < 3), then
   `ProgrammeLog.confirm(p, "showcase demo")`; then, when `n` ≥ 3, propose the last 2 chosen with a second
   `change`. Every call uses `by` `showcase demo` and the company name from the portfolio store (else the key). So
   a programme gets `n − 2` confirmed and 2 proposed members when `n` ≥ 3, else `n` confirmed and 0 proposed.
   `ProgrammeLog` itself does not change.

It prints `ok programmes: <c> confirmed, <q> proposed`, the totals over the four programmes this run wrote (both 0
when every programme was skipped). It never ends, removes or changes a member, never touches a created programme,
and writes nothing on a second run. A `FAIL programmes: <detail>` line and exit 1 if the log cannot be written.

Expected showcase shape (not an acceptance figure): four rows, 18 confirmed and 2 proposed each, with up to 8
engaged per row plus whichever hash-chosen members happen to be engaged.

## PR plan

| PR | Content | Risk | Holdout `Rows:` |
|---|---|---|---|
| 1 | `programmes` and `programme_totals` in `cockpit.build` and `CockpitResponse`; the route reads `ProgrammeLog` once; seed step 5; the panel; regenerated `openapi.json` / `schema.gen.ts`; screenshot and `/impeccable:impeccable audit` | normal | all `holdout` rows (single slice, no `Rows:` line) |

## Rows of `stewardship-cockpit` this spec extends

- **Superseded:** AC-47 (stdout "exactly four lines") by AC-12 here (five lines, the first four as before);
  AC-62 (section order) by AC-17 here. Their holdout and evaluator checks are updated in the same change.
- **Extended, still pass unchanged:** AC-1 (empty cockpit; AC-1 here adds the two new fields), AC-44 and AC-69
  (scope; AC-7 and AC-22 here), AC-46, AC-77, AC-79 and AC-80 (`demo`; AC-9, AC-10 and AC-27 here), AC-50 (second
  seed run writes nothing; AC-14 here adds the programme log), AC-67 and AC-68 (signal colour; AC-23 here), AC-84
  (the themes × tiers grid; AC-25 here).
- Part 1's note "Feature B swaps the theme rows for named programmes" is void (decision 3).

## What is left to the builder

- Function names, and whether the route passes the fold result or the `ProgrammeLog` to `cockpit.build`.
- Spacing, row height and label width within `DESIGN.md` and the mockup.
- Whether the panel shares a row with the emissions panel on wide screens.

## Acceptance

Holdout rows run on the e2e stack under the same start state as `stewardship-cockpit`'s Acceptance section, plus
an empty programme log (`<settings.stewardship_streams_dir>/programmes/events.jsonl` removed). Programme fixtures
are written with `ProgrammeLog(settings.stewardship_streams_dir)`: `create(name, by)`, `change(pid, names, add,
remove, end, reason, by)` and `confirm(pid, by)`, `by` `tester` unless the row says otherwise. "Confirmed in P"
means proposed in programme P, then `confirm(P)`. Companies B, C, D, E, F, G are `isin_XB0000000001` …
`isin_XG0000000001` with `stw_companies` rows ("Beta AG" … "Gamma SE") unless the row says otherwise. "Engaged"
means one open engagement taken in by intake (`fir_theme` as the row says, else `climate_mitigation`).
"Cockpit" means `GET /api/stewardship/cockpit?as_of=2026-11-17` unless the row adds parameters.

"The demo stack" is part 1's "Showcase setup" followed by `seed-cockpit-demo`. "The panel stack" is the demo stack
plus `create("Water engagement programme")` with 3 held companies confirmed in it, exactly 1 of them engaged, none
proposed, and none of them held in portfolio `DAX`; the evaluator creates it with the Workbench routes
(`POST /api/stewardship/programmes`, `…/{id}/members`, `…/{id}/confirm`) as an analyst.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | empty programme log, no engagements | Cockpit | `programmes` is `[]` and `programme_totals` is `{selected: 0, engaged: 0}` | holdout |
| AC-2 | in `climate`: B and C confirmed; D proposed only; E confirmed, then ended with reason "done". B engaged with `fir_theme` `natural_capital`. C has no `stw_companies` row and no engagement | Cockpit | `programmes` is exactly `[{programme_id: "climate", name: "Climate engagement programme", label: "Climate", selected: 2, engaged: 1, proposed: 1}]` | holdout |
| AC-3 | AC-2, with B's engagement `status` `stalled` | Cockpit | the `climate` row has `engaged` 1 | holdout |
| AC-4 | AC-2, with B's engagement `status` `resolved` | Cockpit | the `climate` row has `engaged` 0 | holdout |
| AC-5 | `create("Water engagement programme")` with F confirmed in it; G confirmed in `nature`; B confirmed in `climate`; nothing in `ai` or `governance` | Cockpit | `programmes` as `{programme_id, label}` is exactly `[{climate, "Climate"}, {nature, "Nature"}, {water_engagement_programme, "Water"}]` | holdout |
| AC-6 | B confirmed in `climate` and in `nature`, B engaged; C confirmed in `nature`, not engaged | Cockpit | `programme_totals` is `{selected: 2, engaged: 1}`; `climate` row `selected` 1, `engaged` 1; `nature` row `selected` 2, `engaged` 1 | holdout |
| AC-7 | portfolio P (saved by the test) holds B only; B and C confirmed in `climate`, both engaged; C confirmed in `nature`; D proposed in `climate` | Cockpit `&portfolio_id=P` | `programmes` as `{programme_id, selected, engaged, proposed}` is exactly `[{climate, 1, 1, 0}, {nature, 0, 0, 0}]`; `programme_totals` is `{selected: 1, engaged: 1}` | holdout |
| AC-8 | `create("Biodiversity ENGAGEMENT PROGRAMME")` and `create("Water stewardship")`, each with B confirmed | Cockpit | their `label`s are `"Biodiversity"` and `"Water stewardship"` | holdout |
| AC-9 | B confirmed in `climate` with `by` `showcase demo` for both the proposal and the confirmation; no other demo row | Cockpit | `demo` is `true` | holdout |
| AC-10 | AC-9 with `by` `tester` | Cockpit | `demo` is `false` | holdout |
| AC-11 | B engaged, no confirmed tier; B confirmed in `climate` | Cockpit | `summary` is `{selected: 0, engaged_selected: 0, engaged_outside_selection: 1}` and every `tiers` entry is `{selected: 0, engaged: 0}` (programmes change no part-1 count; must not change) | holdout |
| AC-12 | `stewardship-cockpit` AC-47's fixture, empty programme log; `H` = companies with a total held market value above 0 across all portfolios as of 2026-11-27 | `arp stewardship seed-cockpit-demo --as-of 2026-11-27` | exits 0; stdout's lines are those of `stewardship-cockpit` AC-47 (and of any step the merged fixes add), then a last line exactly `ok programmes: <4 × (min(20, H) − 2)> confirmed, 8 proposed` (supersedes `stewardship-cockpit` AC-47's "exactly four lines") | holdout |
| AC-13 | after AC-12 | Cockpit `?as_of=2026-11-27` | `programmes` as `programme_id` is exactly `["climate", "nature", "ai", "governance"]`; each row has `selected` `min(20, H) − 2` and `proposed` 2 | holdout |
| AC-14 | after AC-12 | run `seed-cockpit-demo --as-of 2026-11-27` again | its last line is exactly `ok programmes: 0 confirmed, 0 proposed`; the programme log's line count is unchanged | holdout |
| AC-15 | AC-12's fixture, with B confirmed in `climate` (`by` `tester`) before the seed | `seed-cockpit-demo --as-of 2026-11-27` | `GET /api/stewardship/programmes/climate` lists exactly one member, B, `confirmed`; `nature`, `ai`, `governance` each list `min(20, H)` members | holdout |
| AC-16 | AC-12's fixture plus, among the held companies, 3 with an open engagement whose `fir_theme` is `natural_capital` | `seed-cockpit-demo --as-of 2026-11-27` | all 3 are members of `nature` | unit |
| AC-17 | the demo stack (part 1 "Showcase setup", then `seed-cockpit-demo`) | open `#/stewardiq/cockpit` | sections in this order: key figures, 30-day strip, engaged vs selected by theme and tier, engaged vs selected by programme, financed emissions, upcoming engagement meetings, upcoming shareholder meetings, control gaps, escalation ladder, voting season to date (supersedes `stewardship-cockpit` AC-62) | evaluator |
| AC-18 | the panel stack | read the programme panel | one row per `programmes` entry in API order, each with the `label` and "<engaged> / <selected>" equal to the API; the four built-in rows show "+2 proposed" and the Water row shows no proposed note; the header reads "<programme_totals.engaged> / <programme_totals.selected>" | evaluator |
| AC-19 | the panel stack | measure the Water row's bar against a built-in row's full track | Water's track is `3 / max` and its fill `1 / max` of the full track width, each within 2 px, where `max` = the largest `selected` in the API's `programmes` | evaluator |
| AC-20 | the panel stack | the panel's link | "Manage programmes in the Workbench →" opens `#/stewardship/workbench` | evaluator |
| AC-21 | the stack after `arp showcase load` only, empty programme log | open `#/stewardiq/cockpit` | the panel shows the one line "No programme has members yet." and the link "Open the Workbench →" to `#/stewardship/workbench`, with no bars and no legend | evaluator |
| AC-22 | the panel stack | pick portfolio `DAX` in the scope selector | the programme rows, their numbers and the header equal `GET /api/stewardship/cockpit?portfolio_id=<its id>` for the same `as_of`; the Water row shows `–` and no bar | evaluator |
| AC-23 | the demo stack, Graphite and Night themes | look for the signal colour inside the programme panel | none; the signal colour appears only where `stewardship-cockpit` AC-67 lists (must not change) | evaluator |
| AC-24 | the panel stack | 390 px wide viewport | the programme panel is full width, in the page's single column | evaluator |
| AC-25 | the demo stack | the "Engaged vs selected, by theme and tier" grid | still shown, and `stewardship-cockpit` AC-84, as amended by `cockpit-review-fixes`, still holds (must not change) | evaluator |
| AC-26 | AC-2 | Cockpit, then read the programme log file | the file's bytes are the same as before the request (must not change: the cockpit never writes the log) | holdout |
| AC-27 | after AC-12 | Cockpit `?as_of=2026-11-27` | `demo` is `true` | holdout |
| AC-28 | the panel stack | 390 px wide viewport | every programme row's `label` is fully visible (it wraps, no ellipsis), and the page has no horizontal scroll | evaluator |
| AC-29 | 500 held companies, 300 of them engaged; a programme log of 5,000 member events across 10 programmes | Cockpit, median of 3 requests, against the same request with an empty programme log | the response time is at most 0.2 s above the empty-log time | unit |

Must not change: part 1's counts (AC-11), the themes × tiers grid (AC-25), where the signal colour may appear
(AC-23), and the programme log on a cockpit read (AC-26). Supersedes: `stewardship-cockpit` AC-47 (by AC-12) and
AC-62 (by AC-17).
