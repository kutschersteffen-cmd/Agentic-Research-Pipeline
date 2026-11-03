# Authority taxonomy UI

Spec slug: `authority-taxonomy-ui`. Status: draft, awaiting owner approval.
Depends on: PR #325 (`authority-taxonomy-agent`, spec `2026-11-03-authority-taxonomy-agent-design.md`). Nothing
here is built before #325 is merged.

## Why

PR #325 adds a pausing authority-taxonomy run with three user checkpoints, but only through the API and the CLI.
UI was a non-goal there. Analysts need to drive the run from the app: start it, pick and add sources, review and
edit the quoted draft, then accept or cancel. The Taxonomy Library still offers the old `authority_source` create
flow (first ~20k characters, one quote per activity, no review step), which the new run supersedes.

## Goals

1. One screen in the Taxonomy Library that drives a run through its three checkpoints:
   1. **Start:** theme name, theme key (one of the 10 library themes, or none), scope text, source guidance,
      value-chain toggle.
   2. **Sources** (stage `awaiting_sources`): list candidates with title, summary, reason, fetchable flag, checklist
      coverage (`covers`) and a "from library" marker; tick candidates; add URLs; upload documents.
   3. **Review** (stage `awaiting_review`): view and edit the draft taxonomy document, save, then accept or cancel.
2. The slow steps (discovery, fetch and extraction) run in the background; the screen shows progress by polling and
   never fails on a proxy timeout.
3. A run survives a closed tab: the run id is in the URL, and opening the URL resumes at the current stage.
4. Uploaded documents land under `settings.documents_dir`, so the API accepts their paths.
5. It **replaces** the old `authority_source` create flow in `TaxonomyLibrary.tsx` (owner, 2026-11-03).

## Non-goals

- A list of past or open runs. Resuming is by URL only.
- Editing or adding quotes. Citations are shown read-only; they are verbatim, grounding-checked text.
- Managing the authority-source library (`arp authority-library propose|approve|reject` stays CLI-only).
- Changing the other derivation methods, `compare`/`merge`, ratification or the theme run.
- Showing a run's progress per source (only the stage is reported).

## Anti-goals

- A user edit that silently drops a citation, or lets an activity reach accept without one.
- A taxonomy saved without the user pressing Accept.
- A spinner that waits forever: a failed background step must show its error and let the user act.
- An uploaded file written outside `documents_dir`, or a run that reads one.

## Constraints

- Frontend: React + TypeScript in `frontend/src`, hash routing (`navigate(tab, ...params)` in `App.tsx`), API calls
  through `frontend/src/api/client.ts`, types from the generated `frontend/src/api/schema.gen.ts`.
- nginx (`frontend/nginx.conf`) sets no proxy timeout, so requests longer than the 60 s default fail with 504.
- The API from #325: `POST /api/authority-taxonomy/runs`, `GET /runs/{id}`, `POST /runs/{id}/sources`,
  `GET|PUT /runs/{id}/draft`, `POST /runs/{id}/accept`, `DELETE /runs/{id}`.
- `PUT /draft` rejects any activity with no citations (422).
- `POST /sources` accepts only file paths under `settings.documents_dir` (422 otherwise).

## Approaches (slow steps)

Discovery and extraction can take minutes, which is longer than the 60 s nginx default.

1. **Background task plus polling (chosen by the owner, 2026-11-03).** `POST /runs` and `POST /runs/{id}/sources`
   return as soon as the state is saved; the work runs as a background task; the UI polls `GET /runs/{id}`.
   Costs a small backend change; gains no timeouts and resume after a closed tab.
2. Keep the endpoints synchronous and raise the nginx timeout to ~15 min for `/api/authority-taxonomy/`. One config
   line, but the browser holds a request open for minutes, a closed tab leaves the user guessing, and a retry gets
   409 because the run has moved on.
3. Synchronous, but recover by re-reading the run on timeout. Does not work: `POST /runs` returns the run id only
   when discovery has finished.

