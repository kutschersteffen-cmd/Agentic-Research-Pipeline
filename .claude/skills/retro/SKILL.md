---
name: retro
description: Weekly factory retro - read the last 7 days of PRs, CI failures, blocked items and reverts, log what went wrong, and propose at most three small rule changes in one PR. Use when the weekly scheduled task fires, or when the owner asks for a retro.
---

You look back over the factory's last 7 days and turn repeated failures into rule changes, so the
same mistake costs one week, not every week. You never merge, and you change rules only by PR.

## 1. Gather (GitHub tools, this repo only, last 7 days)

- **Merged and closed PRs:** for each, the number of pushed fixes after the first red check, and
  whether it carried `factory:blocked`, `tests-weakened-ok` or a `Blocked: fix limit` comment.
- **`Spec question:` comments:** the spec and row each one quoted.
- **Main guard:** `Revert <sha>` PRs and the issues it opened, and which merge broke `main`.
- **Failed CI runs on PRs:** group by job name; note the jobs that failed on three or more PRs.
- **Holdout and evaluator:** `<slug> AC-n: fail` lines in Holdout acceptance logs, and failing rows
  in posted acceptance matrices.

Never attach or read the `holdout` repo; the AC labels in the app repo's logs are all you need.

## 2. Log

Append one entry to `docs/FACTORY_RETRO_LOG.md` (create it if missing), newest first:

```
## <YYYY-MM-DD>
PRs merged <n> · fix rounds total <n> · blocked <n> · reverts <n> · spec questions <n>
- <finding, one line, with PR or run links>
```

At most 8 findings. Each names what happened, how often, and the link. No blame, no guesses
presented as facts.

## 3. Propose rule changes

Only for a pattern seen **at least twice** this week, or in this week and an earlier log entry.
At most 3 changes, each the smallest edit that would have prevented it, in one of:
`.claude/skills/**/SKILL.md`, `.claude/CLAUDE.md`, `docs/superpowers/ACCEPTANCE_TEMPLATE.md`.

- Never loosen a guard: no lower coverage bar, no higher fix limit, no fewer checks, no skipped tests.
- A fix that needs a workflow, hook or app-code change goes in the PR body as a proposal; don't edit
  those files.
- One-off failures go in the log only.

## 4. Open the PR

- Branch `claude/retro-<YYYY-MM-DD>` off `main`; PR against `main`, titled `Factory retro <date>`.
- Label `risk:normal` if it edits `.claude/`, else `risk:low` (see the steward skill).
- Body: the numbers line, then each rule change with the findings it answers.
- Nothing happened this week (no PRs, no failures): no PR; say so in the session and stop.
