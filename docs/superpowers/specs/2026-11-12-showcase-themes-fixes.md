# Showcase fixes for the R&D Lab screens (rehearsal of 11 Nov 2026)

## Intent

A live rehearsal with real model calls on 11 Nov 2026 found 12 defects in the R&D Lab screens: Thematic
Universe, Theme dossiers, Emerging Themes, Taxonomy Library, Research Plans, Index Construction and the
Signals workbench. The showcase is next week, in a bank JupyterLab: Gemini through Vertex AI, one uvicorn
process serving the built frontend, Postgres, dev sign-in or two local users, no Superset, Neo4j or
OpenSearch, and outbound web search probably blocked.

This spec fixes all 12 so that no screen ends in a dead end, a raw error or a number that means something
else than its label. Every fix comes with a test that failed before it.

## Build order and PRs

- Two implementing PRs, both `risk:normal`, both with `Spec: showcase-themes-fixes`.
  - **PR 1, flows that break:** defects 1, 2, 3, 4, 5, 6, 9, 11 and the "Approve standards" half of 8.
    Rows AC-1 to AC-49 and AC-91 to AC-97 (`Rows:` line in the PR description).
  - **PR 2, wrong or confusing display:** defects 7, 10, 12 and the links half of 8. Rows AC-50 to AC-90 and
    AC-98 to AC-102. It is the last slice, so it carries no `Rows:` line.
- Both build on `main` **after PR #413 and PR #410 are merged**. #410 replaces the API's blanket error
  handlers (`arp/errors.py`: `ClientInputError` is 400, `NotConfigured` is 503, anything else a generic 500)
  and touches `universe.py`, `plan_executor.py`, `plan_planner.py` and `plan_store.py`. #413 already fixes
  theme-run evidence ranking, the no-documents verdict and the setup wording in `setupErrors.ts`.
  The two PRs conflict with each other in `backend/arp/llm/factory.py`; that is theirs to resolve.
- Risk stays `risk:normal` because the cvxpy wording is fixed in the frontend only. A change under
  `backend/arp/index/` would make it `risk:high`; AC-100 forbids it.

## Causes (verified in code: `main` f21bab0 with #413 and #410 merged in a scratch copy)

| # | Defect | Cause |
|---|--------|-------|
| 1 | Plans fail at step 1 | `planner_context` (`orchestration/plan_planner.py:56-63`) lists taxonomies, frameworks and calibrations, no universes. `universe_build` (`plan_steps.py:43-58`) passes `source` straight to `load_company_universe`, which accepts only an existing `.csv`/`.json` path. Draft-time checking (`plan_check.py`) validates argument types only. |
| 2 | Waiting plan pins a thread | `plan_executor.py:97-101`: `while not reviewed(row): time.sleep(poll)` inside the worker that `plans.py:126` started with `asyncio.to_thread`, on the event loop's default pool. |
| 3 | "Find sources" says nothing | The search client returns `[]` for a bot challenge (`site_finder.py:49-51`); `_run_queries` (`research/taxonomy_sources/discovery.py:34`) swallows every error. The dossier round has no reason field and hides "Add source" after a failed proposal. |
| 4 | News mining | `news_mining.py:30` calls the search unguarded, so a connection error is an unhandled 500 (sent without CORS headers, hence "Failed to fetch"). `news_mining.py:79` raises the "pass a search client" text. |
| 5 | Decompose dead end | `ThemeBuilder.tsx:73-85` keeps the drafted theme in page state only; Run needs a ratified taxonomy (`:117-125`). `POST /api/taxonomies` with `llm_draft` ignores a supplied `theme` and drafts again (`routers/taxonomies.py:149-151`). |
| 6 | No "view source" | `grounding.py:304` sets `source_filename` only from a local file; EDGAR documents have `local_path=None` and a `source_url` (`ingestion/edgar.py:155-162`), and `Citation` has no URL field. `ThemeBuilder.tsx:593` always renders the source panel (`index.css:822`: 46% wide). `index.css:667` lets detail text overflow its cell. |
| 7 | Emerging Themes | `emerging_themes/pipeline.py:104-107` sets `company_count` to the mention count and the card says "companies"; the pipeline never passes `cost_delta_usd` or `model`; the page has no run-status check on its empty text and no polling; `confidence_score` is the novelty score (`synthesis.py:162`), 1.0 on a first scan; an empty company list renders as a blank cell. |
| 8 | Dossier | `dossier_position.py:296-298` answers 409 `find companies first` while `ThemePosition.tsx:183-187` disables the button only when busy. Step 4's link goes to the run page, not the review item (`themes/dossiers.py:173`). `Plans.tsx:125` links done steps only. |
| 9 | Vanished run | `RunProgress.tsx:24-40` shows a poll error only before the first manifest loaded, and polls a 404 forever. Cancel is cooperative; nothing reads `cancel_requested`. |
| 10 | Index Construction | The page never sends `candidates`, so `routers/index.py:29-32` always uses `demo_universe()`. The fallback text is built in `index/capping.py:312-317` and shown as is (`IndexBuilder.tsx:1434-1443`, `:989-993`). |
| 11 | Universe upload | `universe.py:57-64`: a `regimes` cell is `None` or a string, `CompanyRef.regimes` is a list, and the pydantic `ValidationError` is not caught by the upload route. `TaxonomyLibrary.tsx:637-640` prints `result.path`. |
| 12 | Smaller items | Listed with their fixes under "Decided", section 12. |

## Goals

- A Research Plan can name a saved universe and runs on it; a universe that does not exist is refused when
  the plan is drafted, in plain words.
- A plan waiting for a review holds no worker thread.
- When web search cannot be reached, the three "find sources" features and news mining say so and say what
  to do by hand; none shows an empty list without a reason, a 500 or the raw 422.
