# Refine Chat (stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `Refine` page where a chat edits an RFP project's answers or a house deck's slides, with a live view, undo, a turn log, and a fully editable `.pptx` export.

**Architecture:** One background "turn" per instruction: a single `complete_structured` call returns `RefineOps`; code applies the ops (RFP: grounded re-draft per question, saved one by one; deck: one step on `deck.json`), records `before`/`after` in `refine_turns`, and the page polls. The slide preview is the backend's `render_deck_html` in an iframe.

**Tech Stack:** FastAPI, SQLAlchemy (Postgres, `create_all` + additive columns via `arp/storage/postgres_schema.py`), python-pptx, Jinja HTML renderer, React + TypeScript (no new dependency), pytest with the stand-in client (`arp/standins.py`).

**Spec:** `docs/superpowers/specs/2026-11-14-refine-chat-design.md` (approved 2026-11-14). Every AC id below is that spec's row.

## Global Constraints

- The model proposes ops; code applies them. The model never writes to the database.
- Turn output model is named `RefineOps`; RFP re-drafts keep output model `DraftOut` (stand-ins are keyed by these names).
- Error texts are verbatim from the spec: `A change is already running on this document.`, `Viewers cannot change documents.`, `This report has no deck yet. Approve its storyline in Report Builder first.`, `Nothing to undo.`, `Q<id> changed after this turn; undo would overwrite it.`, `Slide <n> changed after this turn; undo would overwrite it.`, `This RFP has more than 400 questions. Name a section or question numbers.`
- Reasons verbatim: `approved`, `no source; use Auto-fill on RFP Answers`, `not backed by the library`, `draft failed`, `no such question`, `no such slot`, `no such variant`, `no such slide`, `chart type does not fit the data`.
- Constants: `REFINE_HISTORY_TURNS = 5`, `REFINE_MAX_QUESTIONS = 400`, `REFINE_ANSWER_PREVIEW_CHARS = 300`, `REFINE_TURN_TIMEOUT_MIN = 10`.
- Slide ids in results are 1-based positions after the turn; RFP ids are question ids.
- No new frontend dependency. API contract: `python scripts/export_openapi.py` then `npm run gen:api`; new `request<T>()` lines go in `frontend/src/api/contract.ts`.
- Do not touch the Plans page, Ask ARP, or RFP Answers behaviour (AC-46, AC-47, AC-49).

## Review Focus

1. A turn on a document while RFP Answers' Auto-fill runs on the same project: chat skips `no source` questions, so they don't collide; pin it with a test that a `rewrite` of a `no source` question never calls `DraftOut` (Task 2).
2. The model returns an op the schema allows but with missing fields (`rewrite` without `question_ids`, `set_text` without `slot`): skip that op with reason `no such question` / `no such slot`, never a 500 (Tasks 2, 3).
3. An empty `ops` list (the model only answers in prose): the turn ends `done`, nothing changes, and undo skips it, so undo never "undoes" nothing (Task 4).
4. A deck whose dataset was deleted after the deck was built: `deck/html` must still return 200 (the chart slot renders empty, as `render_deck_html` does today) instead of failing the live view (Task 5).
5. A long-running turn when the browser tab is closed: the turn finishes server-side and shows as `done` when the page reopens; nothing depends on the tab (Task 5, covered by the background design; test: GET the turn after the client disconnects).

---

### Task 1: Turn log table, manifest fields, turn store

**Files:**
- Modify: `backend/arp/db/models.py` (new `RefineTurn` after the RFP models, ~line 730)
- Modify: `backend/arp/schemas/reporting.py:320` (`ReportManifest`)
- Create: `backend/arp/refine/__init__.py`, `backend/arp/refine/turns.py`
- Test: `backend/tests/test_refine_turns.py`