## Design

### Backend change (follow-up PR after #325)

- `Stage` gains `discovering` and `extracting`. `RunState` gains `error: str | None = None`.
- `POST /runs` saves a state at `discovering`, schedules discovery in the background, and returns
  `{id, stage: "discovering"}` (still 201). When discovery finishes, the state moves to `awaiting_sources`.
- `POST /runs/{id}/sources` validates the request (non-empty, file paths under `documents_dir`, stage
  `awaiting_sources`) synchronously as today, then saves `extracting` and returns the state. When extraction
  finishes, the state moves to `awaiting_review`.
- A background failure keeps the run at the stage it came from (`awaiting_sources` for an extraction failure) with
  `error` set, so the user can change the selection and retry. A discovery failure moves the run to `failed` with
  `error`, since there is nothing to retry from; the UI offers "start again" with the same inputs. The next
  successful step clears `error`.
- `cancel` also accepts `discovering` and `extracting`; a background step that finishes after a cancel does not
  overwrite the `cancelled` state.
- The CLI keeps its synchronous behaviour (it calls the run functions directly).
- Regenerate `openapi.json` and `schema.gen.ts`.

### Upload

The screen reuses `POST /api/documents/upload` with `company_id = "_authority"` and `doc_type = "other"`. Files
land in `documents_dir/_authority/other/`, never overwrite, and respect `max_upload_bytes`. The returned `path`
goes into the `files` list of `POST /sources`. Accepted file types in the picker are `.pdf`, `.txt` and `.md`,
which are the types the run can read. No backend change.

### Routing

- `#/taxonomy/authority` opens the start form.
- `#/taxonomy/authority/<runId>` loads the run and shows the screen for its stage.
- The old "Authority source" option in the Taxonomy Library create flow is removed. Its slot links to the new
  screen. Components only the old flow used are deleted. `SourceDiscoveryPanel` stays if the thematic-fund
  discovery still uses it.

### Screen per stage

- **Start form.** Theme name (required), theme key (a select of the 10 keys from `library.THEME_KEYS` plus "none",
  hard-coded in the frontend with readable labels), scope (textarea), source guidance (textarea), value-chain
  checkbox. Submitting calls `POST /runs` and navigates to `#/taxonomy/authority/<id>`.
- **discovering / extracting.** A progress message with the theme name and what is happening, plus a Cancel button.
  Poll `GET /runs/{id}` every 3 s while the tab is visible. Stop polling when the stage changes.
- **awaiting_sources.** A card per candidate: title (linked to the URL, opens in a new tab), source type, summary,
  reason, a "from library" badge, a "not fetchable" warning when `fetchable` is false, and checklist coverage as 8
  chips (`theme_description`, `activities`, `boundaries`, `technologies`, `definitions`, `sector_codes`,
  `value_chain`, `thresholds`), filled when the item is in `covers`. A candidate starts ticked when it is both
  `from_library` and `fetchable`; all others start unticked. Below the list: "Add URL" (input plus list of added URLs, removable) and
  "Upload document" (file input, list of uploaded files, removable from the selection). "Build draft" is disabled
  until at least one source is selected and no upload is in progress. If `error` is set, show it above the list.
- **awaiting_review.** The draft document, editable, with Save, Accept and Cancel. See below.
- **accepted.** A confirmation with a link to the new taxonomy in the Taxonomy Library (`taxonomy_id`).
- **cancelled / failed.** A message (and `error` for failed) with "Start a new run", which opens the start form
  prefilled with this run's inputs.

### Review screen

Sections, in order:

1. **Theme description**: editable textarea. Read-only scope shown above it.
2. **Technologies**: list of name plus citations; name editable; item removable.
3. **Definitions**: term and text editable; citations shown; item removable.
4. **Activities**: one block per activity with name, in-scope and out-of-scope description, criteria (text
   editable, citations shown, removable), seed keywords (chip editor: add/remove), value-chain role (select: core,
   upstream, enabling), sector codes (list of `system code` with an origin badge `source` / `map_standards` /
   `exiobase`; removable, not addable, since the schema has no origin for a hand-added code: builder-chosen
   default), citations, and out-of-scope citations. Activities are removable; there is no "add activity",
   since a new activity has no quote and the API would reject it.