- "Decompose into activities" can be saved as a taxonomy draft from the Thematic Universe screen.
- A citation links to its source when one is known and offers no "view source" when none is; no empty
  source panel takes space or clips text.
- A run that no longer exists stops showing "running"; Cancel gives feedback.
- Universe upload accepts a `regimes` column, answers bad files in plain words and shows no server path.
- "Approve" (standards) is disabled until companies are found.
- Emerging Themes, Index Construction, Signals, Plans and the dossier screens label what they show
  correctly (defects 7, 10, 12 and the links of 8).

## Non-goals

- Making web search reachable in the bank, or a second search provider.
- Building a universe from company names or a region in a brief ("Nel, ITM Power…", "EU").
- Real universes for Index Construction; installing cvxpy; any change under `backend/arp/index/`.
- Reworking the embedding lock or the thread pool beyond freeing the waiting plan's thread.
- Continuing a waiting plan after a server restart (unchanged: nothing restarts it today either).
- A transcript upload for the news-mining method.
- A real confidence score for emerging themes (the column is relabelled, the number is unchanged).
- Anything PR #413 fixes; the Argus, portfolio and stewardship showcase cards; the queued follow-up cards.
- The dossier's step 5 "to review" link, the Index objective picker's raw ids and the missing-CSV entries in
  "Or pick a saved universe": seen while reading, not in the defect list, left alone.

## Anti-goals

- No existing test is changed, removed or weakened. The pinned tests are listed under "Existing tests".
- No index, weight or portfolio number changes.
- A search that worked and found nothing must not be reported as unreachable.
- A plan step that waits for review must never be started a second time when the plan continues.

## Approaches

For most defects the cause leaves one sensible fix (a missing label, check or link). Three had real choices.

**Defect 1, how a plan names a universe**

1. **Saved universes by file name (chosen).** The planner's context lists the files in
   `<runs_dir>/_universes` that the pickers already show; `universe_build` resolves a file name to that
   folder; a draft naming anything else is refused. Small, and it matches what "Save N companies as a
   universe" already produces.
2. A new plan step that builds a universe from company names. Rejected: two existing tests pin the step
   count at 8, and name matching is a feature, not a fix.
3. Refuse every path that is not a saved universe, also on hand edits and in the CLI. Rejected: existing
   tests edit and run scripts with `source="u.csv"`.

**Defect 2, what waits instead of the thread**

1. **The API's worker returns at the gate; an asyncio task in `routers/plans.py` polls `reviewed` and starts
   the worker again (chosen).** No thread is held between polls, the plan still continues by itself, and
   `run_plan` keeps its blocking behaviour for the CLI and the existing tests.
2. A scheduler in the app's lifespan that scans waiting plans. Rejected: more machinery, and the test apps
   (`FastAPI()` plus the router) have no lifespan.
3. Continue the plan when the Plans page polls it. Rejected: a plan would stall with the page closed.

**Defect 3, how "unreachable" is told from "nothing found"**

1. **A search call that fails is an error, also for a bot challenge; a feature whose queries all failed
   reports "unreachable" (chosen).** One rule for the four features.
2. A status field on every search result list. Rejected: changes the client's return type for 20 callers.
3. Leave the client, guess from an empty list. Rejected: that is today's defect.

## Decided

Texts in `code` are exact. "Search down" means: every query of that feature call ended in a connection
error, an HTTP error status or a bot-challenge answer (HTTP 202 from DuckDuckGo). The test stand-in's
`search.json` `{"error": …}` counts as such a failure.

### 1. Research Plans and saved universes

- A **saved universe** is a `.json` or `.csv` file directly in `<runs_dir>/_universes`, named by its file
  name (for example `acme_screen_1794441173.json`).
- `planner_context` gets a fourth section, headed `Saved universes (universe_build source):`, one line per
  entry of `catalog.universes(runs_dir)`: `- <file name>: <catalog name>`. With none: `- none saved yet`.
  The planner prompt says `source` must be one of these file names. The API's and the CLI's `_context()`
  both pass the list.
- `universe_build`: when `<runs_dir>/_universes/<source>` is a file, that file is loaded. Otherwise
  `source` is used as a path, as today.
- **Draft and re-plan through the API** (`POST /api/plans`, `POST /api/plans/{id}/replan`): a
  `universe_build` call whose `source` is neither a saved universe nor an existing `.json`/`.csv` file is
  a validation error with the line M1. It goes through the planner's existing retry (one more attempt);
  after the second failure the API answers 422 as today for rejected scripts.
  M1: `"<source>" is not a saved universe. Save one on the Thematic Universe page ("Save … as a universe") or upload one there, then name it in the brief. Saved universes: <file names joined by ", ", or none>.`
- **At run time**: when the universe cannot be loaded (no such file, unsupported type), the step fails with
  M1 instead of `Unsupported universe file type:` or `[Errno 2]`.
- **Not checked**: a hand edit (`PUT /api/plans/{id}`) and the CLI. They fail at run time with M1.
- Plans page: the brief's placeholder becomes
  `Grid-storage companies in the saved universe "eu listed": extract green capex for significant names, score, report`
  and a help line under the brief reads `Name a saved universe in the brief. Save one on the Thematic Universe page first.`

### 2. A waiting plan holds no thread

- `run_plan` keeps blocking by default. With an opt-in argument it returns `"awaiting_review"` once the gate
  is recorded. Only `routers/plans.py` passes it.
- After such a return the router keeps an asyncio task that every 5 s calls `reviewed` for the waiting step
  (in a short `to_thread` call). When it is reviewed, the task starts the worker again as `start_plan` does.
  When the plan is no longer `awaiting_review` (cancelled), the task ends.
- On re-entry a step stored as `awaiting_review` with the same kind and parameters is **not run again**:
  reviewed, it is marked `done` and its stored result is used; not reviewed, the worker returns again.