**Interfaces:**
- Produces:
  - `m.RefineTurn` columns: `id: int`, `kind: str`, `doc_id: str`, `user_id: str`, `message: str`, `ops: list` (JSONB), `before: dict` (JSONB), `after: dict` (JSONB), `status: str`, `done: int`, `total: int`, `result: dict` (JSONB: `reply, changed, not_changed, check_figures`), `error: str | None`, `created_at: datetime`, `undone_at: datetime | None`. Partial unique index `uq_refine_turns_running` on `(kind, doc_id)` `WHERE status = 'running'`.
  - `ReportManifest.has_deck: bool = False`, `ReportManifest.deck_edited_since_render: bool = False`.
  - In `arp/refine/turns.py`:
    - `class TurnBusy(Exception)`
    - `start_turn(kind: str, doc_id: str, user_id: str, message: str) -> int` (raises `TurnBusy` on the unique-index violation)
    - `save_progress(turn_id: int, *, done: int | None = None, total: int | None = None, result: dict | None = None, before: dict | None = None, after: dict | None = None) -> None`
    - `finish_turn(turn_id: int, status: str, *, error: str | None = None) -> None`
    - `reap_stale_turns(now: datetime | None = None) -> int` (sets `failed`/`interrupted` on rows `running` older than `REFINE_TURN_TIMEOUT_MIN`; with `now=None` at startup, every `running` row)
    - `turn_out(turn_id: int) -> dict` (`{id, status, reply, done, total, changed, not_changed, check_figures, error}`)

- [ ] **Step 1: Write failing tests** `test_second_running_turn_raises_busy` (two `start_turn` on the same `(kind, doc_id)` → second raises `TurnBusy`; a different `doc_id` succeeds), `test_reap_marks_interrupted` (a `running` row; `reap_stale_turns()` → status `failed`, error `interrupted`; `start_turn` on the same doc then succeeds) — the AC-53 unit row, `test_manifest_defaults` (`ReportManifest().has_deck is False and .deck_edited_since_render is False`). Use `ARP_TEST_POSTGRES_DSN` like `test_rfp_api.py`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_refine_turns.py -v` — expect FAIL (import error).
- [ ] **Step 3: Implement** the model, the two manifest fields and `turns.py`. Catch `IntegrityError` on the index name for `TurnBusy`.
- [ ] **Step 4: Run** the same command — expect PASS; `ruff check .` clean.
- [ ] **Step 5: Commit** `feat(refine): turn log table and turn store`.

### Task 2: RFP operations

**Files:**
- Modify: `backend/arp/rfp/draft.py:85` (`draft_answer` gains keyword-only `instruction: str | None = None, current: str | None = None`; when given, both are appended to the prompt as `Style instruction: <instruction>` and `Current answer: <current>`)
- Create: `backend/arp/refine/rfp_ops.py`
- Test: `backend/tests/test_refine_rfp_ops.py` (fixture per the spec's Acceptance preamble, reusing `tests/rfp_fixtures.py`)

**Interfaces:**
- Consumes: `draft_answer`, `store.questions_of`, `store._active_entries`, `transaction()`, `save_progress` (Task 1).
- Produces: `async def apply_rfp_ops(turn_id: int, project_id: int, ops: list[dict], llm: LLMClient, *, today: date, settings=None) -> dict` returning `{changed: list[int], not_changed: list[{id, reason}], before: dict[str, dict], after: dict[str, dict]}`; `before`/`after` keyed by question id as string, each `{answer, status, sources, flags, last_editor}`.

Rules (spec "RFP operations"): process target questions one at a time in id order; save each in its own transaction and call `save_progress(done=…)` before the next; `total` = number of distinct target ids across ops. `NO_SOURCE` draft → `not backed by the library`; exception → `draft failed`; approved → `approved`; `no source` → `no source; use Auto-fill on RFP Answers` (no model call); unknown id or missing `question_ids` → `no such question`. Success: answer, status `drafted`, sources, flags, `last_editor = None`. `leave_blank` uses the same state change as the existing leave-blank endpoint.

- [ ] **Step 1: Write failing tests:** `test_rewrite_two_grounded` (AC-1/AC-2 values), `test_ungrounded_keeps_answer` (AC-3), `test_figure_not_in_source_keeps_answer` (AC-4, answer `42 funds`), `test_approved_untouched` (AC-5), `test_no_source_skipped_without_model_call` (AC-6; stand-in records 0 `DraftOut` calls — Review Focus 1), `test_leave_blank` (AC-7), `test_draft_error_continues` (AC-52), `test_instruction_reaches_draft_prompt` (AC-58: `DraftOut` prompt contains `shorter` and `A1`), `test_missing_question_ids_is_no_such_question` (Review Focus 2).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_refine_rfp_ops.py -v` — expect FAIL.
- [ ] **Step 3: Implement** the `draft_answer` keywords and `apply_rfp_ops`.
- [ ] **Step 4: Run** it plus `tests/test_rfp_api.py tests/test_rfp_golden.py` — all PASS (the existing RFP tests prove `draft_answer` without the new keywords is unchanged).
- [ ] **Step 5: Commit** `feat(refine): RFP operations`.

