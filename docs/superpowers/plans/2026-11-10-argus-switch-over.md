# Argus switch-over (slice 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The new Argus flow becomes the only way to run an extraction:
- old addresses redirect into it;
- hand-overs from other workspaces open step 1 with the companies listed;
- XBRL Facts uses step 1's company picker;
- the rules editor moves to step 3;
- the old Extraction, Universe and Transition Plan screens are deleted.

**Architecture:**
- **Redirects:** use the existing `RETIRED` table in `lib/nav.ts`. A sentinel route `#/argus/new` (and `#/argus/new/transition_plan`) creates a flow and replaces the hash with step 1.
- **Hand-overs:** `sendUniverse` in `App.tsx` becomes `sendToArgus`. It creates a flow, adds the saved universe (`POST /api/argus/flows/{id}/companies` with `universe_path`) and opens step 1.
- **Shared picker:** step 1's inline picker becomes `components/CompanyPicker.tsx` with three callbacks. Step 1 wires them to the flow; XBRL Facts wires them to a saved universe path.
- **Rules editor:** the existing `RulesList` / `RuleEditor` and "Suggest rules" move under step 3's field table.
- **Deletions:** only after every importer is gone, checked with grep.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` ("Duplicates removed", slice 6, AC-62 to AC-71).

## Owner decisions (2026-11-10)
- The rules editor moves to step 3 and is not dropped. Its e2e test moves with it.
- AC-66 covers Argus pages only. Thematic Universe, Emerging Themes, Proxy Voting and Taxonomy Library keep their own upload. The PR states this reading.

## Global Constraints

- **Redirects** (sub-paths included):

  | Old route | Lands on |
  |---|---|
  | `#/extraction…` | `#/argus` |
  | `#/argusUniverse…`, `#/identity…`, `#/discovery…` | `#/argus/new` (step 1 of a new flow) |
  | `#/transitionPlan…` | `#/argus/new/transition_plan` (step 1 of a new flow, with the Transition plan preset `transition_plan_indicators` installed and chosen for step 3) |

- **`#/argusWalkthrough` stays.** The spec does not remove it.
- **Hand-over buttons** read `Argus →` and land on `#/argus/<flow_id>/1` with the companies listed. The callers:
  - Thematic Universe's "Go to Extraction Engine →";
  - Risk Monitoring and Data Hub's "Extraction →" and "Transition Plan →" (`PersistentSelectionPane`). The Transition Plan button also preselects the preset.

  A failed hand-over shows its error on the sending page.
- **XBRL Facts** mounts `CompanyPicker` with the same controls and labels as step 1. Its only sender, ArgusUniverse, is deleted, so its `pendingUniverse` hand-over is removed.
- **Rules editor in step 3:**
  - shown for a saved custom schema (not Financials or TNFD);
  - saving rules makes the next version, the same as `Edit as v<n+1>`;
  - `Suggest rules` uses the existing `POST /api/extraction/schemas/suggest-rules`.
- **Deleted:**
  - `pages/Extraction.tsx` and `pages/extraction/*`, `pages/ArgusUniverse.tsx`;
  - the components `PipelineEditor`, `StageFlowChart`, `IdentityStage`, `DocumentsStage`, `FlowRuns`, `DocumentUpload` and `SchemaFieldsEditor`, but only if step 3's rules editor does not need it;
  - `lib/jobs.ts`, `lib/workbench.ts` and their tests;
  - `TnfdResults` and `TransitionPlanResults` only if Task 6 shows Run History and the Review Queue give the same counts without them (AC-69); otherwise they stay.
- **Repointed links:**
  - `lib/argusStart.ts`: a run with no flow → `#/review/<run_type>/<id>` (`reviewKind`), else `#/history`;
  - `ProcessHub` "Run process" → `#/argus/new`;
  - `lib/processes.ts`: the Argus screens and steps, and Transition Intel's Transition Plan screen and step → the flow;
  - `NavIcons` keys for removed tabs.
- **Carried over from the slice 5 review:**
  - `KeptDocuments` calls `DocumentSourceRegistry.fetch_all(dedup=False)` (or `prefer=`) instead of copying it.
  - A source failure counts toward `Kept file not found` only for the local source the kept files come from.
- **Test changes, all listed in the PR:**
  - `nav.test.ts`, `processes.test.ts`, `argusStart.test.ts`, `argusFlow.test.ts`: expectations for the new routes and links;
  - `jobs.test.ts`, `workbench.test.ts`: deleted with their modules;
  - `test_app_smoke.py`'s phone-drawer test uses another screen;
  - `test_schema_rules.py` is rewritten against step 3, with the same checks.
- **Golden set:** `arp golden-set run` on the PR build (AC-71). By hand if CI skips it; the key is in the session.

## Review Focus

