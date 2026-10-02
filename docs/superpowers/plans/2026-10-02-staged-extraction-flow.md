# Staged Extraction Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Extraction screen into one tabbed, staged flow: Companies → Identify → Documents → Schema → Extract. Identify and Documents become reviewable checkpoints with manual, automatic or skip handover. On top sit an overview flow chart and a current-runs panel, and every step has a Review tab.

**Architecture:** All flow state is a pure reducer in `frontend/src/lib/stagedFlow.ts` (no React import), so it is unit-tested with Node's built-in test runner. Components are thin views over existing endpoints. The bodies of the Identity Resolution and Document Discovery pages move into stage components that the old pages wrap. No backend changes.

**Tech Stack:** React 19, TypeScript 6 (`erasableSyntaxOnly`), Vite, ReactFlow 11, oxlint, `node --test` (Node 22) for pure logic.

**Spec:** `docs/superpowers/specs/2026-10-02-staged-extraction-flow-design.md`

## Global Constraints

- No new npm dependencies. Tests use `node --test --experimental-strip-types`. Test files live in `frontend/tests/`, outside `src`, so `tsc -b` (which includes only `src` with `types: ["vite/client"]`) never sees `node:test`.
- `stagedFlow.ts` uses only erasable TS syntax (no `enum`, no parameter properties) and only `import type`, so Node can strip and run it.
- Reuse the existing styles `.sub-nav`, `.nav-tab`, `.tab-badge`, `.pipeline-card`, `.status-*`, `.card`, `.view-toggle`, `.data-table`, plus `ProposedTag`, `ReviewControls`, `ReviewerField`, `useReviewer`, `RunProgress`, `UniversePicker`, `SourcePanel` and `PipelineEditor`.
- Handover default is `"manual"`. **Run all automatically** is off by default.
- Markers always carry words ("System", "Edited", "Uploaded", "Discovered"), never colour alone.
- Backend checks from the spec, resolved while planning:
  1. Identity review can be done in the tab: `api.getIdentityReviewQueue` / `api.submitIdentityReview` (`decision: "edit"`, `edited_value: { resolved_website, resolved_cik }`).
  2. Discovery downloads to `settings.documents_dir/<company_id>/<doc_type>/`. `POST /api/documents/upload` writes to the same place, and `GET /api/documents/{company_id}` (`api.listDocuments`) lists files on disk.
  3. `step_settings` accepts `pre_identity_enabled`, `pre_content_search_enabled` and `pre_document_mgmt_enabled`. All three default to `false`.
  4. A run's `params` are **not** enough to rerun identity runs (only `company_count`) or discovery runs (`universe_source` is the text "N companies"). **Rerun** is therefore offered only for runs this flow started, using the input the flow holds. Extract uses `PipelineEditor`'s existing restart.
- Batch / Single filter: `company_count === 1` means Single. This works for every run type, because extraction stores the expanded `companies` and clears `universe_path`.

## Review Focus

1. **Run stopped or failed mid-way.** The stage shows partial results and enters `review` ("Stopped" / "Run failed"). It never auto-continues. Pinned in Task 1 (`runFinished` with `cancelled` / `failed`).
2. **Every company rejected or unticked, so the output is empty.** The stage never hands over an empty list; it stays in `review` with "No companies to carry forward". Pinned in Task 1.
3. **New company list loaded after stages ran.** Every stage with a run and the extraction become stale; nothing re-runs by itself. Pinned in Task 1.
4. **4,000-company universe.** The Documents review must not call `listDocuments` once per company. Only companies with no discovered documents, or with uploads this session, are checked. Pinned in Task 1 (`companiesToCheck`).
5. **Profile switched mid-flow.** Identify and Documents results stay; only the extraction run clears. Pinned in Task 1 (`profileChanged`).

---

### Task 1: Flow state reducer and pure helpers

**Files:**
- Create: `frontend/src/lib/stagedFlow.ts`
- Create: `frontend/tests/stagedFlow.test.ts`
- Modify: `frontend/package.json` (add `"test": "node --test --experimental-strip-types tests/"`)

