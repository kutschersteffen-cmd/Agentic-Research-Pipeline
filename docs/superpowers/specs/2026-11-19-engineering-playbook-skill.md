# Engineering playbook skill and advisory function

Status: draft implementation for owner review; no installation or release approval implied.

Provide a repository-discoverable Codex skill, an optional adapter for the existing
Claude marketplace, and a standard-library Python function/CLI. The skill carries
the owner-approved operating preferences: AI agents, human design/release approvals,
V1–V8, independent hidden tests, mutation testing and a shared 900-second budget.

The executable helper reports local evidence readiness and accounts for elapsed
execution. It does not authenticate actors, prove CI truth, cancel remote jobs,
register an MCP tool, implement application fixes, merge, or deploy. Existing
factory/CI/deployment controls are not replaced. A missing invocation mode means plan.

Risk: high, because agent instructions and the plugin marketplace change. Human
merge ownership remains. Unit checks are used for this local helper because it
has no running-app endpoint and must not require attaching holdout to its builder.
Required independent review must identify remaining gaps before adoption.

## Deliverables and contracts

The canonical entry is `.agents/skills/engineering-playbook/SKILL.md`; Codex UI
metadata is `agents/openai.yaml` beneath it with implicit invocation disabled.
`references/playbook.md` defines V1–V8, human approval A/B and the 900-second policy.
`references/helper.md` is the normative CLI/JSON contract: it enumerates commands,
arguments, gate-specific record names, actor checks, permitted statuses and approval
binding. The executable is `scripts/workflow.py` under the same skill root. Its
pure public function is `evaluate_run(run, evidence, *, gate="merge", now=None)`;
`new_run`, `checkpoint` and `transition` accept an injected numeric `now` for
deterministic clock tests. No remote authenticity is inferred from local records.

The Claude adapter is `.claude/mods/engineering-playbook/.claude-plugin/plugin.json`
plus `commands/engineering.md`, registered in `.claude-plugin/marketplace.json`.
It explicitly reads the matching checkout's canonical skill, defaulting missing
mode to plan and never executing argument text as shell code. It is not a portable
hosted ChatGPT plugin. Usage/limitations live in `docs/ENGINEERING_SKILL.md`.

The ledger's clock uses elapsed wall seconds between checkpoints while running,
not worker-count multiplication. Paused time is persisted as reason/seconds on
resume. Backwards clocks and altered limits fail closed. Registration denotes an
active worker until `worker-end` removes it. A pause requires zero registered
workers; host-side verification of actual activity remains required.
The helper cannot measure agent reasoning, enforce remote deadlines, prove actor
identity or independently retrieve CI. Gate output always includes
`deployment_authorized: false`. The `release` gate means readiness to request
approval B; the `done` gate also checks its candidate/environment-bound reference.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | No ledger exists; task, implementer, two unique AC IDs, and lowercase 40- or 64-character candidate/spec SHAs are supplied | `init` runs | It exits 0 with parseable JSON containing `budget_seconds: 900` | unit |
| AC-2 | An existing ledger | `init` is repeated at the same path | It exits 2 with outcome `blocked` | unit |
| AC-3 | A ledger starts at injected time 100; two workers are registered at time 110 | `checkpoint(now=130)` runs | `used_seconds` is 30 | unit |
| AC-4 | A ledger has a registered active worker | CLI `pause --reason owner-approval` runs | It exits 2 with JSON `outcome: blocked` and leaves the ledger bytes unchanged | unit |
| AC-5 | A ledger starts at 100, pauses at 130, resumes at 1130 | `checkpoint(now=1140)` runs | `used_seconds` is 40 and `waits` is `[{"reason":"owner-approval","seconds":1000}]` | unit |
| AC-6 | Execution reaches 900 seconds | A complete evidence packet is evaluated | Outcome is `blocked` with zero remaining seconds | unit |
| AC-7 | Evidence omits, duplicates or adds an expected acceptance ID | The merge gate is evaluated | Outcome is `blocked` | unit |
| AC-8 | An owed holdout result is skipped, missing, not run or failed | The merge gate is evaluated | Outcome is `blocked` | unit |
| AC-9 | A control is recorded by the implementer | The merge gate is evaluated | Outcome is `blocked` | unit |
| AC-10 | All merge/release records defined in `references/helper.md` are complete, subject-bound and have non-builder actor IDs | `evaluate_run(gate="release")` runs without approval B | JSON contains `outcome: advisory-ready` and `deployment_authorized: false` | unit |
| AC-11 | Production evidence lacks candidate/environment-bound approval B | The done gate is evaluated | Outcome is `blocked` | unit |
| AC-12 | The package is added to the branch | Repository integration is inspected | No existing hook, CI workflow, deployment configuration or application source is changed | unit |
| AC-13 | An initialized running ledger exists | CLI `status` runs | It exits 0 with parseable JSON and non-decreasing `used_seconds` | unit |
| AC-14 | Skill files are inspected | Invocation and metadata are read | Missing mode defaults to plan and `allow_implicit_invocation` is false | unit |
| AC-15 | Bundled process is inspected | Required control rows are enumerated | Exactly one definition exists for each V1 through V8 | unit |
| AC-16 | A temporary state path does not exist | Helper is invoked with `deploy`, `merge`, `install` or `cancel-remote` as action | Each exits 2 without creating the state path | unit |
| AC-17 | Plugin manifest and auto-install hook are inspected | Auto-run components are enumerated | Manifest contains no hooks/MCP/LSP definitions and the auto-install hook does not name this plugin | unit |

Must not change: existing application behavior, auto-install hooks and CI/release authority (AC-12).
