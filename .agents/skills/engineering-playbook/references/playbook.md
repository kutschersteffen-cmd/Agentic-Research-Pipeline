# Engineering Playbook — AI-led delivery

Version: 0.2 · Date: 2026-11-17 · Status: draft for owner review

## 1. Operating agreement

AI agents perform engineering work. The owner sets priorities and approves (A) requirements/design and (B) production releases. Routine planning within approved scope, implementation, testing, independent review, and staging verification proceed without repeated permission requests.

**Time constraint:** the entire automated process has a maximum execution budget of **15 minutes per PR**, including work to prepare that PR, implementation, verification and its attributable release work. The owner clarified that this covers agent and CI execution only; waiting for owner decisions and human user-testing sessions is recorded separately. Budget exhaustion stops the work and blocks completion; it never authorizes skipping required controls. The detailed clock and enforcement rules appear in section 5.

This document defines a proposed operating process. Creating it does not authorize application implementation, activate automation, change repository policy, or authorize a deployment. Application implementation remains paused while this process is defined.

Existing repository controls remain in force until deliberately reconciled and updated. In particular, the repository currently requires the owner to merge high-risk PRs. Consolidate that review into the release decision where practical, but do not silently remove or bypass it. Existing eligible low/normal-risk dispatcher merges remain subject to every repository gate. Merging and production deployment are separate events; any merge-triggered deployment must be identified before relying on this separation.

### Human approval A — requirements and design

The owner receives one reviewable packet: user problem and current evidence; proposed behavior and exclusions; user journeys and UI prototype where relevant; architecture/data/security decisions; numbered acceptance criteria; delivery slices; and risk, cost, and service dependencies.

Approval identifies the exact document revision. Changes to user-visible behavior, acceptance criteria, data-loss risk, permissions, external commitments, or approved cost limits return to this gate. Routine implementation choices within that agreement do not.

### Human approval B — production release

The owner receives one release packet identifying the exact artifact/commit and target environment, intended changes, acceptance evidence, unresolved issues, migration/backout instructions, health thresholds, verification window, and rollback conditions. Approval authorizes only that packet. A changed artifact or material release condition invalidates the approval.

Approval does not require another tap for the already-described deployment steps. It does not authorize unrelated changes. Missing approvals are not inferred from silence.

## 2. Roles and independence

| Role | Responsibility | Boundary |
|---|---|---|
| Owner | Priorities, requirements/design approval, release decision, business exceptions | Product and production authority remains human |
| Coordinator agent | Backlog, stage transitions, dependencies, assigned roles, evidence completeness, escalation | Cannot declare missing evidence passed or approve its own exceptions |
| Product/design agent | Discovery, specification, user journeys, UX prototype, acceptance criteria | Resolves material ambiguity with the owner before building |
| Implementer agent | Small scoped changes, developer tests, PR, technical documentation | Cannot approve its own work or edit independent tests to pass |
| Independent test/review agent | Acceptance tests, code review, adversarial cases, real workflow checks | Separate context from the implementation; conclusions grounded in evidence |
| Release/operations agent | Staging, release packet, approved deployment, monitoring and recovery | Cannot deploy a new production version without approval B |

Roles are responsibilities, not a requirement to run six agents on every task. Small changes may combine coordination and implementation. Verification of behavior remains independent of the implementer. Independent agents reduce shared assumptions but do not guarantee correctness: executable checks and observable outcomes remain necessary.

Use separate branches/worktrees for concurrent implementations. One agent owns a delivery slice; shared contract changes are sequenced by the coordinator. The existing private holdout arrangement remains isolated from implementing sessions. If a required independent role or service is unavailable, mark that gate blocked rather than letting the builder certify it alone.

## 3. End-to-end lifecycle

