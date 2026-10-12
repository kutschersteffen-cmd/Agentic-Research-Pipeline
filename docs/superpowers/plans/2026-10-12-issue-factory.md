# Issue Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily scout proposes GitHub issues, the person approves with the `claude` label, an hourly worker builds one approved issue into a PR against `main`.

**Architecture:** Two project skills hold the instructions (`.claude/skills/factory-scout/SKILL.md`, `.claude/skills/factory-worker/SKILL.md`); two Routines start fresh cloud sessions that run them. GitHub labels carry all state; no code, no database.

**Tech Stack:** Claude Code skills (Markdown), GitHub Issues/labels via the GitHub MCP tools, claude-code-remote Routines.

**Spec:** `docs/superpowers/specs/2026-10-12-issue-factory-design.md`

## Global Constraints

- Labels exactly: `claude-proposed`, `claude`, `claude-working`, `claude-needs-info`, `claude-pr-open`.
- Scout: never edits code or pushes; at most **3** issues per run; never re-proposes an issue closed in the last 90 days.
- Worker: one issue per run; oldest `claude` issue first; branch `claude/issue-<N>-<slug>` from `origin/main`; PR base `main`; PR body contains `Closes #<N>`.
- Stalled claim: `claude-working` for more than **3 hours** with no linked open PR → back to `claude`.
- Issue template fields: What, Why, Done when, Size (S / M / L).
- Scout schedule `CRON_TZ=Europe/Berlin 17 5 * * *`; worker `0 * * * *`; both fresh-session Routines with push notifications.
- Nothing merges automatically. Routines are created only after this PR merges and the manual runs pass.

## Review Focus

1. Two worker runs overlapping (a run lasting over an hour) → the second must skip the issue already `claude-working`.
2. An issue the person labels `claude` that lacks "Done when" (written without the template) → worker asks, does not build.
3. The scout proposing something already fixed on `main` (stale deferred finding) → it must check current code before filing.
4. A closed-as-rejected proposal reappearing after a rename → match on file and symbol, not only title.
5. A worker run where the Stop hook keeps failing → draft PR plus `claude-needs-info`, never a normal PR with red checks.

Items 1, 2 and 5 are exercised in Task 3's manual run; 3 and 4 are checked in Task 2's manual run.

---

### Task 1: Issue template, labels, `CLAUDE.md`

**Files:**
- Create: `.github/ISSUE_TEMPLATE/claude-task.md`
- Modify: `.claude/CLAUDE.md` (new `## Factory` section after `## Checks`)

- [ ] **Step 1:** Write the template: front matter `name: Claude task`, `about: Work for the issue factory`, no default labels; body headings `## What`, `## Why`, `## Done when`, `## Size` (with the line `S: under an hour · M: a few hours · L: needs a spec`).
- [ ] **Step 2:** Add `## Factory` to `CLAUDE.md`, at most 8 lines: the five labels and their meaning in one line each; "the daily scout (`/factory-scout`) proposes, the person approves with `claude`, the hourly worker (`/factory-worker`) builds"; "don't work on an issue labelled `claude-working` by hand".
- [ ] **Step 3: Verify.** `wc -l .claude/CLAUDE.md` under 200; template renders (YAML front matter parses: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/ISSUE_TEMPLATE/claude-task.md').read().split('---')[1])"` exits 0).
- [ ] **Step 4: Commit** `docs: add issue template and Factory section`.

### Task 2: Scout skill

**Files:** Create `.claude/skills/factory-scout/SKILL.md`

**Interfaces:** Produces issues labelled `claude-proposed` with the four template headings.

- [ ] **Step 1:** Write the skill: front matter `name: factory-scout`, `description:` (when to use: the daily Routine, or the person typing `/factory-scout`), `disable-model-invocation: true`. Body = the spec's Scout section as numbered steps, plus:
  - Before filing, confirm the problem still exists in current `main` (read the file / rerun the check).
  - Duplicate check: search open issues and issues closed in the last 90 days by title words **and** by the file path and symbol named.
  - Ranking: red CI > security > correctness > debt > simplification.
  - Each issue body uses the template headings; "Done when" names a test or command.
  - End with a one-line summary: "Filed N proposals: #a, #b" or "Nothing to propose".
- [ ] **Step 2: Manual run.** In this session, follow the skill exactly. Expected: ≤3 issues, each labelled `claude-proposed`, each with the four headings; none duplicates another; each problem verified on current `main`.
- [ ] **Step 3: Manual re-run.** Follow the skill again immediately. Expected: "Nothing to propose" (or only new items) — no duplicates of step 2's issues.
- [ ] **Step 4: Commit** `feat: add factory-scout skill`.

### Task 3: Worker skill

**Files:** Create `.claude/skills/factory-worker/SKILL.md`

**Interfaces:** Consumes issues labelled `claude`; produces a PR with `Closes #N` and the label transitions in Global Constraints.

- [ ] **Step 1:** Write the skill: front matter `name: factory-worker`, `disable-model-invocation: true`, description as for the scout. Body = the spec's Worker section as numbered steps, plus:
  - Re-read the labels immediately before claiming; if the issue already carries `claude-working`, pick the next one (Review Focus 1).
  - Missing or uncheckable "Done when", or Size L → ask, don't build (Review Focus 2).
  - Gate failure path → draft PR, comment the failing command, `claude-needs-info` (Review Focus 5).
  - The claim comment includes the session link (`get_session` with no id).
  - End with a one-line summary: "Opened PR #X for issue #N", "Asked on #N", or "No approved issues".
- [ ] **Step 2: Manual run, empty queue.** With no `claude` issues, follow the skill. Expected: "No approved issues", no label or branch changes.
- [ ] **Step 3: Manual run, unclear issue.** Create a test issue without "Done when", label it `claude`, follow the skill. Expected: claim comment, then questions, label `claude-needs-info`, no branch. Close the test issue afterwards.
- [ ] **Step 4: Manual run, real issue.** The person relabels one Task 2 proposal (Size S) to `claude`; follow the skill. Expected: claim comment with session link; branch `claude/issue-<N>-…`; Stop hook passes; PR to `main` with `Closes #N`; label `claude-pr-open`; PR link commented on the issue.
- [ ] **Step 5: Commit** `feat: add factory-worker skill`.

### Task 4: Review and PR

- [ ] Run `/ponytail:ponytail-review` and `/code-review` on the branch diff; fix findings.
- [ ] Open the PR against `main`. Never merge locally.

### Task 5: Routines (after the person merges the PR)

- [ ] Create `factory-scout`: `create_new_session_on_fire: true`, prompt `/factory-scout`, cron `CRON_TZ=Europe/Berlin 17 5 * * *`, notifications push on, initiation `human_request`.
- [ ] Create `factory-worker`: same, prompt `/factory-worker`, cron `0 * * * *`.
- [ ] Verify with `list_triggers`: both enabled, `next_run_at` matches the schedule. Report the trigger ids and how to pause them.
