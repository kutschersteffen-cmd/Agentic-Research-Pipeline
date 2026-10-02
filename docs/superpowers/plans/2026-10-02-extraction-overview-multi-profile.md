# Extraction Overview and Multi-Profile Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Overview landing tab to the Extraction screen (chart, scoring summary, all runs, per-company steps) and let one flow run any combination of profiles, including several Custom schemas, as one extraction run per job.

**Architecture:** "Jobs" (one built-in profile or one Custom schema each) are pure data with pure helpers in `frontend/src/lib/jobs.ts`. The flow reducer keys extraction runs by job id. The per-run UI (Run block, Review block) moves into per-job components, so the page renders one of each per job. The Overview tab hosts the chart and the monitoring panels. No backend change.

**Tech Stack:** React 19, TypeScript 6 (`erasableSyntaxOnly`), ReactFlow 11, oxlint, `node --test --experimental-strip-types` for pure logic.

**Spec:** `docs/superpowers/specs/2026-10-02-extraction-overview-multi-profile-design.md`. It extends `docs/superpowers/specs/2026-10-02-staged-extraction-flow-design.md`.

## Global Constraints

- No backend changes and no new npm dependencies. Pure logic is tested in `frontend/tests/*.test.ts` and imported as `../src/lib/<file>.ts`. Test files use only `import type` from `../src/types` and use erasable syntax.
- Verification for every UI task: `cd frontend && npm test && npx tsc -b && npm run lint && npm run build`. Lint exits 0 and adds no warnings to the 13 already there.
- Existing rulings stay in force:
  - Each stage component is mounted exactly once.
  - Chart callbacks are stable (`useCallback`/`useMemo`).
  - All tab panels stay mounted with `hidden`.
  - Markers carry words, not colour alone.
  - No horizontal page scroll at 375px.
- Copy, verbatim from the spec:
  - "Pick at least one profile"
  - "Custom (no schema yet)"
  - "Custom: <schema name>"
  - "Starts N runs × M companies"
  - "None attached"
  - "← Overview"
  - "Add another schema"
  - "Remove"
- Job ids: `"financials"`, `"tnfd"`, `"transition_plan"`, and `"custom:<n>"` with an increasing integer `n`.
- Run type per profile: custom → `"extraction"`, financials → `"financials"`, tnfd → `"tnfd"`, transition_plan → `"transition_plan"`.
- Chart height on Overview: 420px. Landing tab: Overview.

## Review Focus

1. **Unticking the last profile.** The picker refuses it and shows "Pick at least one profile". Pinned in Task 1 (`toggleProfile`).
2. **Start with a Custom job that has no schema.** Every other job still starts; that one shows "Custom (no schema yet)". Pinned in Task 1 (`jobsToStart`).
3. **One job's start call fails.** The other jobs still start, and the error is shown on that job only. Pinned in Task 1 (`startJobs`).
4. **A job is removed after its run started.** Its run leaves `extractRuns`; other runs stay. Pinned in Task 2 (`jobsChanged`).
5. **Start is pressed again after some jobs ran.** Only jobs without a run start. Pinned in Task 1 (`jobsToStart`).

---

### Task 1: Jobs model and pure helpers