| Stage | Owner | Required result and exit condition |
|---|---|---|
| 1. Intake | Coordinator | One work item: affected user, problem, evidence, impact, classification, priority, dependencies, risk, and named owner. Check for duplicates and existing fixes. |
| 2. Discovery | Product/design | Inspect wiki, Graphify, source, runtime behavior and relevant user feedback. Verify inferred graph relationships against source. Record current behavior and unknowns. |
| 3. Requirements/design | Product/design + independent challenger | Exact acceptance criteria; exclusions and compatibility requirements; workflow/architecture decisions; failure behavior; applicable security, accessibility, performance and AI-quality targets. Independent specification challenge resolved; owner approval A recorded. |
| 4. Delivery/test preparation | Coordinator + verifier | Small independently reviewable slices, explicit dependencies, independent acceptance coverage, repeatable environment and representative data. Each additional verification control has a scope, owner, oracle, evidence and gate. No unspecified business decisions left to the builder. |
| 5. Implementation | Implementer | Branch from the approved base; scoped code and developer tests; failing-before evidence for fixes; required generated contracts; documentation and draft PR. Local checks pass. |
| 6. Independent verification | Verifier | Code/UX/security review as applicable; tests against acceptance rows; observed evidence from the running candidate. Confirmed blocking findings resolved on the current candidate. |
| 7. Integration/staging | Release agent | Test the integrated candidate and promote an identifiable immutable artifact to staging. Verify cross-feature workflows, real persistence, configuration, migrations and recovery. |
| 8. Release decision | Owner | Complete release packet and approval B for the exact candidate/environment. Required gates are green; accepted lower-risk exceptions have owners and due dates. |
| 9. Deployment/verification | Release agent | Deploy the approved artifact, perform smoke checks, compare health with the release thresholds, verify the production version, and record the result or execute the approved rollback. |
| 10. Operation/improvement | Coordinator + operations | Monitor, triage incidents, retain regression tests, update documentation, and review escaped defects. Feed corrective actions into the backlog. |

Work-item states: Proposed → Discovery → Awaiting design approval → Ready → Building → Verifying → Staging → Awaiting release approval → Deploying → Production verification → Done. Any state can become Blocked; record the reason, responsible party and next action. A rejected or withdrawn item is Closed with a reason, not Done.

### Definition of ready

A slice is ready when its approved acceptance rows, scope, dependencies, environment, test data, interfaces, verification responsibility and risk are explicit. Backend-only work does not need decorative UI prototypes. Significant workflow changes need a reviewable prototype before implementation.

Before automation starts, forecast the remaining execution against the 15-minute budget. Slice work early if the forecast cannot fit. Existing approved specifications, reusable test infrastructure and reference datasets may be used, but their creation time must not be hidden as unrecorded work on the same PR. An oversized request is not a promise to deliver an oversized PR within 15 minutes.

### Definition of done

All required criteria pass on the released candidate; mandatory independent reviews and the release evidence reconciliation are complete; documentation/runbooks are current; release approval is recorded; production smoke checks and the defined observation window pass; remaining lower-risk issues are explicitly accepted and tracked. Human usability evidence is present when the change requires it. At most 15 minutes of attributable agent/CI execution was used; time blocked and waiting is disclosed. A merged PR, green isolated tests, a screenshot, or a successful deployment command alone does not establish completion.

## 4. Specifications and evidence

Use the repository's stable acceptance IDs and Given/When/Then format. Each row describes an observable result with a named check method. Include regression behavior and settings that affect the outcome. Existing approved criteria are not rewritten to accommodate implementation failures.

Every work item connects request → specification → delivery slice → PR/commit → acceptance evidence → artifact → release → production result.

Each evidence record contains:

- Acceptance ID and expected result.
- Candidate commit/artifact, timestamp, environment, configuration and relevant data fixture.
- Actual steps or command, observed output, and accessible supporting logs/screenshots.
- Result: Pass, Fail, Blocked, Not run, or Not applicable with justification.
- Whether dependencies were real, simulated, or unavailable; verifier identity/session.

Evidence becomes stale when the tested behavior, artifact, configuration, or relevant dependencies change. Re-run affected checks; do not repeat unrelated checks without reason. Never label a simulated API test as end-to-end integration or a missing required check as success.

Screenshots establish visible state. Pair them with assertions and persistence/API checks when the claim concerns saved data or behavior. Reports must distinguish confirmed defects, unverified hypotheses, and usability recommendations.

## 5. Quality gates

Select checks by impact and dependencies, not just changed filenames. Before release, exercise the integrated critical paths even when a PR's narrow checks are green.

