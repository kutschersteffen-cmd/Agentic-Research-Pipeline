---
name: spec-critic
description: Critique a spec's acceptance table before the owner is asked to approve it - flags rows that aren't observable or exact, goals with no row, and wording a builder could read two ways. Use after writing or changing a spec in docs/superpowers/specs/, before asking for approval.
---

Run this in a **fresh subagent** that did not write the spec, so it reads the spec the way the
implementer will. Give it only the spec file and `docs/superpowers/ACCEPTANCE_TEMPLATE.md`; it may open the repo
files the spec names, for check 10.

## What it checks

For each row of the spec's `## Acceptance` table:

1. **Observable:** can someone outside the code see it (CLI output, API response, database row, UI)?
   "Calls X", "uses Y internally" fail.
2. **Exact:** does "Then" name values, counts, messages or status codes? "Works", "correctly",
   "fast", "handles errors" fail unless a number or message follows.
3. **One behaviour:** a row with "and" joining two outcomes should be two rows.
4. **Checkable as typed:** `holdout` rows must be deterministic. AI output (extraction, ranking,
   summaries) belongs in a `golden` row with a threshold, not an exact `Then`. `holdout` and
   `evaluator` rows drive the app started by `backend/scripts/e2e_stack.sh up`, so a "Given" that app
   cannot be in (a required setting unset, so it won't start; a file it reads only at startup) fails:
   make the row `unit`.
5. **Two readings:** write down any phrase two competent builders could implement differently, with
   both readings.

Across the spec:

6. Every goal and anti-goal is covered by at least one row.
7. Behaviour the change must not break has a "must not change" row.
8. No row tests something the Non-goals exclude.

Without the conversation that produced the spec:

9. **Fresh reader:** in two sentences, say what will be built and for whom. If you can't, or the
   spec's own summary says something else, that is a finding on the summary.
10. **Ready to build:** list every question a builder would have to ask before starting: a file,
    endpoint, setting or table the spec names that doesn't exist or doesn't match the repo; a default,
    unit or limit left open; an order of steps left open. Each question is a finding.

## Output

A table, one line per finding: `row or goal | problem | suggested rewrite`. Then one line:
`Ready for approval` when there are no findings, or `N findings, fix before approval`.

The critic never edits the spec. The spec's author fixes the findings and runs the critic again; the
owner sees the spec only once it reads `Ready for approval`, or with the open findings listed.
