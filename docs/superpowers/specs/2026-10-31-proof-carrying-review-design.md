# Proof-carrying review findings

Small change. Source: [ANTHROPIC_TESTING_PRACTICES_RESEARCH.md](../../ANTHROPIC_TESTING_PRACTICES_RESEARCH.md)
(Anthropic credits "write a proof that their finding is valid" for raising substantive review comments from 16% to 54%).

## Intent

A blocking review finding costs the implementing session a fix round. Today a finding blocks on the
reviewer's word alone. After this change it blocks only if it carries proof and a fresh agent that
did not write it confirms that proof.

## Goals

- Every blocking finding in a `Code review (factory)` comment carries one proof: a failing test or
  command with its output, or a file:line trace of the faulty path.
- Before posting, the review session hands each blocking finding (finding, proof, PR diff; not the
  reviewer's reasoning) to a fresh subagent that re-runs or re-reads the proof and answers
  `confirmed` or `not confirmed`.
- Confirmed findings stay blocking. Unconfirmed ones stay in the comment, marked
  `unverified, optional`, and the implementing session may ignore them.

## Non-goals

- No new factory stage or cloud session. No backend or workflow code.
- Optional findings need no proof and are not verified.
- The steward's three-round CI fix limit is unchanged.

## Anti-goals

- A real bug vanishing from the comment (hence demote, never drop).
- The verifier seeing the reviewer's reasoning (it would just agree).

## Approaches

1. **Verifier subagent inside the review session** (picked): one comment, edits only
   `factory/SKILL.md` stage 4 review prompt and `steward/SKILL.md`. Independence comes from a fresh
   subagent, as `/code-review` already does.
2. Separate verifier cloud session: more independent, but a new stage, more sessions, and an edited
   comment the implementer might read early. Rejected for cost.
3. Implementer verifies before fixing: the author judges its own review. Rejected.

## Decided

- Unconfirmed → `unverified, optional` (owner, 2026-10-31).
- Approach 1 (owner, 2026-10-31).

## Left to the builder

- Exact wording of the prompt text and the comment's finding format, within the rows below.

## Acceptance

Review output is AI output: each `evaluator` row is run once on a seeded PR, not retried until it passes.
`unit` rows are fixed-string checks on the skill files.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A PR with a seeded off-by-one error that a pytest test reproduces | The factory review session runs on it | The `Code review (factory)` comment lists that finding under `blocking` | evaluator |
| AC-2 | A PR seeded with a suspicious-looking but correct boundary check, covered by a passing test | The review session posts its comment | Any finding about that code is under the exact label `unverified, optional`, never under `blocking`; if no finding mentions it, the row is `not exercised` and the seed is reworked | evaluator |
| AC-3 | A comment whose only findings are `unverified, optional` | The implementing session reads it under the steward skill | It adds no `factory:blocked` label and no `Blocked:` comment because of them | evaluator |
| AC-4 | `factory/SKILL.md` after the change | Search the stage 4 review prompt | It contains the strings `Proof:` and `fresh subagent` | unit |
| AC-5 | A PR with no findings | The review session runs | One comment headed `Code review (factory)` containing `No findings` | evaluator |
| AC-6 | `factory/SKILL.md` after the change | Search stage 4 | It still contains `at most three rounds per PR` | unit |
| AC-7 | The same PR as AC-1 | The review session posts its comment | That finding has a line starting `Proof:` holding a command plus its output, or a `path:line` trace | evaluator |
| AC-8 | `steward/SKILL.md` after the change | Search it | It contains `only confirmed blocking findings` | unit |
| AC-9 | `factory/SKILL.md` after the change | Search the verifier hand-off in stage 4 | It contains `finding`, `proof`, `PR diff` and `not the reviewer's reasoning` (covers anti-goal 2) | unit |
| AC-10 | A PR seeded with 2 real reproducible bugs and 1 correct-but-suspicious boundary | The review session posts its comment | Both real bugs are under `blocking`; every finding the verifier received (per the review session transcript) appears in the comment (covers anti-goal 1) | evaluator |
| AC-11 | `steward/SKILL.md` after the change | Search section 2 | It still contains `Stop after three failed fix rounds` | unit |
| AC-12 | `factory/SKILL.md` after the change | Search the verifier hand-off in stage 4 | It contains `confirmed` and `not confirmed` as the verifier's only answers | unit |

Must not change: the comment heading and `No findings` (AC-5), the three review rounds (AC-6), the
steward CI fix limit (AC-11).