5. **Thresholds**: separate section, text editable, citations shown, removable. Labelled as not used for activity
   matching.
6. **Citations**: each citation shows the quote, the source URL (linked) and the location, wherever it appears.
7. **Checklist report**: a table, one row per source (URL or file name), one column per checklist item, showing
   found / not in source.
8. **Notes**: run notes (`notes`, for example "Could not read: …"), read-only.

Behaviour:

- Edits are local until Save, which calls `PUT /draft`. A 422 shows the server message. Leaving the page with
  unsaved edits asks for confirmation.
- Accept saves first if there are unsaved edits, then calls `POST /accept`.
- Cancel asks for confirmation, then calls `DELETE /runs/{id}`.
- A 409 (wrong stage, for example another tab accepted) reloads the run and shows its current stage.

## Testing

- Backend follow-up: unit tests for the new stages, background failure (`error` set, stage kept), cancel during a
  background step, and the API returning before the work finishes.
- Frontend: component tests in the existing `frontend/tests` style for each stage view, the coverage chips, the
  upload-then-select path, Save/Accept/Cancel calls and the 409 reload, with the API client mocked.
- One end-to-end walk in the running app with a stubbed LLM, through start → sources → review → accept.

## Left to the builder

- Layout, styling and copy within the existing design system (`DESIGN.md`).
- Readable labels for the 10 theme keys.
- Component split and file names.

## Open points

1. Who may accept: the authority-taxonomy router has no role check, like `taxonomies.py`. The UI follows the API
   (builder-chosen default; a role check is a separate change).

## Acceptance

