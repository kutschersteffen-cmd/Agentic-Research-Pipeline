# Factory improvement loop

Status: testing branch prototype. This specification covers the delivery factory that changes ARP software.

## Current behavior

The dispatcher tracks delivery through GitHub and the Factory Board. Independent worker sessions, acceptance requirements, and review evidence are already part of the workflow. The retrospective records recurring issues manually. The prototype starts by collecting comparable evidence about how the workflow runs.

The [engineering playbook](../../../.agents/skills/engineering-playbook/references/playbook.md) defines the operating model. The [gap review](../../FACTORY_PLAYBOOK_GAP_REVIEW.md) documents the controls that adoption must address. The [AI Engineer talk](https://ai.engineer/code/2026/talks/zach-lloyd) motivates evaluating the factory configuration on repeated work.

## Delivery sequence

| Slice | Deliverable | Evidence to proceed |
| --- | --- | --- |
| 1. Local run record | Collect explicit stage events in a local SQLite ledger and render a timeline. Use a synthetic seed to exercise the first flow. | Reimport is idempotent, contradictory imports are atomic, and the report shows revision and evidence references. |
| 2. Historical baseline | Import a completed ARP run from authorized GitHub evidence. Add a versioned definition for routing decisions and compare proposed transitions with the current dispatcher in shadow mode. | Compare normal, blocked, stale-head and high-risk cases. Verify duplicate events and worker restarts preserve the decision history. |
| 3. Evidence gates | Pin the approved spec revision, acceptance manifest, PR head and holdout revision. Require complete current-head results. Isolate private test execution and verify deployment approval separately. | Missing or stale required results block progression. Production approval and branch protections are verified before any operational rollout. |
| 4. Replay and improvements | Freeze a small representative set of historical tasks and compare baseline and candidate variants. Record whether each factory change improves correctness, reviewer effort, cost or active execution time. | A draft factory improvement has linked failures, replay evidence and an explicit owner rollout decision. |

## Slice 1 scope

The owner asked for changes confined to a new test branch. This slice provides a standalone operator CLI and synthetic data. It stores supplied observations as evidence pointers and reports per-attempt outcomes. It does not establish the authenticity of imported observations. Live acquisition, the Board UI, workflow execution, validity of evidence at merge time, time-budget enforcement, and deployment changes belong to later slices.

The CLI takes a local normalized JSON Lines file and writes a new run ledger or appends to an existing one. The schema treats events as immutable. One run pins one factory commit even if the PR head changes during that run. Reuse of an event ID with different content is a conflict. Approval evidence and candidate identity should be included in their respective events when available. Costs are disclosed per finished attempt only when supplied. A reviewer can check the sample report against the fixture independently of the implementation.

## Acceptance

| ID | Given | When | Then | Checked by |
| --- | --- | --- | --- | --- |
| AC-1 | A synthetic run with an owner decision, a failed check, and a retry | Import and report | The timeline shows the factory SHA, ordered event records, latest state per stage, the approval and check references, and the distinct attempt IDs. | unit |
| AC-2 | An already imported event | Reimport the same content | The record count and report are unchanged. | unit |
| AC-3 | A batch with a new event followed by a conflicting event ID or factory revision | Import | The CLI reports a conflict and no records from that batch persist. | unit |
| AC-4 | One finished attempt with a supplied cost and another without it | Report | The reported attempt-cost subtotal includes only the known amount and lists the count of finished attempts with missing cost. | unit |
| AC-5 | A new or malformed input | Import or report | Unknown run IDs and malformed records produce clear errors. A malformed batch leaves existing records intact. | unit |

Slice 1 uses a synthetic fixture, independent structural assertions, and a real local SQLite database. It exercises retry and transaction rollback checks from V4 and traces results to the rows above. Production controls and independent holdout verification are outside this slice. A live run comparison and the playbook's 15-minute active execution measurement remain unmeasured.

