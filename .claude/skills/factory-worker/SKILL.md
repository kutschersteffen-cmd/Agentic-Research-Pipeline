---
name: factory-worker
description: Build one approved GitHub issue (label claude) into a PR against main. Run by the hourly factory-worker Routine, or when the person types /factory-worker.
disable-model-invocation: true
---

You build at most **one** issue per run. Repo: `kutschersteffen-cmd/agentic-research-pipeline`.
Labels: `claude` (approved) → `claude-working` (yours) → `claude-pr-open` or `claude-needs-info`.
You never merge, and never work on an issue without the `claude` label.

## 1. Release stalled claims

List open issues labelled `claude-working`. For each whose claim comment ("Picked up by Claude") is more
than **3 hours** old and that has no open PR containing `Closes #<N>`: remove `claude-working`, add
`claude`, comment "Released after a stalled run."

## 2. Pick

List open issues labelled `claude`, oldest first. Skip any that also carry `claude-working`. None left →
end with `No approved issues`.

## 3. Claim

Re-read the issue's labels right before claiming; if `claude-working` appeared, go back to step 2.
Otherwise set the labels to drop `claude` and add `claude-working`, and comment
"Picked up by Claude: <session link>" (the link from `get_session` with no id).

## 4. Triage

Read the issue and its comments. Stop and ask instead of building when:

- there is no checkable "Done when" (a test, or a command and its expected output), or
- Size is L, or the change needs a new subsystem, an interface change or more than a day of work.

Then comment 1–3 concrete questions or a proposed split, swap `claude-working` → `claude-needs-info`,
and end with `Asked on #<N>`.

## 5. Build

1. `git fetch origin main && git checkout -B claude/issue-<N>-<short-slug> origin/main`.
2. Follow `CLAUDE.md`: test first (watch it fail), smallest change, `bash .claude/hooks/ensure-deps.sh
   <part>` before running tests by hand. The Stop hook checks your work before you can finish.
3. Run `/ponytail:ponytail-review` and `/code-review` on your diff; fix what they find.
4. Commit and `git push -u origin claude/issue-<N>-<short-slug>`.

## 6. Hand over

- **Checks pass:** open a PR against `main`. Body: what changed, the "Done when" evidence (command and
  output), any test changes listed, and `Closes #<N>`. Swap `claude-working` → `claude-pr-open` and
  comment the PR link on the issue. End with `Opened PR #<P> for issue #<N>`.
- **Checks still fail after a real attempt:** push anyway, open the PR as a **draft** with the failing
  command and its output, swap `claude-working` → `claude-needs-info`, comment what you need. End with
  `Draft PR #<P> for issue #<N>: <one-line blocker>`.

Do not wait for CI. One issue, then stop.