**Files:**
- Create: `frontend/src/lib/jobs.ts`
- Test: `frontend/tests/jobs.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type BuiltIn = "financials" | "tnfd" | "transition_plan";
  export interface CustomJob { id: string; profile: "custom"; schema: DataPointSchema | null; request: string }
  export interface BuiltInJob { id: BuiltIn; profile: BuiltIn }
  export type Job = BuiltInJob | CustomJob;
  export interface JobSettings { stepSettings: StepSettings; templateId: string | null }   // kept per job id by the page
  export const PROFILE_META: Record<ExtractionProfile, { label: string; runType: RunScoringKind; about: string }>;
  export function jobLabel(j: Job): string;          // "Financials" | "TNFD" | "Transition Plan" | "Custom: <name>" | "Custom (no schema yet)"
  export function jobReady(j: Job): boolean;         // built-in → true; custom → schema != null
  export function jobRunType(j: Job): RunScoringKind;
  export function toggleProfile(jobs: Job[], profile: ExtractionProfile, nextCustomId: () => string): { jobs: Job[]; error: string | null };
  export function addCustomJob(jobs: Job[], id: string, request: string): Job[];
  export function removeJob(jobs: Job[], id: string): { jobs: Job[]; error: string | null };
  export function jobsToStart(jobs: Job[], extractRuns: Record<string, string>): Job[];
  export function startsText(jobCount: number, companyCount: number): string; // "Starts 3 runs × 50 companies"
  export async function startJobs(jobs: Job[], start: (j: Job) => Promise<string>): Promise<{ started: Record<string, string>; errors: Record<string, string> }>;
  export function initialJobs(profile: ExtractionProfile, customId: string, request: string): Job[];
  ```
- Move `PROFILES` (label, runType, about) out of `Extraction.tsx` into `PROFILE_META`, keeping the existing `about` text verbatim. Custom's `about` stays `""`.

Rules:
- `toggleProfile`:
  - Ticking a built-in profile adds its job. Ticking `"custom"` when no custom job exists adds one with `request` `""`.
  - Unticking removes the built-in job, or removes **all** custom jobs.
  - When the result would be empty, it returns the input unchanged with `error: "Pick at least one profile"`.
