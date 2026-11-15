# Voting statistics: abstain and withhold are not "against management", a re-cast ballot counts once; two demo-seed fixes

Slug: vote-abstain-and-seed-fixes

Risk: `risk:high` for the implementing PR: `load-npx` rewrites a stored column on rows already in the database,
and `seed-demo` changes how it deletes and re-creates demo rows (steward table: data migrations, deleting stored
data). Size M, 1 PR. The cockpit page changes, so the UI review applies (Playwright screenshot,
`/impeccable:impeccable audit`).
Status: draft, for the owner's approval.
Starts after: cockpit PR 2 (#490, financed emissions, `risk:high`) is merged. It touches `cockpit.py` and
`StewardCockpit.tsx` too. The build branches from `main` after that merge.

## Intent

The owner, 15 Nov 2026, from the open review findings: the voting statistics must stop counting abstain and
withhold votes as "against management", a ballot cast twice must count once, and two demo-seed bugs are fixed. The
cockpit is shown live to senior management on about 27 Nov 2026, so its voting numbers must be right and easy to
explain.

## Owner decisions

Taken by button in the dispatcher session, 15 Nov 2026:

1. **Abstain and withhold: "Own category on the cockpit".** An abstain counts neither for nor against management
   (stored `against_management` null). A withhold counts as against management only when management recommended
   `for`; otherwise null. Abstain and withhold also get their own visible share in the cockpit's voting statistics.
2. **Headline:** "x% against management" is measured against all votes cast. Abstentions stay in the total.
3. **A ballot cast twice:** the later cast replaces the earlier. Each ballot item counts once, with its latest
   decision.
4. **Existing databases:** when `load-npx` runs again it refreshes the stored flag of the `npx_urth_demo` rows it
   already loaded. The showcase database is rebuilt before about 27 Nov anyway. Recommended and not objected to; the
   owner confirms it with the approval of this spec.

Taken by button in this spec session, 15 Nov 2026:

5. **How the new category shows on the cockpit:** <owner answer, see "Cockpit page">.
6. **Process view:** <owner answer, see "Process view">.

## What is wrong today (main `b53ad65`)

- **N-PX load.** `backend/arp/stewardship/npx_load.py:119` stores `_AGAINST.get(<CSV for_against_management>)`
  (map at `:31`). The fetch script computes that CSV column as "FOR if `how_voted` equals the recommendation, else
  AGAINST" (`data/voting/npx_urth/fetch_npx.py:55-61`). So every ABSTAIN, and every WITHHOLD where management
  recommended AGAINST, is stored as against management. Across the three committed CSVs that is 339 decisions (283
  abstain, 56 withhold); 2,233 stored `true` become 1,894. Abstain or withhold where management recommended NONE
  already has an empty column and stays null. The intake rule (`against_management()` in
  `backend/arp/schemas/vote_ledger.py:20`, used by `intake.py:361`) is already right.
- **Cockpit buckets.** `_vote_bucket` (`backend/arp/stewardship/cockpit.py:80-83`) puts `withhold` into
  `against`, and abstain into `abstain`. With the load bug, an abstain shows in the bar as "abstain" and also in
  "against management".
- **Re-cast ballots.** `count` in `cockpit.py:266-280` adds every run item with status `cast` from every
  `proxy_voting` run, and every `vote_decisions` row. When a ballot is re-run and cast again, its items count once
  per run. (The calendar of upcoming meetings already keeps only the latest run per ballot, `cockpit.py:208-216`.)
- **Seed purge.** `seed_demo` (`backend/arp/stewardship/seed_demo.py:225-227`) commits `_purge` in its own
  transaction, then calls `intake_engagements`, which opens another. If intake fails, the old demo rows are gone
  and no new ones exist.
- **Seed refusal.** `_purge` (`seed_demo.py:185-208`) refuses to replace the seed when rows of other sources hang
  on demo engagements, but checks only `stw_objectives`, `stw_activities`, `stw_commitments`, `stw_transitions`.
  A `stw_watch_topics` or `stw_evidence_suggestions` row on a demo engagement makes the delete fail with a raw
  `ForeignKeyViolation` instead of the refusal message.

## Goals

1. `load-npx` stores `against_management` with the intake rule, not the CSV column.
2. Running `load-npx` again corrects the flag on `npx_urth_demo` decisions already stored.
3. The cockpit counts abstain and withhold in one bucket of their own and shows its share.
4. Each ballot item cast in a Proxy Voting run counts once in "Voting, season to date", with its latest decision.
5. `seed-demo` with another seed either replaces the demo rows completely or leaves them as they were.
6. `seed-demo` with another seed prints the refusal, not a database error, when watch topics or evidence
   suggestions of other sources hang on demo engagements.

## Non-goals

- A guard that stops `seed-demo` or `load-npx` on a database that is not a demo one (its own card, owner decision
  needed).
- Demo votes raising unlabelled monitoring triggers on real issuers (its own card).
- De-duplicating re-cast ballots in the process view or in the monitoring fields (`voting_feed.issuer_fields`).
  Only the cockpit's "Voting, season to date" changes.
- Changing the fetch script or the committed CSVs. The CSV column `for_against_management` stays as it is; the
  loader stops reading it.
- The sibling item `cockpit-review-fixes`: client-report tier count, declined-ballot state, demo seed market-value
  rule, theme grid. It owns those parts of the same files.
- New `load-npx` output. Its stdout stays `meetings N, items N, decisions N created`.

## Anti-goals

- An abstain shown as against management anywhere on the cockpit.
- A split vote filed as two decisions (N-PX, imports without a `run_id`) collapsed into one. Those are two votes,
  not a re-cast; cockpit AC-43 keeps them.
- Old demo rows lost when a re-seed fails.
- A second accent colour: the new share uses the existing grey `abstain` swatch, and the signal colour stays
  reserved for "a person must act" (`DESIGN.md`).

## Approaches considered

1. **Loader calls the existing intake rule; cockpit regroups buckets and de-duplicates per ballot item (chosen).**
   One rule for every source, no new tables, the API keeps its shape (one new field per topic).
2. Fix the CSV column in `fetch_npx.py` and re-fetch. Rejected: it needs SEC access, changes committed data, and
   the loader would still trust a derived column.
3. Compute "against management" in the cockpit from vote and recommendation, ignoring the stored flag. Rejected:
   the process view and the monitoring triggers read the stored flag too, and would still be wrong.

## Design

### 1. N-PX load (`npx_load.py`)

- Each decision's `against_management` = `against_management(VoteValue(<vote>), <item's management_recommendation>)`
  from `arp.schemas.vote_ledger`, with the recommendation as the loader already stores it (`for`, `against`, or
  null for NONE/empty). `_AGAINST` and the read of `for_against_management` go.
- Resulting values: `abstain` → null always; `withhold` → true when management recommended `for`, false when it
  recommended `withhold`, otherwise null; `against` → true when `for`, false when `against`; `for` → true when
  `against`, false when `for`; frequency votes, `do_not_vote`, `other` → null; no recommendation → null.
- **Refresh:** in the same transaction, every stored decision with `source = 'npx_urth_demo'` whose `external_id`
  is in the CSVs gets the computed value when its stored value differs. No other column and no other source is
  touched. Counts of created rows (and so stdout) are as before.
- `data/voting/npx_urth/README.md`: in "Caveats", add that the loader ignores `for_against_management` and applies
  the vote-intake rule (abstain never against management; withhold only when management recommended FOR). The
  share line under "Votes against management" stays as it is (it describes the CSV column).

### 2. Cockpit voting (`cockpit.py`, `schemas/cockpit.py`)

- **Buckets:** `for`, `against`, `abstain`, `other`. `abstain` now counts `abstain` **and** `withhold`; `against`
  counts `against` only. The field names stay; the page labels the `abstain` bucket "abstained or withheld".
- **Against management** reads the stored flag (ledger) or the run feed's flag as today. With the loader fixed, an
  abstain is never true; a withhold is true only against a `for` recommendation. A withhold against `for` is
  therefore in the `abstain` bucket and in `against_management`; the footnote on the page says so.
- **Topics:** each `{topic, votes, against_management}` gains `abstain` (abstain or withhold votes in that topic).
- **One count per ballot item** (owner decision 3):
  - Run items: per (`company_id`, meeting date, item number), only the newest `proxy_voting` run in which that
    item has status `cast` counts. `voting_feed.items()` lists runs newest first, as the calendar code already
    relies on. An item cast in an older run and not yet cast in a newer one still counts, from the older run.
  - Ledger decisions with a `run_id`: per `vote_items` row, only the decision with the latest `decided_at` counts
    (a null `decided_at` is older than any date; a remaining tie keeps the greatest `decision_id`).
  - Ledger decisions without a `run_id` (N-PX, imported files) are filed votes: each row counts, as today (split
    votes, cockpit AC-43).
  - The existing rule stays: a run item is not counted when the ledger holds decisions with its `run_id`.
  - Known limit, accepted: a ballot cast in run A whose decisions were imported into the ledger, then re-cast in a
    newer run B that was not imported, counts both casts. That needs a manual import of run results; no showcase
    path does it.
- `meetings` = distinct (company or issuer, meeting date) among the counted votes, as today.

Expected effect on the showcase (all three CSVs loaded, every company in scope, 2026 meeting dates): against
management goes from 3.3% to 2.7% of 18,345 votes (shown as 3% either way); abstained or withheld is 99 votes,
shown as 1%.

### 3. Cockpit page (`frontend/src/pages/StewardCockpit.tsx`, voting card only)

<filled from owner decision 5; recommended layout A below>

**Layout A (recommended): the split lives in the voting card.**

- Season bar: segments for / against / abstained or withheld (plus other, only when above 0), in that order, using
  the existing `for`, `against`, `abstain`, `other` swatch classes. Legend per segment: `<count> <label> (<p>%)`,
  for example `17,156 for (94%)`, `99 abstained or withheld (1%)`. The bar's `aria-label` is exactly
  `<p>% for, <p>% against, <p>% abstained or withheld`, followed by `, <p>% other` only when other is above 0.
- Under it, the heading stays "Against management, by topic". Each topic row keeps its bar (against-management
  share) and reads `<p>% · <a> of <n> · <q>% abstained or withheld`. A topic with 0 votes reads
  `– · 0 of 0 · – abstained or withheld`.
- Footnote under the card, exactly: "Abstentions never count as against management. A withhold counts as against
  management only when management recommended for."
- The key figure "Votes cast, <season>" keeps its note `<m> meetings · <p>% against management`.

**Layout B: as A, and the key figure note also gets the share:**
`<m> meetings · <p>% against management · <q>% abstained or withheld`.

Percentages are whole numbers, rounded half up (`pct()` in `frontend/src/lib/cockpit.ts`), of `voting.votes` for
the bar and of the topic's `votes` for a topic row. No new colour token; no signal colour in the voting card.

### 4. Process view

<filled from owner decision 6; recommended: no change>

- **Recommended: no change.** The stage 4 metric "Against management" keeps its single count. It reads the stored
  flag, so the loader fix corrects it with no code change.
- Alternative: a metric "Abstained or withheld" (count of decided ballot items whose vote is `abstain` or
  `withhold`, source `live`) right after "Against management" in stage 4 (`process.py:357`).

### 5. Seed demo (`seed_demo.py`)

- **One transaction:** the purge and the intake of the new seed run in one database transaction. If intake raises
  or rejects any row, the transaction rolls back and every `stw_*` row of the earlier seed is still there. How to
  share the transaction (for example an optional session argument on `intake_engagements`) is the builder's call.
- **Refusal covers the watch tables:** the check for rows of other sources on demo engagements also counts
  `stw_watch_topics` (by `engagement_id`) and `stw_evidence_suggestions` (by `engagement_id`, or `activity_id` of a
  demo activity). The message format is unchanged: `cannot replace the demo seed: <n> rows from other sources are
  attached to demo engagements (<table>: <n>, …); re-run with --seed <current> or remove them first`, exit 1.
- Extend `test_other_seed_refuses_when_other_source_rows_hang_on_demo_engagements` with a watch topic and an
  evidence suggestion; never weaken it.

## Other specs this changes

The implementing PR edits these, so a test-writer updates the hidden tests in the same change:

- `2026-11-13-stewardship-cockpit.md`
  - **AC-42 superseded** by this spec's AC-10: a `withhold` now counts in `abstain`, so `against` 1 / `abstain` 0
    become `against` 0 / `abstain` 1. Strike it through as "Superseded by AC-n (`vote-abstain-and-seed-fixes`
    AC-10)" and add the new row at the end of its table.
  - Design text "voting": "`withhold` counts as `against`" becomes "`withhold` counts as `abstain`"; "Votes
    counted" gains the one-count-per-ballot-item rule of section 2; topics gain `abstain`. Page text "Voting,
    season to date" follows section 3.
  - AC-40, AC-41 (as a projection on `{topic, votes, against_management}`) and AC-43 keep their expected values.
- `2026-11-12-stewardship-data-foundation-design.md`
  - Line "`against_management` comes from the CSV's `for_against_management`" becomes "`against_management` follows
    the vote-intake rule (see Intake → Rules); the CSV column is not read".
  - **AC-33 amended (Given only):** the fixture's two `AGAINST` records have management recommendation `FOR`, and
    no other record is `FOR` with management `AGAINST`, or `AGAINST` / `WITHHOLD` with management `FOR`. A hidden
    fixture that does otherwise must be changed to match. AC-33's own expected counts are unchanged.
  - **AC-34** and **AC-38** use that fixture; their expected values (exactly 2 true; one `vote_against_management`
    trigger) are unchanged once AC-33's Given is amended.
  - AC-35, AC-36 and AC-37 keep their expected values.

## Left to the builder

- How purge and intake share one transaction.
- Whether the refresh runs as one `UPDATE … FROM (VALUES …)` or in batches.
- Test names and fixtures for the `unit` rows.

## Acceptance

All cockpit rows: `GET /api/stewardship/cockpit?as_of=2026-11-17`, no `portfolio_id`; company G has an
`stw_companies` row named "Gamma SE"; company H likewise "Hotel AG". "Fixture CSV" means a CSV in the committed
N-PX format (`data/voting/npx_urth/README.md`) with one meeting dated 03/10/2026 and one record per item.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture CSV with 3 items: `ABSTAIN` with management `AGAINST` and `for_against_management` `AGAINST`; `ABSTAIN` / `FOR` / `AGAINST`; `ABSTAIN` / `NONE` / empty | `arp stewardship load-npx <dir>` | all 3 `vote_decisions` rows have `against_management` null | holdout |
| AC-2 | Fixture CSV with 2 items: `WITHHOLD` / management `AGAINST` / `AGAINST`; `WITHHOLD` / `FOR` / `AGAINST` | `load-npx <dir>` | the first decision's `against_management` is null, the second's is true | holdout |
| AC-3 | Fixture CSV with 3 items: `AGAINST` / `FOR` / `AGAINST`; `FOR` / `AGAINST` / `AGAINST`; `FOR` / `FOR` / `FOR` | `load-npx <dir>` | `against_management` is true, true, false (must not change) | holdout |
| AC-4 | AC-1 and AC-2 fixtures in one directory, loaded once; then the test sets `against_management` = true on all 5 decisions by SQL | `load-npx <dir>` again | the 5 decisions read null, null, null, null, true (AC-1 order, then AC-2 order) | holdout |
| AC-5 | as AC-4 | `load-npx <dir>` again | exit 0; stdout is exactly `meetings 0, items 0, decisions 0 created` (must not change) | holdout |
| AC-29 | as AC-4 | `load-npx <dir>` again | `vote_decisions` still has exactly 5 rows with `source` `npx_urth_demo` (must not change) | holdout |
| AC-6 | as AC-4, plus one `vote_decisions` row with `source` `api`, `vote` `abstain`, `against_management` set to true by SQL | `load-npx <dir>` again | the `api` row's `against_management` is still true | holdout |
| AC-7 | the committed CSVs in `data/voting/npx_urth/` | `load-npx data/voting/npx_urth/` | `select count(*) from vote_decisions where source = 'npx_urth_demo' and against_management` = 1,894 | holdout |
| AC-8 | as AC-7 | — | `select count(*) from vote_decisions where source = 'npx_urth_demo' and vote = 'abstain' and against_management is not null` = 0 | holdout |
| AC-9 | G, ledger meeting 2026-03-10, five decisions with no `run_id`: `abstain` (`against_management` null), categories `{DIRECTOR ELECTIONS}`; `withhold` (true), `{DIRECTOR ELECTIONS}`; `withhold` (null), `{DIRECTOR ELECTIONS}`; `against` (true), `{SECTION 14A SAY-ON-PAY VOTES}`; `for` (false), `{AUDIT-RELATED}` | Cockpit | `voting` has `meetings` 1, `votes` 5, `for` 1, `against` 1, `abstain` 3, `other` 0, `against_management` 2 | holdout |
| AC-10 | G, ledger meeting 2026-03-10 with three decisions `withhold`, `one_year`, `do_not_vote` (replaces cockpit AC-42) | Cockpit | `voting` has `votes` 3, `for` 0, `against` 0, `abstain` 1, `other` 2 | holdout |
| AC-11 | AC-9 | Cockpit | `voting.topics` as `{topic, votes, against_management, abstain}` is exactly `[{Shareholder proposals,0,0,0},{Remuneration,1,1,0},{Director elections,3,1,3},{Auditors,1,0,0},{Capital and other,0,0,0}]` | holdout |
| AC-12 | G, ledger meeting 2026-03-10, one item with two decisions: `run_id` `R1`, `decided_at` 2026-03-01, `for` (false); `run_id` `R2`, `decided_at` 2026-03-05, `against` (true) | Cockpit | `voting` has `votes` 1, `for` 0, `against` 1, `against_management` 1 | holdout |
| AC-13 | as AC-12, but `R1`'s decision has `decided_at` 2026-03-09 | Cockpit | `voting` has `votes` 1, `for` 1, `against` 0, `against_management` 0 | holdout |
| AC-14 | one item with two decisions with `run_id` `R1` and `R2`, both `decided_at` null | Cockpit | `voting.votes` is 1 | unit |
| AC-15 | two `proxy_voting` runs for H, meeting 2026-03-12, items 1 and 2, management `for` on both, all cast; older run votes `for`, `for`; newer run `against`, `for`; no ledger rows | Cockpit | `voting` has `meetings` 1, `votes` 2, `for` 1, `against` 1, `against_management` 1 | unit |
| AC-16 | as AC-15, but in the newer run item 2 is decided `against` and not cast | Cockpit | `voting` has `votes` 2, `for` 1, `against` 1, `against_management` 1 (item 1 `against` from the newer run, item 2 `for` from the older) | unit |
| AC-17 | the demo stack of cockpit "Showcase setup" | open `#/stewardiq/cockpit`, voting card | the legend reads, in order, `<n> for (<p>%)`, `<n> against (<p>%)`, `<n> abstained or withheld (<p>%)`, and `<n> other (<p>%)` only when other is above 0; the bar has one segment per legend entry with a count above 0, in the same order | evaluator |
| AC-18 | the demo stack | voting card, topic rows | each of the 5 topic rows reads `<p>% · <a> of <n> · <q>% abstained or withheld`, `<q>` = the topic's `abstain` / `votes` in whole percent | evaluator |
| AC-19 | the demo stack | voting card | the footnote reads exactly "Abstentions never count as against management. A withhold counts as against management only when management recommended for." | evaluator |
| AC-20 | the demo stack | key figures row | "Votes cast, 2026" note reads `<m> meetings · <p>% against management` (layout A; layout B: `<m> meetings · <p>% against management · <q>% abstained or withheld`) | evaluator |
| AC-21 | `voting.topics` has a topic with `votes` 0 | the voting card renders | that row reads `– · 0 of 0 · – abstained or withheld` | unit |
| AC-22 | the demo stack, theme switch on Light, then on Dark | voting card | the abstained-or-withheld bar segment and its legend swatch have the computed background of `var(--neutral)` | evaluator |
| AC-30 | as AC-22 | voting card | no element in the card has a text, background or border colour equal to `--hi`, `--hi-ink`, `--await` or `--await-edge` | evaluator |
| AC-23 | a ballot with two decided items: `abstain` (management `for`), `against` (management `for`); process option "no change" | `GET /api/stewardship/streams/{stream_id}/flow`, the stage with `id` `voting` | its `metrics` labels are exactly "Resolutions", "Expected against", "Case-by-case", "Sanction votes", "Ballot items decided", "Against management", and "Against management" has `value` 1 | unit |
| AC-31 | as AC-23, process option "add a second number" | same | labels end with "Against management", "Abstained or withheld", with `value` 1 and 1 | unit |
| AC-24 | `arp showcase load`, then `arp stewardship seed-demo --seed 7`; one `stw_watch_topics` row with `source` `app` on a `mock_voice_seed` engagement | `arp stewardship seed-demo --seed 8` | exit 1; stderr contains `stw_watch_topics: 1` | holdout |
| AC-32 | as AC-24 | same | row counts of every `stw_*` table are unchanged (on `main` the database error also rolls back, so this half passes before and after; it guards the new code) | holdout |
| AC-25 | as AC-24, but one `stw_evidence_suggestions` row with `source` `app` on a `mock_voice_seed` engagement instead of the watch topic | `seed-demo --seed 8` | exit 1; stderr contains `stw_evidence_suggestions: 1` | holdout |
| AC-33 | as AC-25, but the suggestion's `engagement_id` is an engagement with `source` `app` on the same company, and its `activity_id` is a `mock_voice_seed` activity | same | exit 1; stderr contains `stw_evidence_suggestions: 1` | holdout |
| AC-26 | `seed-demo --seed 7` done; nothing of another source attached | `seed-demo --seed 8` | exit 0; every `mock_voice_seed` row of `stw_engagements` has an `external_id` starting with `s8:` (must not change) | holdout |
| AC-27 | `seed-demo --seed 7` done; the engagement intake is made to raise during `seed_demo(seed=8)` | `seed_demo(dsn, seed=8)` | the error propagates; the set of `(table, external_id)` of `mock_voice_seed` rows across all `stw_*` tables equals the set before | unit |
| AC-28 | as AC-27, but the intake returns a report with one rejected row | `seed_demo(dsn, seed=8)` | the set of `(table, external_id)` of `mock_voice_seed` rows equals the set before | unit |
| AC-34 | as AC-28 | same | raises `RuntimeError` whose message starts `seed rows rejected:` (must not change) | unit |

Must not change: cockpit AC-40, AC-41 and AC-43 (split votes without a `run_id` count once per row) keep their
expected values and stay in the regression suite; data-foundation AC-35 and AC-36 (row counts after `load-npx`)
too; and AC-3, AC-5, AC-6, AC-26, AC-29, AC-34 above.

The owner's answer to decision 6 keeps one of AC-23 and AC-31; the other is retired with ~~strikethrough~~ before
approval is recorded. Decision 5 picks the layout A or B wording of AC-20.

AC-21 needs a topic with 0 votes, which the showcase data does not have (all five topics have votes in 2026), so it
is a `unit` row on the rendering; AC-18 is checked on the showcase.
