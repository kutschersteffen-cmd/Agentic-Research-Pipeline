---
name: steward
description: How an agent drives its own PR in this repo's software factory - risk label, fix-loop limit, the blocked state for spec questions, and how many agent PRs may run at once. Use when opening, watching or fixing a PR, or when a spec or acceptance row looks wrong.
---

Repo rules for an agent that opens or drives a PR. They sit on top of the session's own PR rules and
never loosen them: no skipped tests, no history rewrites, and the agent never approves a PR and merges
only as `.claude/CLAUDE.md` (button mode) allows: a spec PR the owner's spec approval covers or, in a
test-writer session, its holdout PR. Code PRs are merged by the factory dispatcher or the owner, never by you.

## 1. Label the risk when you open the PR

Pick the highest tier any changed file falls in, add the label, and say why in one line of the PR body.

| Label | Files | What the owner does |
|---|---|---|
| `risk:low` | Only `docs/**`, `*.md` outside `.claude/`, frontend copy or styles (`*.css`, text-only `.tsx` edits) | Nothing if the dispatcher tracks it: it auto-merges once every gate is clean; else merges it on GitHub |
| `risk:normal` | Anything not low or high | Nothing if the dispatcher tracks it: it auto-merges once every gate is clean; else merges it on GitHub |
| `risk:high` | Auth, permissions, secrets; database schema or data migrations; money, portfolio weights or index maths; deleting stored data; `.github/workflows/**`, `.github/scripts/**`, `.gitleaksignore`; any file a session loads at start (`.claude/**`, `.claude-plugin/**`, `.mcp.json`) | Reads the acceptance matrix and the diff, then merges on GitHub |

A `risk:low` or `risk:normal` PR is merged without a tap by the factory dispatcher once every gate in
`.claude/CLAUDE.md` (auto-merge) is clean; else the owner merges it. Relabel `risk:high` if a later push
touches a `risk:high` path.

When unsure between two tiers, take the higher one. Never lower a label the owner set, nor below the
risk the factory's intake gave (your prompt names it).

When the PR implements a spec, put `Spec: <slug>` on its own line in the description (the spec file
name without date and `.md`), so the Holdout acceptance job runs that spec's hidden tests. You never
see those tests: a failure reads `<slug> AC-n: fail`; fix the behaviour the row describes.
When the PR builds one slice of a spec, add a `Rows: AC-1, AC-4` line under it naming the rows that
slice delivers, so hidden tests for later slices don't run yet. The last slice drops the line.
A PR that fixes a nightly failure puts `Holdout: full` and `Refs #<issue>` (the nightly issue) each on its
own line, so the full hidden suite runs before it merges. Its fix-round count starts at 0. The issue closes
on the next green full run on `main`, not by the PR. If `Holdout acceptance` skips because no app code
changed, start a manual `holdout.yml` run on the PR branch and link it in the PR; it must be green before
the merge.

## 2. Stop after three failed fix rounds

A round is one pushed fix for a failing check. After the third pushed fix on which the **same check**
is still red, stop pushing:

1. Comment on the PR, starting with `Blocked: fix limit` and stating, in at most 5 lines, the
   check, what you tried in each round, and your best guess at the cause.
2. Add the `factory:blocked` label and stop until the owner answers.

A different check failing, or the owner asking for another try, starts a new count.

Before the third fix round, write one line: what the failing check assumes, and whether the state it
checks is legitimate. If the premise is wrong, fix the premise, not the symptom. Repeat that line in the
`Blocked: fix limit` comment. Classify the failure first (this PR's, red on `main` too, or gone on one
re-run) and re-run at most once.

The third round is not yours alone. Before it, start a fresh session to diagnose: `create_session` on
this repo, `model: fable`, `permission_mode: auto`, title `fix diagnosis: PR #<n>`, prompt: *"Diagnose
the failing check `<check>` on PR #<n>. You did not write it. Two fixes failed: `<sha>` <one line
each>. Reproduce the failure, say what the check assumes and whether that state is legitimate, and
find the root cause. Don't push and never attach the holdout repo. Post one PR comment headed `Fix
diagnosis (factory)`: premise, cause with `path:line`, the smallest fix, and the command that shows
it. Then send one line to session `<your id>` with `send_message`."* Your third round applies that
diagnosis, or says in the PR why not. If `create_session` is unavailable, go on without it.

## 3. A wrong spec is a question, never a reinterpretation

If the spec or its acceptance table contradicts itself, is impossible, or can be read two ways that
change the result:

1. Don't guess and don't edit the spec or its `## Acceptance` table: those belong to the owner.
2. Comment starting with `Spec question:`, quote the row, and offer at most 3 concrete options, with
   the one you recommend first.
3. Add `factory:blocked`. Carry on only with the parts the question doesn't touch.

A bug report is a spec question first: check whether an acceptance row expected the behaviour before
changing code. If a fix PR for it already exists, verify it (run its failing-before test) instead of
writing a second one.

## 4. One item per PR

Don't fold an unrelated fix in, open its own PR or suggest it as a task.

## 5. Before the holdout and evaluator run

Merge `main` into the branch (a merge commit, never a rebase of someone else's branch) so hidden
acceptance tests and the evaluator see the code as it would land.
Once the PR is green, don't merge `main` in again just because `main` moved: that re-runs every check.
Merge it only for a real conflict, or when the owner or the dispatcher asks.

## 6. Review findings

In a `Code review (factory)` comment, fix or answer every finding under `blocking`: those are the
confirmed ones, and only confirmed blocking findings block. Findings marked `unverified, optional` may
be ignored or answered; they never justify `factory:blocked`.

## 7. Show the failure before the fix

Every fix PR pastes the failing-before output (command and result) in its description.
