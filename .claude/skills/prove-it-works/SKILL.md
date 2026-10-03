---
name: prove-it-works
description: Use after finishing a task and before saying it is done, fixed or passing. Verify against the real artifact (run the feature, read the actual value, inspect the diff), not a proxy, a self-report, or "it compiles".
---

# Prove it works

Check the real thing directly. Do not infer from proxies, from a subagent's summary, or from "it compiles".

**Why:** unverified work has unknown correctness. Indirect checks (file timestamps, a fresh-looking output file, a cached screenshot, an agent's report) feel cheaper than observing the source, and acting on a wrong inference costs far more.

- Read the actual value, not a cached or derived copy of it.
- Run the command and show its output. In this repo that means the commands in `.claude/CLAUDE.md`.
- When a check fails, suspect how you observed before you suspect the system.
- A test that would still pass if every function it imports returned `undefined` proves nothing. Assert a literal expected value.

## Script the check when you can

The strongest proof is a deterministic script that re-runs the same comparison. Write it, run it, and keep its output where a reviewer can re-run it. Commit it only when the work is large enough that the trail must be auditable later (see `show-me-your-work`).

Adapted from pstack (Lauren Tan, MIT). See `../PSTACK-LICENSE.txt`.
