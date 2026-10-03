---
name: show-me-your-work
description: Keep a reviewable decision trail for long-running or unattended work, one TSV row per decision (what, why, evidence, result). Use when asked, or for autonomous, multi-phase or overnight runs a human reviews later.
---

# Show me your work

Keep one append-only log so a reviewer can follow what was decided and check it.

## Format

A TSV file, one row per decision. Cells stay on one line. Evidence is a pointer, not prose.

Columns: `ts`, `phase`, `decision`, `why`, `evidence`, `result`. Start from `references/decision-log-template.tsv`.

- **evidence:** a commit SHA, PR number, `file:line`, or a path to an artifact. Never a paragraph.
- **result:** the outcome, such as `tests green`, `reverted`, `INCONCLUSIVE`, `open`.

Example:

```
ts	phase	decision	why	evidence	result
2026-10-03T09:02:00Z	frame	counted the affected modules first, about 12	wanted the size before starting	commit 3a9f1c2	found 2 open questions
2026-10-03T11:15:00Z	extract	kept the grounding check on the new path	every citation must be re-verified	commit 7c21e0a	tests green
```

## Logging a row

Write each row the way you would tell a teammate. Plain words, concrete actions.

Use `scripts/log.sh <logfile> <phase> <decision> <why> <evidence> <result>`. It stamps `ts`, writes the header on first use, strips tabs and newlines, and prefixes a leading `=`, `+`, `-` or `@` with a quote so a spreadsheet cannot run it as a formula. Use it when cells come from generated text, PR titles or filenames.

Log decision points and checkpoints, not every action: a fork chosen, a unit finished with its verification result, a pivot or revert and its trigger, a blocker, a gate fixed.

## Where it lives

A working artifact by default, not committed: `decisions.tsv` in the working directory, or `.audit/<task-slug>.tsv` when several efforts run at once. Commit it only when a reviewer needs the trail to trust the result.

## Rules

- Append-only. A wrong call gets a new row that supersedes it. Never edit or delete history.
- Before handing back, re-read the log against what actually happened. Add a row for any fork or abandoned approach that shaped the work but is missing. Correct the log with new rows, not by rewriting old ones.
- End the reply with a short "Attention" list: rows with weak or no evidence, checks skipped, choices that look risky in hindsight. "No flags" is a valid answer.

Review a trail top to bottom, follow the evidence pointers and spot-check. `column -s$'\t' -t decisions.tsv` renders it in a terminal.

Adapted from pstack (Lauren Tan, MIT). See `../PSTACK-LICENSE.txt`.