| Area | Required checks when affected |
|---|---|
| Build/contracts | Lint, type checking, build, API schema/client compatibility, clean reproducible setup |
| Behavior | Deterministic unit/component tests, independent acceptance tests, regression coverage |
| Persistence | Real Postgres integration; transaction boundaries, concurrency, idempotency, migration/backout behavior |
| Workflows | Browser checks with real services for the critical path; separate fixture-driven error/slow/empty-state tests |
| Authorization/security | Role boundaries, independent approval, input/file/network handling, secrets/dependency checks; threat review for high-risk changes |
| UX/accessibility | Primary task completion, keyboard/focus, understandable errors, draft recovery, WCAG 2.2 AA checks; human task validation for substantial redesigns |
| Performance | Representative data volume and explicit latency/resource targets; compare to a recorded baseline |
| AI behavior | Versioned model/prompt/configuration, golden dataset and predeclared quality thresholds, citation grounding, cost limits, provider-failure behavior |
| Operations | Smoke checks, monitoring, useful request/run IDs, backups/restoration, rollout and rollback verification |

For ARP, critical paths include extraction through review/publication; conflicting reviewer decisions; corrected normalized values; versioning/withdrawal; financial/portfolio calculations; saved drafts; cancellation/resume; and permissions. Model stand-ins keep deterministic tests repeatable; real-model evaluation is a separate gate with preapproved cost limits. Missing model credentials do not turn a required evaluation into a pass.

Use the existing risk classification as a minimum. Auth, financial calculations, migrations, deletion and engineering-control changes receive high-risk review. No unresolved P0/P1 issue may affect the release's supported workflows. Lower-priority exceptions require the owner's explicit recorded acceptance, mitigation, owner and due date. Safety-critical acceptance failures cannot be hidden as UI polish or test flakiness.

### Independent holdout acceptance tests

Hidden tests answer whether the implementation satisfies the approved behavior without allowing the builder to tailor its implementation to the verifier's assertions. Public requirements remain visible; only the independent test implementation and private fixtures are hidden. Hidden tests must not introduce requirements the owner never approved.

The test-writer works from the approved specification and baseline interfaces in a separate session, without the implementation branch. It creates versioned tests in the private `holdout` repository. The implementer cannot attach or read that repository or change its tests. This restriction also applies to shared context, logs and artifacts: merely using a different agent name is not separation. The owner retains visibility.

For a behavior-changing PR, the coordinator records `Spec: <slug>` and, for a slice, exactly its approved `Rows: AC-...`. The expected acceptance manifest is derived independently from the approved specification and slice assignment, not trusted solely from editable PR metadata. Missing, malformed or narrowed metadata must not bypass owed checks. Each expected row must execute exactly as planned, with no missing, duplicate or unexplained skipped rows.

Pin the application candidate, holdout commit, specification revision and environment in every result. Freeze test selection before evaluating a candidate. Test changes are reviewed separately; they do not silently turn a failing application candidate green. If an independent reviewer confirms the test or specification is wrong, record the diagnosis and correct the test through its own review. Business-behavior changes return to approval A. Never disclose the private test source as the default way to diagnose a failure.

Builder-facing results contain acceptance ID, expected public behavior, observed symptom and redacted diagnostic identifiers. They exclude private source, fixtures, credentials and unrestricted runner output. Owner/verifier diagnostics are retained separately with restricted access. Test execution infrastructure must prevent application code and untrusted PR changes from gaining the private-repository credential or reading private tests; separate sessions and log redaction alone are not a security boundary. Audit the existing runner design before claiming this isolation.

Run the PR's owed rows before merge. Run the full compatible regression suite nightly and against the integrated release candidate before approval B. Keep completed acceptance tests as regression coverage and keep their associated specification history. Missing credentials, unavailable services, runner errors, absent rows or incomplete execution are Blocked/Fail when coverage is required, never Pass. Docs-only changes may be Not applicable with an explicit dependency-based reason.

### Mutation testing: verification of test sensitivity

Mutation testing introduces controlled faults into an isolated test copy and checks whether tests detect them. It complements ordinary tests, hidden acceptance tests and browser review. A passing original suite is a prerequisite; mutation results from a broken baseline cannot establish test quality. Never mutate production, the release artifact or the developer's working copy in place.

