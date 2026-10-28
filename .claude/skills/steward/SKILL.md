---
name: steward
description: How an agent drives its own PR in this repo's software factory - risk label, fix-loop limit, the blocked state for spec questions, and how many agent PRs may run at once. Use when opening, watching or fixing a PR, or when a spec or acceptance row looks wrong.
---

Repo rules for an agent that opens or drives a PR. They sit on top of the session's own PR rules and
never loosen them: no skipped tests, no history rewrites, and the agent never approves or merges,
except a merge the owner approved with the merge button (`.claude/CLAUDE.md`, button mode).

## 1. Label the risk when you open the PR

Pick the highest tier any changed file falls in, add the label, and say why in one line of the PR body.

| Label | Files | What the owner does |
|---|---|---|
| `risk:low` | Only `docs/**`, `*.md` outside `.claude/`, frontend copy or styles (`*.css`, text-only `.tsx` edits) | Merges once CI is green |
| `risk:normal` | Anything not low or high | Reads the PR's acceptance matrix, then merges |
| `risk:high` | Auth, permissions, secrets; database schema or data migrations; money, portfolio weights or index maths; deleting stored data; `.github/workflows/**`, `.claude/hooks/**`, `.claude/settings.json` | Reads the acceptance matrix and the diff |

When unsure between two tiers, take the higher one. Never lower a label the owner set.

When the PR implements a spec, put `Spec: <slug>` on its own line in the description (the spec file
name without date and `.md`), so the Holdout acceptance job runs that spec's hidden tests. You never
see those tests: a failure reads `<slug> AC-n: fail`; fix the behaviour the row describes.
When the PR builds one slice of a spec, add a `Rows: AC-1, AC-4` line under it naming the rows that
slice delivers, so hidden tests for later slices don't run yet. The last slice drops the line.

## 2. Stop after three failed fix rounds

A round is one pushed fix for a failing check. After the third pushed fix on which the **same check**
is still red, stop pushing:

1. Comment on the PR, starting with `Blocked: fix limit` and stating, in at most 5 lines, the
   check, what you tried in each round, and your best guess at the cause.
2. Add the `factory:blocked` label and stop until the owner answers.

A different check failing, or the owner asking for another try, starts a new count.

## 3. A wrong spec is a question, never a reinterpretation

If the spec or its acceptance table contradicts itself, is impossible, or can be read two ways that
change the result:

1. Don't guess and don't edit the spec or its `## Acceptance` table: those belong to the owner.
2. Comment starting with `Spec question:`, quote the row, and offer at most 3 concrete options, with
   the one you recommend first.
3. Add `factory:blocked`. Carry on only with the parts the question doesn't touch.

## 4. At most three agent PRs in flight

Before starting a new item, count open PRs from agent branches (`ccr-*`, `claude/*`) that don't carry
`factory:blocked`. At three or more, don't start; say so and wait. One item per PR: don't fold an
unrelated fix in, open its own PR or suggest it as a task.

## 5. Before the holdout and evaluator run

Merge `main` into the branch (a merge commit, never a rebase of someone else's branch) so hidden
acceptance tests and the evaluator see the code as it would land.