1. **Stored runs stay readable (AC-69):** open stored `extraction`, `transition_plan`, `financials`, `tnfd`, `identity` and `discovery` runs from Run History. Their result and review counts must match `main`. Check this before deleting any results component.
2. **`#/argus/new` must create exactly one flow,** even on reload or a double render (React StrictMode). Use a guard ref, and replace the hash, don't push it, so Back does not create another flow.
3. **A failed hand-over** (expired universe file, network) must not navigate away or lose the selection.
4. **Nothing else imports a deleted file:** grep, plus `tsc -b`, plus the full frontend suite.
5. **The rules editor in step 3** must not let the user save rules onto a released version in place. It always makes a new version, and then the repeat rule sees a new version.

---

### Task 1: Redirects and `#/argus/new`

**Files:** `frontend/src/lib/nav.ts` (`RETIRED`), `App.tsx` (route `argus/new[/preset]`), `pages/ArgusStart.tsx` or `ArgusFlow.tsx` (create, preset, replace hash); Tests `frontend/tests/nav.test.ts`, e2e `backend/tests/e2e/test_argus_switchover.py` (new)

- [ ] Test-first:
  - each old route and a sub-path maps as in the table;
  - e2e: `#/extraction/companies/auto` → `#/argus` (AC-62);
  - e2e: `#/argusUniverse`, `#/identity`, `#/discovery` → step 1 of a new flow (AC-63);
  - e2e: `#/transitionPlan` → step 1, with step 3 showing the Transition plan template chosen (AC-64);
  - a reload of `#/argus/new` creates one flow.
- [ ] Implement, then commit.

### Task 2: Hand-overs into step 1

**Files:** `App.tsx` (`sendToArgus`), `PersistentSelectionPane.tsx`, `ThemeBuilder.tsx`, `PortfolioRiskMonitoringTool.tsx` (types); e2e in `test_argus_switchover.py`

- [ ] Test-first: e2e for each of Thematic Universe, Risk Monitoring and Data Hub. The hand-over lands on step 1 listing the handed-over companies (AC-65). A failed hand-over shows an error and stays.
- [ ] Implement, then commit.

### Task 3: Shared company picker on XBRL Facts

**Files:** Create `components/CompanyPicker.tsx`; Modify `ArgusFlow.tsx` (step 1 uses it), `XbrlFetchArea.tsx` / `XbrlFacts.tsx`; Test `frontend/tests/companyPicker.test.ts` (labels) and e2e

- [ ] Test-first: step 1 and XBRL Facts show the same controls and labels (AC-67). An XBRL fetch for CIK 0000320193 completes with more than 0 facts (AC-68). That needs the network, so it is key- or network-gated like other live tests, and also checked by hand.
- [ ] Implement, then commit.

### Task 4: Rules editor in step 3

**Files:** `ArgusSchema.tsx` (rules section under the field table, using `RulesList` / `RuleEditor` and suggest-rules); rewrite `backend/tests/e2e/test_schema_rules.py` against step 3

- [ ] The ported e2e test checks:
  - the same rule kinds as before can be added and saved;
  - Suggest rules fills the list;
  - saving creates `v<n+1>`.
- [ ] Implement, then commit.

### Task 5: Slice-5 carry-overs

**Files:** `backend/arp/ingestion/registry.py`; Test `backend/tests/test_argus_no_text.py` (append)

- [ ] Test-first:
  - `KeptDocuments` goes through `fetch_all(...)`, with no copied gather;
  - an EDGAR failure plus an unreadable kept local file reads `No text could be read from <file>`, not `Kept file not found`.
- [ ] Implement, then commit.

### Task 6: Delete the old screens and repoint links

**Files:** the deletions above; `lib/argusStart.ts`, `ProcessHub.tsx`, `lib/processes.ts`, `NavIcons.tsx`, `App.tsx` (`TABS`, lazy imports, routes, handoff); tests listed in Global Constraints

- [ ] First, the AC-69 check:
  - seed or use stored runs of each of the six types, and record their result and review counts as Run History and the Review Queue show them on `main`;
  - after the deletions, assert the same counts in an e2e test;
  - if the Review Queue needs `TnfdResults` / `TransitionPlanResults`, keep them.
- [ ] Delete only after grep shows no importer.
- [ ] AC-66 check by e2e:
  - every sidebar and All screens route opens;
  - the company upload appears only on step 1 and XBRL Facts among the Argus pages;
  - the document upload appears only on step 2;
  - no page shows the overview flow diagram or the `PipelineEditor` canvas.
- [ ] AC-70: a run started from step 3 is listed in Run History.
- [ ] Then:
  - `npm run lint && npx tsc -b && npm test`, backend ruff and the touched tests run alone;
  - all e2e tests with and without a key;
  - `arp golden-set run` (AC-71);
  - screenshots of `#/argus`, step 1 after a hand-over, XBRL Facts and step 3 with rules, light and dark;
  - commit, push, PR with `Spec: argus-simplified-pipeline` and `risk:normal`. Then the factory review and evaluator run.
