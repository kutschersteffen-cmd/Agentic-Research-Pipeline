# Extraction overview and multi-profile runs: design

Status: draft for review · Extends `2026-10-02-staged-extraction-flow-design.md` (the staged flow)

## Goal

1. Give the Extraction screen a first page, **Overview**, that shows the flow chart and works as the
   place to navigate from and to monitor everything running.
2. Let one flow run **any combination** of extraction profiles on the same companies, including
   **several Custom schemas**, with scoring shown per run on the Overview.

## Decisions

| Question | Decision |
|---|---|
| Where the chart lives | Only on the Overview tab (option a). Step tabs get a "← Overview" link |
| Landing tab | Overview |
| Profile choice | Multi-select. Any combination of Financials, TNFD, Transition Plan and Custom; at least one |
| Custom schemas | Several per flow. Each Custom schema is its own run |
| How combinations run | One extraction run per selected job, all on the same company list. No backend change |
| Onboarding | Companies → Identify → Documents run once for the whole selection |
| Scoring | One framework per job, chosen in Extract › Setup; a scoring summary per run on the Overview |

## Jobs

A **job** is one extraction run to start: a built-in profile, or one Custom schema.

```ts
type Job =
  | { id: "financials" | "tnfd" | "transition_plan"; profile: "financials" | "tnfd" | "transition_plan" }
  | { id: string /* "custom:<n>" */; profile: "custom"; schema: DataPointSchema | null; request: string };
```

- The profile picker ticks built-in jobs on or off. "Custom schema" ticked means at least one Custom job
  exists; the Schema tab adds and removes them.
- Each job keeps its own Pipeline settings (`StepSettings`) and scoring framework (`templateId`).
- A job's label: the profile name, or the Custom schema's `name` ("Custom: Green capex"), or
  "Custom (no schema yet)".
- The entry point `initialProfile` (the Transition Plan menu item) starts with that one job ticked.

## Tabs

0. **Overview** (landing) · 1. Companies · 2. Identify · 3. Documents · 4. Schema (when a Custom job
exists) · 5. Extract (Setup · Run · Review).

Step tabs no longer show the chart. Each has a "← Overview" link at the top. The tab bar's ✓ / ⏸ / !
marks stay.

## Overview

Top to bottom:

1. **Profile picker**: four checkboxes (Custom schema, Financials, TNFD, Transition Plan), each with its
   one-line description. Unticking the last one is refused with "Pick at least one profile". The
   "Run all automatically" switch sits beside it.
2. **Flow chart**, about 420px tall (was 260px). Same nodes and controls as before. Changes:
   - **Extract & verify** lists every job on its own line: label, then status and counts
     ("Financials ✓ 50/50", "TNFD running 12/50", "Custom: Green capex · needs review").
     Clicking a line opens Extract › Review with that job selected.
   - **Scoring** and **Results** show per-job counts the same way.
   - Start on Extract & verify starts every job that has no run yet (see "Starting").
3. **Scoring summary**: one row per job with a run. Columns: job, framework (or "None attached"),
   companies scored / total, tier distribution (from `api.getRunDecision(runId).result.tier_summary`),
   and "Open" to Extract › Review for that job. Rows load when the run finishes, and refresh with the
   runs panel's poll.
4. **Current runs**: identity, discovery and every job's extraction runs in one list (the existing
   panel with all run types).
5. **Per-company steps**: the existing `PipelineEditor` step chart for the run selected in Current runs
   (default: the newest extraction run). Hidden when there is no extraction run.

## Schema tab (Custom jobs)

- A list of Custom schemas, one card each: research request, "Draft extraction schema", the field
  editor, and "Remove".
- "Add another schema" adds a card (and a Custom job).
- Removing the last card unticks Custom on the picker.
- A Custom job with no schema cannot start; the chart shows it as "Custom (no schema yet)" in the
  warning tone.

## Extract tab

- **Setup**: a job switch (one button per job). The selected job shows its Pipeline card and its
  scoring framework picker (`ScoringTemplatePicker` with that job's run type and, for Custom, its field
  names). Below the switch: **Start extraction** and the line "Starts N runs × M companies".
- **Run**: one block per job with a run: `RunProgress`, its own Stop, restart via `PipelineEditor`,
  Refresh and CSV.
- **Review**: the job switch, then the tiles and the results table for the selected job, as today
  (System / Edited markers, tile filtering, `RunScoringPanel`).

## Starting

- Start extraction starts one run per job that is ready (built-in, or Custom with a schema) and has no
  run in this flow yet. Jobs already started are left alone; restart stays per job in Extract › Run.
- Every run gets the same input (`extractInputs` → `universe_path` or `companies`) and the same pre-step
  flags as today. TNFD jobs also get `as_of`.
- Runs start one after another, not in parallel, so a failure is attributed to its job. A failed start
  shows its error on that job and does not stop the others.

## State changes

- `FlowState.extractRunId` becomes `extractRuns: Record<string, string>` (job id → run id).
- `extractStarted` carries `{ job, runId }` and appends to `runIds` as before.
- `profileChanged` becomes `jobsChanged { jobIds }`: drops runs whose job no longer exists; stages are
  untouched.
- `extractStale` stays one flag for the whole selection.
- The Overview, chart and Extract tab read `extractRuns`; `FlowRuns` runTypes on Overview are identity,
  discovery and every selected job's run type.

## Out of scope

- One backend run that covers several profiles.
- Saving job combinations or schemas as presets (the schema library is a separate feature).
- Comparing results across jobs in one table.

## Testing

- Reducer tests: `extractStarted` per job, `jobsChanged` dropping removed jobs' runs, `runIds`.
- Pure helper tests: job labels, "ready to start" per job, starts-count text.
- Browser: Overview loads first; tick Financials + TNFD + two Custom schemas; Start launches four runs
  (they fail without an LLM key, each shown on its own line); clicking a job line opens its Review;
  phone width has no sideways scroll; screenshots of every tab.