An independent test-quality agent reviews results and selects additional fault probes for critical behavior. It may strengthen public tests in a test-focused change or ask the independent holdout writer for behavior-based coverage. The implementer must not weaken assertions, suppress meaningful mutants, or change business logic merely to improve a percentage.

Classify every generated result: detected fault; surviving fault; uncovered code; suspected equivalent mutant; invalid/compile-error mutant; timeout; or infrastructure error. A survivor is a lead for investigation, not automatic proof of an application defect. An equivalent-mutant exclusion needs independent justification and a recorded rationale. Review timeouts separately: a deterministic introduced hang can be meaningful, but an infrastructure timeout earns no detection credit.

Always report selection scope, candidate/test commits, tools and versions, generation/analysis counts, exclusions and reasons. Report mutation score together with uncovered and unanalyzed code. A run with zero analyzed mutants is Not evaluated, not 100%. Direct-import text matching alone does not establish complete test impact; use runtime coverage/dependency evidence and conservative selection where that evidence is incomplete.

Proposed rollout of gates:

1. Establish a complete, reproducible baseline and triage existing survivors. Make missing coverage and tool failures visible immediately; do not claim a global score from a selected subset.
2. Before high-risk merges, require targeted mutation checks plus explicit fault probes for the affected critical invariants: permission checks, independent approvals, financial calculations, publication/withdrawal and idempotency. No unaddressed meaningful survivor may violate those invariants. Keep nightly broader mutation runs.
3. For changed analyzable logic, use an initial 80% score floor, excluding only independently justified equivalent/invalid mutants. Apply this only after the toolchain baseline is validated. Critical fault probes still must be detected regardless of the aggregate score. Legacy untouched debt remains tracked separately; thresholds are not lowered by the implementer.
4. Include applicable mutation results and survivor dispositions in the release packet. No new human approval is needed for a normal passing run; a required gate that cannot be completed blocks release readiness.

The repository currently runs backend/frontend mutation workflows nightly and on high-risk PRs. Its scripts default `--min-score` to zero; the workflow does not set a higher threshold. The backend skips some modules and selects tests by import matching; the frontend also selects directly imported modules and counts mutation timeouts with killed mutants. The holdout workflow can succeed without the credential or without a `Spec:` selection. These are inspected configuration facts, not claims about which credentials or branch protections are currently installed. Reconcile these behaviors with the above rules in the process-adoption change, not by assuming a green GitHub badge proves execution.

### Additional verification controls — all included

All eight controls below are part of the process. Each work item records which acceptance rows they cover. Apply behavior-specific controls to affected behavior; an independent verifier must justify any Not applicable entry. A genuine Not applicable result is distinct from a required check that could not run. Reuse valid reference data, infrastructure and unchanged evidence when appropriate, while executing candidate-dependent checks against the actual candidate.

| ID | Control | Responsible role | Required evidence | Gate |
|---|---|---|---|---|
| V1 | Specification challenge | Independent verifier, separate from specification author | Counterexamples, ambiguities, omissions, conflicts and their dispositions, linked to acceptance IDs | Before owner approval A |
| V2 | Invariant/property and metamorphic tests | Independent test agent; implementer adds complementary developer tests | Named properties, generated cases, fixed seeds, minimized counterexamples, expected relationships and outcomes | Affected behavior before merge and on integrated release candidate |
| V3 | Independent calculation/reference checks | Independent test agent; independent reviewer validates the oracle | Versioned known-answer data or a separately derived reference, units, rounding/tolerance, provenance and comparison results | Consequential calculations before merge/release |
| V4 | Failure injection and recovery | Verifier with release/operations agent | Injected failures, concurrent operation history, before/after state, retry/restart results and consistency assertions | Affected transaction/workflow boundaries before release |
| V5 | Acceptance and evidence reconciliation | Evidence reviewer who did not create the submitted evaluation evidence | Approved expected-row manifest matched to actual results, candidate/test/spec revisions, omissions and expiry decisions | Before merge for owed rows and before approval B for release scope |
| V6 | Production and restoration verification | Release/operations agent, independently reviewed | Deployed artifact identity, approved smoke/synthetic results, health observations, restore/rollback drill results and measured recovery | Per deployment; restoration drills on adoption, relevant recovery changes and quarterly |
| V7 | Independence of expected answers | Independent reviewer | Oracle provenance, method of derivation, shared assumptions, separate test authorship and unresolved disagreements | Before accepting V2/V3, holdout, or AI-quality evidence |
| V8 | Human task-based usability validation | Product/design agent facilitates; representative analysts/approvers perform tasks | Task script, participants and relevant experience, completion/assistance, mistakes, time, recovery observations and findings | Substantial UX/workflow redesign before approval B; periodic quarterly reassessment |