### Task 3: Deck operations

**Files:**
- Create: `backend/arp/refine/deck_ops.py`
- Test: `backend/tests/test_refine_deck_ops.py`

**Interfaces:**
- Consumes: `Deck`, `SlideContent`, `ChartSpec` (`schemas/reporting.py`), the layouts/variants from `house_style` (`style/layouts.json`), `build_native_chart_data` and `render_chart_svg` for the fit check.
- Produces: `def apply_deck_ops(deck: Deck, ops: list[dict], datasets: list[QuantitativeDataset], findings_text: str) -> tuple[Deck, dict]`, pure (no I/O); the dict is `{changed: list[int], not_changed: list[{id, reason}], check_figures: list[int]}` with positions after the turn.

Algorithm the tests don't fully fix: resolve every op's `slide` to the slide object at turn start; apply content ops (`set_text`, `set_headline`, `set_variant`, `set_chart_type`) in order; then `move_slide`/`delete_slide` in order, where `move_slide.to` is the 1-based position in the list as it stands at that moment; finally map changed/skipped slide objects to their final positions (a deleted slide is reported in neither list). Figure check: every number token in written text must occur in `findings_text`, the datasets' values, or that slide's text before the turn. Chart fit: try `build_native_chart_data` (native types) or `render_chart_svg` with the new type; any exception → skip with `chart type does not fit the data`.

- [ ] **Step 1: Write failing tests:** `test_set_text` (AC-19 data), `test_unknown_slot_skipped_others_apply` (AC-21/22), `test_unknown_variant` (AC-23), `test_set_chart_type_keeps_columns` (AC-24), `test_move_then_delete_start_positions` (AC-25: S4,S1,S2), `test_move_to_is_live_position` (AC-56: S3,S4,S1), `test_unbacked_figure_flagged_but_applied` (AC-26/27), `test_chart_type_that_does_not_fit` (AC-57), `test_slide_out_of_range` (`no such slide`), `test_set_text_without_slot` (Review Focus 2).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_refine_deck_ops.py -v` — expect FAIL.
- [ ] **Step 3: Implement** `apply_deck_ops`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(refine): deck operations`.

### Task 4: The turn (model call, prompt, orchestration)

**Files:**
- Create: `backend/arp/refine/agent.py`
- Test: `backend/tests/test_refine_agent.py`

**Interfaces:**
- Consumes: Tasks 1–3; `ReportingStore` (`load_deck`, `save_deck`, `load_manifest`, `save_manifest`, `load_request`), findings via the store's `findings.json`.
- Produces:
  - `class RefineOp(BaseModel)`: `op: Literal["rewrite","leave_blank","set_text","set_headline","set_variant","set_chart_type","move_slide","delete_slide"]`, optional `question_ids: list[int]`, `instruction: str`, `slide: int`, `slot: str`, `text: str | list[str]`, `variant: str`, `chart_type: ChartType`, `to: int`.
  - `class RefineOps(BaseModel)`: `reply: str`, `ops: list[RefineOp]`.
  - `def build_prompt(kind: str, document: dict, message: str, history: list[dict]) -> str` (keeps the last `REFINE_HISTORY_TURNS`; RFP lists id, status, question, first `REFINE_ANSWER_PREVIEW_CHARS` of the answer; deck lists per slide position, layout, variant, headline, slots, chart type, allowed variants and slot names).
  - `async def run_turn(turn_id: int, kind: str, doc_id: str, message: str, history: list[dict], llm: LLMClient, store: ReportingStore, *, today: date) -> None` — loads the document; RFP with more than `REFINE_MAX_QUESTIONS` questions → reply `This RFP has more than 400 questions. Name a section or question numbers.`, no model call; otherwise one `complete_structured(output_model=RefineOps)`; applies ops; saves `ops`, `before`, `after`, `result`; deck: writes `deck.json` and sets `deck_edited_since_render = True` only if something changed; `finish_turn("done")`. A model-call exception → `finish_turn("failed", error=str(exc))`, nothing written.

