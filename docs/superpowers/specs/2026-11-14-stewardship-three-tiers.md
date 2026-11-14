# Stewardship coverage tiers: bilateral, letter, monitor, with nothing collaborative, and bilateral picked by hand or by rule

Slug: stewardship-three-tiers

Risk: `risk:high` for every PR, because each one changes how stored tier rows, engagement records or policy
versions are read. Size M, 3 PRs (A, B, C).

Status: **draft for owner approval**, 14 Nov 2026.

## Owner decisions

These are the owner's words from 14 Nov 2026, said in the Cockpit spec session and quoted in owner decision 6 of
`2026-11-13-stewardship-cockpit.md`:

- "Only change: tier: bilateral, letter, monitor"
- "Delete collaborative everywhere. We don't do that."
- "We need to be able to manually or per rule setting select companies for bilateral, … which is then part of the
  final approval."
- "What I said matters only for the prioritisation. Not the cockpit. Cockpit is only monitoring."

The owner answered these with buttons in the intake session, 14 Nov 2026:

1. "Delete collaborative everywhere" also removes the escalation step `joint_engagement` ("Tier + ladder step").
2. Old tiers map as follows: Priority Bilateral becomes bilateral, Scaled Baseline becomes letter, and Systemic /
   Market-Level becomes monitor. An issuer whose confirmed tier was Thematic & Collaborative is proposed again by the
   rules and needs a new confirmation.
3. The final approval is the existing tier confirm. There is no new approval flow and no four-eyes step.

The owner answered these with buttons in this spec session, 14 Nov 2026:

4. "Selected for bilateral" means the coverage tier `bilateral`. The rules propose it, and a person can propose it by
   hand. The existing tier confirm makes it count. The workbench's quarterly engagement selection remains a separate
   list and does not change.
5. The three rules that proposed Thematic & Collaborative now propose `letter`: high-emitting sector, high-impact
   nature sector, and "an engagement is open".
6. The engager roles `lead`, `active_support` and `passive_support` are removed. Only `bilateral` stays (or no role).

## Why

The house does not run collaborative engagements. The current tier model contains a whole tier for that work
(Thematic & Collaborative). The ladder has a step for it (joint engagement), and the engagement ledger has three
roles for it. Each of these creates work and labels that do not describe what the house does.

What remains are three forms of coverage:

- **Bilateral**: the house's own dialogue with the company.
- **Letter**: the standard expectations letter plus the voting policy.
- **Monitor**: voting and monitoring only, with no company-specific escalation.

Deciding who gets bilateral is the part of prioritisation the owner wants to control. The rules propose it, an
analyst can pick a company by hand, and a person confirms both kinds of proposal in the same step.

## Goals

1. **Three tiers.** `tiers.TIERS` is `["bilateral", "letter", "monitor"]` and `TIER_LABELS` is `Bilateral`,
   `Letter`, `Monitor`. Every screen, report, score and rule that lists tiers follows those two constants (PR A).
2. **Rules.** The bundled `house_coverage_policy` and `house_escalation_policy` use the new keys (PR A). The
   ladder caps move to the six-step ladder (PR B).
3. **Old data still reads correctly.**
   - Rows in `tier_assignments.jsonl` and saved coverage-rule versions are mapped to the new keys when read, and
     are never rewritten (PR A).
   - Stored `joint_engagement` stages are read as `private_engagement` (PR B).
   - Stored collaborative engager roles are read as no role (PR B).
   - Saved escalation-rule versions written for the seven-step ladder are retired (PR B).
4. **No joint engagement.** The ladder has six steps:
   private engagement → written escalation to the board → escalation to the chair → vote against management →
   file or co-file a resolution → public statement (PR B).
5. **No collaborative anywhere.** No tier, ladder step, engager role, engagement mode or initiative type is called
   collaborative, in code or in `docs/STEWARDSHIP_OPERATING_MODEL.md` (PRs A and B).
6. **Bilateral picks.** An analyst picks a company for bilateral with a reason. While the pick stands, it is that
   company's tier proposal. The existing tier confirm makes it count, and a person can withdraw it (PR C).

## Non-goals

- Cockpit features. The cockpit reads `TIERS` and `TIER_LABELS`, so its grid changes with them. Its escalation
  ladder follows the six steps (see "Other specs this changes").
- A new approval flow, a new four-eyes step, or a second confirm for picks. A pick is confirmed exactly like a rule
  proposal.
- Picking a company by hand for `letter` or `monitor`. Only bilateral is picked by hand. To move a company out of
  bilateral when a rule put it there, a person edits the coverage rules.
- Picks that expire. A pick stands until a person withdraws it.
- Any change to the workbench's quarterly engagement selection.
- Migration scripts or database schema changes. Old values are mapped when read and never rewritten. The single
  exception is the bundled sample file, which is edited directly.
- A settings form for the bilateral rules. "By rule" means the coverage rules, which the owner already edits in the
  rule editor (Selection studio → Design), with versions activated under the existing four-eyes rule.

## Anti-goals

- **A tier counts without a person.** A pick changes only the proposal. Only `POST /tiers/confirm` writes
  `tier_assignments.jsonl` (AC-51, AC-62).