**V1 — challenge the requirement, not just the implementation.** Probe approval disagreements, identity ambiguity, missing evidence, stale data, retries and backwards compatibility. Every material contradiction must be resolved before the builder receives an approved specification. The challenger does not silently choose business policy.

**V2 — properties must express domain rules.** For ARP: published versions increase even after withdrawal; disagreeing corrections never finalize as agreement; retrying a committed action does not duplicate it; valid portfolio outputs meet the specified weight constraints; and ungrounded data does not become trusted solely because a model labels it correct. Use state-machine and concurrent-operation tests where the invariant spans multiple actions. Metamorphic checks assert only relationships the approved domain permits, such as input-order independence for an explicitly order-independent aggregate. Preserve seeds and minimized failures as regressions.

**V3/V7 — verify the expected answer independently.** Reference calculations must not be copied from production implementation. Use reviewed worked examples or separately derived reference logic with traceable source data. Specify units, precision and tolerances in the acceptance criteria. A second model agreeing, or two suites sharing the same mistaken oracle, is not independent confirmation. Disagreement remains unresolved until diagnosed against the approved requirement; majority voting is not an oracle.

**V4 — inject failures in isolated environments.** Cover relevant failures immediately before and after commit, lost responses followed by retries, database disconnects, provider failures, worker termination, expired sessions and concurrent reviewers. Verify persisted state and audit events in addition to UI messages. Exercises must not affect real client data, place real votes, publish real facts or spend unapproved model credits. Any production synthetic action must be explicitly included in approval B, isolated and reversible.

**V5 — evaluate evidence completeness independently.** Reconcile every approved acceptance ID and slice with every expected executed row. Record Pass, Fail, Blocked, Not run and justified Not applicable separately. Reject stale commits, incomplete shards, absent artifacts, inaccessible evidence and simulated checks presented as real integration. A green job badge or a builder's self-attestation cannot substitute for the manifest. The release record covers all merged slices and the integrated candidate.

**V6 — verify both running software and recoverability.** Check the actual production artifact identity and approved critical-path synthetics. Define observation windows and measurable error/latency thresholds before approval B. Restore backups into an isolated environment and verify recovered data, permissions and application behavior; successful backup creation alone does not prove restoration. Measure recovery time and achievable data-recovery point against the approved recovery objectives. An unsupported or stale recovery claim blocks readiness for changes that depend on it. Continuous monitoring does not end when a PR closes, but any new PR-specific automated verification job still consumes that PR's budget.

**V8 — observe people completing tasks.** Use representative analyst/approver scenarios, neutral instructions and versioned task scripts. Define task-success and error thresholds in the approved specification before testing; do not adjust them after seeing results. Record unassisted and assisted completion separately, critical mistakes, abandoned tasks, elapsed task time and recovery behavior. Agent walkthroughs and accessibility scanners remain complementary; they cannot be labeled human usability validation. If participants are unavailable, the required human validation remains Blocked. Human session/approval waits do not consume the automation budget; agents' preparation, analysis and reporting do.

### Fifteen-minute automation budget per PR

The limit is **900 seconds of attributable agent/CI execution on the elapsed critical path**, not the sum of parallel agents' CPU minutes. Concurrent work counts once: three checks running together for four minutes use four minutes of the budget. This is an execution deadline, not a guarantee that any size of change can safely ship within it.

The clock starts with the first automated work undertaken specifically to prepare the PR; creating the PR later does not hide earlier implementation or specification work. It includes agent reasoning and tool execution, independent test writing/review, environment setup, builds, targeted holdout/mutation checks, staging and attributable deployment verification. Retries and fixes consume the same remaining budget. Shared release work is recorded against each included PR's release-stage elapsed budget; it is not left unattributed.

