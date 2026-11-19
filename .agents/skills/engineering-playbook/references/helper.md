# Executable function and CLI

The skill orchestrates through the host agent. `scripts/workflow.py` is a Python
3.11+ standard-library helper for local accounting and conservative evidence checks.
It makes no network calls and never invokes a shell, edits application files,
reads private tests, merges a PR, installs hooks, or deploys.

## Function contract

`evaluate_run(run: dict, evidence: dict, *, gate="merge", now=None) -> dict`

The function is pure: it returns `advisory-ready` or `blocked`, a list of blockers,
used/remaining seconds and cleanup-reserve status without modifying either input.
It rejects stale candidate/spec references, a missing test revision, incomplete or
duplicate acceptance rows, missing controls/checks, builder self-verification,
unjustified not-applicable results, unfinished registered workers, paused execution,
missing approval references and an exhausted budget. Malformed inputs raise errors;
the CLI converts those errors to a blocked result and exit code 2.

`release` checks readiness to request approval B; it does not grant deployment
permission. `done` additionally requires an approval-B reference for the same
candidate/environment and recorded production verification. All gates require an
approval-A reference bound to the specification revision.

Local JSON is **untrusted evidence**, not an authenticated approval system. A
different actor string does not prove a person or independent agent approved
anything. The coordinator/verifier must retrieve and authenticate records through
the actual host/GitHub tools, validate artifact identity and test outcomes, and
enforce branch/deployment permissions externally. This package intentionally does
not replace GitHub Actions or a shared remote deadline governor.

## CLI

Run from the repository root, substituting full actual commit SHAs:

```sh
python .agents/skills/engineering-playbook/scripts/workflow.py init \
  --state .engineering-playbook/task-123.json \
  --task "Fix conflicting reviewer corrections" \
  --candidate-sha <candidate-sha> --spec-sha <approved-spec-sha> \
  --implementer builder-session-123 --rows AC-1 AC-2 \
  --spent-seconds <preparation-seconds-already-spent>

python .agents/skills/engineering-playbook/scripts/workflow.py status \
  --state .engineering-playbook/task-123.json

python .agents/skills/engineering-playbook/scripts/workflow.py worker-start \
  --state .engineering-playbook/task-123.json --worker ci-run-123

python .agents/skills/engineering-playbook/scripts/workflow.py worker-end \
  --state .engineering-playbook/task-123.json --worker ci-run-123

python .agents/skills/engineering-playbook/scripts/workflow.py pause \
  --state .engineering-playbook/task-123.json --reason owner-approval

python .agents/skills/engineering-playbook/scripts/workflow.py resume \
  --state .engineering-playbook/task-123.json

python .agents/skills/engineering-playbook/scripts/workflow.py check \
  --state .engineering-playbook/task-123.json \
  --evidence <independently-verified-evidence.json> --gate merge
```

Use `human-testing` or `infrastructure` for separately recorded legitimate waits.
Pausing requires no registered active worker. Validate the host really is idle;
the helper cannot discover unregistered remote work. Inactive time continues to
count until explicitly paused. Status/check checkpoint elapsed time. Reinitializing
an existing ledger, moving its clock backwards, changing its 900-second budget,
or resuming an exhausted ledger is rejected. Writer locks fail fast; after a crash,
inspect the process and ledger before manually removing a stale `.lock` file.
Use one trusted coordinator and private state storage. The helper does not prevent
an actor with filesystem write access from editing records or creating another file.

At 840 seconds the status includes `reserve_cleanup: true`. At or beyond 900,
the helper reports blocked. The host must use the remaining budget to set remote
job/tool timeouts and safely cancel jobs. Running this helper does not enforce
timeouts on external agents/CI or measure reasoning performed before initialization.

Exit code 0 means a valid ledger operation or advisory-ready check; exit 2 means
blocked, malformed input or budget exhaustion. It is never production authorization.

## Evidence format

```json
{
  "candidate_sha": "<full actual SHA>",
  "spec_sha": "<approved specification SHA>",
  "test_sha": "<pinned test-suite SHA>",
  "environment": "staging-or-production-name",
  "approval_a": {"actor": "owner-id", "subject_sha": "<spec SHA>", "source": "<authenticated approval reference>"},
  "approval_b": {"actor": "owner-id", "subject_sha": "<candidate SHA>", "environment": "production-name", "source": "<authenticated release approval>"},
  "acceptance": [{"id": "AC-1", "result": "pass", "actor": "verifier-id", "candidate_sha": "<candidate SHA>", "spec_sha": "<spec SHA>", "source": "<evidence reference>"}],
  "controls": {},
  "checks": {}
}
```

Each controls/checks entry uses the same result/actor/candidate/spec/source fields
as an acceptance result. `not_applicable` requires an independent actor and a
nonempty reason. Fail, blocked, skip, missing and not-run never pass.

| Gate | Cumulative required records |
|---|---|
| merge | Exact expected acceptance IDs; V1, V2, V3, V4, V5, V7; `ci`, `holdout`, `mutation`, `independent_review`; approval A |
| release | Everything above plus V8, `integrated_regression`, `recovery_readiness`, target environment |
| done | Everything above plus V6, `production_smoke`, approval B matching candidate and environment |

Applicability is decided by the approved specification and independently checked
manifest. The helper cannot infer whether a test name accurately describes a real
run, whether all shards executed, or whether a requested row set matches a GitHub
specification: V5 and authenticated CI must verify those facts. Never narrow `--rows`
or declare a check not applicable just to fit the deadline.

If the candidate/spec changes, retain the original ledger as history. Carry all
execution spent into the replacement candidate ledger with `--spent-seconds`,
independently verify a reference to the predecessor, and rerun affected evidence.
Do not reset a PR's allowance by changing candidates, files or workflow runs.