**Interfaces:**
- Produces (all exported from `stagedFlow.ts`):
  ```ts
  export type StageId = "identify" | "documents";
  export type FlowStep = "companies" | StageId | "schema" | "extract";
  export type Handover = "manual" | "auto" | "skip";
  export type StageState = "idle" | "running" | "review" | "ready" | "done" | "skipped" | "stale" | "failed";
  export interface StageOutput { path: string; count: number }
  export interface Stage { handover: Handover; state: StageState; runId: string | null; output: StageOutput | null; flagged: number; note: string | null }
  export interface FlowState { companies: StageOutput | null; identify: Stage; documents: Stage; extractRunId: string | null; extractStale: boolean; runIds: string[] }
  export type FlowAction =
    | { type: "companies"; output: StageOutput }
    | { type: "setHandover"; stage: StageId; handover: Handover }
    | { type: "allAuto"; on: boolean }
    | { type: "runStarted"; stage: StageId; runId: string }
    | { type: "runFinished"; stage: StageId; status: JobStatus; flagged: number; failed: number }
    | { type: "handedOver"; stage: StageId; output: StageOutput }
    | { type: "useAnyway"; stage: StageId }
    | { type: "extractStarted"; runId: string }
    | { type: "profileChanged" };
  export const STAGES: StageId[]; // ["identify", "documents"]
  export const initialFlow: FlowState;
  export function flowReducer(s: FlowState, a: FlowAction): FlowState;
  export function stageInput(s: FlowState, stage: StageId): StageOutput | null;
  export function extractInput(s: FlowState): StageOutput | null;
  export function autoContinueDue(stage: Stage): boolean;
  export interface ReviewTileCounts { pending: number; approved: number; edited: number; rejected: number; flagged: number }
  export function reviewCounts(pending: number, decisions: ReviewDecision[], flagged: number): ReviewTileCounts;
  export function valueOrigin(d?: ReviewDecision): "system" | "edited";
  export function runScope(m: RunManifest): "batch" | "single";
  export function runEndedAt(m: RunManifest): string | null;
  export function companiesToCheck(results: DiscoveryCompanyResult[], uploaded: Set<string>): string[];
  export interface DocRow { companyId: string; name: string; discovered: number; onFile: number; uploaded: boolean; flagged: boolean }
  export function docRows(results: DiscoveryCompanyResult[], onFile: Record<string, number>, uploaded: Set<string>): DocRow[];
  ```
  `JobStatus`, `ReviewDecision`, `RunManifest` and `DiscoveryCompanyResult` come from `../types` via `import type`.

