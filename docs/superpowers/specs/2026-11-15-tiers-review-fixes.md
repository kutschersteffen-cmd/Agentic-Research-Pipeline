# Tiers review fixes: five bug fixes and two hardening points on the three-tiers work

Slug: tiers-review-fixes

Risk: `risk:normal` for both PRs. Size M, 2 PRs. This spec PR is `risk:low` (docs only).

Status: **approved by the owner on 15 Nov 2026** (buttons in the spec session, after two spec-critic passes were fixed).

Parent spec: [`2026-11-14-stewardship-three-tiers.md`](2026-11-14-stewardship-three-tiers.md) (bilateral / letter /
monitor, bilateral picks, coverage and escalation rules). Every finding below was reproduced on `main`.

## Owner decisions

- **15 Nov 2026, by button in the dispatcher session:** a damaged log line is skipped and a warning is written to
  the server log; the screens keep working.
- **15 Nov 2026, by button in this spec session:** the same rule applies to the confirmed-tiers log
  (`tier_assignments.jsonl`), not only to the bilateral-picks log.

Defaults stated for the owner's approval (approving this spec approves them):

1. Saving a coverage rule set or an escalation rule set that names an old tier key is rejected with 422 and a
   message that names the old key.
2. A second simultaneous pick of the same company gets the existing 422 `<id> is already picked for bilateral`.
3. The lock is the repo's cross-process `KeyedLock` (`backend/arp/storage/locks.py`): one module-level
   `KeyedLock(lock_path=lambda p: Path(p + ".lock"))` keyed by the log's path, so the lock files are
   `bilateral_picks.jsonl.lock` and `tier_assignments.jsonl.lock` next to the logs (the pattern of
   `arp/discovery/downloader.py`). The sibling item `workbench-review-fixes` should use the same pattern for the
   selection, programme and notes logs; neither item touches the other's files.

## Why

A review of the three-tiers work found five bugs and two small gaps. The worst (F1) takes down most stewardship
screens when one line of a log file is damaged. The showcase (about 27 Nov 2026) runs as one uvicorn process, so the
race in F2 is robustness, not showcase risk.

## What is wrong today, and the fix

| # | Where (on `main`) | What goes wrong | Fix |
|---|---|---|---|
| F1 | `tiers.py` `PickStore.standing()` and `TierStore.all()` | One torn or damaged line raises `JSONDecodeError` (or `KeyError`): the cockpit, worklist, process view and the tiers, worklist, programme and client-report routes answer 500 | A damaged line is skipped with one `WARNING` in the server log naming the file and the line number. The file is never rewritten. A line is damaged when it is not valid UTF-8, not a JSON object, or lacks a required field: picks `issuer_id`, `event`, and for a `picked` event also `reason`, `by`, `at`; tiers `issuer_id`, `tier`, `assigned_at` |
| F2 | `tiers.py` `pick()`, `withdraw()`; `process.py` `confirm_tiers()` (which reads the open changes, then appends through `TierStore.confirm()`) | Check-then-append without a lock: two simultaneous picks of one company are both accepted and the later reason wins; two simultaneous confirms append every change twice | Each check and its append run under one `KeyedLock` per log file, held across processes |
| F3 | `policies.py` `_validate_coverage` | Only decision-table cells that are bare literals are checked: an expression node (or an expression inside a cell) that sets an old tier name is accepted, then silently mapped by `map_tier` | Every text value in every node of the graph is checked for a quoted old tier key (`'priority_bilateral'` or `"priority_bilateral"`, same for the other three), whether or not the rule fires |
| F4 | `tiers.py` `map_tier` | `OLD_TIERS.get(tier, tier)` with a list or dict raises `TypeError`: saving such a coverage rule answers 500 | `map_tier` maps only text; anything else falls through to the existing "no valid tier" `ValueError`, which the save route answers with 422 |
| F5 | `policies.py` `_validate_escalation` (and `_validate_client_escalation`) | `tier_caps` keys are never checked: an escalation graph keyed by the old tier names saves (it needs two people to activate), and then Monitor and Letter issuers fall to the "no tier yet" row and get the top cap instead of their own | Same check as F3, on house and client escalation graphs |
| H1 | `tiers.py` lines 103, 119, 134, 147 | Files are opened without an encoding while writing `ensure_ascii=False`: reasons and names with umlauts follow the server's locale | Both logs are written and read as UTF-8. Reading decodes line by line, so a legacy line written under another locale is a damaged line (F1), never a whole-file failure |
| H2 | `policies.py` `retired()` | An activation that points at a missing `v<n>.json` silently falls back to version 0 | Raise `KeyError("escalation_rules v<n>")`, as `content()` does; `activations()` is already strict on purpose |