- [ ] **Step 1: Write failing tests:** `test_history_keeps_last_five` (AC-13 unit row: 7 entries in, prompt in `calls.jsonl` has the 5 newest and not the 2 oldest), `test_large_rfp_refused_without_model_call`, `test_model_failure_changes_nothing`, `test_empty_ops_done_and_not_undoable_marker` (Review Focus 3: `result.changed == []`, `before == {}`), `test_deck_turn_sets_edited_flag` (AC-31).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_refine_agent.py -v` — expect FAIL.
- [ ] **Step 3: Implement** `agent.py`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(refine): turn orchestration and prompt`.

### Task 5: API (turns, undo, deck read, roles, startup reaper)

**Files:**
- Create: `backend/arp/api/routers/refine.py`, `backend/arp/refine/undo.py`
- Modify: `backend/arp/api/main.py` (include router; call `reap_stale_turns()` in `lifespan` after `require_cutover`)
- Modify: `backend/arp/api/routers/reporting.py` (add `GET /{report_id}/deck`, `GET /{report_id}/deck/html`)
- Modify: `backend/arp/reporting/service.py:189` (`_rerender` sets `deck_edited_since_render = False`); wherever `save_deck` is first called for a report, set `has_deck = True`
- Test: `backend/tests/test_refine_api.py`

**Interfaces:**
- Consumes: Tasks 1–4; `require_role("analyst")`; `schedule_llm_run` pattern from `routers/rfp.py:160-198` for the background run.
- Produces (routes):
  - `POST /api/refine/{kind}/{doc_id}/turns` body `RefineTurnIn {message: str, history: list[RefineHistoryItem]}` (no `max_length`) → 202 `{turn_id: int}`; 403/409 texts from Global Constraints; a deck with no `deck.json` → 409 before any row is created.
  - `GET /api/refine/turns/{turn_id}` → `RefineTurnOut` (the `turn_out` dict).
  - `POST /api/refine/{kind}/{doc_id}/undo` → 200 `RefineTurnOut`.
  - `GET /api/reports/{id}/deck` → `Deck`; `GET /api/reports/{id}/deck/html` → `text/html` from `render_deck_html(deck, request.datasets, mode=request.layout.theme)`.
- `undo.py`: `def undo_last(kind: str, doc_id: str) -> int` — newest `done` turn on the doc with non-empty `before`, not undone; compare current state to `after` (RFP: per question id ascending; deck: whole deck, message names the first differing position in the current deck or the first position past the shorter); restore `before`; `status = undone`, `undone_at = now()`; deck undo sets `deck_edited_since_render = True`. Takes the same lock first: `start_turn(kind, doc_id, user_id, "undo")`, then `finish_turn(…, "done")` with empty `before`, so it cannot race a turn and is itself never undone.

