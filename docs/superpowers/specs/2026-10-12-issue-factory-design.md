# Issue factory: scout proposes, you approve, worker builds

Date: 2026-10-12. Status: draft for review.
Builds on: `docs/superpowers/specs/2026-10-11-engineering-process-design.md` (gates, on-demand
dependencies).

## Goal

Work reaches a reviewed PR without the person starting a session. Claude finds candidate work,
the person approves it with one label, Claude builds it under the existing gates and opens a PR.
The person reviews and merges.

Success means: on a normal day the person spends about 2 minutes approving proposals plus PR
review time, and never writes a prompt to get routine work done.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Work queue | GitHub Issues on this repo |
| Where work runs | Routines on the person's Claude plan: fresh cloud sessions in this environment, so the Stop hook, `ensure-deps.sh`, plugins and `CLAUDE.md` all apply. No API key. |
| Who approves before work starts | The person, always. The scout only proposes. |
| Merge | Always the person. No auto-merge. |
| Scout schedule | Daily 05:17 Europe/Berlin (`CRON_TZ=Europe/Berlin 17 5 * * *`) |
| Worker schedule | Hourly (`0 * * * *`) |

## Labels

| Label | Set by | Meaning |
|---|---|---|
| `claude-proposed` | scout | Proposal waiting for the person |
| `claude` | person | Approved: the worker may take it |
| `claude-working` | worker | Claimed; other runs skip it |
| `claude-needs-info` | worker | Unclear, too big, or gates failed; a comment says what is needed. Re-adding `claude` hands it back. |
| `claude-pr-open` | worker | PR opened, waiting for review |

## Scout (`.claude/skills/factory-scout/SKILL.md`, invoked as `/factory-scout`)

Never changes code or pushes. Each run:

1. Collect candidates from:
   - CI on `main`: the latest workflow run; if red, the failing job and test.
   - Deferred findings: "Known limits" / "Deferred" sections in descriptions of PRs merged in
     the last 30 days (PR #130 has six).
   - `ponytail:` comments in the code (the `/ponytail:ponytail-debt` skill).
   - `/ponytail:ponytail-audit` top findings.
   - `pip-audit` / `npm audit` high or critical findings (run via `ensure-deps.sh`).
2. Drop any candidate that matches an open issue, or an issue closed in the last 90 days, by
   title or by the file and symbol it names. Closed = rejected; never re-propose.
3. File at most **3** issues, highest value first (red CI > security > correctness > debt >
   simplification), each using the template fields, labelled `claude-proposed`.
4. If nothing qualifies, file nothing.

## Worker (`.claude/skills/factory-worker/SKILL.md`, invoked as `/factory-worker`)

Each run:

1. **Recover stuck issues:** any issue labelled `claude-working` whose label was added more than
   3 hours ago and has no linked open PR → remove `claude-working`, add `claude`, comment
   "Released after a stalled run".
2. **Pick:** the oldest open issue labelled `claude` (not `claude-working`). None → end the run.
3. **Claim:** remove `claude`, add `claude-working`, comment "Picked up by Claude (run <session
   link>)".
4. **Triage:** if the issue lacks a checkable "Done when", or needs a spec (new subsystem,
   interface change, more than about a day of work) → comment 1–3 questions or a proposed split,
   swap to `claude-needs-info`, end the run.
5. **Build:** branch `claude/issue-<N>-<slug>` from `origin/main`; follow `CLAUDE.md` (TDD,
   ponytail, Stop hook). Run `/ponytail:ponytail-review` and `/code-review` on the diff and fix
   what they find.
6. **PR:** open against `main`, body includes "Closes #N" and lists any test changes.
   - Gates pass → normal PR; swap the issue to `claude-pr-open`; comment the PR link.
   - Gates still fail after the session's attempts → open as **draft**, comment what fails,
     swap to `claude-needs-info`.
7. One issue per run. CI and review follow-up happen through the existing PR rules in later
   sessions when the person asks; the worker does not wait on CI.

## Issue template (`.github/ISSUE_TEMPLATE/claude-task.md`)

Fields: **What** (the change), **Why** (the problem it solves), **Done when** (a checkable
condition, ideally a test), **Size** (S: under an hour / M: a few hours / L: needs a spec).
Default label: none; the person adds `claude` when ready.

## `CLAUDE.md`

Add a short "Factory" section (about 6 lines): the labels, the two loops, and "issues labelled
`claude` are worked by the hourly Routine; don't pick them up by hand while `claude-working`".

## Routines

Created after the PR merges and the manual test passes, with `create_new_session_on_fire`
(fresh session per run, this environment) and push notifications on:

- `factory-scout`: prompt `/factory-scout`, `CRON_TZ=Europe/Berlin 17 5 * * *`.
- `factory-worker`: prompt `/factory-worker`, `0 * * * *`.

Pausing: disable either Routine in claude.ai → Routines.

## Testing

1. Create the five labels.
2. Run `/factory-scout` by hand in a session; check: at most 3 issues, template fields present,
   no duplicates of existing issues, labelled `claude-proposed`.
3. Approve one (relabel `claude`); run `/factory-worker` by hand; check: claim comment, branch
   name, PR against `main` with "Closes #N", label `claude-pr-open`.
4. Run `/factory-worker` again with no `claude` issues; check it ends without changes.
5. Only then create the Routines.

## Not included

Auto-merge; starting work without the person's label; production error feeds (gap 5); a
GitHub Action trigger (add if hourly pickup proves too slow).

## Risks

- **Usage:** an hourly worker with nothing to do still starts a session (checks issues, ends).
  Cost per empty run not measured; if noticeable, the worker can be moved to every 2–3 hours.
- **First run per container installs dependencies** (about 3–4 minutes) before the gates can
  pass, so a worker run takes at least that long.
- **Scout quality:** proposals are only as good as the sources; closing a proposal is the
  feedback signal, and the scout must never re-propose a closed one.