- Cancel while waiting: the plan becomes `cancelled`, the waiting step becomes `cancelled`, nothing later
  starts.

### 3. "Find sources" with search down

- **Dossier → Research → Propose sources.** The round ends `proposal_failed` as today and gets a new field
  `search_unreachable: bool` (true when search was down, false for any other failure).
  `POST …/research/sources` is accepted on a `proposal_failed` round and turns it into `proposed`; every
  other rule of the source plan is unchanged. The page shows the "Add source" form on a failed round, and
  S1 when `search_unreachable`, else S1b.
  S1: `The web search could not be reached, so no sources were proposed. Add a source by hand below, or propose again.`
  S1b: `The source proposal failed. Propose again, or add a source by hand below.`
- **Build from authority sources.** With search down the run ends discovery in `awaiting_sources` (not
  `failed`), with the approved library entries as candidates and `error` = S2. The sources screen already
  shows `error` and already has "Add URL" and "Upload document".
  S2: `The web search could not be reached, so no sources were found. Add a URL or upload a document below.`
- **Taxonomy Library → Universe builder → fund search.** `POST /api/taxonomies/discover-sources` answers 200
  with a new field `search_unreachable: bool` (true when every fund query failed). The page then shows S3.
  After a search that worked and found nothing it shows `No candidates found. Try another name.`; before
  any search the existing `No candidates yet — run a search above.` stays.
  S3: `The web search could not be reached. Download the fund's holdings file from the provider's website and upload it in step 2 below.`

### 4. News-mining taxonomy method

- The search call is guarded. With search down and no transcripts found the API answers 422 with S4a; with
  "also search news" off and no transcripts, 422 with S4b. With search down but transcripts found, the
  draft is built from the transcripts and `source_notes` contains
  `News search could not be reached; drafted from transcripts only.`
  S4a: `The news search could not be reached and no earnings-call transcripts were found for the selected universe, so there is nothing to draft from. Use another method, for example "Build from authority sources" with an uploaded document.`
  S4b: `No earnings-call transcripts were found for the selected universe and the news search is switched off, so there is nothing to draft from. Tick "Also search news", or use another method.`

### 5. Thematic Universe: Decompose

- `POST /api/taxonomies` with `derivation_method: "llm_draft"` **and** a `theme` stores that theme as
  version 1 (status draft) without a model call. Without `theme` it drafts with the model as today.
- After Decompose, while no taxonomy is loaded, the screen shows the button `Save as taxonomy draft`. It
  sends the drafted theme as above, loads the new taxonomy on the screen and shows
  `Saved as draft "<name>". Ratify it and release its schema in the Taxonomy Library, then come back and run it.`
  followed by the link `Open the Taxonomy Library` to `#/taxonomy`. The Run hint then reads the existing
  `Ratify this version and release its schema first.`

### 6. Citations and the source panel

- `Citation` gets `source_url: str | None`. Grounding sets it to the document's `source_url` when the
  document has no local file. Runs stored before this change have none.
- `CitationList`: with `source_filename`, "view source" opens the panel as today. Without it and with an
  `http(s)` `source_url`, "view source" is a link to that URL in a new tab (`rel="noopener noreferrer"`).
  With neither, there is no "view source" control.
- Thematic Universe renders the source panel only while a source is open. The hint
  `Click "view source" on any citation…` is therefore gone from that screen.
- Detail text (theme-run rationale, Emerging Themes candidate detail) wraps inside its cell.

### 7. Emerging Themes (PR 2)

- Progress reads `<done>/<total> mentions` for `emerging_themes` runs (also in the aria text); other run
  types keep `companies`. The backend counts are unchanged.
- The run records `cost_delta_usd` for every model call (`estimate_cost_usd`) and `model = settings.llm_model`.
- While the selected run is `running` or `pending`, the candidates area reads
  `Scanning… candidates appear when the scan finishes.`
- While any listed scan is `running` or `pending`, the page reloads the Recent scans list every 2.5 s, and
  the selected run's candidates when it finishes.
- The column and the detail label `Confidence` become `Novelty`, with the help text
  `How different this cluster is from themes in earlier scans. 100% on a first scan.` The API field
  `confidence_score` is unchanged.
- An empty Companies cell reads `None in your universe`.
- Schedule: a successful Save shows `Schedule saved.` in the schedule card. An interval below 1 shows
  `Enter an interval of at least 1 hour.` and sends nothing. The API refuses `interval_hours <= 0` with 422.

### 8. Dossier

- (PR 1) Position page: `Approve` in the Standards card and `Check companies` are disabled while the
  dossier's step 4 is not `done`, with the hint `Find companies first: finish step 4 of the dossier.` and
  a link `Open the dossier` to `#/themes/<id>`. The API's 409 stays.
- (PR 2) Dossier step 4 in state `waiting` links to `#/review/theme/<run_id>` with the text
  `Review the open items`. In every other state its link is unchanged.
- (PR 2) Plans: a step in `awaiting_review` shows the link `Review`: `#/review/<type>/<run_id>` with type
  `theme` for `universe_build`, `discovery` for `document_discovery`, `extraction` for `extraction`,
  `financials` for `financials_extraction`; `#/reporting` for a step whose `result_ref` starts `report:`;
  no link for any other kind.

### 9. Run progress card

- A poll answered 404 stops the polling. The card shows `This run no longer exists.` and neither a status
  nor a count.
- Any other poll error after a manifest was loaded shows `Could not refresh: <message>` under the card and
  polling goes on.
- After Cancel, while the run is still `running` with `cancel_requested`, the card shows
  `Cancelling… the run stops after the item in progress.` and the Cancel button is disabled.

### 10. Index Construction (PR 2, frontend only)

