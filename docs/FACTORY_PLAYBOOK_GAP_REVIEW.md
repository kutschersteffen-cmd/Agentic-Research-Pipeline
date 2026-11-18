# Factory vs. Engineering Playbook v0.2: gap review

Date: 2026-11-18 · Status: review for the owner · Playbook: "Engineering Playbook — AI-led delivery", v0.2 (2026-11-17, draft)

This review compares the factory as it runs today with the playbook. It changes nothing. Like the
playbook itself, it authorizes no implementation, automation change, repository-policy change or
deployment. Every fix below is a **proposed change** for the playbook's adoption step (§7, item 1).

## What was inspected

| Source | Revision |
|---|---|
| App repo: `.claude/CLAUDE.md`, `.claude/skills/{factory,steward,test-writer,evaluator,spec-critic}/SKILL.md`, `docs/superpowers/ACCEPTANCE_TEMPLATE.md` | `main` at `47edcf9` |
| App repo workflows: `ci.yml`, `holdout.yml`, `mutation.yml`, `golden-set.yml`, `deploy-compute.yml`, `main-guard.yml`, `pr-guards.yml`; scripts `ci_changes.py`, `holdout_complete.py`, `backend/scripts/mutation_check.py`, `.github/scripts/mutation_frontend.py`, `backend/scripts/e2e_stack.sh` | `47edcf9` |
| Holdout repo: `README.md`, `run.py`, `.github/workflows/check-tests.yml`, folder layout | `main` at `2898398` |
| `arp-gcp` repo | `f010d58` (no workflows, one script) |
| Today's factory runs: app PRs #587–#592, holdout PRs #148–#150, `docs/FACTORY_RETRO_LOG.md` | GitHub, 2026-11-18 |

Not inspected: branch-protection settings and which checks are *required* (no API read of them),
installed secrets, GCP project configuration, Cloud Build triggers configured outside GitHub.

Severity scale used below:

- **Critical**: a required control can be bypassed silently, or production changes without approval B.
- **High**: a playbook gate does not exist, or "missing" can report as "pass".
- **Medium**: the control exists but is partial, manual or unrecorded.
- **Low**: wording, record-keeping or naming.

## Summary: the six gaps that matter most

1. **Merge can deploy to production without approval B (Critical).** `deploy-compute.yml` builds and
   deploys the Cloud Run services on every push to `main` that touches ingestion, compute, retrieval
   embedding/rerank, `schemas/common.py`, `pyproject.toml` or `scripts/gcp/**`. The dispatcher may
   auto-merge `risk:normal` PRs, and most of those paths are `risk:normal`. So an agent merge is a
   production deploy, with no release packet, no GitHub environment approval and no smoke check.
