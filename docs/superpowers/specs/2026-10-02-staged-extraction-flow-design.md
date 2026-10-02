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
| Own documents | The Documents stage also accepts manual uploads by document type, next to discovery |
| Override marking | Review tabs show whether a value is system-extracted or human-edited |
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

Two levels. Top level: Companies → **Identify** → **Documents** → Schema (Custom only) → **Extract**.

The three process steps (Identify, Documents, Extract) each have inner tabs, with **Review** always last:

| Top tab | Inner tabs | Contents |
|---|---|---|
| Companies | none | Batch (`UniversePicker`) or single company, reporting period (TNFD only) |
| Identify | **Run** · **Review** | Run: start the identity run, results table, handover control. Review: the flagged companies, approve or edit website and CIK. |
| Documents | **Run** · **Review** | Run: start the discovery run, **add documents by hand** (see below), results table, handover control. Review: companies with no documents or an unreachable site, with a tick per company for what carries forward. |
| Schema | none | Research request, draft button, field editor (Custom only) |
| Extract | **Setup** · **Run** · **Review** | Setup: `PipelineEditor` settings, `ScoringTemplatePicker` (optional), **Start extraction**. Run: `RunProgress`, per-item flow chart, stop and restart, CSV. Review: results table with the review controls and source panel, charts, `RunScoringPanel`. |

The old Scoring, Run and Results top-level tabs are folded into Extract, so the bar stays at five tabs
(four for the built-in profiles). The Review tab on each step shows a count badge (reusing `.tab-badge`)
of items waiting on a person, and a ⏸ when the step is holding for review.

### What each Review tab reuses