All rows are `unit` until `HOLDOUT_TOKEN` is set (owed to `holdout`). Backend rows use a stubbed LLM and search
client; UI rows run in the app started by `backend/scripts/e2e_stack.sh up` with stubbed model calls.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A discovery stub that blocks until released | `POST /api/authority-taxonomy/runs` with a valid body | Response 201 with `stage == "discovering"` arrives before the stub is released | unit |
| AC-2  | A run at `discovering` whose discovery finishes with 2 candidates | `GET /runs/{id}` | 200, `stage == "awaiting_sources"`, `candidates` has 2 items, `error` is null | unit |
| AC-3  | A run whose discovery raises `RuntimeError("boom")` | `GET /runs/{id}` | 200, `stage == "failed"`, `error` contains `boom` | unit |
| AC-4  | A run at `awaiting_sources`, extraction stub blocks until released | `POST /runs/{id}/sources` with one URL | Response 200 with `stage == "extracting"` arrives before the stub is released | unit |
| AC-5  | A run at `awaiting_sources` | `POST /runs/{id}/sources` with a file path outside `documents_dir` | 422, `detail` starts with `file not allowed:`; `GET /runs/{id}` still shows `awaiting_sources` | unit |
| AC-6  | A run whose extraction reads no source | `GET /runs/{id}` after the step ends | `stage == "awaiting_sources"`, `error` contains `no selected source could be read` | unit |
| AC-7  | A run at `extracting` | `DELETE /runs/{id}`, then extraction finishes | DELETE returns 204; `GET /runs/{id}` shows `stage == "cancelled"` and `draft` null | unit |
| AC-8  | A run at `awaiting_review` after a failed earlier extraction | `GET /runs/{id}` | `error` is null | unit |
| AC-9  | The app is open | Open `#/taxonomy/authority` | A form with fields Theme name, Theme key (11 options: 10 themes plus "None"), Scope, Source guidance, a Value chain checkbox and a Start button | evaluator |
| AC-10 | The start form with Theme name empty | Click Start | No request is sent; the Theme name field shows a required-field message | evaluator |
| AC-11 | The start form filled in | Click Start | The URL becomes `#/taxonomy/authority/<runId>` and a progress message with the theme name and a Cancel button is shown | evaluator |
| AC-12 | A run at `awaiting_sources` with one candidate `from_library: true, fetchable: true` and one `from_library: false, fetchable: false` | Open its URL | 2 cards; the first is ticked and shows a library badge; the second is unticked and shows a "not fetchable" warning | evaluator |
| AC-13 | A candidate with `covers == ["activities", "thresholds"]` | Its card is shown | 8 checklist chips, exactly 2 of them (activities, thresholds) marked as covered | evaluator |
| AC-14 | A run at `awaiting_sources` | Upload `note.txt` via Upload document | The file is listed as selected; the request to `/api/documents/upload` sends `company_id=_authority` and the returned path starts with the `documents_dir/_authority/other/` path | unit |
| AC-15 | Upload finished, file selected, all candidates unticked, one URL added | Click Build draft | `POST /sources` body is `{"urls": [<added url>], "files": [<upload path>]}` | unit |
| AC-16 | A run at `awaiting_sources` with nothing ticked, no URL, no file | The sources screen is shown | Build draft is disabled | evaluator |
| AC-17 | A run at `awaiting_review` with a draft of 2 activities, 1 threshold and a checklist report for 2 sources | Open its URL | Sections Theme description, Technologies, Definitions, Activities (2 blocks), Thresholds (1 item), Checklist report (2 rows × 8 columns), Notes | evaluator |
| AC-18 | The review screen | Look at any citation | Its quote, a link to its source URL, and its location are shown; the quote is not editable | evaluator |
| AC-19 | The review screen | Look at a sector code with `origin == "exiobase"` | It shows its system, code and an `exiobase` origin badge; there is no control to add a sector code | evaluator |
| AC-20 | The review screen | Look for an "add activity" control | None exists | evaluator |
| AC-21 | The review screen, activity 1's value-chain role changed to `upstream` | Click Save | `PUT /draft` is sent; reloading the page shows `upstream` for activity 1 | evaluator |
| AC-22 | The review screen, `PUT /draft` answers 422 `activity X has no citation` | Click Save | That message is shown on the screen; the edits stay in the form | unit |
| AC-23 | The review screen with unsaved edits | Click Accept | `PUT /draft` is sent before `POST /accept`; then a confirmation with a link to taxonomy `<taxonomy_id>` is shown | unit |
| AC-24 | The review screen | Click Cancel, then confirm | `DELETE /runs/{id}` is sent; the screen shows the cancelled message and a "Start a new run" button | evaluator |
| AC-25 | A cancelled run | Click "Start a new run" | The start form opens with that run's theme name, theme key, scope, guidance and value-chain value filled in | evaluator |
| AC-26 | The review screen open in two tabs, accepted in tab 1 | Click Save in tab 2 | Tab 2 shows the accepted confirmation (409 handled by reloading the run) | unit |
| AC-27 | A run at `discovering` | The screen polls | `GET /runs/{id}` is called every 3 s ± 0.5 s and stops once the stage is `awaiting_sources` | unit |
| AC-28 | The review screen with unsaved edits | Navigate to another tab of the app | A confirmation prompt appears; dismissing it keeps the review screen | evaluator |
| AC-29 | The Taxonomy Library create flow | Open it | No "Authority source" option inside the old create flow; an entry opens `#/taxonomy/authority` | evaluator |

Must not change:

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-30 | The CLI | `arp taxonomy author start …` then `select` with a stub LLM | The command returns only after the step finishes and prints the same output as on #325 | unit |
| AC-31 | The other create methods in the Taxonomy Library | Create a taxonomy with each remaining method | Same requests and results as on `main` before this change | unit |
| AC-32 | `POST /api/documents/upload` | Upload with any `company_id` | Same response and file location as on `main` | unit |