- `removeJob` follows the same empty rule.
- `jobsToStart` returns jobs that are `jobReady` and have no entry in `extractRuns`.
- `startJobs` awaits `start` for each job **in order**. A rejection records `errors[id] = message` and continues with the next job.
- `startsText(1, 1)` returns "Starts 1 run × 1 company". Use singular nouns at 1.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/jobs.test.ts`:
  - `labels`: `jobLabel` gives "Financials"; a custom job with schema `{name:"Green capex"}` gives "Custom: Green capex"; a custom job with a null schema gives "Custom (no schema yet)".
  - `toggle adds and removes`: from `[financials]`, ticking tnfd gives ids `["financials","tnfd"]`; unticking financials gives `["tnfd"]`.
  - `cannot untick last`: from `[financials]`, unticking financials gives `error === "Pick at least one profile"` and jobs unchanged.
  - `custom toggle`: ticking custom adds one job with an id starting `"custom:"`; with two custom jobs, unticking custom removes both.
  - `removeJob last refused`: same error text.
  - `jobsToStart skips unready and started`: jobs [financials, tnfd, custom(no schema), custom(schema)] with `extractRuns {financials:"r1"}` return ids [tnfd, the custom with schema].
  - `startJobs continues after a failure`: given a fake start that rejects for tnfd, it returns `started` with financials and custom ids, and `errors.tnfd` set to the rejection message. The call order equals the job order.
  - `startsText`: `(3,50)` gives "Starts 3 runs × 50 companies"; `(1,1)` gives "Starts 1 run × 1 company".
- [ ] **Step 2: Run to verify they fail.** Command: `cd frontend && npm test`. Expected: cannot find `../src/lib/jobs.ts`.
- [ ] **Step 3: Implement `jobs.ts`.** It imports only types from `../types`.
- [ ] **Step 4: Run to verify they pass.** Command: `cd frontend && npm test && npx tsc -b`.
- [ ] **Step 5: Commit** with message `feat(extraction): jobs model for multi-profile runs`.

### Task 2: Reducer keys extraction runs by job

**Files:**
- Modify: `frontend/src/lib/stagedFlow.ts`, `frontend/tests/stagedFlow.test.ts`
- Modify (compile-only, behaviour unchanged): `frontend/src/pages/Extraction.tsx`, `frontend/src/components/StageFlowChart.tsx`

**Interfaces:**
- Produces:
  - `FlowState.extractRuns: Record<string, string>`, which replaces `extractRunId`.
  - Actions:
    - `{ type: "extractStarted"; job: string; runId: string }`
    - `{ type: "jobsChanged"; jobIds: string[] }`, which replaces `profileChanged`
  - Helper: `export function latestExtractRun(s: FlowState): string | null`. It returns the last id in `runIds` that is a value of `extractRuns`.
- Rules:
  - `extractStarted` sets `extractRuns[job] = runId`, appends to `runIds`, and sets `extractStale = false`.
  - `jobsChanged` drops `extractRuns` entries whose key is not in `jobIds`. Stages are untouched.
  - Every place that set `extractStale` from `extractRunId != null` now uses `Object.keys(extractRuns).length > 0`.
- Compile fix:
  - `Extraction.tsx` uses job id = current `mode`, so it reads `flow.extractRuns[mode]`, dispatches `extractStarted { job: mode }` and `jobsChanged { jobIds: [mode] }`.
  - `StageFlowChart`'s Extract Stop uses `latestExtractRun(flow)`.
  - The full multi-job wiring is Task 6.

- [ ] **Step 1: Update the tests.** Replace the `profileChanged` and `extractRunId` assertions, and add:
  - `extract runs per job`: two `extractStarted` calls (financials r1, tnfd r2) give `extractRuns {financials:"r1", tnfd:"r2"}` and `runIds` ending `["r1","r2"]`.
  - `jobsChanged drops removed jobs`: from the above, `jobsChanged(["tnfd"])` gives `extractRuns {tnfd:"r2"}` with `identify` unchanged.
  - `latestExtractRun`: returns `"r2"`.
  - `stale with any run`: with any extract run, `runStarted(identify)` sets `extractStale` true.
- [ ] **Step 2: Run to verify the new tests fail.** Command: `cd frontend && npm test`.
- [ ] **Step 3: Implement**, and fix the two callers as above.
- [ ] **Step 4: Verify** with `cd frontend && npm test && npx tsc -b && npm run lint`.
- [ ] **Step 5: Commit** with message `refactor(extraction): key extraction runs by job`.

### Task 3: Chart shows one line per job, with a height prop

**Files:**
- Modify: `frontend/src/components/StageFlowChart.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: `latestExtractRun` from Task 2.
- Produces. `ExtractNodeInfo` becomes:
  ```ts
  export interface JobLine { id: string; label: string; status: StageState; counts: string | null; ready: boolean; scoring: string | null }
  export interface ExtractNodeInfo { jobs: JobLine[]; status: StageState }   // status = worst of the jobs: failed > review > running > ready > done > idle
  ```
  New props: `height?: number` (default 260) and `onOpenJob: (jobId: string) => void`.
- Remove `schemaLabel`. Its strings now come from `jobLabel` in Task 1. Update its import in `Extraction.tsx`: compile-only, mapping the current single job to one `JobLine`.
- The Extract & verify card shows one line per job: the label, then a state word and counts. Each line is a `nodrag` button calling `onOpenJob(id)`. A line with `ready: false` uses the warning tone.
- The Scoring card lists `scoring` per job. The Results card lists counts per job. Neither shows anything when no job has a run.
- Start on Extract & verify is enabled when any job is ready and has no run. The parent decides which jobs start.
- Export a pure `export function worstStatus(states: StageState[]): StageState` and test it in `frontend/tests/jobs.test.ts`: `["done","running"]` gives `"running"`; `["review","failed"]` gives `"failed"`; `[]` gives `"idle"`.

- [ ] **Step 1: Write the `worstStatus` test** and see it fail.
- [ ] **Step 2: Implement** the props, the job lines, `worstStatus` and the height. Keep the props stable.
- [ ] **Step 3: Verify** (the Global Constraints command).
- [ ] **Step 4: Commit** with message `feat(extraction): chart lists each job`.

### Task 4: Per-job Run and Review components