- **A stored record fails to load** after an enum value it used was removed (AC-22, AC-30).
- **A step changes without a decision.** A `joint_engagement` record is read one step down, never one step up
  (AC-22).
- **An old tier name shows up** in a label, a chart, a sort order or a response (AC-17, AC-33).

## Constraints

- Tiers are still read through `TierStore`, `current_tiers` and `tier_review`, which stay the only path. The
  workbench (`worklist.py`), cockpit, client report, process stages and policy calibration all read from them.
- Engagements are read through the engagement store interface (file or Postgres). The mapping on read is a
  before-validator on the Pydantic models in `arp/schemas/engagement.py`, so both stores get it.
- Request and response models change in PRs B and C. Each of those PRs runs `scripts/export_openapi.py` and
  `npm run gen:api` and commits both generated files. Each new `request<T>()` gets a line in
  `frontend/src/api/contract.ts`.
- Roles:
  - Reading `GET /tiers` needs `viewer`.
  - Picking and withdrawing need `analyst` or above.
  - Confirming keeps its existing rule.
- Frontend changes in PRs A, B and C each carry a Playwright screenshot of the changed page and an impeccable audit.

## Approaches considered

1. **Tier confirm (picked by the owner, decision 4).** Bilateral is a coverage tier, and a hand pick is a
   different kind of proposal. The final approval is the existing tier confirm at Human Checkpoint (stage 5).
   - Pro: no new approval and no new concept. Escalation caps follow the confirmed tier as they do today.
   - Pro: the workbench selection keeps its meaning (who is engaged this quarter).
   - Con: two confirm steps still exist side by side (tiers and the quarterly selection).
2. **The workbench's quarterly selection sets bilateral.** Confirming a company in the house selection for a
   quarter would make it bilateral.
   - Con: tiers would become per-quarter and per-scope.
   - Con: it reverses the workbench's "no pre-ticked rows" rule, because rules would pre-propose rows.
   - Con: workbench PRs 2 and 4 would be reworked.
3. **Mapping old data on read (picked, my call), versus rewriting stored data once.**
   - Pro of mapping on read: no migration script, nothing destroyed, and old files stay as written. Append-only
     logs stay append-only.
   - Con: a few lines of mapping code stay in the codebase, and grep tests have to exclude them.

## Design

### PR A: three tiers

**Keys and labels.** `TIERS = ["bilateral", "letter", "monitor"]`. `TIER_LABELS = {"bilateral": "Bilateral",
"letter": "Letter", "monitor": "Monitor"}`. Tier order everywhere is bilateral → letter → monitor.

**Mapping old keys on read** (in `tiers.py`; this is the only place the old keys appear):

| Old key | Read as |
|---|---|
| `priority_bilateral` | `bilateral` |
| `scaled_baseline` | `letter` |
| `systemic` | `monitor` |
| `thematic_collaborative` | in `tier_assignments.jsonl`: retired (see below); in a coverage-rule output: `letter` |

- **`TierStore.all()` and `latest()`**
  - Map the keys on every row and never rewrite the file.
  - If an issuer's **latest** row is `thematic_collaborative`, that issuer has **no confirmed tier**. Its earlier
    rows do not come back into force (owner decision 2).
  - `review_tiers` then lists the issuer under `changes` with `current_tier` `null`.
- **`tiers.evaluate`**
  - Maps the old keys in a rule's `tier` output, so a coverage-rule version saved before PR A still runs. Its
    thematic outputs become `letter`, as decided in owner decision 5.
- **Approved programme versions** (`program_versions[].targets[].tier` in client stream files, returned by
  `GET /api/stewardship/streams/{id}/program`) are mapped on read with the same table; `thematic_collaborative`
  reads as `letter` there. Nothing is rewritten.
- **Saving a coverage-rule version**
  - `POST /policies/coverage_rules/versions` refuses content whose rules output an old key.
  - The check reads the `tier` output cell of every rule in every decision table, without evaluating the rules,
    so an old key in a rule that never fires on the sample is also caught.
  - The response is 422 with detail
    `Coverage rules may only propose bilateral, letter or monitor (found <key>)`, naming the first old key in rule
    order.
  - So the mapping applies only to old versions; no new version can contain an old key.

**Bundled coverage rules** (`house_coverage_policy.graph.json`, hit policy `first`, the same order and rule ids):

| Rule id | When | Tier |
|---|---|---|
| `top_weight` | index weight ≥ 1 % | `bilateral` |
| `large_exposure` | AUM held > EUR 500 m | `bilateral` |
| `escalated` | an open engagement is escalated | `bilateral` |
| `high_emitter` | high-emitting sector | `letter` |
| `nature_impact` | high-impact nature sector | `letter` |
| `open_engagement` | an engagement is open | `letter` |
| `small_position` | index weight < 0.05 % | `monitor` |
| `default` | everyone else | `letter` |

The `_description` texts drop "collaborative" and "initiatives". For example, `high_emitter` reads "High emitters
get at least the expectations letter." On the sample universe: SYN03 and SYN07 are `bilateral`, the other 10 are
`letter`, and none is `monitor`.