| Step | Review source |
|---|---|
| Identify | `api.getIdentityReviewQueue` and `api.submitIdentityReview` (the Review Queue page's identity handling) |
| Documents | No review queue exists for discovery runs. Review is the per-company tick list over `api.getDiscoveryResults`; the accepted rows become the carried-over list |
| Extract | The existing results tables and the profile's review endpoints (`submit*Review`), unchanged |

Reviewer name uses the existing `ReviewerField` and `useReviewer`. The Review tab renders the same
components the Review Queue page uses, so decisions made in either place show up in both.

Tabs are numbered from the visible list, which removes the step-number arithmetic. Inner tabs that need a
run (Extract Run and Review) stay disabled until one exists. Inactive tabs stay mounted and hidden (`hidden` attribute),
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

## Manual documents (Documents stage)

Some companies' reports are not on a crawlable site, or the team already has the files. The Documents
tab Run view gets an **Add documents** area beside the discovery run, so a company can be filled by
discovery, by upload, or both.

- One drop zone per document type, using the existing `DocType` values: annual report (10-K),
  sustainability report, proxy (DEF-14A), earnings transcript, investor presentation, other.
- A company picker (from the Documents stage's input list) decides whom the files belong to.
- Each file goes to the existing `POST /api/documents/upload` (`company_id`, `doc_type`, `file`). That
  endpoint already stores it where discovery writes, so extraction cannot tell the two apart. No backend change.
- The results table counts uploaded files with discovered ones and marks the source of each ("uploaded" or
  "discovered"), so a company whose crawl found nothing but has uploads is **not** flagged.
- New client method: `api.uploadDocument(companyId, docType, file)`.

Not included: categories that have no `DocType` today (for example controversies or green revenue).
Adding them is a separate change to the `DocType` enum and its consumers.

## Review status tiles and override marking

**Status tiles.** The top of every Review tab (Identify, Documents, Extract) shows a row of tiles:
**Pending**, **Approved**, **Edited**, **Rejected**, **Flagged**, each with a count; clicking a tile filters the
list below it. Counts come from the data each Review tab already loads: the review queue and, for
Extract, `ReviewDecision` records (`approve`, `edit`, `reject`). The same counts feed the Review tab's badge.

**System vs override.** Wherever a review table shows a value, a marker says where it came from:

| Marker | Meaning | Source |
|---|---|---|
| System | The value the pipeline extracted or resolved | The record's own value |
| Edited | A person replaced it | `ReviewDecision.decision === "edit"`, showing `edited_value`, `reviewer` and `decided_at` |

An edited value displays the edited value, with the system value one click away ("was: …"), so a reviewer
can see what a person changed and undo by approving the original. The marker uses the shared
`ProposedTag`-style badge rather than a new component, and never relies on colour alone (it carries the
words System or Edited). Documents Review marks "uploaded" in the same place.

## Current runs panel (on every tab)

Every tab, top-level and inner, shows a **Current runs** panel under the flow chart, so what is running
and what ran is never hidden. One component, `FlowRuns.tsx`, fed by `api.listRuns(runType)` and polled
while any listed run is `running` or `pending`.

| Tab | Runs shown |
|---|---|
| Identify (Run, Review) | `identity` runs |
| Documents (Run, Review) | `discovery` runs |
| Extract (Setup, Run, Review) | The profile's extraction runs: `extraction`, `financials`, `tnfd` or `transition_plan` |
| Companies, Schema | All three kinds, compact, so the user sees the whole flow's activity |

Only runs started from this flow session, plus any run opened from Run History, are listed. The newest
run is first, and a running run is pinned above the rest. Each row shows:

| Detail | Source (`RunManifest`) |
|---|---|
| Run id, type, started time | `run_id`, `run_type`, `created_at` |
| Status and progress | `status`, `completed_count` of `company_count`, `failed_count`, `review_count` |
| Input | The universe (file name and count) and, for extraction, the schema name from `params` |
| Cost | `estimated_cost_usd`, `input_tokens` and `output_tokens`, `model` |
| Ended | `updated_at` once `status` is no longer running or pending, shown beside started time |
| Error | `error`, when set |
| Actions | **Stop** (`api.cancelRun`) while running, **Rerun** when finished, **Open** (selects that run in its tab), **Review →** when `review_count > 0` |

A **Batch / Single** filter above the list separates runs started on a list from runs started on one company
(`params`: a `universe_path` means batch, a `companies` array of one means single). **Rerun** starts a new run
with the same `params` (the same call that started it) and selects the new run; for Extract it reuses
`PipelineEditor`'s existing restart. Reruns never overwrite the old run, which stays in the list.

Selecting a row makes it the run the tab shows. Starting a new run selects it. The panel is collapsed to
a one-line summary ("1 running · 3 done") when the user collapses it, and the choice is remembered per tab
in `localStorage`, with the panel open when storage fails.

## Flow chart (overview)

A chart above the tab bar, always visible, showing the whole pipeline at stage level. It reuses ReactFlow
and the existing `.pipeline-card` and `status-*` styles, so it looks like the per-item chart in the Run
tab. It is built by a new component, `StageFlowChart.tsx`.

Nodes, left to right:

`Companies → Identify → Documents → Extract & verify → Scoring → Results`

(Schema appears as a node between Documents and Extract & verify for Custom only.) The last three nodes are
steps inside the Extract tab: a click on Extract & verify opens Extract › Setup, Scoring opens Setup, and
Results opens Extract › Review.

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

Clicking a node switches to its tab (a node in `review` state opens that step's Review tab). A line between two nodes is dashed when the stage in between is
skipped, and highlighted when a handover is waiting on the user.

**Stop** calls `api.cancelRun(runId)` on the stage's run (a cooperative stop: no further companies start).
After a stop the stage is `review` with the partial results and can be continued or re-run.
**Start** starts the stage's run, or, for Extract & verify, `api.startExtraction`.

The per-item chart in `PipelineEditor` stays on the Extract tab's Setup and Run inner tabs. Because Identify and
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
| `frontend/src/components/DocumentUpload.tsx` | New. Per-type drop zones and the company picker for the Documents tab. |
| `frontend/src/components/ReviewTiles.tsx` | New, small. The status tile row and the System / Edited marker, shared by the three Review tabs. |
| `frontend/src/components/FlowRuns.tsx` | New. The Current runs panel, filtered by run type. |
| `frontend/src/components/StepTabs.tsx` | New. The two-level tab bar with Review badges and arrow-key handling. |
| `frontend/src/components/IdentityReview.tsx` | New, small. The identity review list, taken from the Review Queue page's identity handling so both screens share it. |
| `frontend/src/pages/Extraction.tsx` | Hosts the tab bar, the chart and the hook. Existing cards move into tabs unchanged. |
| `frontend/src/api/client.ts` | Adds `uploadDocument`. |
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
4. A started run's `params` is enough to rerun it for identity and discovery runs; if not, the panel's Rerun uses the inputs the flow still holds and is disabled for runs started elsewhere.

If any of these fail, the plan lists a minimal backend change. None is expected.

## Open question for review

Documents have no review queue, so the Documents Review tab records a person's decision only as which
companies end up in the carried-over list. The repo's stance is that every automated suggestion is
reviewed by a person before it counts. If you want that decision logged with a reviewer name and time, as
the other review kinds are, that needs a small backend addition (a discovery review endpoint).
Default in this spec: **no backend, list-only**.

## Out of scope

- Scheduled discovery (stays on its own page).
- Per-company retry inside a stage.
- Putting the tab or stage into the URL hash.
- Applying the same layout to other screens.

## Testing

- Unit test for `stagedFlow.ts`: manual hold, automatic advance on clean, automatic hold on flagged,
  skip pass-through, stale marking on re-run.
- `tsc` and a production build.
- Upload one file of each type for a company the crawl finds nothing for, and confirm it is counted, marked "uploaded" and not flagged.
- Edit one value in Extract Review and confirm the tile counts, the Edited marker and the "was" value.
- Rerun a finished run from the panel and confirm a new row appears with the old one kept.
- Browser check that every tab shows its Current runs panel with the right run type, that a running run is
  pinned and Stop works, and that each step's Review tab shows its flagged items and badge.
- Browser check: Custom flow end to end in manual mode; one built-in profile in automatic mode; a flagged
  company holding the flow; Stop mid-run then Continue; the chart showing the drafted schema's name.