**Files:**
- Create: `frontend/src/pages/extraction/JobRun.tsx`, `frontend/src/pages/extraction/JobReview.tsx`
- Modify: `frontend/src/pages/Extraction.tsx` (move code out; keep behaviour for the current single job)

**Interfaces:**
- Produces:
  ```ts
  export function JobRun(p: { job: Job; runId: string; onRestarted: (runId: string) => void; onStatus: (s: { status: StageState; counts: string | null }) => void }): JSX.Element
  export function JobReview(p: { job: Job; runId: string; reviewer: string; onSourceOpen: (s: ActiveSource) => void }): JSX.Element
  ```
- `JobRun` owns `RunProgress`, `PipelineEditor` in run mode (restart → `onRestarted`), Refresh, CSV, and the manifest poll that today lives in `Extraction.tsx`. It reports its status upward through `onStatus`, called only when the value changes.
- `JobReview` owns everything the review side holds today:
  - Results and decisions state for its profile, and their loading.
  - `tileFilter`, `ReviewTiles` (hidden for TNFD), `ResultsTable`, `BatchSpendChart` / `TransitionPlanBatchOverview`, `SourcePanel` and `RunScoringPanel`.
  - It loads on mount, when `runId` changes, and on its own Refresh.
- `Extraction.tsx` renders `<JobRun>` and `<JobReview>` for the single current job. There must be no behaviour change, and `Extraction.tsx` shrinks.

- [ ] **Step 1: Move the code** into the two components.
- [ ] **Step 2: Verify** (the Global Constraints command), then load `#/extraction` in Chromium (`executablePath: '/opt/pw-browsers/chromium'`). Expect no console errors except failed requests.
- [ ] **Step 3: Commit** with message `refactor(extraction): per-job run and review components`.

### Task 5: Schema tab with several Custom schemas

**Files:**
- Create: `frontend/src/pages/extraction/SchemaPanel.tsx`
- Modify: `frontend/src/pages/Extraction.tsx`

**Interfaces:**
- Consumes: `CustomJob`, `addCustomJob` and `removeJob` from Task 1.
- Produces:
  ```ts
  export function SchemaPanel(p: { jobs: Job[]; onChange: (jobs: Job[]) => void; nextCustomId: () => string; defaultRequest: string }): JSX.Element
  ```
- One card per custom job:
  - A research request textarea, which updates `request`.
  - "Draft extraction schema", which calls `api.draftSchema(request)` and sets `schema`; the busy and error state are per card.
  - `SchemaFieldsEditor` when a schema exists.
  - "Remove", which calls `removeJob`. If the last custom job is removed while other jobs exist, the Custom profile becomes unticked. If it is the last job of all, show the returned error.
- "Add another schema" calls `addCustomJob(jobs, nextCustomId(), "")`.
- The first custom job's request defaults to `DEFAULT_CRITERIA`. Move that constant to `SchemaPanel.tsx` and export it as `defaultRequest`.

- [ ] **Step 1: Implement**, with `Extraction.tsx` holding `jobs` state and passing it in.
- [ ] **Step 2: Verify.** Run the command, then check in the browser that two schema cards can be added and one removed.
- [ ] **Step 3: Commit** with message `feat(extraction): several custom schemas`.

### Task 6: Overview tab, multi-select, start all, per-job Extract