Record explicit owner-decision and human-usability waiting intervals separately. While another agent or CI job is still working on the PR, that elapsed work continues to count. Human approval resumes the same clock with its remaining balance. Infrastructure queues and externally blocked intervals are also disclosed separately from execution; do not count them as successful testing or conceal them in the execution metric. Total lead time is reported alongside execution time so a PR with ten minutes of execution and two days of waiting is never presented as a ten-minute end-to-end delivery.

Suggested maximum allocation, adjustable within the same total:

| Execution stage | Budget |
|---|---:|
| Intake, requirement/design preparation and independent challenge | 2 minutes |
| Implementation and regression-test preparation | 5 minutes |
| Independent review, CI, holdout, targeted properties/reference/failure checks and mutation analysis in parallel where independent | 4 minutes |
| Integrated staging checks and release evidence reconciliation | 2 minutes |
| Approved deployment and immediate production verification | 1 minute |
| Cancellation, recording results and contingency | 1 minute |
| **Total** | **15 minutes** |

Warm isolated environments, pinned dependencies, cached artifacts, reusable fixtures/oracles and test-impact selection are prerequisites for this target. The coordinator establishes fit before starting. Run independent checks concurrently only when their dependencies permit; acceptance evidence reconciliation waits for their actual results. All applicable control IDs remain represented in the evidence manifest.

The current repository has not been demonstrated to meet this target: the inspected backend mutation script allows 30 minutes per module, and holdout test jobs allow 45 or 60 minutes. Those are timeout ceilings, not measured runtimes. Process adoption must measure and optimize the required path, narrow slices without reducing acceptance scope, and enforce the shared budget before claiming compliance.

For extended human studies, observation periods or recovery exercises, record the waiting period explicitly. PR-specific agent/CI execution during those activities still counts. Pre-existing periodic drill results may be reused only when independently confirmed applicable and current; a changed recovery mechanism requires new validation. Full nightly regressions and broad mutation runs supplement required candidate-specific checks; moving a mandatory PR/release check to a later nightly run does not satisfy its gate or evade the deadline. A required check that cannot fit makes the slice unsuitable for completion within the budget.

The coordinator owns one shared deadline across all agents, jobs and workflow runs. Each worker receives the remaining allowance and has a timeout no greater than that balance. Before 14 minutes of execution, stop starting new work that cannot finish and use the reserved minute for safe cancellation, environment cleanup and evidence preservation. At 900 seconds the outcome must be either a verified completion or **Blocked — execution budget exhausted**. Never merge, deploy, mark Done or waive a required control just to meet the time limit. A PR already merged but not yet release-verified is not Done.

No rerun, additional agent or new workflow resets the budget. An oversized or exhausted item returns to scoping; closing and recreating the same work does not erase its recorded effort. Create genuinely smaller independently testable slices with explicit dependencies, preserve the original outcome and time spent, and obtain approval A again only when that rescoping materially changes the approved agreement. Any unavoidable exception to the 15-minute constraint must be negotiated with the owner as a changed requirement before continuing; agents cannot grant it themselves.

Add these fields to the PR/release evidence record: budget limit; execution used/remaining; first-work timestamp; parallel execution intervals; approval, human-testing and infrastructure waiting intervals; forecast; final outcome; and reason for every blocked check. Implement the shared timer and safe cancellation in the process-adoption change, not merely as a per-job `timeout-minutes: 15`, which could allow many sequential jobs to exceed the total.

## 6. Defects, incidents and escalation

Defects follow the same lifecycle, with proportional documentation. Start from a reproducible symptom and failing-before evidence; determine whether behavior violates an approved requirement. A material contradiction returns to the owner; preserve unaffected work.

Classify severity separately from change risk:

- P0: active severe outage, security compromise, or widespread data corruption. Immediate incident response.
- P1: major supported workflow blocked, incorrect consequential data, or broken permission/approval controls.
- P2: significant error or friction with a workable recovery path.
- P3: minor usability, copy, or cosmetic issue.

An incident record names the commander/coordinator, impact, timeline, current mitigation, and communication owner. Recovery may shorten design documentation, but a new production change still needs approval B. The release packet can preauthorize precise automatic rollback conditions for that release; otherwise request the owner decision. Never assume a code rollback reverses a destructive data migration: specify backup/restore or a forward-repair procedure.