**Bundled escalation tier caps** (`tier_caps` in `house_escalation_policy.graph.json`). Caps are named by step here.
The number is the index on the ladder of the PR that ships it.

| Tier | Highest step | Index in PR A (7-step ladder) | Index from PR B (6-step ladder) |
|---|---|---|---|
| `bilateral` | public statement | 6 | 5 |
| `letter` | vote against management | 4 | 3 |
| `monitor` | private engagement (no company-specific escalation) | 0 | 0 |
| none yet | public statement | 6 | 5 |

The thematic cap row ("beyond means promotion to Priority Bilateral") is deleted. `promote_tier` keeps its meaning:
the rules want a step above the tier's cap.

**Saved escalation-rule versions** (house and every client stream) are keyed by the old tier names, so from PR A
they would cap `letter` and `monitor` issuers at the "no tier yet" row. They are retired:

- PR A retires every saved `escalation_rules` version written before PR A. PR B retires every version written before
  PR B (written for the 7-step ladder). Version 0 (the bundled graph) is always current.
- `PolicyStore.active("escalation_rules")` skips a retired version and falls back to version 0.
  `GET /policies/escalation_rules` (with or without `?stream=`) then reports `active_version` 0.
- Retired versions stay listed and readable.
- `POST /policies/escalation_rules/activate` on a retired version returns 422 with detail
  `Version <n> was written for the old tiers or ladder; save a new version`.
- How a version is recognised as retired is the builder's call. For example, every version saved from PR A on could
  carry `"rules_format": "three_tiers"` in its record, and from PR B on `"three_tiers_6_steps"`. Tests create an old
  version by writing a version file the way `main` writes it today.

**Places that follow.** None of these hard-codes the old keys after PR A:

- `worklist.TIER_VALUE` becomes `bilateral` 1.0, `letter` 0.5, `monitor` 0.0.
- `process.py` stage 2 table and stage 5 tier-change labels.
- `policies.py` calibration distributions.
- `client_report.py` tier chart.
- `program.py` tier labels.
- `studios.tsx`: `TIER_ORDER` becomes `["Bilateral", "Letter", "Monitor"]`, and the Selection studio help text
  lists `bilateral, letter or monitor`.
- `docs/STEWARDSHIP_OPERATING_MODEL.md`:
  - The tier table gets three rows: Bilateral, Letter, Monitor.
  - The `tier` enum line becomes `bilateral | letter | monitor`.
  - The rule examples and the caps text change to match.
- `tests/fixtures/stewardship_worklist_unchanged_main.json`: its `/tiers` and `/policies/coverage_rules` parts are
  removed, because workbench AC-144 and AC-145 compare only the triggers and the universe.

**Test changes (PR A).** Value renames only, no assertion removed; the PR lists each file:
`test_stewardship_tiers.py`, `test_stewardship_policies.py`, `test_stewardship_escalation.py`,
`test_api_stewardship.py`, `test_stewardship_worklist.py`, and the fixture above.

### PR B: no joint engagement, no collaborative engager roles

**Ladder.** `EscalationStage` and `ESCALATION_ORDER` lose `JOINT_ENGAGEMENT`, so the ladder has 6 steps (indexes
0–5). `escalation.TOP` becomes 5.

The following derive the ladder from `ESCALATION_ORDER` or by stage name, so the change needs no other logic edits:

- the step names in `drafting.py`
- `reporting_agent.py`
- the `escalated` flags in `tiers.py` and `worklist.py`

The frontend lists change as well: `ESCALATION_STAGES` in `EngagementIssuePanel.tsx` and `studios.tsx`, and
`EscalationStage` in `types.ts` (regenerated from openapi where it is generated).

**Stored stages.** A before-validator reads `joint_engagement` as `private_engagement`. It applies to:

- `EngagementIssue.escalation_stage`
- `EscalationTransition.stage`

The history entry keeps its `decided_by`, `changed_at` and `reason`. Nothing is rewritten in files or Postgres.

`POST /api/engagement/records/{c}/issues/{i}/escalate` with `{"stage": "joint_engagement"}` is a 422, the normal
enum validation error.

**Bundled data.**

- `examples/sample_meetings.json`: SYN02's `board_governance` engagement moves from `joint_engagement` to
  `private_engagement`.
- `house_escalation_policy.graph.json`: caps take the PR B column above.
- `examples/client_escalation_example.graph.json`: `max([house.max_step, 4])` becomes `max([house.max_step, 3])`,
  which is still "vote against management".

**Saved escalation-rule versions:** PR B retires every version written before PR B, as described under PR A. New
versions are validated against the 6-step ladder, so a cap or step of 6 fails with the existing `(a whole number 0-5)`
message.

**Engager roles.** `EngagerRole` keeps only `BILATERAL`.

- **Stored values:** `lead`, `active_support` and `passive_support` in stored engagements (Postgres
  `stw_engagements.engager_role`, file records) are read as `null` (no role).
- **Intake:** the API and Excel intake reject those three values with the existing rejection,
  `reason` `not one of bilateral`.
- **Excel template:** the `engager_role` option list holds only `bilateral`, and its labels for `lead` and
  `passive_support` are removed.