- Under the page intro, on every tab, a warning banner:
  `Demo data: reviews on this page run on a built-in synthetic universe of 60 companies. The results describe nothing real.`
- A result exception containing `cvxpy is not installed` is shown as
  `The optimiser is not installed on this server, so this review used step-by-step capping instead of "<label>". Ask your administrator.`
  where `<label>` is the catalogue's label for the method named in the message (`Least-squares projection`,
  `Minimum tracking error`), or the raw method id when the catalogue has none. Other exceptions are shown
  as they are.
- The Compose notice for a missing solver reads
  `The optimiser is not installed on this server. A calibration that asks for it falls back to step-by-step capping, and the review says so. Ask your administrator.`
- Screen and tilt cards are titled with the catalogue label (`Metric threshold`), falling back to the id.
- Errors on this page drop the status prefix, and a path `spec › screens › <n> › <type>: ` becomes
  `Screen <n+1> (<label>): `; a message that starts with the raw type id loses that id. Example:
  `422: spec › screens › 0 › metric_threshold: metric_threshold needs at least one of min_value / max_value`
  becomes `Screen 1 (Metric threshold): needs at least one of min_value / max_value`.

### 11. Universe upload

- A `regimes` value that is text is split on `;` and `,`, trimmed, blanks dropped; a blank cell is `[]`.
  A list (JSON) is kept.
- A row that fails validation is refused with 422 and
  `Row <n>: "<field>" is missing or not valid.` (`n` counts companies from 1; the first failing field of
  the first failing row). Also 422: `Unsupported file type "<suffix>". Upload a .csv or .json file.` and
  `The file is not valid JSON.` No answer contains `pydantic` or a class name.
- This is done in `load_company_universe` by raising `UniverseRejected` (a 422 in the upload route, a 400
  elsewhere through `ClientInputError`), so every caller gets it. No test pins the old
  `Unsupported universe file type` text.
- Universe builder (from holdings): the success line reads
  `Built <n> companies and saved them as the universe "<file name>". Pick it under "Or pick a saved universe" on the Thematic Universe page.`
  The API responses keep `path`: the pickers need it.

### 12. Smaller items (PR 2)

| Item | Fix |
|------|-----|
| Thematic Universe URL | After Start the address becomes `#/theme/<run_id>` (`history.replaceState`, no remount, form kept). |
| Results need "Refresh results" | Results load when the progress card sees the run finish. |
| "Save 1 companies" | `Save 1 company as a universe`, `Saved 1 company as a universe.`; other counts unchanged. |
| "$0.00 / 0 tokens" | A finished run with 0 tokens shows `No new model calls (answers reused or nothing to read)` in place of cost and tokens. |
| Edited draft shows "Manual" | `POST /api/taxonomies/{id}/versions` keeps the `derivation_method` of the taxonomy's latest version. |
| Compare & merge dropdown stale | The Library reloads its taxonomies when a sub-tab is opened. |
| Authority run accepts "not a url" | `POST /api/authority-taxonomy/runs/{id}/sources`: a URL without scheme `http`/`https` or without a host is refused with 422 `Not a web address: "<url>". Enter a full address starting with http:// or https://.` No DNS lookup. Nothing is stored. |
| Stale error while a note is written | Research page: the action error is cleared when the latest note is `writing`. |
| Position shows raw ids | A cited item shows its title; the id only when no title is known. |
| No un-shelve | `PATCH /api/dossiers/{id}` accepts `{"status": "active"}` from whoever may shelve: status `active`, `shelved_by`, `shelved_at` and `shelve_reason` cleared. On an active dossier it changes nothing. A shelved dossier's page shows the button `Un-shelve`. |
| Emerging schedule | Section 7. |
| Index card titles and errors | Section 10. |
| Signals: IC unrounded | IC mean and t-statistic with 3 decimals; `—` when missing. |
| Signals: identical experiments | The experiments table gets the columns `Created` (`YYYY-MM-DD HH:MM`) and `ID` (first 8 characters of `experiment_id`). |
| Signals: identical recipe | When a run returns an experiment already listed, the page shows `This recipe was already run on this data. Showing the existing result (<experiment_id>).` The API is unchanged. |
| Signals: no sample | Two static files, `samples/signals-recipe.json` (method `price_momentum`) and `samples/signals-prices.csv`, served with the frontend and offered as the links `Sample recipe (JSON)` and `Sample prices (CSV)`. Relative URLs, so they work behind the Jupyter proxy prefix. Run together they succeed. |
| Plans list says "running" | The list reloads whenever the open plan's status changes. |

## Existing tests that pin behaviour (none may change)

- Plans: scripts with `source="u.csv"` are stored, edited and run in `test_plan_store_pg.py`,
  `test_plan_executor_pg.py`, `test_plan_api_pg.py` (`test_edit_resets_approval` edits through the API),
  `test_plan_planner_pg.py`, `test_plan_replan_pg.py`, `test_plan_script.py`, `test_plan_steps_pg.py`
  (`test_universe_adapter_takes_best_exposure` replaces `load_company_universe`). Two tests pin 8 step
  kinds. `test_review_gate_pauses_then_continues`, `test_review_gate_resumes_with_running_status` and
  `test_cancel_while_awaiting_review_is_kept` need `run_plan`'s blocking wait.
- Search: `test_a_failed_search_fails_the_round_and_it_can_be_proposed_again` (stand-in error →
  `proposal_failed`, step 3 `("failed", "source proposal failed")`); `test_discovery_survives_a_failing_query`;
  `test_authority_taxonomy_discovery.py` (an all-empty search does not fail); `test_discover_success`
  (`discover_candidates` returns a list); `frontend/tests/research.test.ts` (`planOpen` only for `proposed`);
  `e2e/test_authority_taxonomy_page.py` (posts `u1` as a URL against a mocked API, so the frontend may not
  reject non-URLs).