`map_tier` keeps mapping old keys when **reading** stored files (parent AC-8, AC-19): only saving new content is
stricter.

## Goals

- One damaged log line no longer breaks any screen (F1).
- One company can hold at most one standing pick, even under simultaneous requests or processes (F2).
- No new policy version can carry an old tier key, wherever it sits in the graph (F3, F5).
- A malformed coverage tier answers 422, not 500 (F4).
- Umlauts survive any server locale (H1); a missing policy file fails loudly (H2).

## Non-goals

- No change to the tier rules, caps, picks UI, or the API shape. No frontend change: both affected routes already
  answer 422 with a `detail` the UI shows (`frontend/src/api/contract.ts` and `studios.tsx` need nothing).
- No repair tool for damaged files; no rewriting of stored files.
- No change to `cockpit.py`, `worklist.py`, `programmes.py` (other open fix items change them) or to the selection,
  programme and notes logs (`workbench-review-fixes`).

## Anti-goals

- A damaged line must never silently change a policy: activation logs and policy version files stay strict (H2).
- A rejected save must never store a version.

## Approaches considered

1. **Chosen:** fix each finding in place in `tiers.py` and `policies.py`, reusing `KeyedLock` and the existing
   messages. Smallest change; no new concepts.
2. Move both logs to Postgres (`stw_*` tables) for transactions. Fixes F1 and F2 for good, but is a migration with
   data moves: too large for a fix item two weeks before the showcase.
3. For F3/F5, evaluate the graph once per old key and look at the raw output instead of scanning text. Misses rules
   that never fire on the sample (parent AC-18 already requires catching those), so rejected.

## PR split

- **PR 1 (`tiers.py` and `process.py` `confirm_tiers`, with tests):** F1, F2, F4, H1. Rows AC-1 to AC-13 and
  AC-22 to AC-27.
- **PR 2 (`policies.py`, with tests):** F3, F5, H2. Rows AC-14 to AC-21 and AC-28 to AC-29.

Neither PR touches `cockpit.py`, `worklist.py` or `programmes.py`, the files other open fix items change. The PRs
are independent and can merge in either order.

## Parent rows

- Extended (expected values unchanged, so their hidden tests stay as they are): AC-9 and AC-18 (coverage save
  check, now also expressions), AC-26 (escalation save check, now also tier keys), AC-58 (already picked, now also
  under simultaneous requests), AC-10 (confirm, now also under simultaneous requests), AC-5 (reading old tier rows,
  now line by line), AC-24 (retired versions, now loud when the file is missing).
- Superseded or changed: **none.** No parent row's expected value changes.

## Left to the builder

- How the unit tests force a non-UTF-8 locale (for example a subprocess with `PYTHONUTF8=0` and a Latin-1 locale).
- The exact warning wording, as long as it names the file and the line number.

## Acceptance

Terms as in the parent spec's Acceptance section: **Fixture T**, **D**, **Main-format saved version**, **Stream
`client-s`**. Holdout rows run on the e2e stack with `ARP_ENGAGEMENT_STORE=postgres`.

- **Damaged picks file:** `<stewardship_streams_dir>/bilateral_picks.jsonl` with three lines: a main-format
  `picked` event for `SYN01` (reason `CEO change`, by `A`), then the torn line `{"issuer_id": "SYN0`, then a
  main-format `picked` event for `SYN02` (reason `Board change`, by `A`).