**Files:**
- Create: `frontend/src/pages/extraction/Overview.tsx`, `frontend/src/pages/extraction/ScoringSummary.tsx`
- Modify: `frontend/src/pages/Extraction.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  ```ts
  export function ScoringSummary(p: { rows: { job: Job; runId: string }[]; onOpen: (jobId: string) => void }): JSX.Element
  export function Overview(p: { /* picker */ jobs: Job[]; onToggle: (profile: ExtractionProfile) => void; pickerError: string | null;
                                 allAuto: boolean; onAllAuto: (on: boolean) => void;
                                 chart: JSX.Element; runs: JSX.Element; selectedRunId: string | null; selectedProfile: ExtractionProfile | null;
                                 scoring: JSX.Element }): JSX.Element
  ```
- `ScoringSummary`:
  - For each row, call `api.getRunDecision(runId)`. A 404 or error means "None attached".
  - Columns: job label, framework name (`decision.framework_name` or the nearest field; read `RunDecision` in `types.ts`), "scored / total", and tiers as "Tier name: n" joined with " · ".
  - The last column is an "Open" button calling `onOpen(job.id)`.
  - Re-fetch a row when its run's status turns final. Simplest version: re-fetch every 10s while any row's run is running.
- `Extraction.tsx` changes:
  - **Tabs:** `overview` comes first and is the default.
  - **Step tabs:** they show a `← Overview` link and no chart.
  - **Chart:** rendered only inside Overview, with `height={420}` and `onOpenJob` opening Extract › Review for that job.
  - **Picker:** four checkboxes in the order Custom schema, Financials, TNFD, Transition Plan. Each shows its `about` text; Transition Plan also shows `TransitionPlanMethodology` when ticked.
  - **Ticking:** goes through `toggleProfile`. Unticking dispatches `jobsChanged`.
  - **TNFD period field:** shown on Companies when a TNFD job exists.
  - **Schema tab:** shown when any custom job exists.
  - **Extract › Setup:**
    - A job switch (`.view-toggle`) with the selected job's `PipelineEditor` and `ScoringTemplatePicker`. Settings are kept per job id in `Record<string, JobSettings>`.
    - Then **Start extraction** with `startsText(jobsToStart(...).length, inputCount)`.
    - Start calls `startJobs(jobsToStart(jobs, flow.extractRuns), startOne)`. `startOne` builds the request as today, with that job's profile, schema, `as_of`, `templateId` and step settings, plus the pre-step flags. It dispatches `extractStarted { job, runId }` for each started job and shows per-job errors next to the job switch.
  - **Extract › Run:** one `JobRun` per job with a run.
  - **Extract › Review:** a job switch, then the selected job's `JobReview`.
  - **FlowRuns on Overview:** `runTypes` = identity, discovery, and the run types of the selected jobs. The selected row's run feeds the per-company `PipelineEditor` on Overview, defaulting to `latestExtractRun(flow)`.
  - **Removed:** the old single-profile `view-toggle` and `mode` state. `initialProfile` seeds `initialJobs(...)`.

- [ ] **Step 1: Implement** `ScoringSummary`, then `Overview`, then rewire `Extraction.tsx`. Keep `Extraction.tsx` under about 500 lines by keeping panels in `pages/extraction/`.
- [ ] **Step 2: Verify** (the Global Constraints command).
- [ ] **Step 3: Commit.** Use 1–3 commits, e.g. `feat(extraction): overview tab and multi-profile runs`.

### Task 7: Browser check and screenshots

**Files:** none. Fixes go into the task they belong to.

- [ ] **Step 1: Start the servers.** Backend with scratch `ARP_*_DIR` directories and a dummy `ARP_ANTHROPIC_API_KEY`, then `npm run dev`. Use the setup in `/tmp/claude-0/-home-user-Agentic-Research-Pipeline/b918c8f8-b27b-508c-9ad1-5af384ddf4fc/scratchpad/shots/shots.py`.
- [ ] **Step 2: Walk the flow** and record PASS/FAIL for each check:
  - Overview loads first.
  - Ticking Financials, TNFD and Custom, then adding a second Custom schema, gives 4 jobs on the chart's Extract card.
  - Unticking everything shows "Pick at least one profile".
  - Start shows "Starts 3 runs × 2 companies" with one custom job undrafted, and starts three runs. Each run fails on its own line without an LLM.
  - Clicking a job line opens its Review.
  - The scoring summary shows "None attached".
  - At 375px there is no sideways scroll.
- [ ] **Step 3: Screenshots** of every tab and inner tab, saved to the scratchpad `shots-v2/`, then stop the servers.