After two failed fixes to the same check, obtain an independent diagnosis before a third attempt. After the third unsuccessful pushed fix, stop further pushes to that check and escalate, following existing repository rules. Classify product defects, environment failures and flaky tests separately. A flaky result stays visible until fixed or explicitly quarantined with replacement coverage, an owner and an expiry.

Escalate immediately for contradictory requirements, unexpected destructive operations, missing required verification, unapproved external costs, or release threshold failures. Do not start unrelated scope to compensate for a blocked item.

## 7. Rollout and operating cadence

Default cadence: continuous automated checks per PR; a daily coordinator summary while work is active; an owner-approved release when a candidate is ready; and a weekly review of incidents, escaped defects and workflow bottlenecks. Combine small related approved changes into a release packet without combining unrelated implementation concerns into one PR.

The daily summary states: completed outcomes, current stage per item, evidence gaps, blockers, next action, and decisions owed by the owner. No unnecessary status messages or repeated approvals for already-authorized work.

Track lead time, per-PR automation execution time (15-minute maximum), waiting time by cause, budget-exhaustion rate, deployment frequency, failed-change rate, production recovery time, escaped defects by severity, flaky-test rate and primary-task completion. These are improvement signals, not targets for agents to optimize by hiding failures or reducing coverage.

For the first adoption:

1. Review this playbook and reconcile it with existing factory/merge/deployment controls in one explicitly scoped process change.
2. Inventory every production deployment trigger; ensure production release approval cannot be bypassed by a merge, scheduled job or configuration change.
3. Establish repeatable development/staging environments, reference datasets/oracles, shared execution-budget tracking and evidence storage. Map V1–V8 to acceptance rows and close required holdout/mutation enforcement gaps. Keep baseline failures visible.
4. Pilot one bounded, already-confirmed defect through the entire process. Measure whether each handoff and gate works and whether agent/CI execution completes within 15 minutes before scaling up the redesign. A timed-out pilot is a recorded failure to meet the process target, not evidence that controls should be removed.
5. Review the pilot, simplify unnecessary steps, and version the playbook. Resume application work only after the process and the relevant work specification are approved.

## 8. Detailed Factory adoption backlog