Reducer rules (from the spec's Stage model):
- `initialFlow`: both stages `{ handover: "manual", state: "idle", runId: null, output: null, flagged: 0, note: null }`.
- `setHandover` with `"skip"` sets state `"skipped"`. Leaving skip goes back to `"idle"`.
- `allAuto` sets every non-skipped stage to `"auto"` (on) or `"manual"` (off).
- `runStarted`: the stage becomes `running` with that `runId`, and `runId` is appended to `runIds`. Every **later** stage whose state is `done`, `ready` or `review` becomes `stale`. `extractStale = extractRunId != null`.
- `runFinished`:
  - `failed` → state `failed`, note "Run failed".
  - `cancelled` → `review`, note "Stopped".
  - `flagged + failed > 0` → `review`, note `` `${flagged + failed} companies need review` ``.
  - Otherwise → `ready`.
  - `flagged` is stored.
- `handedOver`: `output.count === 0` → `review`, note "No companies to carry forward". Otherwise `done` with that output.
- `useAnyway`: `stale` → `done`, keeping the output.
- `companies`: stores the output. Every stage with a `runId` becomes `stale`, and `extractStale` follows the same rule as above.
- `extractStarted`: sets `extractRunId`, appends to `runIds`, sets `extractStale = false`.
- `profileChanged`: `extractRunId = null`, `extractStale = false`. Stages are untouched.
- `stageInput(identify) = companies`. `stageInput(documents)` = the identify output when identify is `done`, `stageInput(identify)` when identify is `skipped`, otherwise `null`. `extractInput` applies the same rule to documents.
- `autoContinueDue(stage) = stage.handover === "auto" && stage.state === "ready"`.
- `reviewCounts`: approved, edited and rejected count `decision` values of `approve`, `edit` and `reject`.
- `runEndedAt` returns `updated_at` unless the status is `running` or `pending`, in which case it returns `null`.
- `companiesToCheck` returns the ids of companies with `documents_found.length === 0`, plus every id in `uploaded`, de-duplicated.
- `docRows`: `onFile = onFile[id] ?? discovered`. `flagged = discovered === 0 && onFile === 0`.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/stagedFlow.test.ts`, importing from `../src/lib/stagedFlow.ts` and using `node:test` and `node:assert/strict`. Each test name below lists its assertions:
  - `manual clean run waits` — `runStarted` then `runFinished(completed, 0, 0)` gives `state === "ready"` and `autoContinueDue === false`.
  - `auto clean run is due` — the same with handover `auto` gives `autoContinueDue === true`.
  - `auto with flagged holds` — `runFinished(completed, 3, 0)` under auto gives `review`, note `"3 companies need review"`, and not due.
  - `stopped run holds` — `cancelled` gives `review`, note `"Stopped"`. `failed` gives `failed`.
  - `empty handover holds` — `handedOver` with `{count: 0}` gives `review`, note `"No companies to carry forward"`, output still `null`.
  - `skip passes input through` — identify skipped plus `companies {path:"u.csv",count:5}` gives `stageInput(s,"documents")` deep-equal `{path:"u.csv",count:5}`.
  - `rerun marks later stages stale` — identify done and documents done with `extractRunId` set, then `runStarted(identify)`, gives documents `stale` and `extractStale === true`.
  - `useAnyway clears stale` — documents `stale` then `useAnyway` gives `done` with its output kept.
  - `new companies stale everything` — both stages with run ids, then `companies`, gives both `stale`.
  - `profile change keeps stages` — `profileChanged` gives `extractRunId === null` with identify state unchanged.
  - `runIds accumulate` — two `runStarted` and one `extractStarted` give `runIds.length === 3`.
  - `reviewCounts` — `reviewCounts(2, [approve, edit, edit, reject], 4)` deep-equals `{pending:2, approved:1, edited:2, rejected:1, flagged:4}`.
  - `valueOrigin` — `undefined` gives `"system"`, `approve` gives `"system"`, `edit` gives `"edited"`.
  - `runScope and runEndedAt` — `company_count:1` gives `"single"` and `50` gives `"batch"`. A `running` manifest gives `null`; a `completed` one gives its `updated_at`.
  - `companiesToCheck skips companies with documents` — of 3 results with 0, 2 and 0 documents and `uploaded={"b"}`, it returns the ids of the two zero-document companies plus `"b"`, de-duplicated (length 3).
  - `docRows flags only empty companies` — 0 discovered with `onFile 2` gives `flagged false`; 0 and 0 gives `flagged true`.

- [ ] **Step 2: Run to verify they fail**
  Run: `cd frontend && npm test`
  Expected: FAIL, cannot find module `../src/lib/stagedFlow.ts`.

- [ ] **Step 3: Implement `stagedFlow.ts`** with the interfaces and rules above. Keep the reducer as one `switch` on `a.type`, with a `later(stage)` helper based on `STAGES` order.

- [ ] **Step 4: Run to verify they pass**
  Run: `cd frontend && npm test && npx tsc -b`
  Expected: all tests pass and tsc exits 0.

- [ ] **Step 5: Commit**
  `git add frontend/src/lib/stagedFlow.ts frontend/tests/stagedFlow.test.ts frontend/package.json && git commit -m "feat(extraction): staged flow reducer and helpers"`

### Task 2: Shared review list, status tiles and origin marker

**Files:**
- Create: `frontend/src/components/RunReviewList.tsx`
- Create: `frontend/src/components/ReviewTiles.tsx`
- Modify: `frontend/src/pages/ReviewQueue.tsx` (render `RunReviewList` for each run's pending items instead of its inline loop; move `ReviewItemFields`, `QUEUE_FNS`, `SUBMIT_FNS` and `HISTORY_FNS` into `RunReviewList.tsx` and export them)
- Modify: `frontend/src/index.css` (`.review-tiles` grid and `.origin-tag`)

**Interfaces:**
- Consumes: `reviewCounts`, `valueOrigin` and `ReviewTileCounts` from Task 1.
- Produces:
  ```ts
  export function RunReviewList(p: { kind: ReviewableRunKind; runId: string; reviewer: string; onOpenSource: (s: ActiveSource) => void; filter?: keyof ReviewTileCounts | null; onCounts?: (pending: number, decisions: ReviewDecision[]) => void }): JSX.Element
  export function ReviewTiles(p: { counts: ReviewTileCounts; active: keyof ReviewTileCounts | null; onSelect: (k: keyof ReviewTileCounts | null) => void }): JSX.Element
  export function OriginTag(p: { decision?: ReviewDecision; systemValue?: string }): JSX.Element
  ```
  - `OriginTag` renders "System", or "Edited by {reviewer}, {when(decided_at)}" with a `<details>` "was: {systemValue}".
  - `ReviewTiles` renders five buttons labelled Pending, Approved, Edited, Rejected and Flagged, each with its count and `aria-pressed`. Clicking the active tile clears the filter.

- [ ] **Step 1: Move the per-run item rendering into `RunReviewList`** and make `ReviewQueue.tsx` use it. Behaviour must be unchanged: same items, same `ReviewControls`, same reopen and history buttons.
- [ ] **Step 2: Add `ReviewTiles` and `OriginTag`**, with styles in `index.css` next to `.tab-badge`.
- [ ] **Step 3: Verify**
  Run: `cd frontend && npx tsc -b && npm run lint && npm test`
  Expected: exit 0. In the browser, `#/review` lists the same pending items as before the change.
- [ ] **Step 4: Commit** with message `refactor(review): shared RunReviewList; add ReviewTiles and OriginTag`.

### Task 3: Current runs panel

**Files:**
- Create: `frontend/src/components/FlowRuns.tsx`
- Modify: `frontend/src/index.css` (`.flow-runs`, pinned-row style)

**Interfaces:**
- Consumes: `runScope` and `runEndedAt` from Task 1; `api.listRuns`, `api.cancelRun`; `runTypeLabel` and `when` from `lib/runs`.
- Produces:
  ```ts
  export function FlowRuns(p: {
    runTypes: string[];              // e.g. ["identity"], or the three kinds on Companies/Schema
    runIds: string[];                // FlowState.runIds; only these are listed
    selected: string | null;
    onSelect: (runId: string) => void;
    onRerun?: (run: RunManifest) => void; // shown only when given and status is final
    onReview?: (run: RunManifest) => void;
    compact?: boolean;
    storageKey: string;              // localStorage key for collapsed state
  }): JSX.Element
  ```
- Behaviour:
  - Calls `api.listRuns(type)` for each type and keeps only `runIds`.
  - Sorts running and pending runs first, then by `created_at` descending.
  - Polls every 3000 ms while any listed run is running or pending.
  - Columns: run id and type; started and ended times; status and `completed_count/company_count` with failed and review counts; input (`params.universe_path` file name, or `company_count`, plus `params.datapoint_schema.name` when present); cost (`$estimated_cost_usd`, tokens, `model`); error.
  - Actions: Stop (`cancelRun`, only while running), Rerun, Open (`onSelect`), and "Review →" when `review_count > 0`.
  - A Batch / Single / All `.view-toggle` filters by `runScope`.
  - Collapsing shows a one-line summary ("1 running · 3 done"). The collapsed state is read from and written to `localStorage[storageKey]` inside try/catch, and defaults to open.
  - An empty list shows "No runs yet in this flow."

- [ ] **Step 1: Implement `FlowRuns.tsx`** as above.
- [ ] **Step 2: Verify** with `cd frontend && npx tsc -b && npm run lint` (exit 0).
- [ ] **Step 3: Commit** with message `feat(extraction): current runs panel`.

### Task 4: Identity stage

**Files:**
- Create: `frontend/src/components/IdentityStage.tsx`
- Modify: `frontend/src/pages/IdentityResolution.tsx` (becomes a wrapper)

**Interfaces:**
- Consumes: `Stage`, `StageOutput` and `FlowAction` from Task 1; `RunReviewList`, `ReviewTiles` and `reviewCounts` from Task 2.
- Produces:
  ```ts
  export function IdentityStage(p: {
    input: StageOutput | null;             // list to resolve; null = show UniversePicker (standalone use)
    stage: Stage;
    dispatch: (a: FlowAction) => void;
    view: "run" | "review";
    reviewer: string;
    onOpenSource: (s: ActiveSource) => void;
  }): JSX.Element
  ```
- Run view:
  - **Start** calls `api.startIdentityRun({ universe_path })` and dispatches `runStarted`.
  - Shows `RunProgress` and the existing results table.
  - When the manifest status is final, dispatches `runFinished` with `flagged = review_count` and `failed = failed_count`.
  - Handover: a `.view-toggle` with Manual / Automatic / Skip that dispatches `setHandover`.
  - **Continue →** is shown when state is `ready` or `review`, or when `autoContinueDue(stage)` (in which case a `useEffect` fires it once). It calls `api.getEnrichedUniverse(runId)` then `api.universeFromCompanies(companies, "identity_resolved")` and dispatches `handedOver({path, count})`.
  - Shows `stage.note` as status text.
- Review view: `ReviewTiles` over `RunReviewList kind="identity"`, filtered by the active tile.
- `IdentityResolution.tsx` keeps its own `useReducer(flowReducer, initialFlow)` and renders `IdentityStage` with `input` from its `UniversePicker`. After `handedOver` it shows the existing "Go to Document Discovery →" button, so the hub page works as before.

- [ ] **Step 1: Move the page body into `IdentityStage`** and add the handover controls and Review view.
- [ ] **Step 2: Verify**
  Run: `cd frontend && npx tsc -b && npm run lint`
  Expected: exit 0. In the browser, `#/identity` resolves a 2-company CSV and "Go to Document Discovery" still works.
- [ ] **Step 3: Commit** with message `feat(extraction): identity stage component`.

### Task 5: Documents stage with manual upload

**Files:**
- Create: `frontend/src/components/DocumentsStage.tsx`
- Create: `frontend/src/components/DocumentUpload.tsx`
- Modify: `frontend/src/api/client.ts` (add `uploadDocument`)
- Modify: `frontend/src/pages/DocumentDiscovery.tsx` (the manual-run card becomes `DocumentsStage`; schedule and event feed stay)

**Interfaces:**
- Consumes: Task 1 (`docRows`, `companiesToCheck`, `DocRow`, `Stage`, `FlowAction`) and Task 2 (`ReviewTiles`).
- Produces:
  ```ts
  // client.ts — multipart like rawUpload (FormData, headers: {})
  uploadDocument: (companyId: string, docType: DocType, file: File) => Promise<{ path: string }>   // POST /api/documents/upload

  export function DocumentUpload(p: { companies: { company_id: string; name: string }[]; onUploaded: (companyId: string) => void }): JSX.Element
  export function DocumentsStage(p: { input: StageOutput | null; stage: Stage; dispatch: (a: FlowAction) => void; view: "run" | "review" }): JSX.Element
  ```
- `DocumentUpload`:
  - A company `<select>`.
  - One `<input type="file" multiple>` per type: `"10-K"` "Annual report", `"sustainability_report"` "Sustainability report", `"DEF-14A"` "Proxy statement", `"earnings_transcript"` "Earnings transcript", `"investor_presentation"` "Investor presentation", `"other"` "Other".
  - Uploads each file in turn and shows a per-file result, including the server's error message on failure.
  - The company list comes from the discovery results (`company_id`, `name`). `api.getRunCompanies` is extraction-only, so it is not used here. Upload is offered once a discovery run has results.
- `DocumentsStage` Run view:
  - Start calls `api.startDiscoveryRun({ universe_path: input.path })` and dispatches `runStarted`.
  - Shows `RunProgress runType="discovery"`, then `DocumentUpload`, then the results table.
  - After results load, calls `api.listDocuments` only for `companiesToCheck(results, uploadedThisSession)`.
  - The table shows `docRows` with a marker: "Discovered", "Uploaded", or "None" for flagged rows.
  - `runFinished` gets `flagged = rows.filter(r => r.flagged).length` and `failed = failed_count`.
  - Handover toggle as in Task 4.
- `DocumentsStage` Review view:
  - `ReviewTiles`: pending = flagged rows not yet decided; approved = ticked; rejected = unticked. Edited is always 0.
  - Under the tiles is the row list with a tick per company. Default: ticked unless flagged.
  - **Continue →** builds `api.universeFromCompanies(tickedCompanies, "documents_ready")` and dispatches `handedOver`.

- [ ] **Step 1: Add `uploadDocument` to `client.ts`.**
- [ ] **Step 2: Implement `DocumentUpload` and `DocumentsStage`**, and make `DocumentDiscovery.tsx` use `DocumentsStage`.
- [ ] **Step 3: Verify**
  Run: `cd frontend && npx tsc -b && npm run lint`
  Expected: exit 0. In the browser, on `#/discovery`, upload a PDF for a company whose crawl found nothing. That row then shows "Uploaded", is not flagged, and `GET /api/documents/<id>` lists the file.
- [ ] **Step 4: Commit** with message `feat(extraction): documents stage with manual upload`.

### Task 6: Overview flow chart

**Files:**
- Create: `frontend/src/components/StageFlowChart.tsx`
- Modify: `frontend/src/index.css` (only what `.pipeline-card` lacks: mode chip, button row)

**Interfaces:**
- Consumes: `FlowState`, `FlowStep`, `FlowAction` and `Handover` from Task 1; `layoutPipeline` from `lib/pipelineLayout`.
- Produces:
  ```ts
  export interface ExtractNodeInfo { schemaLabel: string; ready: boolean; status: StageState; counts: string | null }
  export function StageFlowChart(p: {
    flow: FlowState;
    profile: ExtractionProfile;
    extract: ExtractNodeInfo;
    counts: Partial<Record<StageId, string>>;          // e.g. "47/50 resolved"
    onOpen: (step: FlowStep, sub?: "setup" | "run" | "review") => void;
    onStart: (step: StageId | "extract") => void;
    onStop: (runId: string) => void;
    onContinue: (stage: StageId) => void;
    dispatch: (a: FlowAction) => void;
  }): JSX.Element
  ```
- Nodes: Companies → Identify → Documents → [Schema, Custom only] → Extract & verify → Scoring → Results, laid out with `layoutPipeline`. The chart is read-only: no dragging or connecting, and controls are shown.
- Each node card shows the label, status dot (reusing `status-*`), counts line, mode chip and buttons, following the spec's "Flow chart (overview)" table.
- Schema labels, verbatim from the spec:
  - Custom: `` `${schema.name} · ${schema.fields.length} fields · ${when(schema.created_at)}` ``, or "No schema yet" in a warning tone, with Start disabled.
  - Financials: "Financials: segments, CapEx, R&D".
  - TNFD: "TNFD: 14 recommendations + core metrics".
  - Transition Plan: "Transition Plan: 64 indicators".
- Clicks:
  - A stage node in `review` → `onOpen(stage, "review")`.
  - Extract & verify → `onOpen("extract", "setup")`, Scoring → `"setup"`, Results → `"review"`.
- Edges: dashed (`style.strokeDasharray`) into and out of a skipped stage. Use the accent colour when the source stage is `ready` and manual.

- [ ] **Step 1: Implement `StageFlowChart.tsx`.**
- [ ] **Step 2: Verify** with `cd frontend && npx tsc -b && npm run lint` (exit 0).
- [ ] **Step 3: Commit** with message `feat(extraction): stage overview flow chart`.

### Task 7: Tabbed Extraction screen

**Files:**
- Create: `frontend/src/components/StepTabs.tsx`
- Modify: `frontend/src/pages/Extraction.tsx`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces:
  ```ts
  export interface StepTab { id: string; label: string; badge?: number | null; mark?: "done" | "waiting" | "attention" | null; disabled?: boolean }
  export function StepTabs(p: { label: string; tabs: StepTab[]; active: string; onSelect: (id: string) => void }): JSX.Element
  ```
  `StepTabs` uses `.sub-nav` / `.nav-tab`, `role="tablist"` and `role="tab"`, `aria-selected`, and ArrowLeft / ArrowRight that move to and focus the next enabled tab. It shows `.tab-badge` for `badge > 0`, and the marks ✓ / ⏸ / ! with `aria-label`s "done", "waiting on you" and "needs attention".
- `Extraction.tsx` changes:
  - `const [flow, dispatch] = useReducer(flowReducer, initialFlow)`. Seed it with `companies` from `pendingUniverse`. Dispatch `companies` when `UniversePicker` resolves or a single company is entered; the single company goes through `api.universeFromCompanies([singleCompany], "single")`.
  - Top tabs: Companies, Identify, Documents, Schema (Custom only), Extract, numbered from the visible list. Inner tabs: Identify and Documents get `run | review`; Extract gets `setup | run | review`. Run and review are disabled until `extractRunId`.
  - Every tab panel stays mounted with the `hidden` attribute.
  - Order inside the page: profile toggle, then a "Run all automatically" checkbox (dispatches `allAuto`), then `StageFlowChart`, then `StepTabs`, then `FlowRuns`, then the panel.
  - `FlowRuns` `runTypes` per tab: identity / discovery / the profile's run type, and all three on Companies and Schema. `storageKey` is `` `flowRuns:${tab}` ``.
  - Extract › Setup: the existing Pipeline card, then scoring picker, then **Start extraction**. Start sends `universe_path: extractInput(flow).path`. Its `step_settings` merges, for each stage **not** skipped, `pre_identity_enabled: false`, `pre_content_search_enabled: false` and `pre_document_mgmt_enabled: false`. It then dispatches `extractStarted` and opens Extract › Run.
  - When `extractStale`, Start shows "Inputs changed since this run".
  - Extract › Run: the existing Run progress card (RunProgress, PipelineEditor with restart wired to `extractStarted`, refresh, CSV, ReviewerField).
  - Extract › Review: `ReviewTiles` from `reviewCounts`, using the profile's decisions map and the run's `review_count`. Below that, the existing charts, results table, `SourcePanel` and `RunScoringPanel`.
  - `switchMode` also dispatches `profileChanged` and selects Companies.
  - Remove `scoringStepNumber` and `universeStepNumber`.

- [ ] **Step 1: Implement `StepTabs.tsx`.**
- [ ] **Step 2: Restructure `Extraction.tsx`** as above. Move the existing JSX into panels unchanged where possible.
- [ ] **Step 3: Verify**
  Run: `cd frontend && npx tsc -b && npm run lint && npm test`
  Expected: exit 0 and all tests pass.
- [ ] **Step 4: Commit** with message `feat(extraction): tabbed staged flow screen`.

### Task 8: System / Edited markers in result tables

**Files:**
- Modify: `frontend/src/components/ExtractionResults.tsx` (`ExtractionResultsTable` field value cells, `FinancialsResultsTable` company row)
- Modify: `frontend/src/components/TransitionPlanResults.tsx` (`IndicatorDetail`)

**Interfaces:**
- Consumes: `OriginTag` from Task 2. The `reviewDecisions` maps these tables already receive.
- Wherever a value is shown next to `ReviewControls`, add `<OriginTag decision={reviewDecisions[key]} systemValue={String(value ?? "—")} />`. When the decision is `edit`, the cell shows `edited_value.value` in place of the system value.

- [ ] **Step 1: Add the markers** in the three places above.
- [ ] **Step 2: Verify**
  Run: `cd frontend && npx tsc -b && npm run lint`
  Expected: exit 0. In the browser, edit one value in Extract › Review. The cell then shows the edited value, "Edited by <name>", the "was: …" detail, and the Edited tile count goes up by 1.
- [ ] **Step 3: Commit** with message `feat(review): system vs edited markers on result values`.

### Task 9: End-to-end check

**Files:** none (fix-ups only, committed into the task they belong to)

- [ ] **Step 1: Build**
  Run: `cd frontend && npm test && npm run build && npm run lint`
  Expected: tests pass, build succeeds, lint exits 0.
- [ ] **Step 2: Browser walkthrough** (backend and `npm run dev`, Playwright Chromium). Take screenshots of each item:
  - Custom profile, manual mode end to end: Companies, then Identify (run, Continue), then Documents (one upload, Continue), then Schema draft, then Extract start, Run, Review.
  - Transition Plan with Run all automatically: the flow stops at the first flagged stage with its note.
  - Stop a running identity run from the chart: the stage shows "Stopped" and its partial results.
  - Every tab shows `FlowRuns` with the right run type. Rerun adds a new row and keeps the old one.
  - The chart's Extract node shows the drafted schema name.
  - At 375 px width there is no horizontal page scroll, and the tab bar wraps or scrolls inside itself.
- [ ] **Step 3: Commit** any fixes.
