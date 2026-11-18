# Authority taxonomy UI

Spec slug: `authority-taxonomy-ui`. Status: approved by the owner, 2026-11-03.
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
   2. **Sources** (stage `awaiting_sources`): list candidates with title, source type, summary, reason, fetchable
      flag, checklist coverage (`covers`) and a "from library" marker; tick candidates; add URLs; upload documents.
   3. **Review** (stage `awaiting_review`): view and edit the draft taxonomy document, save, then accept or cancel.
2. The slow steps (discovery, fetch and extraction) run in the background; the screen shows progress by polling and
   never fails on a proxy timeout.
3. A run survives a closed tab: the run id is in the URL, and opening the URL resumes at the current stage, with the
   last source selection restored.
4. Uploaded documents land under `settings.documents_dir`, so the run accepts their paths.
5. It **replaces** the old `authority_source` create flow in `TaxonomyLibrary.tsx` (owner, 2026-11-03).

## Non-goals

- A list of past or open runs. Resuming is by URL only.
- Editing or adding quotes. Citations are shown read-only; they are verbatim, grounding-checked text.
- Managing the authority-source library (`arp authority-library propose|approve|reject` stays CLI-only).
- Changing the other derivation methods, `compare`/`merge`, ratification or the theme run.
- Progress per source (only the stage is reported).
- A role check on the authority-taxonomy API. The router has none, like `taxonomies.py`; the UI follows the API.

## Anti-goals

- A user edit that silently drops a citation, or lets an activity reach accept without one.
- A taxonomy saved without the user pressing Accept.
- A spinner that waits forever: a failed or interrupted background step must show its error and let the user act.
- An uploaded file written outside `documents_dir`, or a run that reads one.

## Constraints

- Frontend: React + TypeScript in `frontend/src`, hash routing (`navigate(tab, ...params)` in `App.tsx`, the
  Taxonomy Library tab id is `taxonomy`), API calls through `frontend/src/api/client.ts`, types from the generated
  `frontend/src/api/schema.gen.ts`.
- nginx (`frontend/nginx.conf`) sets no proxy timeout, so requests longer than the 60 s default fail with 504.
- The API from #325: `POST /api/authority-taxonomy/runs`, `GET /runs/{id}`, `POST /runs/{id}/sources` (body
  `{"urls": [...], "files": [...]}`), `GET|PUT /runs/{id}/draft`, `POST /runs/{id}/accept`, `DELETE /runs/{id}`.
- `PUT /draft` rejects any activity with no citations (422 `activity <name> has no citation`).
- `POST /sources` accepts only file paths under `settings.documents_dir` (422 `file not allowed: <name>`).
- `POST /api/documents/upload` cannot be reused: its `safe_id` check (`backend/arp/storage/safe_path.py`) rejects a
  `company_id` starting with `_`, and a plain id would read as a company to the per-company document code.
- The in-process job launcher loses background work on a process restart; `run_alive` (`orchestration/jobs.py`)
  tells whether a run's worker still holds its lease.

## Approaches

### Slow steps

Discovery and extraction can take minutes, which is longer than the 60 s nginx default.

1. **Background task plus polling (chosen by the owner, 2026-11-03).** `POST /runs` and `POST /runs/{id}/sources`
   return as soon as the state is saved; the work runs as a background task; the UI polls `GET /runs/{id}`.
   Costs a small backend change; gains no timeouts and resume after a closed tab.
2. Keep the endpoints synchronous and raise the nginx timeout to ~15 min for `/api/authority-taxonomy/`. One config
   line, but the browser holds a request open for minutes, a closed tab leaves the user guessing, and a retry gets
   409 because the run has moved on.
3. Synchronous, but recover by re-reading the run on timeout. Does not work: `POST /runs` returns the run id only
   when discovery has finished.

### Uploads

1. **Own endpoint `POST /api/authority-taxonomy/uploads` (chosen by the owner, 2026-11-03).** Part of the same
   backend follow-up; touches neither the shared id check nor company folders.
2. Reuse `/api/documents/upload` with a plain id like `authority-sources`. No backend change, but the folder reads
   as a company and could clash with a real one.
3. Loosen `safe_id` to allow a leading `_`. Smallest diff, but changes a security check every file store uses.

## Design

### Backend change (follow-up PR after #325)

- `Stage` gains `discovering`, `extracting` and `failed`. `RunState` gains `error: str | None = None` and
  `selection: SourcesRequest | None = None` (the last `{urls, files}` sent to `POST /sources`).
