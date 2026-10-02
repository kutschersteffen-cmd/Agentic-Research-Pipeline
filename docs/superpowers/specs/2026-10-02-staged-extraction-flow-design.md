# Staged extraction flow: design

Status: draft for review · Extends the Extraction screen (`frontend/src/pages/Extraction.tsx`)

## Goal

Make extraction one guided flow instead of one long page and three separate screens. The flow starts
at entity identification and document download, then runs extraction, verification, scoring and
review. The user can see at a glance which steps are active and which schema is in use. They can start
and stop steps, review each checkpoint, and choose per step whether the next one starts by hand or
automatically.

## Decisions

| Question | Decision |
|---|---|
| Where the steps live | Tabs on the Extraction screen, one per step |
| Identify and Documents | Own checkpoint stages, run and reviewed **before** extraction (not inline pre-steps) |
| Handover between stages | Per-stage toggle: **Manual** (default), **Automatic**, or **Skip** |
| Automatic handover | Continues only when nothing is flagged or failed; otherwise holds and says why |
| Overview | A flow chart above the tabs: every stage, its state, the schema in use, start and stop |
| Backend | No new endpoints expected (see "Backend check") |
| Profiles | Custom, Financials, TNFD and Transition Plan keep working; the profile toggle stays above the tabs |

## Current state (what this changes)

- `Extraction.tsx` stacks eight cards in one page. Step numbers shift by profile (five for Custom, three
  for the others) through `scoringStepNumber` and `universeStepNumber`.
- Identity Resolution and Document Discovery are separate pages in the "Onboard issuers" hub. Each has
  its own `UniversePicker` and run, and they pass results onward by hand ("Send to Document Discovery").
- An extraction run can also run four optional pre-steps inline (`PRE_STEPS` in
  `backend/arp/extraction/steps.py`: identity, content_search, document_mgmt, parse_index). They are
  hidden toggles inside the Pipeline card, with no review between them. A company that fails one is
  stopped with an error report.
- `PipelineEditor` already draws the per-item graph with ReactFlow, shows status and counts per step, and
  can stop (`api.cancelRun`) and restart a run.

## Tabs

Companies → **Identify** → **Documents** → Schema (Custom only) → Extract & verify → Scoring → Run → Results

| Tab | Contents |
|---|---|
| Companies | Batch (`UniversePicker`) or single company, reporting period (TNFD only) |
| Identify | Identity stage: run, results table, approve or edit flagged rows, handover control |
| Documents | Discovery stage: run, results table, tick companies to carry forward, handover control |
| Schema | Research request, draft button, field editor (Custom only) |
| Extract & verify | `PipelineEditor` for this run's extraction and verification settings |
| Scoring | `ScoringTemplatePicker` (optional) and **Start extraction** |
| Run | `RunProgress`, per-item flow chart, stop and restart, refresh, CSV |
| Results | Charts, results table, source panel, `RunScoringPanel` |

Tabs are numbered from the visible list, which removes the step-number arithmetic. Run and Results stay
disabled until an extraction run exists. Inactive tabs stay mounted and hidden (`hidden` attribute),
because `UniversePicker` and `SchemaFieldsEditor` keep local state. Tabs use `role="tablist"`,
`aria-selected` and arrow-key navigation. Switching profile resets to Companies, as `switchMode` already
clears the run.

## Stage model

```ts
type StageId = "identify" | "documents";
type Handover = "manual" | "auto" | "skip";
type StageState = "idle" | "running" | "review" | "ready" | "done" | "skipped" | "stale" | "failed";

interface Stage {
  handover: Handover;          // default "manual"
  state: StageState;
  runId: string | null;        // the identity or discovery run
  output: { path: string; count: number } | null; // the list handed to the next stage
  flagged: number;             // rows needing a person
}
```

A small hook, `useStagedFlow()`, in `frontend/src/lib/stagedFlow.ts` owns the working list and both
stages. Each stage reads the previous stage's output as its input.

State meanings:

| State | Meaning |
|---|---|
| idle | Not started |
| running | Run in progress |
| review | Run finished with flagged or failed rows; waiting on a person |
| ready | Finished and clean; waiting on the Continue click (manual mode) |
| done | Output handed to the next stage |
| skipped | Stage set to Skip; its input passes through unchanged |
| stale | An earlier stage was re-run; this stage's output is out of date. Nothing re-runs by itself |
| failed | Run itself failed |

### Handover rules

1. **Manual:** a **Continue →** button builds the output list from the approved rows. Identify uses
   resolved and approved companies, via `api.getEnrichedUniverse` then `api.universeFromCompanies`.
   Documents uses companies with at least one document. The user can untick companies first.
2. **Automatic:** when the run finishes with `flagged === 0` and no failures, the stage builds its output and
   advances the active tab. With any flagged or failed row it enters `review` and shows the reason
   ("3 companies need review"), and the flow waits.
3. **Skip:** the stage does not run. The Companies output passes straight through. A skipped Identify
   still gives Documents a list with whatever website values the file had.