2. **Hidden-test isolation is not a security boundary (Critical).** In `holdout.yml`'s test job, the
   PR's own code is installed and started first (`e2e_stack.sh up` leaves `uvicorn` and `vite` running
   with `nohup`), and only then are the private tests checked out into `.holdout/` with
   `HOLDOUT_TOKEN`, in the same job and as the same OS user. Untrusted PR code can therefore read the
   hidden tests (and plausibly the checkout step's token from `/proc`). The playbook (§5) says separate
   sessions and log redaction alone are not a boundary and asks for exactly this audit.
3. **"Missing" or narrowed rows report as "pass" in the holdout gate (Critical).** `Holdout acceptance` is green when
   `HOLDOUT_TOKEN` is absent (warn and skip), when the PR has no `Spec:` line, when `Rows:` names rows
   that match no test (`run.py` treats that as "nothing to run"), and when a row's tests all *skip*
   (`run.py` counts `skip` as OK). The owed-row manifest is read from the editable PR body; only the
   dispatcher's manual gate 3 compares it to the spec, and owner-merged PRs get no such comparison.
   The `Rows:` parser also narrows silently: `sed 's/^Rows: *\([AC0-9, -]*\).*/\1/'` stops at the
   first character outside that class, so `Rows: AC-1 to AC-19` becomes `AC-1`, and
   `Rows: AC-1, AC-4, AC-7b, AC-8` becomes `AC-1,AC-4,AC-7` (reproduced locally). On PR #591 today,
   which carries `Rows: AC-1 to AC-19`, the own-rows run is reported to have run only AC-1 and passed.
4. **Builders started before hidden tests merged (High, seen today).** App PRs #590 (16:51 UTC),
   #591 (17:13) and #592 (17:43) were opened before their holdout PRs #148–#150 merged (20:39–20:42).
   The factory skill's table says stage 3 starts after stage 2 is done, but nothing enforces it, and
   the test selection is not frozen per candidate: a PR's result depends on holdout `HEAD` at run time.
5. **No staging, release packet, approval B, or production verification stage (High).** The factory
   ends at merge (stage 5) plus regression move (stage 6). Playbook stages 7–9, V6 and the definition
   of done (released candidate, smoke checks, observation window) have no counterpart.
6. **No execution budget (High).** Nothing measures or limits per-PR agent/CI time. Timeout ceilings
   are 45 min (holdout own rows), 60 min (shards), 30 min per module (mutation), 30 min (evaluator).
   Today's three features each took several hours of elapsed time; agent execution time is not recorded.

## Section-by-section review

### §1 Approvals A and B

| Topic | Factory today | Gap | Sev. | Smallest change that closes it |
|---|---|---|---|---|
| Approval A, packet | Spec session writes `docs/superpowers/specs/<date>-<slug>.md` with decisions first, `## Acceptance`, `## Slices`; spec-critic runs; owner taps `Approve` on a question showing the spec and the PR head SHA, which also merges the spec PR. | Exact-revision approval is good. Packet lacks required sections: current evidence of the user problem, user journeys/prototype (for workflow changes), security/data decisions, risk, cost and service dependencies. | Medium | Add those headings to `ACCEPTANCE_TEMPLATE.md` (or a spec template) and a spec-critic check that they are present or marked N/A with a reason. |
| Approval A, re-entry | Steward §3: a wrong spec is a `Spec question:` + `factory:blocked`; builders never edit the table. | No rule that a *change* to user-visible behaviour, acceptance rows, permissions or cost after approval sends the spec back to approval A; spec PRs after approval are ordinary edits. | Medium | One rule in CLAUDE.md: any later diff to an approved spec's Acceptance/Slices/decisions needs a fresh owner `Approve` on its new SHA. |
| Approval B | Does not exist. `risk:low`/`risk:normal` PRs auto-merge on dispatcher gates; `risk:high` PRs are merged by the owner on GitHub. | Merge is treated as the end. Merges that touch deploy-compute paths deploy immediately (see Summary 1). | Critical | (a) Put `deploy-compute.yml` behind a GitHub Environment `production` with the owner as required reviewer, so the deploy waits for approval B; (b) until then, add the deploy-compute paths to the steward `risk:high` row so no agent merges them. |
| High-risk merge by owner | Kept; dispatcher never merges `risk:high`. | Matches "do not silently remove". The playbook wants it folded into the release decision "where practical". | Low | Leave as is until approval B exists; then decide whether the owner's merge tap and the release tap become one packet. |

### §2 Roles and independence

| Role | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Coordinator | Dispatcher session (factory skill); in project threads, the project coordinator starts stage threads because threads have no `create_session`. | Dispatcher can mark gates passed from comments it reads; the skill requires it to verify reviewers' own session events, but in project threads it can only see `message_thread` lines, so that check degrades to trusting a message. | Medium | Record in the board card which evidence each gate was judged on (comment URL + head SHA + sender thread). |
| Product/design | Spec session (`fable`), superpowers brainstorming. | Fine for specs. No UX prototype step for workflow changes. | Low | Covered by the approval A packet change. |
| Implementer | Builder session; never attaches `holdout`; steward rules; `No tests removed` guard. | Matches. | – | – |
| Independent test/review | Code review, security review, UI review, evaluator, evidence review, test-writer, each a fresh session. | Fresh sessions, but shared channels exist: in project threads every thread shares project memory and `/mnt/project-files/`. A test-writer can write hidden-test details to shared memory that a builder later recalls. The playbook names shared context, logs and artifacts explicitly. | High | Rule for the test-writer and evidence reviewers: never write test content, assertions or fixture values to project memory or project files; and a memory-hygiene check in the test-writer skill. Longer term: run test-writer threads in a separate project. |
| Release/operations | None. | No role owns staging, release packet, deployment, monitoring or rollback. | High | Add a release stage to the factory skill (see §3) owned by a separate session. |
| "Blocked, not self-certified" | Evaluator: unclear = fail; evidence review: missing evidence = fail. | Holdout and golden gates instead pass when their service/credential is missing (see §5). | High | See §5 changes. |

### §3 Lifecycle stages

| Playbook stage | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| 1 Intake | Stage 0 intake session: `GO` / `NEEDS-INFO` / `REJECT`, risk, size S/M/L. | Close match. Missing: affected user, evidence, priority, named owner, duplicate-fix check is present. | Low | Add those fields to the intake answer format. |
| 2 Discovery | Part of intake + spec brainstorming (wiki, graphify, notes). | No recorded "current behaviour and unknowns" section; graph INFERRED edges are checked by rule in CLAUDE.md. | Low | Spec template heading "Current behaviour (verified)". |
| 3 Requirements | Spec + spec-critic + owner Approve. | spec-critic is a subagent of the spec author's session (V1 gap below). | Medium | See V1. |
| 4 Delivery/test prep | `## Slices`; stage 2 hidden tests. | No readiness check before stage 3: today builders started before hidden tests merged; no forecast against the 15-minute budget; environment/test-data readiness is implicit. | High | Factory skill: stage 3 starts only when the holdout PR for the slug is **merged** and its merge SHA is written on the board card; the builder prompt carries that SHA. |
| 5 Implementation | Builder, steward, CI, Stop hook. Failing-before evidence required for fixes (steward §7). | Matches. Draft PR not required. | Low | – |
| 6 Independent verification | Code/security/UI review with verified `Proof:`; evaluator; evidence review; holdout own rows. | Mostly matches. Evidence review covers `evaluator` rows only, not holdout/unit/golden rows (V5 gap). | Medium | See V5. |
| 7 Integration/staging | None. E2E job runs on the PR build; `main` CI after merge; Main guard reverts red `main`. | No immutable artifact, no staging environment, no integrated-candidate run before release. | High | First step: tag the merge commit and run the full holdout suite (`Holdout: full`) plus E2E on it as the "release candidate" run. |
| 8 Release decision | None. | No release packet, no approval B. | High | Release packet template (artifact SHA, environment, changes, evidence links, migration/backout, health thresholds, window, rollback conditions) and an owner `Approve` tap on it. |
| 9 Deploy/verify | Deploy-compute deploys on merge, no smoke check, no version check. | No smoke checks, no production version verification, no rollback. | High | Add a post-deploy step that calls each Cloud Run service's version/health endpoint and compares `parser_version()` to the tag. |
| 10 Operation | Nightly holdout full run with issue on failure; Main guard; weekly retro. | Retro covers escaped defects partially. No incident record. | Medium | See §6. |
| States | Board card stages 0–6 + `waiting:` text. | Playbook states (Awaiting design approval … Production verification, Blocked with reason/owner/next action, Closed vs Done) are not modelled; a merged PR is treated as done. | Medium | Map board stages to playbook states; add `Closed` and `Blocked(reason, owner, next)` fields. |
| Definition of done | Merge (or last slice merged + regression move). | Playbook: released, smoke-checked, observed, budget reported. | High | Follows from stages 7–9. |

### §4 Specifications and evidence

| Topic | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Stable IDs, Given/When/Then | `ACCEPTANCE_TEMPLATE.md`: stable IDs, never renumber, strike to retire, settings in Given, regressions as rows. | Matches. | – | – |
| Traceability chain | Spec → slice (`Rows:`) → PR (`Spec:`) → holdout result lines → merge. | Stops at merge: no artifact, release or production result. Holdout result does not record the spec revision. | Medium | Holdout setup prints spec file SHA (`git rev-parse HEAD:docs/superpowers/specs/<file>`) next to the holdout commit. |
| Evidence record fields | Evaluator matrix: head SHA, row, result, screenshot/text evidence; evidence page artifact. Holdout: `<folder> AC-n: pass\|fail\|skip`. | Missing: environment/config, data fixture, real vs simulated dependency, verifier identity, Blocked / Not run / N/A as distinct results (holdout has only pass/fail/skip; skip counts as pass). | High | Holdout: treat `skip` as `fail` for owed rows (or require an explicit `N/A` marker with reason). Matrix: add columns "Dependencies (real/stand-in)" and "Verifier session". |
| Staleness | Matrix names its head; a later app-code push re-runs the evaluator. Code review re-runs on a code push. | Holdout runs against holdout `HEAD`, which can change between runs on the same app head (no freeze). | Medium | Pin the holdout commit per PR on first run (store it as a PR comment/label) and re-use it; a newer holdout commit needs a deliberate re-run. |
| Simulated vs real | Stand-ins (`ARP_STANDINS_DIR`) used for holdout and evaluator. | Not labelled in results: a stand-in run reads the same as a real integration run. | Medium | Add `standins: on/off` to every result header. |

### §5 Quality gates

| Area | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Check selection | `ci_changes.py` by filename rules, safe default for unknown paths; `holdout.yml` skips on its own simpler rule (all under `docs/`, `.claude/` or `*.md`). | The two rules disagree: `docs/decision-studio/**`, `docs/transition_barrier/**` and `docs/INSTALLATION.md` run backend CI (backend tests read them) but skip the holdout gate. Playbook asks for selection by impact and dependencies. | Medium | Make `holdout.yml` call `ci_changes.py` (`app=true`) instead of its own awk rule. |
| Persistence / workflows | Real Postgres + Neo4j in CI, holdout and E2E. | No migration/backout, concurrency or idempotency checks as named gates. | Medium | Covered by V2/V4 rows in specs that touch those areas. |
| Security | gitleaks, dependency audit + SBOM, Trivy, security review for `risk:high` paths. | Matches for code; holdout runner isolation unaudited (see holdout below). | – | – |
| UX/accessibility | UI review with `/impeccable:impeccable audit` on frontend changes. | No WCAG 2.2 AA check named; no human task validation (V8). | Medium | Add axe-core run to UI review; V8 below. |
| Performance | Retrieval recall job; no latency/resource baselines. | No recorded baselines. | Low | Out of scope until a spec needs it. |
| AI behaviour | Golden-set CI on AI paths; Anthropic key, Gemini fallback. | Without `ARP_ANTHROPIC_API_KEY` (and no Gemini key) the job **warns and passes**; transition-barrier golden is warn-only. No cost limit recorded. Playbook: missing credentials do not turn a required evaluation into a pass. | High | Golden job fails (Blocked) when a required evaluation cannot run; a declared cost ceiling per run. |
| Risk classification | Steward table; `risk:high` for auth, migrations, money, deletion, workflows, session-loaded files. | Matches the playbook's minimum. Deploy-triggering paths are not `risk:high`. | Critical | Add deploy-compute paths to the `risk:high` row (interim until approval B). |

#### Holdout rules

| Playbook rule | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Test-writer works from approved spec + `main`, separate session | test-writer skill; only session that attaches `holdout`; holdout CI checks `new` fails and `keep` passes on `main`. | Matches. | – | – |
| Implementer cannot read hidden tests (infrastructure boundary) | Session attach rules + log filtering (`run.py` prints only result lines). | PR code runs in the same job before `.holdout/` is checked out with the token; its background server can read `.holdout/`. | Critical | Split the job: start the PR app in a separate container/job (or a service container) that has no access to the workspace, and run the hidden tests from a job that never executes PR code; or at least check out holdout into a directory owned by a different user before starting the app. Needs a design spec (risk:high). |
| Manifest derived independently, not from PR metadata | `Spec:`/`Rows:` from PR body; dispatcher gate 3 compares by hand for auto-merge. | CI trusts the body; owner-merged PRs have no comparison; `Rows:` matching no test → 0 rows → green. The parser truncates ranges (`AC-1 to AC-19` → `AC-1`) and suffixed IDs (`AC-7b` → stops the list at `AC-7`), so narrowed metadata passes (PR #591). | Critical | Reject any `Rows:` line the parser does not consume completely (fail, don't truncate); then a CI step: read the spec's `## Slices` table and the holdout `specs/<slug>/` row list; fail if `Rows:` is not exactly one slice or if any owed `holdout` row has no test. |
| No missing/duplicate/skipped rows | Full runs: `holdout_complete.py` checks every row exactly once. Own-row runs: result-line count must equal `--count`. | `skip` passes; an own-row run with 0 owed rows passes. | High | `run.py`: `skip` is a failure in non-`--check-new` mode unless the test carries an explicit N/A reason. |
| Missing credential = Blocked | No `HOLDOUT_TOKEN` → warning, job green. Today: HOLDOUT_TOKEN returned 404 from ~16:45 UTC and APP_TOKEN was empty; both renewed ~20:30 UTC. These failed red (good) only because the token was *present but invalid*. | An *absent* token silently passes. | High | Fail `Holdout setup` when the token is absent and the PR changes app code. |
| Pin candidate, holdout commit, spec revision, environment | Holdout commit pinned within one run and printed. | Spec revision and environment not printed; selection not frozen across runs. | Medium | See §4. |
| Full regression nightly and on the release candidate | Nightly full run (6 shards) with issue on failure; `Holdout: full` opt-in on PRs; "showcase freeze" manual run. | No release candidate run (no release stage). | Medium | Part of stage 7. |
| Builder-facing results redacted; owner diagnostics separate | Builders see only `AC-n: fail`; no separate restricted diagnostics store. | Owner has no restricted full-output path; diagnosing a hidden failure means opening the private repo by hand. | Low | Upload unfiltered output as an artifact readable only via a holdout-repo workflow. |

#### Mutation testing

| Playbook rule | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Runs nightly and before high-risk merges | `mutation.yml`: nightly on files changed in 26 h; PRs labelled `risk:high`. | Matches the trigger. Whether it is a *required* check is not verified. | Medium | Confirm in branch protection. |
| Threshold | `--min-score` defaults to 0; the workflow passes none. | No floor; playbook proposes 80% on changed analyzable logic after baseline. | High | Baseline first (playbook rollout step 1), then pass `--min-score 80` on PRs. |
| Zero analyzed = Not evaluated | Both scripts print `100%` overall when nothing was analysed (`... else 100.0`). | Reads as perfect. | High | Print "Not evaluated" and exit non-zero on a required run with 0 analysed mutants. |
| Classify every outcome | Backend counts only `killed`/`survived`; mutmut's `timeout`, `suspicious`, `no tests` outcomes are dropped from the score; a module timeout (30 min) is reported but not a failure. Frontend counts `Timeout` as killed. | Timeouts earn detection credit; other outcomes vanish. | Medium | Report every outcome class in its own column; timeouts get no credit. |
| Test selection | Import-text matching (`tests_for`, `imported_by_tests`); a `SKIP` list of four modules. | Playbook: text matching alone does not establish test impact. | Medium | Use coverage contexts (`coverage run --context`) to select tests; keep import matching as fallback, reported as such. |
| Independent test-quality agent | None; survivors land in the job summary. | No role reviews survivors or adds fault probes. | Medium | Add an optional factory stage for `risk:high` PRs: a fresh session triages survivors. |

### V1–V8 additional controls

| ID | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| V1 Spec challenge | spec-critic in a fresh subagent of the spec session; checks observability, exactness, two readings, goal coverage, readiness. | Not a separate session; it checks form more than domain counterexamples (approval disagreements, retries, stale data, compatibility); dispositions are not recorded. | Medium | Run spec-critic as its own factory session; add a "counterexamples" check and a dispositions table in the spec. |
| V2 Properties / metamorphic | None as a named practice; hypothesis not required. | Missing. | Medium | Template: optional `property` value for "Checked by", with seed recorded. |
| V3 Reference checks | Golden sets for AI; no known-answer data for financial/portfolio maths named as a gate. | Missing for consequential calculations. | Medium | `risk:high` money/index specs must include at least one known-answer row with source and tolerance. |
| V4 Failure injection | None. | Missing. | Medium | Template rows for retry/disconnect/provider failure on specs touching transactions or providers. |
| V5 Evidence reconciliation | Evidence review (fresh `fable` session) for `evaluator` rows; dispatcher gate 3 for holdout rows. | Split across two actors; unit/golden rows are not reconciled; no single manifest per PR. | High | One `Acceptance manifest` comment per PR head listing every owed row with result source, written by the evidence reviewer from the spec, not from the PR body. |
| V6 Production/restore verification | None. | Missing. No backup/restore drill. | High | Part of stage 9; first restore drill on adoption. |
| V7 Independence of expected answers | Test-writer works from spec + `main`; review findings verified by a fresh subagent. | Oracle provenance not recorded; golden labels' provenance partly recorded (`LABELS.md`). | Low | Add "oracle source" column to holdout PR descriptions. |
| V8 Human usability | None; evaluator and UI review are agent walkthroughs. | Missing. | Medium | Spec template flag "substantial UX redesign → V8 required"; result stays Blocked until a session is held. |

### §5 Fifteen-minute budget

| Topic | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Shared clock | None. | No first-work timestamp, no remaining-balance hand-off, no forecast. | High | Board card fields: first-work time, execution used, waiting intervals by cause; each stage prompt states the remaining balance. |
| Per-job timeouts | 5 min setup, 45/60 min holdout, 20 min acceptance, 30 min per mutation module, 30 min evaluator stop. | Ceilings far above the total budget. | High | Measure first (pilot), then lower ceilings; a per-job `timeout-minutes: 15` alone does not satisfy the rule. |
| Feasibility | One holdout own-row job installs the full backend + frontend + Playwright from scratch each run. | 15 minutes end to end is not plausible today for features of the size run today (spec + tests + build + 4 reviews). | High | Pilot one small confirmed defect (playbook §7.4) and record actual times before changing anything else. |

### §6 Defects, incidents, escalation

| Topic | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Fix-loop limit | Steward §2: classify, re-run once, premise line, independent diagnosis session before round 3, stop after third with `Blocked: fix limit`. | Matches the playbook closely. | – | – |
| Spec contradictions | Steward §3 `Spec question:` + `factory:blocked`. | Matches. | – | – |
| Severity P0–P3 | Not defined. | Missing. | Medium | Add the P0–P3 table to `CLAUDE.md` and the retro's categories. |
| Incident record | Main guard opens revert PR/issue; nightly failure issue. | No commander, impact, timeline or communication owner. | Medium | Issue template `incident.md`. |
| Flaky tests | Retro logs them; no quarantine rule. | Missing quarantine with owner/expiry. | Low | One rule in steward. |
| Migration rollback | Not addressed. | A revert does not reverse a destructive migration. | Medium | `risk:high` migration PRs must state backup/restore or forward repair. |

### §7 Rollout and cadence

| Topic | Factory today | Gap | Sev. | Smallest change |
|---|---|---|---|---|
| Daily summary | `/factory` status on demand; check-ins every 4 h. | No daily summary with evidence gaps and owed decisions. | Low | Scheduled daily `/factory` status. |
| Weekly review | Monday retro (`retro` skill) with at most three rule changes. | Matches in spirit; lacks the metric set. | Low | Add lead time, execution time, waiting time, failed-change rate to the retro header. |
| Deploy trigger inventory | Found: `deploy-compute.yml` (push to `main` on listed paths, and manual). `arp-gcp` has no workflows. No other deploy workflow in the app repo. | Cloud Build triggers outside GitHub not checked. | High | Owner confirms in GCP that no Cloud Build trigger deploys on push. |

## Today's runs, against the playbook

- Three features ran with one dispatcher thread each. Spec PRs #587–#589 merged 16:33–16:39 UTC after owner taps (approval A: matches).
- Builders opened #590, #591, #592 at 16:51, 17:13, 17:43 UTC. Hidden-test PRs holdout #148–#150 opened 16:54–17:17 and merged 20:39–20:42. Stage 3 overlapped stage 2 by about four hours. Playbook §3 stage 4 (independent acceptance coverage ready before implementation) was not met.
- `HOLDOUT_TOKEN` (app repo) returned 404 from about 16:45 UTC; `APP_TOKEN` (holdout repo) was empty. Both made checks fail red, which is correct; but with the secret *absent* rather than invalid, `Holdout acceptance` would have gone green.
- PR #591's `Rows: AC-1 to AC-19` was parsed as `AC-1` only, so the own-rows run checked one of 19 owed rows and could pass. The builder prompt asked for "the exact row list as the spec's `## Slices` table writes it", which was a range.
- No PR of the three reached a release; none touches a deploy-compute path.

## Proposed changes, in order

Each is one PR. Most touch `.github/**` or `.claude/**`, so they are `risk:high` and the owner merges them.

| # | Change | Closes | Files | Risk |
|---|---|---|---|---|
| 1 | Add deploy-compute trigger paths to the steward `risk:high` row (interim) | Approval B bypass | `.claude/skills/steward/SKILL.md`, `.claude/CLAUDE.md` | high |
| 2 | Put `deploy-compute.yml` behind a `production` GitHub Environment with owner approval | Approval B bypass | `.github/workflows/deploy-compute.yml` + repo setting | high |
| 3 | Factory: stage 3 waits for the holdout PR's merge SHA; builder prompt carries it | Builders before hidden tests | `.claude/skills/factory/SKILL.md` | high |
| 4 | Holdout: a `Rows:` line that does not parse completely fails (ranges and suffixed IDs like `AC-7b`); absent token fails; `skip` fails for owed rows; `Rows:` must equal one spec slice and match ≥1 test per owed row | Missing = pass | `.github/workflows/holdout.yml`, holdout `run.py` | high |
| 5 | Holdout job isolation design spec (PR code never shares a job/user with the private checkout) | Isolation boundary | new spec in `docs/superpowers/specs/` | low (spec), high (impl) |
| 6 | Mutation: "Not evaluated" for zero mutants, timeouts get no credit, all outcome classes reported | Mutation reporting | `backend/scripts/mutation_check.py`, `.github/scripts/mutation_frontend.py` | high |
| 7 | Golden set: absent credentials fail when the gate is required | Missing = pass | `.github/workflows/golden-set.yml` | high |
| 8 | Holdout skip rule reuses `ci_changes.py` | Selection mismatch | `.github/workflows/holdout.yml` | high |
| 9 | Spec template: approval-A packet headings, V1–V8 applicability, oracle source | Packet, V-controls | `docs/superpowers/ACCEPTANCE_TEMPLATE.md` | low |
| 10 | Board card fields: first-work time, execution used, waiting by cause | Budget visibility | `.claude/skills/factory/SKILL.md` | high |
| 11 | Pilot one confirmed defect end to end and record times (playbook §7.4) | Budget evidence | none (a run) | – |

Changes 1, 3 and 4 are the smallest that remove a silent bypass; 2 and 5 need owner decisions
(GitHub Environment setup, runner design). Staging, release packet and V6 depend on a deployment target
for the main app, which this review did not find.

## openwiki

No behaviour changed, so `openwiki/` needs no update.
