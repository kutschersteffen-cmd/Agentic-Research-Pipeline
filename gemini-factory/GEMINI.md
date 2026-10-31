# Factory rules

This repo builds features through a fixed pipeline: spec → hidden tests → implement → review →
evaluate → merge. Each stage runs in its own fresh chat, started with one `/factory:*` command.
`/factory` alone shows where each feature stands and which command to run next.
Follow these rules in every stage. Where they conflict with a general habit of yours, they win.

## Never

- Never merge, approve or close a PR. The owner merges on GitHub.
- Never read, open, fetch or ask about the holdout repo, unless the current stage is `/factory:tests`.
- Never edit a spec or its `## Acceptance` table outside `/factory:spec`. The owner owns them.
- Never delete, skip or weaken an existing test to make it pass. List every test change in the PR.
- Never push to `main`. Branch off `main` as `gemini/<slug>-<stage>`.

## Asking the owner

Ask one question at a time and end your turn. Approvals and yes/no questions offer exactly two answers,
**Approve** and **Not approved**, each followed by what it triggers. Choices offer one answer per
option, the recommended one first and marked (Recommended). The question must make sense on its own.

## Code

- Smallest working diff. Do only what the spec's rows need. No options, abstractions or "for later" code.
- Reuse what the codebase already has before writing anything new. No new dependency for a few lines.
- Don't touch adjacent code, comments or formatting. Remove imports and variables your change made unused.
- New non-trivial logic gets at least one test.
- Ambiguity that would change the result: ask one question first. Otherwise pick a default and say so.

## Pull requests

1. **Risk label**, the highest tier any changed file falls in, with one line in the PR body saying why:
   - `risk:low`: only docs, `*.md`, copy or styles. The owner merges once CI is green.
   - `risk:high`: auth, permissions, secrets, schema or data migrations, money maths, deleting stored data,
     CI workflows, `GEMINI.md`, `.gemini/**`. The owner reads the diff.
   - `risk:normal`: everything else.
   When unsure, take the higher tier. Never lower a label the owner set.
2. `Spec: <slug>` on its own line in the description, so the hidden-test job runs that spec. A slice of
   a spec adds `Rows: AC-1, AC-4` under it. Hidden-test failures read `AC-n: fail`. Fix the behaviour
   the row describes. Don't guess at the test.
3. **Fix limit.** A fix round is one push that tries to make red CI green or answer a blocking review
   finding. After three failed rounds, stop: comment `Blocked: fix limit` with what failed and what you
   tried (max 5 lines), add the `factory:blocked` label and end.
4. **Spec questions.** If a row looks wrong or reads two ways, don't reinterpret it. Comment
   `Spec question:`, quote the row, give at most 3 concrete options, add `factory:blocked`, and continue
   only with the parts the question doesn't touch.
5. **At most three** open PRs from `gemini/*` branches without `factory:blocked`. At three, don't open another.

## Board

`docs/factory/BOARD.md` has one row per feature. Every stage updates its feature's row when it opens a PR,
gets blocked or finishes: stage, PR link, one-line status. Commit that change on the stage's own branch.
