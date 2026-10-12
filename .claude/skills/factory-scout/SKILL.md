---
name: factory-scout
description: Find candidate work in this repo and file it as GitHub issue proposals labelled claude-proposed. Run by the daily factory-scout Routine, or when the person types /factory-scout.
disable-model-invocation: true
---

You propose work. You never edit code, commit or push. Repo: `kutschersteffen-cmd/agentic-research-pipeline`.
The person approves a proposal by changing its label to `claude`; the hourly `/factory-worker` builds it.

## 1. Collect candidates

Go through the sources **in this order** (it is also the ranking) and apply step 2's filter as you go.
Stop collecting once 3 candidates survive: later sources rank lower and would not be filed. For each,
note a one-line problem, the file and symbol involved, and how to check it is fixed.

1. **CI on `main`**: the latest workflow run on `main` (`actions_list`). If any job failed, read its log
   (`get_job_logs`) and take the failing test or step.
2. **Security**: high or critical findings from `pip-audit` (backend) and `npm audit --audit-level=high`
   (frontend). Run `bash .claude/hooks/ensure-deps.sh backend` / `frontend` first.
3. **Deferred findings**: the "Known limits", "Deferred" or "Deferred minors" sections of PR descriptions
   merged in the last 30 days (`search_pull_requests` with `is:merged`).
4. **Debt**: `ponytail:` comments in the code (`/ponytail:ponytail-debt`).
5. **Over-engineering**: the top findings of `/ponytail:ponytail-audit`.

## 2. Filter

Drop a candidate when any of these hold:

- **Already fixed**: read the current file on `main` or rerun the check; the problem is gone.
- **Already tracked**: an open issue matches by title words **or** names the same file and symbol.
- **Already rejected**: an issue closed in the last 90 days matches the same way. Closed means rejected;
  never propose it again.
- **Needs a spec** (new subsystem, interface change, more than a day): keep it only as a Size L proposal
  that says so.

## 3. File at most 3 issues

Rank: red CI > security > correctness > debt > simplification. File the top 3 (fewer is fine), each with
`issue_write`, label `claude-proposed`, and this body:

```
## What
<the change, one or two sentences>

## Why
<the problem; quote the evidence: failing test, audit line, file:line>

## Done when
<a test name or command and its expected output>

## Size
<S | M | L> — <one line why>

_Proposed by /factory-scout._
```

Title: imperative, under 70 characters, naming the area (e.g. "Stop hook: select tests for `__init__.py` changes").

## 4. Finish

If nothing survives the filter, file nothing. End with exactly one line:
`Filed N proposals: #a, #b, #c` or `Nothing to propose`.
