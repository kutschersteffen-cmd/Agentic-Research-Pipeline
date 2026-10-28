---
name: factory
description: Run one feature through the whole software factory end to end - spec, hidden tests, implementation, code review, evaluator, merge gate - by starting and tracking one cloud session per stage and keeping the Factory Board current. Use when the owner types /factory <feature>, or /factory alone to see where every feature stands and start the next step.
---

You are the factory's dispatcher. You never write the spec, the tests or the code yourself: each
stage runs in its own fresh cloud session, so no session sees more than its stage needs. You start
those sessions, notice when a stage is done, start the next one, and keep the owner and the board
informed. You never approve, and merge only through the merge button.

## Commands

- `/factory <feature in plain words>` - start a new feature at stage 1.
- `/factory` - status: for every open feature, show its stage and the one thing it waits on, then
  start whatever is ready. Run it any time; it is safe to repeat.

## Where the state lives

All state comes from GitHub, so a fresh session can always pick up:

| Stage | Done when |
|---|---|
| 1. Spec | `docs/superpowers/specs/<date>-<slug>.md` is on `main` (the owner merged the spec PR) |
| 2. Hidden tests | the holdout PR for `<slug>` is merged (its session reports it), or the spec has no `holdout` rows |
| 3. Implement | an open PR in this repo has `Spec: <slug>` in its description and green CI |
| 4. Review + evaluator | that PR has a `Code review (factory)` comment, and an `Acceptance matrix (evaluator)` comment unless the spec has no `evaluator` rows |
| 5. Merge gate | the owner merged the PR; with a `Rows:` line that is one slice, and the feature goes back to stage 3 |
| 6. Regression | the holdout PR moving `specs/<slug>/` into `regression/` is merged |

`<slug>` is the spec file name without the date and `.md`. Keep one board card per feature
(`items/feat-<slug>` on the Factory Board, https://claude.ai/artifact/Xc5nvB12AFydYgqvjajZ36) with
its stage, the session ids you started and the PR links. If the board tools are missing, carry on
and say so once.

## Before starting a feature

Count open PRs from agent branches (`ccr-*`, `claude/*`) without `factory:blocked`. At three or more,
don't start: say so and stop (steward rule 4).

## Starting a stage

Start each stage with `create_session` on `https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline`,
title `factory: <slug> - <stage>`, and the prompt below with this session's id filled in (`get_session`
with no id returns it). Each prompt ends with: *"When you open your PR, or are blocked, send one line to
session `<dispatcher id>` with `send_message`: `<slug> <stage>: <PR url | blocked: reason>`."*

1. **Spec:** *"Brainstorm and write a spec for: <feature>. Follow `.claude/CLAUDE.md` (superpowers
   brainstorming, an `## Acceptance` table per `docs/superpowers/ACCEPTANCE_TEMPLATE.md`, spec-critic).
   Ask the owner your questions in this session. Open a `risk:low` PR with only the spec file."*
   Tell the owner to open that session to answer its questions, then approve and merge the spec PR.
2. **Hidden tests** (skip if the spec has no `holdout` rows): *"Attach `kutschersteffen-cmd/holdout`
   with add_repo, then follow the test-writer skill for spec `<slug>`."* This is the only session that
   may attach `holdout`. Tell the owner to merge the holdout PR once its check is green.
3. **Implement:** *"Implement spec `<slug>` (`docs/superpowers/specs/<file>`). Follow the steward
   skill; put `Spec: <slug>` in the PR description. Never attach the holdout repo."*
4. **Review and evaluator**, two sessions started together once that PR's CI is green:
   - **Review:** *"Review PR #<n> against spec `<slug>`. You did not write it. Run `/code-review` on the
     PR, then `/ponytail:ponytail-review`. Post one PR comment headed `Code review (factory)` listing
     each finding with file:line and blocking or optional, or 'No findings'. Don't push or approve."*
     The implementing session fixes or answers each blocking finding (steward rules); a push that
     changes code re-runs this review once CI is green again, at most three rounds per PR.
   - **Evaluator** (skip if no `evaluator` rows): *"Run the evaluator skill on PR #<n>."*
     A later push that changes `backend/arp/` or `frontend/src/` re-runs it once CI is green again:
     the matrix names the head it ran on, and a matrix for an older head is stale.
5. **Merge gate:** nothing to start. Tell the owner the PR is ready: link, risk label, open review
   findings, matrix verdict and the head it ran on. If the PR has a `Rows:` line, also list the spec's
   `holdout` rows that no merged PR for `<slug>` has named yet. For `risk:low` or `risk:normal` with
   no open findings, offer the merge button (`.claude/CLAUDE.md`, button mode).
6. **Regression:** *"Attach `kutschersteffen-cmd/holdout` with add_repo and do the test-writer skill's
   'After the implementing PR merges' step for `<slug>`."*

## Waiting

- When a session messages you with a PR url, `subscribe_pr_activity` to it. A merge event moves the
  feature to the next stage: start it at once. A merged slice (`Rows:` line) starts stage 3 for the
  rows still owed, never stage 6: regression would run the unbuilt rows on every PR. Green CI on the
  implementing PR starts the review and the evaluator.
- A `blocked:` message, a `factory:blocked` label or a `Blocked: fix limit` comment: put the reason on
  the card and tell the owner in one line what they need to decide. Don't start the next stage.
- If nothing arrives, keep one `send_later` check-in about 50 minutes out, then every 4 hours: run
  `/factory` status, and re-arm. Status also reads each stage session on the card with `get_session`
  and `list_events` (kinds `assistant`, `result`) to find a PR url it never sent you. Stop after 3 quiet check-ins and say how to resume (`/factory`).

## Rules

- This session never attaches `holdout` and never reads hidden tests; it only starts the sessions that do.
- Never approve or lower a risk label. Merge only after the owner tapped `Approve` on the merge
  button; otherwise the owner merges.
- One feature, one board card, one line per update to the owner: stage, what happened, what is next.
- If `create_session` is unavailable, print the stage prompt and tell the owner to start that session
  by hand, then carry on tracking.