- **Damaged tiers file:** `<stewardship_streams_dir>/tier_assignments.jsonl` with three lines: a main-format
  confirmed row for `SYN03` (tier `bilateral`, rule `top_weight`, confirmed by `A`), then the torn line
  `{"issuer_id": "SYN0`, then the same row for `SYN07`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture T plus the damaged picks file | `GET /api/stewardship/tiers` | Status 200. `picks` holds exactly `SYN01` then `SYN02`, with reasons `CEO change` and `Board change` | holdout |
| AC-2 | AC-1 | `GET /api/stewardship/worklist` | Status 200 | holdout |
| AC-3 | Fixture T plus the damaged tiers file | `GET /api/stewardship/cockpit` | Status 200 | holdout |
| AC-4 | AC-1 | `PickStore.standing()` | The server log has exactly one `WARNING` record, naming `bilateral_picks.jsonl` and line 2. The file is byte-identical before and after | unit |
| AC-5 | Fixture T plus the damaged tiers file | `GET /api/stewardship/tiers` | Status 200. `assignments` holds exactly `SYN03` and `SYN07`, and `distribution` is `{"bilateral": 2}` | holdout |
| AC-6 | AC-5 | `TierStore.latest()` | The server log has exactly one `WARNING` record, naming `tier_assignments.jsonl` and line 2. The file is byte-identical before and after | unit |
| AC-7 | A picks file holding a `picked` event for `SYN01`, then the line `{"event": "picked"}` (valid JSON, no `issuer_id`) | `PickStore.standing()` | Returns one pick, `SYN01`, and logs one `WARNING` naming line 2 | unit |
| AC-8 | Fixture T | 10 `POST /api/stewardship/tiers/bilateral` `{"issuer_id": "SYN01", "reason": "r<n>"}` sent at the same time (n = 1..10) | Exactly one answers 200. The other nine answer 422 with detail `SYN01 is already picked for bilateral`. `bilateral_picks.jsonl` has exactly one line | holdout |
| AC-9 | An empty streams directory; two OS processes on it | Both call `PickStore.pick("SYN01", …)` at the same moment | One returns; the other raises `ValueError` `SYN01 is already picked for bilateral`. The file has one `picked` line | unit |
| AC-10 | A standing pick for `SYN01`; two OS processes | Both call `PickStore.withdraw("SYN01", …)` at the same moment | One returns; the other raises `ValueError` `SYN01 has no bilateral pick`. The file has one `withdrawn` line | unit |
| AC-11 | Fixture T | `POST /api/stewardship/policies/coverage_rules/versions` with the v0 content where the `default` row's `t` cell is the expression string `["letter"]` (JSON `"t": "[\"letter\"]"`) | Status 422 with a detail that starts `Coverage rules returned no valid tier for SYN01` | holdout |
| AC-12 | Fixture T | The same request with the `t` cell the expression string `{t: "letter"}` (JSON `"t": "{t: \"letter\"}"`) | Status 422 with a detail that starts `Coverage rules returned no valid tier for SYN01` | unit |
| AC-13 | A process whose locale encoding is Latin-1 (`PYTHONUTF8=0`) | It picks `SYN01` with reason `Prüfung Lieferkette`, and confirms a tier with `decided_by` `Jürgen` | `bilateral_picks.jsonl` and `tier_assignments.jsonl` each hold the bytes `c3 bc` for every `ü` | unit |
| AC-22 | AC-13 | A UTF-8 process reads both files (`PickStore.standing()`, `TierStore.latest()`) | The reason reads `Prüfung Lieferkette` and `confirmed_by` reads `Jürgen` | unit |
| AC-23 | Fixture T plus the damaged picks file; stream `client-s` created through the API | `GET /api/stewardship/streams/client-s/program`, `…/report` and `…/flow` | Each answers the same status code and body as the same request after line 2 (the torn line) is removed from `bilateral_picks.jsonl`, leaving the two valid picks | holdout |
| AC-24 | Fixture T | Two `POST /api/stewardship/tiers/confirm` `{}` sent at the same time | `tier_assignments.jsonl` has exactly 12 lines, one per issuer | holdout |
| AC-25 | A picks file whose line 1 is a valid `picked` event for `SYN01` and whose line 2 is a `picked` event for `SYN02` with reason `Prüfung` encoded in Latin-1 (byte `fc`) | `PickStore.standing()` | Returns one pick, `SYN01`, and logs one `WARNING` naming line 2 | unit |
| AC-26 | PR 1; `bilateral_picks.jsonl` and `tier_assignments.jsonl` written by `main` under a UTF-8 locale, with umlauts in a reason and a `confirmed_by` | `GET /api/stewardship/tiers` | The reason and `confirmed_by` read back with their umlauts unchanged (must not change) | unit |
| AC-27 | PR 1 | The parent spec's AC-5, AC-10, AC-50, AC-56 to AC-60 | Each still passes unchanged (must not change) | holdout |
| AC-14 | PR 2; Fixture T | `POST /api/stewardship/policies/coverage_rules/versions` with the v0 content plus an `expressionNode` between `coverage_tiers` and `output` that sets `tier` to `'priority_bilateral'` | Status 422 with detail `Coverage rules may only propose bilateral, letter or monitor (found priority_bilateral)` | holdout |
| AC-15 | PR 2; Fixture T | The same request where the expression is `holding.index_weight_pct > 100 ? 'systemic' : tier` (fires for no sample issuer) | Status 422 with detail `Coverage rules may only propose bilateral, letter or monitor (found systemic)` | holdout |
| AC-16 | PR 2; Fixture T | `POST /api/stewardship/policies/escalation_rules/versions` with the v0 content where the `tier_caps` row `monitor` has tier cell `'systemic'` | Status 422 with detail `Escalation rules may only name bilateral, letter or monitor (found systemic)` | holdout |
| AC-17 | PR 2; Fixture T plus stream `client-s` | `POST /api/stewardship/policies/escalation_rules/versions?stream=client-s` with the client example graph (`GET /api/stewardship/studio/escalation/client-example`) where the `climate_to_vote` row's tier cell is `'scaled_baseline'` | Status 422 with detail `Escalation rules may only name bilateral, letter or monitor (found scaled_baseline)` | holdout |
| AC-28 | PR 2; AC-14 | `GET /api/stewardship/policies/coverage_rules` | `versions` lists only version 0 | holdout |
| AC-18 | PR 2; Fixture T; written to disk: a house `escalation_rules/v1.json` in PR 2's format (`rules_format` `three_tiers_6_steps`, `created_by` `A`) and an `activations.jsonl` line for version 1 with `approved_by` `B`; then `v1.json` deleted | `GET /api/stewardship/policies/escalation_rules` | Status 500 (never 200 with `active_version` 0) | holdout |
| AC-19 | PR 2; AC-18 as a unit fixture | `PolicyStore.active_version("escalation_rules")` | Raises `KeyError` whose message contains `escalation_rules v1` | unit |
| AC-29 | Fixture T; `escalation_rules/activations.jsonl` holding the torn line `{"version": 1, "appr` | `GET /api/stewardship/policies/escalation_rules` | Status 500 (must not change: activation logs stay strict) | holdout |
| AC-20 | PR 2; Fixture T | Save the unchanged v0 content of `coverage_rules`, then of `escalation_rules`, through `POST …/versions` | Both answer 200 with `{"version": 1}` (must not change) | holdout |
| AC-21 | PR 2 | The parent spec's AC-8, AC-9, AC-18, AC-19, AC-24, AC-25, AC-26 | Each still passes unchanged (must not change) | holdout |

Must not change: valid graphs still save (AC-20); stored main-format files and old-key versions still read as
before (AC-21, AC-26, AC-27); activation logs stay strict (AC-29).

New `holdout` rows for the test-writer: AC-1, AC-2, AC-3, AC-5, AC-8, AC-11, AC-14 to AC-18, AC-20, AC-23, AC-24,
AC-28, AC-29. AC-21 and AC-27 are covered by the parent's existing hidden tests.