- [ ] **Step 1: Write failing tests** (TestClient + stand-ins, users as in `test_rfp_api.py`): `test_turn_202_then_done` (AC-1), `test_progress_while_running` (AC-10), `test_second_turn_409` (AC-11), `test_viewer_403` (AC-12), `test_turn_log_row` (AC-9), `test_four_eyes_after_chat` (AC-8 through the HTTP approve), `test_undo_restores` (AC-14), `test_undo_twice` (AC-15), `test_nothing_to_undo` (AC-16), `test_undo_conflict_409` and `test_undo_conflict_changes_nothing` (AC-17/18), `test_viewer_undo_403` (AC-54), `test_deck_get_and_html` (AC-19/20), `test_deck_turn_log` (AC-28), `test_deck_undo` (AC-29), `test_no_deck_409` (AC-30 for turn and html), `test_render_no_model_and_clears_flag` (AC-32), `test_deck_undo_sets_flag` (AC-55), `test_has_deck_in_list` (AC-59), `test_html_with_missing_dataset_200` (Review Focus 4), `test_turn_finishes_without_client` (Review Focus 5: post, close the client, reopen, GET turn → `done`), and the must-not-change rows `test_manual_edit_four_eyes_unchanged` (AC-46), `test_approved_storyline_put_409` (AC-47).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_refine_api.py -v` — expect FAIL.
- [ ] **Step 3: Implement** the router, `undo.py`, the two reporting routes, the startup reaper and the manifest flag updates.
- [ ] **Step 4: Run** it plus `tests/test_ask_tools.py tests/test_ask_transition_plan.py tests/test_reporting_house_service.py` (AC-49) — PASS.
- [ ] **Step 5: Contract:** `cd backend && python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b` — clean.
- [ ] **Step 6: Commit** `feat(refine): API, undo, deck read routes` (include both generated files).

### Task 6: Fully editable export

**Files:**
- Modify: `backend/arp/reporting/house_pptx.py:151-163` (`_slot`: no `add_picture` for charts)
- Modify: `backend/arp/reporting/chart_builder.py` (native data for waterfall as two-series stacked column) and `backend/arp/reporting/html_render.py:68` (`_slot_view`: heatmap → table view)
- Modify: `backend/arp/reporting/style/templates/*.html.j2` only if the heatmap table needs a template branch
- Test: `backend/tests/test_reporting_house_pptx.py` (add tests; change none)

**Interfaces:**
- Produces: `build_waterfall_chart_data(spec: ChartSpec, datasets: list[QuantitativeDataset]) -> CategoryChartData` (series `base` with no fill/no line, series `value`); `heatmap_table(spec, ds) -> tuple[list[str], list[list], list[list[str]]]` (headers, rows, per-cell fill hex from the theme's sequential palette), used by both `house_pptx` (native table) and `html_render` (`<table>` with `style="background:…"`).

- [ ] **Step 1: Write failing tests:** `test_text_slot_is_text_frame` (AC-33), `test_column_after_chart_type_change` (AC-34: native column chart in pptx; SVG in html), `test_waterfall_and_heatmap_native` (AC-35: no picture shape on either chart slot; waterfall `XL_CHART_TYPE.COLUMN_STACKED` with 2 series; heatmap `shape.has_table`), `test_column_chart_unchanged` (AC-48), `test_html_heatmap_table_waterfall_svg` (AC-51).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_reporting_house_pptx.py -v` — new tests FAIL, existing PASS.
- [ ] **Step 3: Implement.** The waterfall base series: each bar's base = running total before it (negative steps: base = running total after the step, value = abs(step)).
- [ ] **Step 4: Run** it plus `tests/test_reporting_house_service.py tests/test_reporting_house_style.py` — PASS.
- [ ] **Step 5: Commit** `feat(reporting): editable waterfall and heatmap in pptx and preview`.

### Task 7: Golden set for the turn

**Files:**
- Create: `backend/arp/golden_set/refine.py`, `backend/tests/golden/refine/cases.json` (≥ 15 cases), `backend/tests/golden/refine/fixtures/*.json` (one RFP project, one deck)
- Modify: `backend/arp/cli/golden_set.py` (command `refine`), `.github/workflows/golden-set.yml` (paths `backend/arp/refine/**`, `backend/tests/golden/refine/**`; step `arp golden-set refine --cases backend/tests/golden/refine/cases.json --min-accuracy 0.9`)
- Test: `backend/tests/test_golden_refine.py`

**Interfaces:**
- Consumes: `build_prompt`, `RefineOps` (Task 4).
- Produces: `async def run_refine_golden(cases_path: Path, llm: LLMClient) -> tuple[int, int]` (passed, total); a case is `{doc_fixture, history, message, expected_ops}` and passes when op names and targets (`question_ids` as a set, `slide`, `slot`, `variant`, `chart_type`, `to`) equal the expected, `instruction`/`text` ignored. CLI exits 1 when `passed/total < --min-accuracy`.

- [ ] **Step 1: Write failing tests:** `test_case_passes_ignoring_instruction_text`, `test_case_fails_on_wrong_target`, `test_cli_exit_code_below_threshold` (stand-in model).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_golden_refine.py -v` — FAIL.
- [ ] **Step 3: Implement**, and write the 15+ cases: at least 5 RFP (bulk by topic, single id, leave blank, style-only, a follow-up that needs history), 8 deck (one per op type, plus a combined move+delete), 2 that should yield no ops (a question about the document).
- [ ] **Step 4: Run** the tests — PASS. Run `arp golden-set refine --cases backend/tests/golden/refine/cases.json --min-accuracy 0.9` once with the real model if `ARP_ANTHROPIC_API_KEY` is set; record the score in the PR (AC-45).
- [ ] **Step 5: Commit** `feat(refine): golden set and CI step`.

### Task 8: Refine page

**Files:**
- Create: `frontend/src/pages/Refine.tsx`, `frontend/src/lib/refine.ts`, `frontend/src/lib/refine.test.ts`
- Modify: `frontend/src/App.tsx:85-96` (tab `{ id: "refine", label: "Refine" }`, route params `rfp`/`report`), `frontend/src/api/client.ts` (calls below), `frontend/src/api/contract.ts` (one line per new `request<T>()`), `frontend/src/types.ts` (re-export generated types)
- Test: `frontend/src/lib/refine.test.ts`

**Interfaces:**
- Consumes: Task 5 routes; `GET /api/rfp/projects`, `GET /api/rfp/projects/{id}`, `GET /api/reports` (`has_deck`), `POST /api/reports/{id}/render`.
- Produces (in `lib/refine.ts`, pure, unit-tested): `resultLines(turn: RefineTurn): string[]` → `["Changed: Q1, Q2", "Not changed: Q3 (approved)", "Check figures: 2"]` (empty parts omitted; deck ids rendered as `Slide n`); `progressLine(turn): string | null` → `"<done> of <total>"` while `running`; `pollMs(turnRunning: boolean): number` → 1000 / 3000; `trimHistory(h): RefineHistoryItem[]` (last 5); `overflowing(el: HTMLElement): boolean` (`scrollHeight > clientHeight`).

Page behaviour (spec "Page"): picker of RFP projects and `has_deck` reports; URL `#/refine?rfp=<id>` / `?report=<id>` per the app's existing hash routing; chat history in component state; after POST, poll the turn and the document every `pollMs(true)`; otherwise the document every `pollMs(false)` while mounted; `changed` label on items in the newest turn's `changed`; deck: thumbnails + large slide as sandboxed `srcDoc` iframes of `deck/html` (show one slide via its `data-slide` index), red outline + `Text doesn't fit` on overflowing `data-slot` elements after each load; `Preview changed since last export` + `Export .pptx` when `deck_edited_since_render`; `Undo last turn` button calling undo and showing its 409 text inline.

- [ ] **Step 1: Write failing tests** in `refine.test.ts` for each pure function above (values exactly as listed).
- [ ] **Step 2: Run** `cd frontend && npm test -- refine` — FAIL.
- [ ] **Step 3: Implement** `lib/refine.ts`, the client calls, `Refine.tsx`, the tab.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — PASS.
- [ ] **Step 5: UI check:** `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up` with `ARP_STANDINS_DIR` set to a folder whose `model/RefineOps.json` returns `set_chart_type(3, "column")`; screenshot `/refine?report=<id>` with Playwright before and after one instruction; run `/impeccable:impeccable audit` on the page and fix what it flags. These are the evaluator rows AC-36–44, AC-50 (checked again by the evaluator skill after CI).
- [ ] **Step 6: Commit** `feat(refine): Refine page`.

---

**PR:** one PR against `main`, body `Spec: 2026-11-14-refine-chat-design`, `risk:normal` per the steward skill; list every test added (no existing test changed); state that `openwiki/` needs an update for the new Refine page and API (the weekly refresh regenerates it).