Use this backlog to turn the operating agreement into scoped changes. The [Factory gap review](../../../../docs/FACTORY_PLAYBOOK_GAP_REVIEW.md) contains the original findings and their evidence. It reflects an earlier repository snapshot. Verify each item against the selected branch head, required checks and live deployment configuration before starting it. The row-parser correction from PR [#594](https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/pull/594) is already present at this test branch's base. The remaining items are proposals unless current evidence shows they have been implemented.

| ID | Change and likely files | Completion evidence |
| --- | --- | --- |
| F01 | Treat paths that can trigger compute deployment as high risk in the steward rules and repository conventions until F02 is effective. | A change on each deployment-triggering path takes the owner merge route. |
| F02 | Bind compute deployment to production approval B. Reconcile `.github/workflows/deploy-compute.yml`, the deployment environment and equivalent cloud-side triggers. | Test that merging a matching change does not deploy without authorization for the named artifact and target. Verify the actual environment protection or its approved equivalent. |
| F03 | Record the merged holdout revision before the dispatcher hands each applicable slice to the builder. Pin that revision in the Factory Board and builder handoff. | A builder stays blocked while an owed holdout is unmerged. An authorized new holdout revision triggers new evidence. |
| F04 | Make Holdout acceptance require a usable credential and a result for each independently derived owed row. Keep #594's strict row parser and fail closed on missing required tests or skipped results. | Retain parser regression cases. Missing credentials, invalid selections, empty owed results and unexpectedly skipped rows report blocked or failed. |
| F05 | Put private tests and the candidate runtime in separate execution environments with distinct identities and storage. Scope the test harness to the approved app interface. | Inspect the separation of jobs, identities, credentials and workspaces. Maintain independent holdout evidence and restricted result reporting. |
| F06 | Report mutation outcomes separately, including killed, survived, timed out and not evaluated. Apply the reporting rules in both mutation scripts. | A run with zero evaluated mutants reports not evaluated. Timeouts receive no credit. Counts reconcile to total scheduled cases. |
| F07 | Make the AI golden-set check block when a required evaluation cannot run. Set an explicit per-run cost ceiling. | A required run with missing credentials or insufficient budget cannot report a pass. |
| F08 | Reuse the shared change-impact calculation in Holdout acceptance. Review `.github/scripts/ci_changes.py` and the holdout workflow together. | Changes to app inputs treated as relevant by CI receive the corresponding holdout decision, including affected documentation inputs. |
| F09 | Extend the acceptance template and spec review for approval A. Record current user evidence, prototype or journeys where relevant, risk, dependencies, V1–V8 applicability and how expected results were derived. | The owner receives a packet tied to the approved spec revision. Explicit reasons cover inapplicable fields. |
| F10 | Record first work, counted agent and CI time, remaining balance and waits by cause on the Factory Board. Add a shared deadline across remote workers as orchestration is introduced. | One bounded run shows execution on the critical path separately from human and infrastructure waits. Expiry blocks progression without waiving a check. |
| F11 | Run one confirmed defect through the revised process and record gate outcomes, handoffs and the 15-minute execution budget. | Publish actual timings and every blocked check, plus the decision to iterate or expand the pilot. |
| F12 | Identify critical user journeys and add a small tagged browser suite in `backend/tests/e2e/`. Exercise saved results, error recovery and keyboard interaction. | Each selected journey has evidence against an integrated candidate, with its environment and dependencies identified. |
| F13 | Add axe checks to the selected browser journeys and explicitly record the WCAG 2.2 AA target in the specification. | Serious and critical automated findings fail the applicable check. The report identifies what automation covered. |
| F14 | Introduce visual regression and color-vision checks for selected critical journeys and charts. | A known visual change is detected, and baselines can be reviewed and updated as a separate change. |
| F15 | Build an acceptance manifest from the approved spec and slice, reconcile all results at the exact PR head, and surface proof and omissions to the owner. | Missing, duplicate, skipped or stale required evidence blocks progression. Legitimately inapplicable rows have an explicit approved reason. |
| F16 | Run the spec critic separately from the writer. Require example countercases, dispositions, and property or failure-injection rows where applicable. | Evidence names the independent challenger and shows how each blocking ambiguity was resolved before approval A. |
| F17 | Require a versioned reference and tolerance for consequential financial and index calculations. | A known-answer check states provenance, units, rounding and tolerance, and is reproducible independently of the implementation. |
| F18 | Evaluate terminology linting for UI copy and structured heuristic review for significant UI work. | The checks identify a seeded terminology or usability issue. Human task-based validation remains documented separately when applicable. |

### Test-branch implementation sequence

1. **Record a baseline.** Capture the factory revision, spec revision, candidate head, worker attempts, checks, owner decisions, elapsed time and available cost. Exercise the run recorder with a synthetic case and then one completed ARP run.
2. **Compare the dispatcher in shadow mode.** Version the stage rules and worker settings. Evaluate proposed transitions using saved events and compare them with the current factory across normal, blocked, stale-evidence and high-risk cases.
3. **Close the hard-gate gaps.** Prioritize F02 before granting any new production or merge authority. Build F03–F05 and F15 together as the independent acceptance path. Use F09, F10 and F12 to prepare the pilot.
4. **Replay and improve.** Pin a small suite of historical ARP tasks. Compare the baseline and a proposed factory change on the same tasks. Require acceptance evidence and an explicit owner rollout decision before applying the candidate. Use F11 to verify handoffs and the shared budget.

The [test-branch implementation spec](../../../../docs/superpowers/specs/2026-11-21-factory-improvement-loop.md) defines the delivery slices and the first acceptance criteria. Separate the deployment-control work from the observability prototype so the branch can be tested without production access.

## References

Repository foundation inspected: `.claude/CLAUDE.md`, `.claude/skills/factory/SKILL.md`, `.claude/skills/steward/SKILL.md`, `docs/superpowers/ACCEPTANCE_TEMPLATE.md`, and the CI/deployment workflows. These were inspected as existing policy, not invoked to launch agents or change GitHub.

UX references: [Nielsen Norman Group heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/), [WCAG 2.2](https://www.w3.org/TR/WCAG22/), and [GOV.UK error recovery](https://design-system.service.gov.uk/components/error-summary/). They guide acceptance criteria; claiming compliance still requires the relevant testing.