- **Demo seed:** data-foundation PR 3 (`seed-demo`, open as #452) seeds only `bilateral`. Whichever of #452 and PR B
  merges second makes this change.

**Test changes (PR B).** Value renames only (`joint_engagement` → another step, step counts 7 → 6, removed roles
→ `bilateral`), no assertion removed; the PR lists each file: `test_stewardship_escalation.py`,
`test_engagement_store.py`, `test_postgres_engagement_store.py`, `test_stewardship_tracking.py`,
`test_api_stewardship.py`, `frontend/tests/engagement.test.ts` and
`tests/fixtures/engagements_migration/*/record.json` (these fixtures keep `joint_engagement` if a test of the mapping
on read uses them).

**Docs.** In `docs/STEWARDSHIP_OPERATING_MODEL.md`:

- The ladder text becomes 6 steps.
- The engagement `mode` enum becomes `bilateral | letter` (letter engagements are the baseline ones).
- The Initiative `type` enum loses `collaborative`, and the `partners` note goes.
- The words "collaborative" and "joint engagement" no longer appear.

### PR C: bilateral picks

**Store.** `bilateral_picks.jsonl` under `stewardship_streams_dir`, append-only. Each event is one of:

- `{"issuer_id", "event": "picked", "reason", "by", "at"}`
- `{"issuer_id", "event": "withdrawn", "by", "at"}`

A pick **stands** from its `picked` event until a later `withdrawn` event for the same issuer.

**Effect on the proposal.**

- **While a pick stands:**
  - The issuer's proposal is `{"tier": "bilateral", "rule": "manual", "reason": "Picked by <by>: <reason>"}`,
    whatever the coverage rules say.
  - `current_tiers`, `tier_review` and so `GET /tiers`, the Human Checkpoint tier changes and
    `POST /tiers/confirm` all use this proposal.
  - Confirming writes a `tier_assignments.jsonl` row with `rule` `manual` and the reason, like any other
    confirmation.
- **Rule previews:** policy calibration (`/studio/coverage/preview`) compares rule versions only, so picks do not
  appear in it.
- **After a withdrawal:** the proposal returns to the rules. If the rules propose a different tier from the
  confirmed one, the change waits at Human Checkpoint as usual. The confirmed tier stays until a person confirms the
  change.

**Routes** (analyst or above):

- `POST /api/stewardship/tiers/bilateral` with `{"issuer_id": str, "reason": str}` returns `{"picked": issuer_id}`.
  Errors are 422:
  - Blank or whitespace reason: `A bilateral pick needs a reason`.
  - Reason over 500 characters: `A bilateral pick reason has at most 500 characters`.
  - Issuer not in `load_sample()["issuers"]`: `Not in the house universe: <id>`.
  - A pick already stands: `<id> is already picked for bilateral`.
- `POST /api/stewardship/tiers/bilateral/{issuer_id}/withdraw` returns `{"withdrawn": issuer_id}`. With no standing
  pick it is a 422, `<id> has no bilateral pick`.
- `GET /api/stewardship/tiers` gains `picks`: the standing picks, oldest first, each
  `{"issuer_id", "name", "reason", "by", "at"}`.
- A pick on a company the rules already propose as bilateral is allowed. It keeps that company bilateral if the
  rules later change.
- A standing pick whose issuer is no longer in the house universe (for example after the universe source changes)
  is listed in `picks` with `name` `null`, makes no proposal, and can still be withdrawn.
- `by` is `principal.name`, as tier confirm records `confirmed_by`. `at` is an ISO 8601 UTC timestamp.

**Screens.**

- **Selection studio** (Steward workflow, stage 2), in its Review section under "Confirmed coverage tiers": a
  **Bilateral picks** block. It contains:
  - a company picker over the house universe, a reason field and a **Pick for bilateral** button;
  - below them, the standing picks as `<company> — <reason> — <by>, <date>`, where `<date>` is the date part of `at`
    as `YYYY-MM-DD`, each with **Withdraw**.
- **Human Checkpoint** (stage 5): tier changes from picks show like any other tier change. Rule `manual` and the
  reason come from the proposal. Confirm works as it does today.
- **Workbench:** PR 4 of the workbench spec adds the same action to step 3 (see the amendment).

## Other specs this changes

Amended in this PR:

- **Priority workbench** (`2026-11-13-stewardship-priority-worklist-design.md`):
  - The tier text: the score mapping becomes 1 / 0.5 / 0, and the sort is Bilateral → Monitor.
  - The API example, the non-goal and "Must not change".
  - Step 3 gains **Pick for bilateral** in PR 4.
  - The rows in the table below.
- **Cockpit** (`2026-11-13-stewardship-cockpit.md`): the ladder has 6 steps, and its rows below. Its demo seed's
  "step 2 to 5" moves need no change: they now land on the 6-step ladder's steps 2 to 5.
- **Data foundation** (`2026-11-12-stewardship-data-foundation-design.md`): the engager role list, the demo seed's
  role mix, and AC-26.

The test-writer amends the hidden tests for these rows. Rows marked superseded are retired. Each replacement row is
a new ID:

| Spec | Row | Change | Replacement |
|---|---|---|---|
| workbench | AC-7 | escalates with `joint_engagement`, which PR B removes | AC-140 (`written_escalation_to_board`) |
| workbench | AC-35, AC-36 | Given AC-7 | AC-141, AC-142 (Given AC-140) |
| workbench | AC-32 | "tests of `tiers.py` and `policies.py` pass unchanged" | AC-143 (`monitoring.py` and `program.py` only) |
| workbench | AC-51 | "`/tiers` equals main" | AC-144 (the monitoring triggers response only) |
| workbench | AC-52 | "`/policies/coverage_rules` equals main" | AC-145 (`/universe` only) |
| workbench | — | new: Pick for bilateral in step 3 (PR 4) | AC-146 |
| cockpit | AC-3 | `ladder` has 7 entries including "Joint engagement" | this spec AC-40 = cockpit AC-85 |
| cockpit | AC-10 | escalates with `joint_engagement` | this spec AC-41 = cockpit AC-86 |
| cockpit | AC-24 | escalates with `joint_engagement`; expects `ladder[3]` | this spec AC-42 = cockpit AC-87 |
| cockpit | AC-55 | escalates with `joint_engagement` | this spec AC-43 = cockpit AC-88 |
| cockpit | AC-25 | expects `ladder[4]` for vote against management | this spec AC-44 = cockpit AC-89 (`ladder[3]`) |
| data foundation | AC-26 | `passive_support` objectives (the role no longer exists) | this spec AC-31 = data-foundation AC-42 |

Not affected:

- The commitment loop (spec merged, PR #456 open), which uses no tier key, ladder step or engager role.
- The workbench PR 3 programmes, which use no tier key.

## PR split and order

1. **PR A: three tiers.** Covers `tiers.py`, both bundled graphs (PR A caps), `policies.py` save check, the places
   that follow, the operating-model tier text, the re-recorded snapshot fixture, frontend labels and tests.
   - Can start now.
   - Lands before workbench PR 2, so the workbench builds on the new keys.
   - Rows AC-1 to AC-19, AC-24, AC-25 and AC-27.
2. **PR B: six-step ladder, no collaborative roles.** Covers the enum changes and mapping on read, retiring saved
   escalation versions, the bundled data, intake and template, frontend step lists, openapi and `gen:api`, and the
   docs.
   - Starts after PR A.
   - Changes the #452 seed if #452 has merged by then. If the cockpit is built by then, its ladder labels change
     too.
   - Rows AC-20 to AC-23, AC-26, AC-28 to AC-35, and AC-40 to AC-44.
3. **PR C: bilateral picks.** Covers the pick log, routes, the effect on proposals, `picks` in `GET /tiers`, the
   Selection studio block, openapi and `gen:api`.
   - Starts after PR A.
   - Lands before workbench PR 4, which uses its route.
   - Rows AC-50 to AC-67.

## Left to the builder

- How PRs A and B mark escalation-rule versions saved from them on, as long as AC-24, AC-25, AC-27 and AC-35 hold.
- The exact layout of the Bilateral picks block, within the existing Selection studio styles.
- Whether the mapping on read for engager roles lives in the Pydantic model or in the Postgres store's row
  conversion, as long as AC-30 holds for both stores.

## Acceptance

Holdout rows run on the e2e stack with `ARP_ENGAGEMENT_STORE=postgres`. Terms used in the rows:

- **Fixture T:**
  - house universe source `sample` (`PUT /api/stewardship/universe` `{"source": "sample"}`, 12 issuers
    `SYN01`..`SYN12`);
  - `coverage_rules` and `escalation_rules` with no saved versions (v0 active);
  - no client streams;
  - `<stewardship_streams_dir>/tier_assignments.jsonl`, `bilateral_picks.jsonl` and the `selection/` directory
    removed;
  - the `stw_*` tables truncated in one `TRUNCATE … CASCADE` (no engagement records).
- **PR tags:** a row whose Given starts `PR X;` applies from that PR on. Rows without a tag apply from PR A.
- **Main row:** a JSON line or file written in the format `main` writes today, before this feature.
- **User A, user B:** analysts with `user_id` and `name` `A` and `B` in a `config/users.json` the test writes.
  Their requests carry `Authorization: Bearer <token>` and `Origin: http://other.invalid`, so the dev sign-in does
  not apply.
- **Q:** the current calendar quarter of the server's date, e.g. `2026-Q4` (the only cycle `POST /selection`
  accepts).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture T | `GET /api/stewardship/tiers` | `changes` has 12 entries. `SYN03` and `SYN07` have `tier` `bilateral` and `rule` `top_weight`. The other 10 have `tier` `letter` | holdout |
| AC-2 | Fixture T | `GET /api/stewardship/tiers` | `SYN02`, `SYN04`, `SYN05`, `SYN09`, `SYN10` and `SYN11` have `rule` `high_emitter`, `SYN12` has `nature_impact`, and `SYN01`, `SYN06` and `SYN08` have `default` | holdout |
| AC-3 | The bundled coverage rules | `tiers.evaluate` on one context: index weight 0.03, AUM held 5, no flags, no engagements | `tier` `monitor`, `rule` `small_position` | unit |
| AC-4 | The bundled coverage rules | `tiers.evaluate` on one context: index weight 0.01, `history.open_engagements` 1, not escalated | `tier` `letter`, `rule` `open_engagement` | unit |
| AC-5 | Fixture T plus a main-format `tier_assignments.jsonl` with rows, in this order: `SYN01` `scaled_baseline`, `SYN05` `systemic`, `SYN03` `priority_bilateral`, `SYN02` `priority_bilateral`, `SYN02` `thematic_collaborative` | `GET /api/stewardship/tiers` | `assignments` has `SYN01` `letter`, `SYN05` `monitor` and `SYN03` `bilateral`, and no entry for `SYN02`. `distribution` is `{"bilateral": 1, "letter": 1, "monitor": 1}`. `confirmed` is 3 | holdout |
| AC-6 | AC-5 | `GET /api/stewardship/tiers` | `changes` holds `SYN02` with `tier` `letter` and `current_tier` `null`, and `SYN05` with `tier` `letter` and `current_tier` `monitor`. It holds no entry for `SYN01` or `SYN03` | holdout |
| AC-7 | AC-5 | `GET /api/stewardship/tiers` twice | `tier_assignments.jsonl` is byte-identical to the file written in AC-5 | holdout |
| AC-8 | Fixture T plus a main-format saved `coverage_rules` v1 (the v0 content from `main`, with the old keys), saved by user A and activated by user B | `GET /api/stewardship/tiers` | Same tiers and rules as AC-1 and AC-2 | holdout |
| AC-9 | Fixture T | `POST /api/stewardship/policies/coverage_rules/versions` with the PR's v0 content where the `default` row's tier is `'scaled_baseline'` | Status 422 with detail `Coverage rules may only propose bilateral, letter or monitor (found scaled_baseline)` | holdout |
| AC-18 | Fixture T | `POST /api/stewardship/policies/coverage_rules/versions` with the PR's v0 content where the `small_position` row's tier is `'systemic'` (a row that fires for no sample issuer) | Status 422 with detail `Coverage rules may only propose bilateral, letter or monitor (found systemic)` | holdout |
| AC-19 | Fixture T plus a client stream S whose stored file holds a main-format approved programme version with one target whose `tier` is `scaled_baseline` | `GET /api/stewardship/streams/S/program` | That target's `tier` in the response's `versions` is `letter` | holdout |
| AC-10 | Fixture T, then `POST /api/stewardship/tiers/confirm` `{}` | `GET /api/stewardship/tiers` | `distribution` is `{"bilateral": 2, "letter": 10}`, and `changes` is `[]` | holdout |
| AC-11 | Fixture T; a record for `SYN03` and one for `SYN01`, each with one open issue at `private_engagement` | `GET /api/stewardship/studio/escalation/recommendations` | The live `SYN03` entry has `tier` `bilateral` and `max_step` `public_statement`. The live `SYN01` entry has `tier` `letter` and `max_step` `vote_against_management` | holdout |
| AC-12 | The bundled escalation rules | `escalation.evaluate` on one sample context with tier `monitor` | `max_step` `private_engagement` and `escalate` false | unit |
| AC-13 | Fixture T | `GET /api/stewardship/worklist` | `SYN03`'s `coverage_tier` is `bilateral` and its `coverage_tier` part has `normalised` 1. `SYN01`'s is `letter` with `normalised` 0.5 | holdout |
| AC-14 | Fixture T on the e2e stack | A user opens the Steward workflow's Selection stage | The "Confirmed coverage tiers" table has the rows `Bilateral`, `Letter`, `Monitor`, in that order, and no other tier row | evaluator |
| AC-15 | AC-14 | The user opens Design and Calibrate in the Selection stage | The help text lists `bilateral, letter or monitor`. The calibration table rows are `Bilateral`, `Letter`, `Monitor` | evaluator |
| AC-16 | Fixture T on the e2e stack | A user opens Human Checkpoint (stage 5) | The proposed column of the tier changes shows only `Bilateral` and `Letter` | evaluator |
| AC-17 | The PR build | Case-insensitive search for `thematic_collaborative`, `thematic & collaborative`, `scaled_baseline`, `scaled baseline`, `priority_bilateral`, `priority bilateral` and `systemic / market-level` in `backend/arp/**/*.{py,json}`, `frontend/src/**/*.{ts,tsx,json}` and `docs/STEWARDSHIP_OPERATING_MODEL.md` | Matches only in `backend/arp/stewardship/tiers.py` (the mapping on read) | holdout |
| AC-20 | PR B; Fixture T; a record for `SYN06` with one open issue | `POST /api/engagement/records/SYN06/issues/{id}/escalate` `{"stage": "joint_engagement"}` | Status 422, and the issue's `escalation_stage` stays `private_engagement` | holdout |
| AC-21 | PR B; AC-11 | `GET /api/stewardship/studio/escalation/recommendations` | The live `SYN03` entry has `cap_index` 5. The live `SYN01` entry has `cap_index` 3 | holdout |
| AC-22 | PR B; Fixture T; an engagement for `SYN06` taken in through `POST /api/stewardship/intake/engagements`, then in SQL: its `stw_engagements.escalation_stage` set to `joint_engagement`, and one `stw_transitions` row inserted for it (`kind` `escalation`, stage `joint_engagement`, `decided_by` `old`, `reason` `r`) | `GET /api/engagement/records/SYN06` | Status 200. The issue's `escalation_stage` is `private_engagement`. Its history entry has `stage` `private_engagement`, `decided_by` `old` and `reason` `r` | holdout |
| AC-23 | PR B; Fixture T | `GET /api/stewardship/studio/escalation/recommendations` | The sample entry for `SYN02`, theme `board_governance`, has `current` `private_engagement` | holdout |
| AC-24 | Fixture T plus a main-format saved `escalation_rules` v1, saved by user A and activated by user B | `GET /api/stewardship/policies/escalation_rules` | `active_version` is 0, and version 1 is still listed | holdout |
| AC-25 | AC-24 | `POST /api/stewardship/policies/escalation_rules/activate` `{"version": 1}` as user B | Status 422 with detail `Version 1 was written for the old tiers or ladder; save a new version` | holdout |
| AC-26 | PR B; Fixture T | `POST /api/stewardship/policies/escalation_rules/versions` with the PR's v0 content where the `bilateral` cap is 6 | Status 422, with a detail that contains `(a whole number 0-5)` | holdout |
| AC-27 | Fixture T plus a client stream S with a main-format saved and activated `escalation_rules` v1 | `GET /api/stewardship/policies/escalation_rules?stream=S` | `active_version` is 0 | holdout |
| AC-35 | PR B; a house `escalation_rules` version saved and activated with the PR A build's format | `PolicyStore.active_version("escalation_rules")` | 0 | unit |
| AC-28 | PR B; Fixture T | `POST /api/stewardship/intake/engagements` with one valid engagement whose `engager_role` is `lead` | Status 422. `rejected` holds one entry with `field` `engager_role` and `reason` `not one of bilateral`, and `created` is 0 | holdout |
| AC-29 | PR B; Fixture T | The same request with `engager_role` `bilateral` | Status 200 and `created` 1 (must not change) | holdout |
| AC-30 | PR B; Fixture T; an engagement taken in with `engager_role` `bilateral`, then its `stw_engagements.engager_role` set to `passive_support` in SQL | The engagement is read through the API that returns it (`GET /api/engagement/records/{company_id}`) | Status 200, and the issue's `engager_role` is `null` | holdout |
| AC-31 | PR B and data-foundation PR 3 (#452) merged; Showcase data as defined in the workbench spec (`arp stewardship seed-demo` run) | `SELECT DISTINCT engager_role FROM stw_engagements WHERE source = 'mock_voice_seed'` | Exactly one row: `bilateral` (mirrored as data-foundation AC-42) | holdout |
| AC-32 | PR B | `GET /api/stewardship/intake/template?kind=engagements`, opened in openpyxl | The `engager_role` option list holds exactly one value, `bilateral` | holdout |
| AC-33 | PR B; the PR build | Case-insensitive search for `joint_engagement`, `joint engagement`, `collaborative`, `active_support`, `passive_support` and `co-lead` in the same files as AC-17 | Matches only in `backend/arp/stewardship/tiers.py` (the tier mapping on read), the mapping-on-read lines of `backend/arp/schemas/engagement.py`, and the Postgres engagement store if the role mapping lives there | holdout |
| AC-34 | PR B; Fixture T; a record and open issue for `SYN06` on the e2e stack | A user opens the issue's escalation control | It offers exactly 6 steps, in ladder order, with no "Joint engagement" | evaluator |
| AC-40 | PR B and cockpit PR 1 merged; as cockpit AC-3 | as cockpit AC-3 | `ladder` has 6 entries with `step` 1..6 and `label` exactly "Private dialogue", "Letter to the board", "Meeting with the chair", "Vote against management", "File a resolution", "Public statement", each `companies` `[]` (mirrored as cockpit AC-85) | holdout |
| AC-41 | PR B and cockpit PR 1 merged; as cockpit AC-10 | `POST …/escalate` with `{stage: "written_escalation_to_board"}` | The stored `planned_meeting_date` is still `2026-11-20` (mirrored as cockpit AC-86) | holdout |
| AC-42 | PR B and cockpit PR 1 merged; as cockpit AC-24, but the two engagements escalated to `written_escalation_to_board` and `escalation_to_chair` | as cockpit AC-24 | `ladder[2].companies` is `[{company_id: "isin_XA0000000001", company: "Alpha AG"}]`, and A is in no other ladder step (mirrored as cockpit AC-87) | holdout |
| AC-43 | PR B and cockpit PR 1 merged; as cockpit AC-55, but A's engagement escalated to `written_escalation_to_board` | as cockpit AC-55 | A's contributor `status` is `in_escalation` (mirrored as cockpit AC-88) | holdout |
| AC-44 | PR B and cockpit PR 1 merged; as cockpit AC-25 | as cockpit AC-25 | A is listed only in `ladder[3]` (mirrored as cockpit AC-89) | holdout |
| AC-50 | PR C; Fixture T | User A: `POST /api/stewardship/tiers/bilateral` `{"issuer_id": "SYN01", "reason": "CEO change"}`, then `GET /tiers` | Status 200, body `{"picked": "SYN01"}`. In `changes`, `SYN01` has `tier` `bilateral`, `rule` `manual`, `reason` `Picked by A: CEO change` and `current_tier` `null` | holdout |
| AC-51 | PR C; AC-50 | The contents of `tier_assignments.jsonl` | The file does not exist or has no `SYN01` row | holdout |
| AC-52 | PR C; AC-50 | `GET /api/stewardship/tiers` | `picks` is `[{"issuer_id": "SYN01", "name": "Synthetic Company 01", "reason": "CEO change", "by": "A", "at": <timestamp>}]` | holdout |
| AC-53 | PR C; AC-50, then user A: `POST /tiers/confirm` `{"issuer_ids": ["SYN01"]}` | `GET /api/stewardship/tiers` | Body of the confirm is `{"confirmed": 1}`. `assignments` has `SYN01` with `tier` `bilateral`, `rule` `manual` and `confirmed_by` `A`. `changes` has no `SYN01` entry | holdout |
| AC-54 | PR C; AC-53; a record for `SYN01` with one open issue | `GET /api/stewardship/studio/escalation/recommendations` | The live `SYN01` entry has `tier` `bilateral` and `max_step` `public_statement` | holdout |
| AC-55 | PR C; AC-53 | User B: `POST /api/stewardship/tiers/bilateral/SYN01/withdraw`, then `GET /tiers` | Body `{"withdrawn": "SYN01"}`. `picks` is `[]`. `changes` has `SYN01` with `tier` `letter`, `rule` `default` and `current_tier` `bilateral`. `assignments` still has `SYN01` `bilateral` | holdout |
| AC-56 | PR C; Fixture T | `POST /tiers/bilateral` `{"issuer_id": "SYN01", "reason": "   "}` | Status 422 with detail `A bilateral pick needs a reason` | holdout |
| AC-57 | PR C; Fixture T | `POST /tiers/bilateral` `{"issuer_id": "NOPE", "reason": "x"}` | Status 422 with detail `Not in the house universe: NOPE` | holdout |
| AC-58 | PR C; AC-50 | `POST /tiers/bilateral` `{"issuer_id": "SYN01", "reason": "again"}` | Status 422 with detail `SYN01 is already picked for bilateral` | holdout |
| AC-59 | PR C; Fixture T | `POST /tiers/bilateral/SYN02/withdraw` | Status 422 with detail `SYN02 has no bilateral pick` | holdout |
| AC-60 | PR C; Fixture T | `POST /tiers/bilateral` with a 501-character reason | Status 422 with detail `A bilateral pick reason has at most 500 characters` | holdout |
| AC-61 | PR C; a `viewer` user (non-dev auth) | `POST /api/stewardship/tiers/bilateral` | Status 403 | unit |
| AC-62 | PR C; Fixture T; user A picks `SYN01`, then confirms the house quarterly selection holding `SYN01` (`POST /api/stewardship/selection` `{"cycle": Q, "add": ["SYN01"]}`, then `POST /api/stewardship/selection/confirm` `{"cycle": Q}`) | `GET /api/stewardship/tiers` | `assignments` has no `SYN01` entry. The quarterly selection confirms no tier (must not change) | holdout |
| AC-63 | PR C; AC-55 | The contents of `bilateral_picks.jsonl` | Two lines: a `picked` event by `A`, then a `withdrawn` event by `B` | unit |
| AC-64 | PR C; AC-50 | `POST /api/stewardship/studio/coverage/preview` with the active v0 graph | `changes` is `[]`, `assignments` has `SYN01` with `rule` `default`, and `distribution_active` is `{"Bilateral": 2, "Letter": 10}` | holdout |
| AC-65 | PR C; Fixture T on the e2e stack | In the Selection stage, the user picks Synthetic Company 01, types `CEO change` and presses **Pick for bilateral** | The Bilateral picks list shows `Synthetic Company 01 — CEO change — <user>, <today as YYYY-MM-DD, UTC>` with a **Withdraw** button | evaluator |
| AC-67 | PR C; a standing pick for issuer `X` and a house universe without `X` (unit fixture) | `GET /tiers` content (`tier_review` plus `picks`) is built | `picks` lists `X` with `name` `null`, and `changes` has no entry for `X` | unit |
| AC-66 | PR C; AC-65 | The user opens Human Checkpoint | A tier change for Synthetic Company 01 shows current `none`, proposed `Bilateral`, rule `manual` and reason `Picked by <user>: CEO change`. Confirming it removes it from the list | evaluator |

Must not change:

- **Confirm without `issuer_ids`** still confirms every proposed change (AC-10).
- **Bilateral engager role:** intake still accepts it (AC-29).
- **The quarterly selection** sets no tier (AC-62).
- **Mapping on read:** stored files stay byte-identical after a read (AC-7).

Superseded rows of other specs: workbench AC-7, AC-32, AC-35, AC-36, AC-51 and AC-52; cockpit AC-3, AC-10,
AC-24, AC-25 and AC-55; data foundation AC-26. See "Other specs this changes".

Rows mirrored into other specs, so the holdout job runs them on whichever PR lands second: AC-40 to AC-44 are
cockpit AC-85 to AC-89, and AC-31 is data-foundation AC-42.
