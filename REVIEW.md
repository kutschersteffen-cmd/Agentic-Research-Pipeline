# Review instructions

Read by `/code-review` and any Claude review of a PR here. Findings advise; a human code owner
still approves.

## Passes

Run three passes and tag each finding with its pass.

- **Bugs.** Logic errors, broken edge cases, subtle regressions, resume/checkpoint breakage in the
  run store (`runs/<run_id>/results.jsonl` must stay append-only and resumable).
- **Security.** Injection, SSRF in the crawler (`net_safety.py` rules), secrets in the diff,
  anything that widens what the API exposes (there is no auth yet).
- **Compliance.** The change matches the spec and plan it came from (`docs/superpowers/specs`,
  `docs/superpowers/plans`), and keeps the repo's design rules:
  - The LLM plans, deterministic code computes. A number a user sees must not come from a model's
    arithmetic.
  - Every citation is re-verified against the source text (`arp/grounding.py`). A new extraction
    path that skips grounding is Important.
  - Standing agents propose and never apply.
  - Ratified frameworks and taxonomies are versioned, never edited in place.

## What Important means here

Reserve Important for a finding that would break behavior, leak data, drop an audit trail, or
breach one of the rules above. Style, naming and formatting are nits.

## Cap the nits

Report at most five nits per review and summarize the rest as a count.

## Do not report

Generated files, lockfiles, and anything CI already enforces (`ruff check .`, `npm run lint`,
`npm run build`, gitleaks, pip-audit, npm audit).

## Tests

A change that makes a failing test pass by editing the test is Important unless the test was
wrong, and the PR says so.