- `test_news_mining_derivation.py::test_build_theme_requires_at_least_one_source` (a `ValueError`).
- `test_universe_nace.py` (exact 422 texts, nothing stored on reject), `test_catalog.py` (universe id is the
  path, name `climate leaders (1 companies)`), `test_save_universe_dedup.py`.
- `e2e/test_argus_switchover.py` clicks `Save 2 companies as a universe` and opens `#/theme/<run_id>`.
- `test_dossiers.py:116-126` (step 4 `("waiting","3 to review")`; the `#/theme/<run_id>` link in state done);
  `frontend/tests/dossiers.test.ts` (`stepLinkText`); `frontend/tests/plans.test.ts` (`resultHref`).
- `test_emerging_themes_scoring.py` (novelty values), `test_emerging_themes_pipeline.py`.
- `test_index_optimize.py:50-63` (`"cvxpy is not installed"` in the result's exceptions);
  `frontend/tests/setupErrors.test.ts`; `frontend/tests/projects.test.ts` (`formatValidationErrors`,
  `apiMessage`).
- `test_api_signals.py:386-393` (`test_run_twice_same_id_one_row`).

## Notes for the builder

- Every fix needs a test that failed before it, with its output in the PR description: a backend pytest, a
  `node:test` on a pure helper in `frontend/src/lib/`, or a browser test in `backend/tests/e2e` with the
  API mocked (`page.route`, as `test_authority_taxonomy_page.py` does). The frontend has no component
  tests, so page logic that needs a test goes into a `lib` helper.
- API models change (`Citation.source_url`, `ResearchRound.search_unreachable`,
  `DiscoverSourcesResponse.search_unreachable`, the schedule's interval, `DossierPatch.status`): run
  `export_openapi.py` and `npm run gen:api` and commit both files.
- The search client is shared. Making a bot challenge an error must not change the identity run
  (`discovery/identity_agents.py:91`, unguarded): AC-96.
- Touching `arp/grounding.py` starts the golden-set job on the PR.
- Left to the builder: helper and argument names, where the search failure type lives, the banner's markup
  (`banner banner-warning` exists), the sample files' contents, test names.
- `openwiki/` needs a refresh afterwards (Plans, dossier research, taxonomy sources, universe upload); the
  weekly `/context-refresh` does it.

## Acceptance

**Fixtures.** "Stack" is the app from `backend/scripts/e2e_stack.sh up` with `ARP_STANDINS_DIR` set and no
model key. "Search down" is `search.json` = `{"error": "down"}` in that folder; "search empty" is
`{"results": []}`. `F` is the file name (last path part of `path`) returned by
`POST /api/universe/from-companies` for one company `{"company_id": "c1", "name": "Acme"}`. "Planner
answers S" means `model/PlanScript.json` = `{"output": {"script": S}}`, so both planner attempts return S.
`unit` rows that need stub plan steps use the harness of `backend/tests/test_plan_api_pg.py` (stub steps
through `plans.build_runtime`, a `reviewed` function the test controls). Browser rows run at 1400×900.
M1, S1 to S4b are the texts under "Decided".

### PR 1

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Stack; `F` saved; planner answers `u = universe_build(taxonomy_id="t", source="F")` (with F's name) | `POST /api/plans` with any brief | the planner call recorded in `calls.jsonl` contains the line `Saved universes (universe_build source):` and a line starting `- F:` (F's name) | holdout |
| AC-2 | as AC-1 | the response is read | status 200 and the plan's `dry_run` has one `universe_build` whose `source` is F's name | holdout |
| AC-3 | Stack; planner answers a script with `source="Nel, ITM Power, Plug Power, thyssenkrupp nucera"` | `POST /api/plans` | status 422 | holdout |
| AC-4 | the AC-3 request | `detail` is read | contains `"Nel, ITM Power, Plug Power, thyssenkrupp nucera" is not a saved universe.` | holdout |
| AC-5 | the AC-3 request, `F` saved | `detail` is read | contains `Saved universes: ` followed by a list that includes F's name | holdout |
| AC-6 | the AC-3 request | `GET /api/plans` before and after | the number of plans is unchanged | holdout |
| AC-7 | Stack; planner answers a script with `source="EU"` | `POST /api/plans` | status 422 and `detail` contains `"EU" is not a saved universe.` | holdout |
| AC-8 | `<runs_dir>/_universes/acme.json` holds two companies; the theme run is replaced by a stub | `universe_build(taxonomy_id=…, source="acme.json")` runs | the stub receives exactly those two companies | unit |
| AC-9 | an approved plan whose script has `source="missing.csv"` (stored directly), real `universe_build` | the plan is run | plan status `failed`; its error starts `step 1 universe_build failed: "missing.csv" is not a saved universe.` | unit |
| AC-10 | the AC-9 plan | its error is read | contains neither `Errno` nor `Unsupported universe file type` | unit |
| AC-11 | a failed plan; the re-plan model answers a script with `source="invented.csv"` twice | `POST /api/plans/{id}/replan` | status 422 and one `detail` line contains `"invented.csv" is not a saved universe.` | unit |
| AC-12 | Stack, no saved universe needed | the Plans page is opened | the brief's placeholder is `Grid-storage companies in the saved universe "eu listed": extract green capex for significant names, score, report` | evaluator |
| AC-13 | as AC-12 | the page is read | under the brief: `Name a saved universe in the brief. Save one on the Thematic Universe page first.` | evaluator |
| AC-14 | 40 approved plans whose second step gates and is not reviewed, each started with `POST /api/plans/{id}/run` and now `awaiting_review` | a 41st approved plan without a gate is started the same way | it reaches `done` within 10 s | unit |
| AC-15 | one plan `awaiting_review` at step 2, started through the API | `reviewed` turns true and no request is made | within 15 s the plan is `done` | unit |
| AC-16 | the AC-15 plan after it is done | the stub steps' call counts are read | the gated step ran exactly once | unit |
| AC-17 | one plan `awaiting_review` at step 2, started through the API | `POST /api/plans/{id}/cancel` | plan status `cancelled` and step 2's status `cancelled` | unit |
| AC-18 | the AC-17 plan | `reviewed` turns true and 12 s pass | step 3 has no call row and its stub was never called | unit |
| AC-19 | Stack, search down; a dossier with a ratified taxonomy | sources are proposed and the round has left `proposing` | the latest round's `search_unreachable` is `true` | holdout |
| AC-20 | the AC-19 round (`proposal_failed`) | `POST …/research/sources` with a valid source | status 200 | holdout |
| AC-21 | after AC-20 | `GET …/research` | the round's `plan_status` is `proposed` and it holds exactly that 1 source | holdout |
| AC-22 | Stack, search returns results, `model/SourceClassificationDraft.json` = `{"error": "x"}` | sources are proposed and the round has left `proposing` | `plan_status` is `proposal_failed` and `search_unreachable` is `false` | holdout |
| AC-23 | the search client answers HTTP 202 to every query (mock transport) | the dossier's sources are proposed | `plan_status` is `proposal_failed` and `search_unreachable` is `true` | unit |
| AC-24 | Stack, search down; the AC-19 dossier | its Research page is opened after the proposal ended | the page shows S1 and the "Add source" form | evaluator |
| AC-25 | Stack, search down | an authority run is started and has left `discovering` | `stage` is `awaiting_sources` | holdout |
| AC-26 | the AC-25 run | `error` is read | equals S2 | holdout |
| AC-27 | the AC-25 run | its page is opened, `https://example.org/a` is typed into "URL" and "Add URL" is clicked | S2 is shown and "Build draft" is enabled | evaluator |
| AC-28 | Stack, search down | `POST /api/taxonomies/discover-sources` with `{"name": "Hydrogen"}` | status 200, `thematic_funds` is `[]`, `search_unreachable` is `true` | holdout |
| AC-29 | Stack, search empty | the same request | status 200 and `search_unreachable` is `false` | holdout |
| AC-30 | Stack, search down | Taxonomy Library → Universe builder: a fund search for "Hydrogen" | the page shows S3 | evaluator |
| AC-31 | Stack, search empty | the same search | the page shows `No candidates found. Try another name.` | evaluator |
| AC-32 | Stack, search down, no universe | `POST /api/taxonomies` with `derivation_method: "news_transcript_mining"`, `mine_news: true` | status 422 and `detail` equals S4a | holdout |
| AC-33 | Stack, no universe | the same with `mine_news: false` | status 422 and `detail` equals S4b | holdout |
| AC-34 | search down; a universe whose company has a local earnings-call transcript; a stand-in model | the same as AC-32 with that universe | status 200 and `source_notes` contains `News search could not be reached; drafted from transcripts only.` | unit |
| AC-35 | Stack, search down | Taxonomy Library → New taxonomy → "News & earnings-call transcript mining" → "Draft & save taxonomy" | the page shows S4a and does not show `Failed to fetch` | evaluator |
| AC-36 | Stack; the stand-in folder holds no model file, so any model call fails; a theme `T` with two activities | `POST /api/taxonomies` with `derivation_method: "llm_draft"` and `theme: T` | status 200; version 1 has status `draft` and the two activities of `T` | holdout |
| AC-37 | Stack; the model stand-in for the decompose call returns a theme with two activities | Thematic Universe: name and description entered, "Decompose into activities", then `Save as taxonomy draft` | the page shows `Saved as draft "<name>". Ratify it and release its schema in the Taxonomy Library, then come back and run it.` and the link `Open the Taxonomy Library` | evaluator |
| AC-38 | after AC-37 | the Taxonomy Library is opened | the taxonomy is listed with method `LLM draft (freeform)` and status draft | evaluator |
| AC-39 | a document with `local_path` none and `source_url` `https://www.sec.gov/x.htm`; a grounded quote from it | a theme run's citations are built | the citation's `source_url` is `https://www.sec.gov/x.htm` and `source_filename` is null | unit |
| AC-40 | theme results with a grounded citation that has `source_url` `https://www.sec.gov/x.htm` and no `source_filename` (API mocked) | the row is expanded | the citation has a link `view source` with that `href` and `target="_blank"` | unit |
| AC-41 | theme results with a grounded citation that has neither `source_filename` nor `source_url` (API mocked) | the row is expanded | the citation has no control named `view source` | unit |
| AC-42 | theme results on screen, no source opened (API mocked) | the page is read | the text `Click "view source" on any citation` is not on the page | unit |
| AC-43 | as AC-42 | the results table is measured | it is at least 90% as wide as the page's content column | unit |
| AC-44 | Emerging Themes with one candidate whose rationale is 600 characters without a line break (API mocked) | its detail is opened | the detail cell's `scrollWidth` is not greater than its `clientWidth` | unit |
| AC-45 | a progress card showing a running run; the next poll of `/api/runs/{id}` answers 404 (API mocked) | 12 s pass | the card shows `This run no longer exists.` and does not show `running` | unit |
| AC-46 | as AC-45 | a further 12 s pass | no further request for that run was made | unit |
| AC-47 | a progress card showing a running run; `POST …/cancel` answers the manifest with `cancel_requested: true`, status `running` (API mocked) | "Cancel run" is clicked | the card shows `Cancelling… the run stops after the item in progress.` and the Cancel button is disabled | unit |
| AC-48 | Stack; a CSV `company_id,name,regimes` with the rows `A,Acme,` and `B,Beta,CSRD; SFDR` | `POST /api/universe/upload` | status 200; `sample[0].regimes` is `[]` and `sample[1].regimes` is `["CSRD", "SFDR"]` | holdout |
| AC-49 | Stack; a CSV `company_id,name` with the rows `A,Acme` and `B,` | `POST /api/universe/upload` | status 422 and `detail` equals `Row 2: "name" is missing or not valid.` | holdout |
| AC-91 | Stack; a file `u.xlsx` | `POST /api/universe/upload` | status 422 and `detail` equals `Unsupported file type ".xlsx". Upload a .csv or .json file.` | holdout |
| AC-92 | Stack; a file `u.json` containing `{not json` | `POST /api/universe/upload` | status 422 and `detail` equals `The file is not valid JSON.` | holdout |
| AC-93 | Stack; a holdings CSV the Universe builder accepts | Taxonomy Library → Universe builder: the file is uploaded | the success line starts `Built ` and contains `saved them as the universe "`; the page text does not contain `_universes` | evaluator |
| AC-94 | a dossier whose step 4 is not `done`, a standards version waiting, signed in as approver (API mocked) | its Position page is opened | `Approve` in the Standards card and `Check companies` are disabled, and the page shows `Find companies first: finish step 4 of the dossier.` with a link to `#/themes/<id>` | unit |

Must not change in PR 1:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-95 | an approved plan whose script has `source="u.csv"` (no such file), edited through `PUT /api/plans/{id}` | the response is read | status 200 and the plan is `draft` (a hand edit is not checked) | unit |
| AC-96 | the search client answers HTTP 202 to every query (mock transport) | an identity run resolves one company | the run ends as on `main`: it does not fail, and the company has no web search hits | unit |
| AC-97 | the dossier's source plan is `approved` | `POST …/research/sources` | status 409 and `detail` is `the source plan is not open for edits` | holdout |

### PR 2

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-50 | a run of type `emerging_themes` with `completed_count` 618 and `company_count` 618 (API mocked) | its progress card is shown | it reads `618/618 mentions` | unit |
| AC-51 | an emerging-themes scan whose stand-in model reports 1,000,000 input and 0 output tokens per call under a model name missing from the price table | the scan finishes | the run's `estimated_cost_usd` equals 3.0 times its number of model calls | unit |
| AC-52 | the AC-51 run, with the setting `llm_model` = `m1` | the run is read | its `model` is `m1` | unit |
| AC-53 | Emerging Themes; the selected run is `running` with no candidates (API mocked) | the page is read | it shows `Scanning… candidates appear when the scan finishes.` and not `No candidates for this run` | unit |
| AC-54 | as AC-53; the runs list answers `completed` from the third request on and the candidates request then returns one candidate (API mocked) | 10 s pass without a click | the Recent scans row reads `completed` and the candidate is listed | unit |
| AC-55 | Stack; an emerging-themes run with at least one candidate | the Emerging Themes page shows it | the candidates table has a column `Novelty` and no column `Confidence` | evaluator |
| AC-56 | a candidate whose `candidate_sectors_companies` is empty (API mocked) | the candidates table is shown | its Companies cell reads `None in your universe` | unit |
| AC-57 | Stack | the Emerging Themes schedule is saved through the API with `interval_hours: 0` | status 422 | holdout |
| AC-58 | Emerging Themes, schedule card (API mocked) | interval `0` is entered and Save is clicked | the card shows `Enter an interval of at least 1 hour.` and no request is sent | unit |
| AC-59 | Stack | interval `24` is entered and Save is clicked | the card shows `Schedule saved.` | evaluator |
| AC-60 | a dossier whose newest theme run `r1` has one pending review item | `GET /api/dossiers/{id}` | step 4 has state `waiting`, detail `1 to review` and `href` `#/review/theme/r1` | unit |
| AC-61 | the dossier page for AC-60 (API mocked) | step 4 is read | its link text is `Review the open items` | unit |
| AC-62 | a plan step `extraction` in `awaiting_review` with `run_id` `r_1` (API mocked) | the Plans page shows the plan | the step's Result cell is the link `Review` to `#/review/extraction/r_1` | unit |
| AC-63 | steps in `awaiting_review` of kind `universe_build`, `document_discovery`, `financials_extraction` with `run_id` `r` | their Review links are read | `#/review/theme/r`, `#/review/discovery/r`, `#/review/financials/r` | unit |
| AC-64 | a step `report_render` in `awaiting_review` with `result_ref` `report:7`; a step `xbrl_facts` in `awaiting_review` | their Result cells are read | the first links to `#/reporting`; the second has no link | unit |
| AC-65 | Stack | the Index Construction page is opened on Compose | it shows `Demo data: reviews on this page run on a built-in synthetic universe of 60 companies. The results describe nothing real.` | evaluator |
| AC-66 | a review result whose `exceptions` hold `solver.method='least_squares' but cvxpy is not installed; fell back to the deterministic waterfall (pip install -e ".[optimize]")` (API mocked, catalogue as on `main`) | the Result tab is shown | the item reads `The optimiser is not installed on this server, so this review used step-by-step capping instead of "Least-squares projection". Ask your administrator.` | unit |
| AC-67 | the same with `'min_tracking_error'` | the Result tab is shown | the item reads the same sentence with `"Minimum tracking error"` | unit |
| AC-68 | a review result whose `exceptions` hold `anything else` | the Result tab is shown | the item reads `anything else` | unit |
| AC-69 | the catalogue says the solver is not available (API mocked) | Compose is shown | it shows `The optimiser is not installed on this server. A calibration that asks for it falls back to step-by-step capping, and the review says so. Ask your administrator.` and the page text does not contain `pip install` | unit |
| AC-70 | Stack | Index Construction → Compose: the screen "Metric threshold" is added | the new card's title is `Metric threshold` | evaluator |
| AC-71 | the run endpoint answers 422 with `loc` `["body","spec","screens",0,"metric_threshold"]` and `msg` `Value error, metric_threshold needs at least one of min_value / max_value` (API mocked) | "Run" is clicked | the page shows `Screen 1 (Metric threshold): needs at least one of min_value / max_value` | unit |
| AC-72 | an experiment with IC mean `0.0423456` and t-statistic `2.34567`; another with IC mean null (API mocked) | the Signals evidence is shown | it reads `0.042` and `2.346`; the null reads `—` | unit |
| AC-73 | two experiments with the same method, universe and window, `experiment_id` `aaaaaaaa1111` and `bbbbbbbb2222`, created `2026-11-11T09:05:00Z` and `2026-11-11T09:07:00Z` (API mocked, browser in UTC) | the experiments table is shown | it has the columns `Created` and `ID`; the rows read `2026-11-11 09:05` / `aaaaaaaa` and `2026-11-11 09:07` / `bbbbbbbb` | unit |
| AC-74 | an experiment `aaaaaaaa1111` is listed; a run answers that same experiment (API mocked) | the recipe is run | the page shows `This recipe was already run on this data. Showing the existing result (aaaaaaaa1111).` | unit |
| AC-75 | Stack | `samples/signals-recipe.json` and `samples/signals-prices.csv` are fetched from the frontend's address | both answer 200; the first is JSON whose `method` is `price_momentum`; the second's first line starts `date,` | holdout |
| AC-76 | Stack; the two files of AC-75 | they are sent to the Signals run endpoint as the page sends them | status 200 and the response has an `experiment_id` | holdout |
| AC-77 | Stack | the Signals workbench is opened | it shows the links `Sample recipe (JSON)` and `Sample prices (CSV)` | evaluator |
| AC-78 | Thematic Universe with a runnable taxonomy and a universe; the start request answers `run_id` `run_9` (API mocked) | "Run" is clicked | the address ends `#/theme/run_9` and the universe picker still shows the chosen universe | unit |
| AC-79 | as AC-78; the run's poll answers `completed` from the second request on and the results request returns one company (API mocked) | 10 s pass without a click | the results table shows that company | unit |
| AC-80 | theme results filtered to 1 company (API mocked) | the save button is read | `Save 1 company as a universe` | unit |
| AC-81 | a progress card for a `completed` run with 0 input and 0 output tokens (API mocked) | the card is read | it shows `No new model calls (answers reused or nothing to read)` and not `$0.00` | unit |
| AC-82 | Stack; a taxonomy created as in AC-36 (`llm_draft` with a theme) | `POST /api/taxonomies/{id}/versions` with an edited theme | the new version's `derivation_method` is `llm_draft` | holdout |
| AC-83 | the Taxonomy Library is open; a taxonomy is then created through the API (API mocked: the list request returns one more entry) | the "Compare & merge" tab is opened | its dropdown lists the new taxonomy | unit |
| AC-84 | Stack, search empty; an authority run in `awaiting_sources` | `POST …/runs/{id}/sources` with `urls: ["not a url"]` | status 422 and `detail` equals `Not a web address: "not a url". Enter a full address starting with http:// or https://.` | holdout |
| AC-85 | the AC-84 request | the run is read | `stage` is still `awaiting_sources` | holdout |
| AC-86 | the Research page shows an action error; the next poll returns a note with status `writing` (API mocked) | the poll is applied | the action error is no longer shown | unit |
| AC-87 | a position whose point cites `itm_0d2b55df5684`, and the approved note has an item with that id titled `IEA hydrogen review` (API mocked) | the Position page is shown | the point's sources read `IEA hydrogen review` and the page's position text does not contain `itm_0d2b55df5684` | unit |
| AC-88 | Stack; a shelved dossier | `PATCH /api/dossiers/{id}` with `{"status": "active"}` as the user who shelved it | status 200; `status` is `active`; `shelved_by`, `shelved_at` and `shelve_reason` are null | holdout |
| AC-89 | Stack; a shelved dossier | its page is opened and `Un-shelve` is clicked | the shelved banner is gone and the Shelve form is shown | evaluator |
| AC-90 | the Plans page with a plan open; the list shows it `running`; the detail poll answers `failed` and the list request then answers `failed` (API mocked) | 8 s pass without a click | the list row reads `failed` | unit |

Must not change in PR 2:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-98 | a run of type `theme` with `completed_count` 2 and `company_count` 5 (API mocked) | its progress card is shown | it reads `2/5 companies` | unit |
| AC-99 | theme results filtered to 2 companies (API mocked) | the save button is read | `Save 2 companies as a universe` | unit |
| AC-100 | the diff of the PR | `git diff --name-only origin/main` is run in CI | it lists no file under `backend/arp/index/` | unit |
| AC-101 | Stack; a taxonomy created with `derivation_method: "manual"` and a theme | `POST /api/taxonomies/{id}/versions` with an edited theme | the new version's `derivation_method` is `manual` | holdout |
| AC-102 | Stack, search empty; an authority run in `awaiting_sources` | `POST …/runs/{id}/sources` with `urls: ["https://a.invalid/x"]` (a host that does not resolve) | the status is not 422 | holdout |

**Checked by.** `holdout` rows are API calls against the Stack. `evaluator` rows are checked in the running
app (10 in PR 1, 6 in PR 2). AC-2 and AC-25 already hold on `main`; they are in the table because the flow
they belong to is new, and their hidden tests are of kind `keep`. `unit` rows are the builder's own tests: they need stub plan steps, a mock
transport, a fake model's token counts or a mocked API in the browser, none of which the Stack can be put
into from outside; "API mocked" rows are browser tests in `backend/tests/e2e` or `node:test` on the helper
that produces the text.