4. A **Run all automatically** switch above the tabs sets both stages to Automatic. It is off by default.
5. Re-running a stage marks every later stage `stale`. A stale stage keeps its results visible but cannot
   hand over until it is re-run or the user confirms "use anyway".

## Flow chart (overview)

A chart above the tab bar, always visible, showing the whole pipeline at stage level. It reuses ReactFlow
and the existing `.pipeline-card` and `status-*` styles, so it looks like the per-item chart in the Run
tab. It is built by a new component, `StageFlowChart.tsx`.

Nodes, left to right:

`Companies → Identify → Documents → Extract & verify → Scoring → Results`

(Schema appears as a node between Documents and Extract & verify for Custom only.)

Each node card shows:

| Part | Content |
|---|---|
| Title and state | Stage name and a status dot: idle, running (spinner), review, ready, done, skipped (dashed), stale, failed. Same vocabulary as `PipelineEditor`. |
| Count | "47/50 resolved", "212 documents · 3 companies none", "38 of 50 extracted" |
| Mode | The handover mode for Identify and Documents: Manual, Auto or Skip, clickable to change |
| Controls | **Start** (when idle, ready or stale), **Stop** (when running), **Continue →** (when ready, manual) |

The **Extract & verify** node shows **the schema in use**:

| Profile | Shown |
|---|---|
| Custom | The drafted schema's `name`, field count and `created_at`. "No schema yet" in a warning tone, with the node disabled, until one exists. |
| Financials | "Financials: segments, CapEx, R&D" |
| TNFD | "TNFD: 14 recommendations + core metrics" |
| Transition Plan | "Transition Plan: 64 indicators" |

Clicking a node switches to its tab. A line between two nodes is dashed when the stage in between is
skipped, and highlighted when a handover is waiting on the user.

**Stop** calls `api.cancelRun(runId)` on the stage's run (a cooperative stop: no further companies start).
After a stop the stage is `review` with the partial results and can be continued or re-run.
**Start** starts the stage's run, or, for Extract & verify, `api.startExtraction`.

The per-item chart in `PipelineEditor` stays on the Extract & verify and Run tabs. Because Identify and
Documents now run as checkpoints, the extraction run starts with `pre_identity_enabled`,
`pre_content_search_enabled` and `pre_document_mgmt_enabled` set to `false` (see below).
`parse_index` stays inline.

## Extraction run configuration

On **Start extraction** the page sends the Documents output as `universe_path`, or the Companies list if
Documents was skipped, with `step_settings` extended by the three pre-step flags above. If a stage was
skipped, its pre-step flag is left to the user's own setting in the Pipeline editor. The extraction then
reads the documents already on disk through the document registry. A company that has no documents never
reaches extraction (it is unticked at the Documents checkpoint), so the inline error report for "no
documents" no longer appears for those.

## Code structure

| File | Change |
|---|---|
| `frontend/src/components/IdentityStage.tsx` | New. Body of `IdentityResolution.tsx`: run, results, review actions, handover control. Takes an input list and an `onOutput` callback. |
| `frontend/src/components/DocumentsStage.tsx` | New. Body of `DocumentDiscovery.tsx`'s manual-run card, same shape. The schedule and event feed stay in the page. |
| `frontend/src/pages/IdentityResolution.tsx`, `DocumentDiscovery.tsx` | Become thin wrappers around the stage components, so the "Onboard issuers" hub keeps working with no duplicated logic. |
| `frontend/src/lib/stagedFlow.ts` | New. `useStagedFlow()` hook and the handover rules. Pure logic, unit-testable. |
| `frontend/src/components/StageFlowChart.tsx` | New. The overview chart. |
| `frontend/src/pages/Extraction.tsx` | Hosts the tab bar, the chart and the hook. Existing cards move into tabs unchanged. |
| `frontend/src/index.css` | A few lines for the tab bar and stage card extras. The `.sub-nav` and `.nav-tab` styles are reused. |

## Backend check

The design relies on existing endpoints: `startIdentityRun`, `getIdentityResults`, `getEnrichedUniverse`,
`universeFromCompanies`, `startDiscoveryRun`, `getDiscoveryResults`, `startExtraction`, `cancelRun`.

To confirm while planning:
1. The identity review actions (approve, edit website or CIK) are reachable from the stage without leaving
   the page; if only the Review Queue page offers them, the stage links there instead.
2. Discovery runs write downloaded documents where the extraction's document registry reads them from.
   `_document_mgmt` uses `settings.documents_dir`, which suggests yes.
3. `step_settings` accepts the three `pre_*_enabled` flags per run.

If any of these fail, the plan lists a minimal backend change. None is expected.

## Out of scope

- Scheduled discovery (stays on its own page).
- Per-company retry inside a stage.
- Putting the tab or stage into the URL hash.
- Applying the same layout to other screens.

## Testing

- Unit test for `stagedFlow.ts`: manual hold, automatic advance on clean, automatic hold on flagged,
  skip pass-through, stale marking on re-run.
- `tsc` and a production build.
- Browser check: Custom flow end to end in manual mode; one built-in profile in automatic mode; a flagged
  company holding the flow; Stop mid-run then Continue; the chart showing the drafted schema's name.
