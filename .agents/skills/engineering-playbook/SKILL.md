---
name: engineering-playbook
description: Run the AI-led engineering playbook for an explicitly requested task, or report its readiness, budget and verification evidence. Use for requests to run the engineering process, prepare a delivery plan, check a PR against the playbook, or prepare a release packet.
---

# Engineering playbook

## Invocation

Use `$engineering-playbook plan <task>`, `$engineering-playbook start <task>`,
`$engineering-playbook status <PR or ledger>`, `$engineering-playbook verify <PR>`,
or `$engineering-playbook release-check <candidate>`. These are agent instructions,
not newly registered MCP functions. An invocation without a mode means **plan**.
Do not start product implementation merely because this skill is installed or loaded.

First read [the canonical playbook](references/playbook.md), then
[the executable helper contract](references/helper.md). Repository instructions and
the user's existing authorization take precedence; do not replace `/factory` or
silently change protected branches, CI, deployment triggers or approval policy.

## Workflow

1. Resolve the repository, issue, approved specification and exact candidate SHA.
   Consult wiki/Graphify for navigation; verify inferred relationships in source.
   Check existing issues/PRs before creating duplicates. Use the host's connected
   GitHub tools for supported operations. Never attach the private holdout repo
   in an implementation session.
2. In **plan**, produce a reviewable scope/design packet with stable acceptance
   IDs, exclusions, CUJs, risk, delivery slices, V1–V8 applicability, independent
   test oracles, release/recovery targets and a forecast within 900 seconds.
   Run an independent specification challenge. Ask the owner only for material
   product decisions and approval A, referencing the exact specification revision.
3. In **start**, verify approval A through the host's authenticated conversation
   or GitHub record. Existing explicit user authorization may already cover it;
   do not ask again. Initialize the ledger at the first attributable work time,
   carrying forward any preparation already spent. Register background workers.
   Assign distinct implementer/verifier contexts using host delegation when
   available. If independent verification is unavailable, mark it blocked.
4. Build one bounded slice on a branch. Add failing-before regression evidence
   for fixes. Independent test writers prepare private holdouts from approved
   requirements, not from the builder's transcript. Keep test secrets, private
   code and unrestricted logs out of the implementation session.
5. Execute applicable checks in parallel within the remaining budget: build,
   types, unit/integration, holdout, properties/metamorphic checks, independent
   calculations, fault injection, mutations, code/security/accessibility review,
   and CUJs. Use real persistence for claims about transactions and saved data.
   Use Playwright/axe for automated UI checks; label mocks and screenshots accurately.
   Human usability validation is distinct from an agent walkthrough.
6. In **verify**, independently reconcile all expected acceptance rows and V1–V8
   with executed results on the exact candidate/spec/test revisions. Apply the
   helper's `evaluate_run` function to the evidence packet. It is a local advisory
   check, not proof that the records are authentic. Independently inspect every
   claimed external result; never convert a timeout, missing test or skipped
   required result into a pass. Fix within the same remaining budget. Obtain an
   independent diagnosis before the third failed fix; stop after three.
7. Prepare a PR against `main` with `Spec: <slug>`, approved slice `Rows:` when
   applicable, risk label, test results, evidence links, budget and limitations.
   Preserve existing high-risk owner-merge rules. Do not merge unless separately
   authorized by current repository/user rules. Creating a skill or a PR does not
   approve application changes or deploy them.
8. In **release-check**, verify integrated staging/full regression and recovery
   readiness, applicable human task validation, current evidence and immutable
   artifact identity. Produce approval packet B. Do not deploy without authenticated
   owner approval bound to that exact candidate and environment. Verify production
   after an authorized deployment, run only approved safe synthetics, and record
   recovery/rollback if required. Installing this package never deploys anything.

## Budget and authority

- 900 seconds total agent/CI execution per PR; parallel intervals count once.
  Register external workers before launching them and stop their records only
  after they finish. The coordinator's reasoning/tool time also counts.
- Pause for owner/human-testing waits only after registered workers are idle
  and independently checking the host's actual activity. Resume the same balance.
  Record infrastructure queue/wait time separately; do not hide execution there.
- Before 840 seconds, stop starting work that cannot fit. At 900 seconds safely
  cancel outstanding work and report **Blocked — execution budget exhausted**.
  No rerun, extra agent or replacement PR erases prior effort.
- The helper does not kill remote CI, monitor reasoning, authenticate approvals,
  guarantee a 15-minute completion, or enforce access separation. Host orchestration
  and GitHub controls must implement those boundaries. If missing, report them.
- Never weaken tests to meet time. If required full holdouts cannot fit, block
  and rescope; a nightly run cannot replace an owed release check.

## Output

Report task/issue/PR, current stage, candidate/spec revisions, verified outcomes,
failures, blocked/not-run checks, next action, execution used/remaining and human/
infrastructure waits. Attach acceptance evidence and disclose what was not checked.
For status requests, inspect records and report only; do not start or resume work.