- `POST /runs` saves a state at `discovering`, schedules discovery in the background, and returns
  `{id, stage: "discovering"}` (still 201). When discovery finishes, the state moves to `awaiting_sources`.
- `POST /runs/{id}/sources` validates the request (non-empty, file paths under `documents_dir`, stage
  `awaiting_sources`) synchronously as today, then saves `extracting` with `selection` set and returns the state.
  When extraction finishes, the state moves to `awaiting_review`.
- Failures:
  - Discovery raises: stage `failed`, `error` = the exception message. Nothing to retry from; the UI offers "Start a
    new run" with the same inputs.
  - Extraction raises (including "no selected source could be read"): stage back to `awaiting_sources`, `error` = the
    message, `selection` kept, so the user can change it and retry.
  - The next successful step clears `error`.
- Interrupted work (author's call, using the existing pattern): `GET /runs/{id}` on a run at `discovering` or
  `extracting` whose `run_alive` is false applies the failure rule above with `error` =
  `interrupted by a server restart`, saves it, and returns it. A step that started less than the lease grace period
  ago counts as alive, measured from the step's own start (not the run's creation, which is old by the time
  extraction starts), so the UI's first poll never flips a healthy run.
- `cancel` also accepts `discovering` and `extracting`. A background step that finishes after a cancel does not
  overwrite the `cancelled` state.
- `POST /api/authority-taxonomy/uploads` (multipart `file`): accepts `.pdf`, `.txt`, `.md` (else 422
  `unsupported file type`), respects `max_upload_bytes` (else 413), passes the name through `safe_filename`, writes to
  `documents_dir/_authority/`, never overwrites (`-2`, `-3` suffix as in `documents.py`), returns
  `{"path": "<absolute path>"}`.
- The CLI keeps its synchronous behaviour (it calls the run functions directly).
- Regenerate `openapi.json` and `schema.gen.ts`; add the new requests to `frontend/src/api/contract.ts`.

### Routing

- `#/taxonomy/authority` opens the start form.
- `#/taxonomy/authority/<runId>` loads the run and shows the screen for its stage.
- The "Authority source" option is removed from the Taxonomy Library create flow. A "Build from authority sources"
  button sits in the Taxonomy Library page header, next to the existing create controls, and opens
  `#/taxonomy/authority`. Components and client calls only the old flow used are
  deleted. `SourceDiscoveryPanel` stays while thematic-fund discovery uses it.

### Screen per stage

- **Start form.** Theme name (required; empty shows the inline text `Theme name is required` and sends nothing),
  theme key (a select of the 10 keys from `library.THEME_KEYS` plus "None", hard-coded in the frontend with readable
  labels), scope (textarea), source guidance (textarea), value-chain checkbox, Start button. Start calls
  `POST /runs` and navigates to `#/taxonomy/authority/<id>`.
- **discovering / extracting.** A message containing the theme name and what is happening, plus a Cancel button.
  Poll `GET /runs/{id}` every 3 s while `document.visibilityState` is `visible`; poll once on becoming visible again.
  Stop polling when the stage is neither `discovering` nor `extracting`.
- **awaiting_sources.** If `error` is set, it is shown above the list. A card per candidate: title (link to the URL,
  `target="_blank"`), source type, summary, reason, a "From library" badge when `from_library`, a "Not fetchable"
  warning when `fetchable` is false, and 8 checklist chips (`theme_description`, `activities`, `boundaries`,
  `technologies`, `definitions`, `sector_codes`, `value_chain`, `thresholds`), marked covered when the key is in
  `covers`. Initial selection: if `selection` is set, it is restored (ticks for candidate URLs in it, the rest as
  added URLs and uploaded files); otherwise a candidate starts ticked when it is both `from_library` and `fetchable`.
  Below the list: "Add URL" (input plus removable list) and "Upload document" (file input with
  `accept=".pdf,.txt,.md"`, removable list of uploaded files). "Build draft" is disabled when nothing is selected or
  an upload is in progress. It sends `{"urls": [ticked candidate URLs, then added URLs], "files": [upload paths]}`.
- **awaiting_review.** The draft document, editable, with Save, Accept and Cancel. See below.
- **accepted.** A confirmation with the taxonomy id and a link to the Taxonomy Library.
- **cancelled / failed.** A message (and `error` when set) with "Start a new run", which opens the start form
  prefilled with this run's theme name, theme key, scope, guidance and value-chain value.

### Review screen

Sections, in this order:

1. **Theme description**: editable textarea. Read-only scope shown above it.
2. **Technologies**: name editable; citations shown; item removable.
3. **Definitions**: term and text editable; citations shown; item removable.
4. **Activities**: one block per activity with name, in-scope and out-of-scope description, criteria (text
   editable, citations shown, removable), seed keywords (chips: add, remove), value-chain role (select: core,
   upstream, enabling), sector codes (`system code` with an origin badge `source`, `map_standards` or `exiobase`;
   removable, not addable, because the schema has no origin for a hand-added code: author's call), citations, and
   out-of-scope citations. Activities are removable. There is no "add activity", since a new activity has no quote
   and the API rejects it.
5. **Thresholds**: text editable, citations shown, removable. Labelled as not used for activity matching.
6. **Checklist report**: one row per source (URL or file name), one column per checklist item, each cell
   `found` or `not in source`.
7. **Notes**: run notes (`notes`), read-only.

Every citation, wherever it appears, shows its quote (not editable), its source URL as a link, and its location.
Editing a text never changes the citations of that item.

Behaviour:

- Edits are local until Save, which calls `PUT /draft`. A 422 shows the server message and keeps the edits.
- In-app navigation away with unsaved edits asks for confirmation; reload or close triggers the browser's
  `beforeunload` prompt.
- Accept: if there are unsaved edits, Save first; if that save fails, stop and show the message. Then
  `POST /accept`.
- Cancel asks for confirmation, then calls `DELETE /runs/{id}`.
- A 409 from any call reloads the run and shows its current stage.

## Testing

- Backend: unit tests for the new stages, failures, interrupted runs, cancel during a background step, the API
  returning before the work finishes, and the upload endpoint.
- Frontend: component tests in the existing `frontend/tests` style with the API client mocked.
- E2E: one walk in the app from `backend/scripts/e2e_stack.sh up` with `ARP_STANDINS_DIR` pointing at a fixture
  folder `backend/tests/fixtures/authority_taxonomy_ui/standins/` (search results, fetched texts and model answers),
  through start → sources → review → accept.

## Left to the builder

- Layout, styling and copy within the existing design system (`DESIGN.md`), except the texts quoted above.
- Readable labels for the 10 theme keys.
- Component split and file names.
- The stand-in fixture contents, as long as they produce the evaluator Givens below.

## Acceptance

Rows marked `unit` are owed to `holdout` once `HOLDOUT_TOKEN` is set. Backend `unit` rows use a stubbed search
client and LLM. Frontend `unit` rows use a mocked API client and fake timers. `evaluator` rows run in the app from
`backend/scripts/e2e_stack.sh up` with `ARP_STANDINS_DIR` set to the fixture folder named in Testing, whose stand-ins
make discovery for theme name `Hydrogen` return two candidates: `EU Taxonomy hydrogen` (`from_library: true,
fetchable: true`, `covers: ["activities", "thresholds"]`) and `Blocked report` (`from_library: false, fetchable:
false`); and make extraction of `EU Taxonomy hydrogen` produce a draft with 2 activities (activity 1 with value-chain
role `core` and one sector code of origin `exiobase`), 1 threshold, and a checklist report for that one source with
`activities` and `thresholds` `found` and the other 6 items `not_in_source`. The evaluator start form (AC-35) is:
Theme name `Hydrogen`, theme key `hydrogen`, scope `S1`, guidance `G1`, value chain ticked.

### Backend

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A discovery stub that blocks until released | `POST /api/authority-taxonomy/runs` with a valid body | 201 with `stage == "discovering"`, received before the stub is released | unit |
| AC-2  | A run at `discovering` whose discovery finishes with 2 candidates | `GET /runs/{id}` | 200, `stage == "awaiting_sources"`, 2 `candidates`, `error` null | unit |
| AC-3  | A run whose discovery raises `RuntimeError("boom")` | `GET /runs/{id}` | 200, `stage == "failed"`, `error` contains `boom` | unit |
| AC-4  | A run at `awaiting_sources`, extraction stub blocks until released | `POST /runs/{id}/sources` with one URL | 200 with `stage == "extracting"` and `selection.urls == [that URL]`, received before the stub is released | unit |
| AC-5  | A run at `awaiting_sources` | `POST /runs/{id}/sources` with a file path outside `documents_dir` | 422, `detail` starts with `file not allowed:` | unit |
| AC-6  | Same as AC-5 | `GET /runs/{id}` afterwards | `stage == "awaiting_sources"` | unit |
| AC-7  | A run whose extraction reads no source | `GET /runs/{id}` after the step ends | `stage == "awaiting_sources"`, `error` contains `no selected source could be read`, `selection` equals the request sent | unit |
| AC-8  | A run at `extracting` | `DELETE /runs/{id}`, then extraction finishes | DELETE 204; `GET` shows `stage == "cancelled"`, `draft` null | unit |
| AC-9  | A run at `discovering` | `DELETE /runs/{id}`, then discovery finishes | DELETE 204; `GET` shows `stage == "cancelled"`, `candidates == []` | unit |
| AC-10 | A run that failed extraction once, then succeeded | `GET /runs/{id}` | `stage == "awaiting_review"`, `error` null | unit |
| AC-11 | A run saved at `discovering` with no live worker (`run_alive` false) | `GET /runs/{id}` | `stage == "failed"`, `error == "interrupted by a server restart"` | unit |
| AC-12 | A run saved at `extracting` with no live worker | `GET /runs/{id}` | `stage == "awaiting_sources"`, `error == "interrupted by a server restart"` | unit |
| AC-13 | A run at `awaiting_review` | `PUT /runs/{id}/draft` with a valid edited draft | 200; `stage == "awaiting_review"`, `taxonomy_id` null; the taxonomy store's count is unchanged | unit |
| AC-14 | — | `POST /api/authority-taxonomy/uploads` with `note.txt` | 200, `path` is `<documents_dir>/_authority/note.txt` and the file has the uploaded bytes | unit |
| AC-15 | `note.txt` already uploaded once | Upload `note.txt` again | `path` ends with `_authority/note-2.txt`; the first file is unchanged | unit |
| AC-16 | — | Upload `x.docx` | 422, `detail == "unsupported file type"`; nothing written | unit |
| AC-17 | A path returned by AC-14 and a run at `awaiting_sources` | `POST /runs/{id}/sources` with `files == [that path]` | 200 | unit |
| AC-52 | — | Upload with filename `../../x.txt` | 422; nothing is written | unit |
| AC-53 | — | Upload a file one byte larger than `max_upload_bytes` | 413; nothing is written | unit |
| AC-54 | A discovery stub that blocks until released | `POST /runs`, then `GET /runs/{id}` at once | `stage == "discovering"`, `error` null | unit |
| AC-55 | A run created over an hour ago, at `awaiting_sources`; an extraction stub that blocks until released | `POST /runs/{id}/sources`, then `GET /runs/{id}` at once | `stage == "extracting"`, `error` null | unit |

### Frontend (component)

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-18 | The start form with Theme name empty | Click Start | No `POST /runs` is sent; the text `Theme name is required` is shown | unit |
| AC-19 | `GET /runs/{id}` returns `stage: "discovering"`, theme name `Hydrogen` | Open `#/taxonomy/authority/<id>` | A message containing `Hydrogen` and a Cancel button are shown | unit |
| AC-20 | The screen opened at t=0; `GET /runs/{id}` returns `discovering` three times, then `awaiting_sources` | Advance fake timers by 15 s | Exactly 4 `GET /runs/{id}` calls in total, at 0, 3, 6 and 9 s | unit |
| AC-21 | A run at `discovering`, loaded once, then `document.visibilityState` set to `hidden` | Advance fake timers by 10 s | No `GET /runs/{id}` after the initial load | unit |
| AC-56 | Same as AC-21 after the 10 s | Fire `visibilitychange` with state `visible` | Exactly 1 `GET /runs/{id}` is sent at once | unit |
| AC-22 | A run at `awaiting_sources` | Choose `note.txt` in Upload document | The request goes to `POST /api/authority-taxonomy/uploads`; `note.txt` is then listed as selected | unit |
| AC-23 | A run at `awaiting_sources` | Inspect the file input | Its `accept` attribute is `.pdf,.txt,.md` | unit |
| AC-24 | A run at `awaiting_sources` with one candidate ticked and an upload whose request has not answered yet | The sources screen is shown | Build draft is disabled | unit |
| AC-25 | One upload done (path P), all candidates unticked, URLs `u1` and `u2` added, then `u2` removed | Click Build draft | `POST /sources` body is exactly `{"urls": ["u1"], "files": ["P"]}` | unit |
| AC-26 | A run at `awaiting_sources` with candidates A (`from_library: false`) and B (`from_library: true, fetchable: true`), `error: "x"`, `selection: {"urls": ["<A url>", "u9"], "files": []}` | Open its URL | `x` is shown above the list; A is ticked; B is unticked; `u9` is listed as an added URL | unit |
| AC-27 | A run at `failed` with `error: "boom"` | Open its URL | `boom` and a "Start a new run" button are shown | unit |
| AC-57 | Start form: Theme name `Hydrogen`, theme key `hydrogen`, scope `S1`, guidance `G1`, value chain ticked | Click Start | `POST /runs` body is exactly `{"theme_name": "Hydrogen", "theme_key": "hydrogen", "scope": "S1", "guidance": "G1", "value_chain": true}` | unit |
| AC-28 | The review screen; criterion 1 of activity 1 has citations C | Edit criterion 1's text, click Save | The `PUT /draft` body has criterion 1 with the new text and citations equal to C | unit |
| AC-29 | The review screen; `PUT /draft` answers 422 `activity X has no citation` | Click Save | `activity X has no citation` is shown; the edited values are still in the form | unit |
| AC-30 | Unsaved edits; `PUT /draft` answers 200 | Click Accept | `PUT /draft` is sent, then `POST /accept`; a confirmation with the returned `taxonomy_id` is shown | unit |
| AC-31 | Unsaved edits; `PUT /draft` answers 422 | Click Accept | No `POST /accept` is sent; the 422 message is shown | unit |
| AC-32 | `PUT /draft` answers 409, the next `GET /runs/{id}` returns `stage: "accepted"`, `taxonomy_id: "T"` | Click Save | The accepted confirmation with `T` is shown | unit |
| AC-33 | The review screen with unsaved edits | Fire `beforeunload` | The handler calls `preventDefault()` on the event | unit |

### In the running app

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-34 | The app is open | Open `#/taxonomy/authority` | Fields Theme name, Theme key (11 options: 10 themes plus "None"), Scope, Source guidance, a Value chain checkbox and a Start button | evaluator |
| AC-35 | The start form filled as in the preamble | Click Start | The URL becomes `#/taxonomy/authority/<runId>` | evaluator |
| AC-36 | The run from AC-35 at `awaiting_sources` | Look at the cards | `EU Taxonomy hydrogen` is ticked and shows a "From library" badge; `Blocked report` is unticked and shows a "Not fetchable" warning | evaluator |
| AC-37 | Same | Look at the `EU Taxonomy hydrogen` card | Title links to its URL in a new tab; source type, summary and reason are shown; 8 checklist chips, exactly `activities` and `thresholds` marked covered | evaluator |
| AC-38 | Same, with everything unticked | Look at Build draft | Disabled | evaluator |
| AC-39 | Same, `EU Taxonomy hydrogen` ticked | Click Build draft, wait for the review screen | Sections in this order: Theme description, Technologies, Definitions, Activities (2 blocks), Thresholds (1 item), Checklist report, Notes. The checklist report has 1 row (the source) with 8 checklist cells: `activities` and `thresholds` show `found`, the other 6 `not in source` | evaluator |
| AC-40 | The review screen from AC-39 | Look at any citation | Quote, a link to its source URL, and location are shown; the quote is not editable | evaluator |
| AC-41 | Same | Look at activity 1's sector codes | Its code shows system, code and an `exiobase` badge; no control to add a sector code exists | evaluator |
| AC-42 | Same | Look for an "add activity" control | None exists | evaluator |
| AC-43 | Same | Set activity 1's value-chain role from `core` to `upstream`, Save, reload the page | Activity 1 shows `upstream`, not `core` | evaluator |
| AC-44 | Same, with an unsaved edit | Click another app tab, then dismiss the confirmation | The review screen stays, with the edit | evaluator |
| AC-45 | Same | Click Cancel and confirm | The cancelled message and a "Start a new run" button are shown | evaluator |
| AC-46 | The cancelled run from AC-45 | Click "Start a new run" | The start form shows `Hydrogen`, theme key `hydrogen`, scope `S1`, guidance `G1`, value chain ticked | evaluator |
| AC-47 | The Taxonomy Library | Open its create flow | No "Authority source" option in it | evaluator |
| AC-58 | The Taxonomy Library | Click "Build from authority sources" in the page header | The URL becomes `#/taxonomy/authority` | evaluator |

### Must not change

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-48 | The CLI with stub LLM and search | `arp taxonomy author start …`, then `select` | Each command returns only after its step finishes; output equals #325's for the same stubs | unit |
| AC-49 | The Taxonomy Library's remaining create methods (all except `authority_source`) | Create with each, mocked API | The request body for each equals the one `main` sends for the same inputs | unit |
| AC-50 | Thematic-fund source discovery | Run it, mocked API | Same request and the same candidate cards as on `main` | unit |
| AC-51 | `POST /api/documents/upload` | Upload with `company_id=acme`, `doc_type=other` | Same response and file location as on `main` | unit |
