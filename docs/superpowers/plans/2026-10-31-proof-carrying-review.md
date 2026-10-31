# Proof-Carrying Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blocking factory review findings carry a `Proof:` line and are confirmed by a fresh verifier subagent; unconfirmed ones become `unverified, optional`.

**Architecture:** Prompt-text change only: the stage 4 review prompt in `factory/SKILL.md` and one rule in `steward/SKILL.md`.

**Tech Stack:** Markdown skill files; checks are `grep -F`.

**Spec:** `docs/superpowers/specs/2026-10-31-proof-carrying-review-design.md`

## Global Constraints

- Keep `Code review (factory)`, `No findings` and `at most three rounds per PR` in factory stage 4 (AC-5, AC-6).
- Keep `Stop after three failed fix rounds` in steward section 2 (AC-11).
- Unconfirmed findings are demoted, never dropped.

## Review Focus

- A finding with proof the verifier can't run (needs Postgres, network): expect `not confirmed` → `unverified, optional`, not a crash or a silent drop. Covered by the prompt wording in Task 1 ("if the proof cannot be re-run or re-read, answer `not confirmed`").
- No blocking candidates at all: no verifier is spawned and `No findings` is still posted (AC-5).

---

### Task 1: Proof + verifier in review, steward rule

**Files:**
- Modify: `.claude/skills/factory/SKILL.md:73-77` (stage 4 Review bullet)
- Modify: `.claude/skills/steward/SKILL.md` (append section 6)

- [ ] **Step 1: Run the checks; expect the new strings missing**

```bash
cd .claude/skills
for s in 'Proof:' 'fresh subagent' 'PR diff' "not the reviewer's reasoning" '`confirmed`' '`not confirmed`' 'unverified, optional' 'at most three rounds per PR' 'Code review (factory)' 'No findings'; do grep -qF -- "$s" factory/SKILL.md && echo "ok  $s" || echo "MISSING $s"; done
for s in 'only confirmed blocking findings' 'Stop after three failed fix rounds'; do grep -qF -- "$s" steward/SKILL.md && echo "ok  $s" || echo "MISSING $s"; done
```
Expected: the first six factory strings, `unverified, optional` and `only confirmed blocking findings` MISSING; the rest ok.

- [ ] **Step 2: Edit factory stage 4 Review prompt**

Inside the quoted Review prompt, after the two review commands and before "Post one PR comment": every blocking finding needs a `Proof:` line (a failing test or command plus its output, or a `path:line` trace). Before posting, hand each blocking finding to a fresh subagent with only the finding, its proof and the PR diff, not the reviewer's reasoning; it re-runs or re-reads the proof and answers `confirmed` or `not confirmed` (proof it cannot re-run or re-read is `not confirmed`). Confirmed stays blocking; the rest are listed as `unverified, optional`, never dropped. Keep the existing heading, `No findings`, and "at most three rounds per PR" text.

- [ ] **Step 3: Append steward section 6**

`## 6. Review findings` — fix or answer only confirmed blocking findings in a `Code review (factory)` comment; `unverified, optional` ones may be ignored or answered, never count as a fix round, and never justify `factory:blocked`.

- [ ] **Step 4: Re-run Step 1's checks**

Expected: every line `ok`.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/factory/SKILL.md .claude/skills/steward/SKILL.md
git commit -m "factory review: proof-carrying findings with a fresh verifier"
```

Evaluator rows (AC-1, 2, 3, 5, 7, 10) are checked after the PR by the evaluator skill on seeded PRs; nothing to build for them here.
