# Ask ARP Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One chat panel, opened from every page, that routes a plain-language question to one of four read-only tools and shows a sourced answer card.

**Architecture:** A new backend module `arp/ask.py` holds the request/response models, the routing output model and the two new code-only tools (newest transition plan assessment, benchmark sector weights). A new router `arp/api/routers/ask.py` exposes `POST /api/ask`: one `complete_structured` routing call, then dispatch to `qa_agent.answer_question`, `smart_search.smart_search` or the two new tools, then one `qa_audit` row. The frontend adds an `AskPanel` in the app shell; the conversation lives in React state and `sessionStorage`.

**Tech Stack:** FastAPI, Pydantic v2, pytest with the `pg` and `fake_llm` fixtures; React + TypeScript (Vite), Vitest.

**Spec:** `docs/superpowers/specs/2026-10-24-ask-arp-panel-design.md` (approved 2026-10-24). Every exact text and value below is copied from it; where they differ, the spec wins.

## Global Constraints

- Model calls go through `LLMClient.complete_structured` only. The routing output model has no number fields.
- `/api/ask` writes nothing except one `qa_audit` row per handled call (200 or 502). A 422 or 403 writes none.
- Access: router included with `dependencies=[Depends(authorize)]` (POST needs `analyst`+). Viewers see no Ask button.
- `question`: 1–1,000 characters. `history`: optional, default `[]`, at most 5 turns, each exactly `{question, tool, standalone_question}` (`extra="forbid"`).
- Error text, verbatim: `Ask could not answer this question. Try again.` (HTTP 502).
- No new tables, no migration. Do not touch `arp/llm`, `arp/extraction`, `arp/grounding.py`.
- After the response models exist: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`; commit both generated files; add a `contract.ts` line.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; `cd frontend && npm run lint && npx tsc -b && npm test`.
- Never edit an existing test to make it pass (AC-27, AC-47).

## Review Focus

1. **A company name with accents**, e.g. "Nestlé": `_normalised_name` drops `é`, so "Nestlé" must still match "Nestlé S.A." (both sides normalise the same way). Test in Task 2.
2. **A completed transition plan run with no result rows**: `from_transition_plan_run` raises on an empty run; the lookup must skip that run, not return 502. Test in Task 2.
3. **A benchmark with no constituents or zero total weight**: no division by zero; `total_pct` 0.0, `unclassified_pct` 0.0, `sectors` []. Test in Task 1.
4. **A whitespace-only question** ("   "): a person expects it to be refused without a model call; strip before the length check, so it is a 422. Test in Task 3.
5. **`sessionStorage` unavailable** (private window, blocked storage): the panel still works and keeps turns in memory. Test in Task 4.

---

### Task 1: Ask models and the benchmark sectors tool

**Files:**
- Create: `backend/arp/ask.py`
- Test: `backend/tests/test_ask_tools.py`

**Interfaces:**
- Produces (all in `arp/ask.py`):
  - `Tool = Literal["portfolio", "smart_search", "transition_plan", "benchmark_sectors", "none"]`
  - `class HistoryTurn(BaseModel)`: `question: str`, `tool: Tool`, `standalone_question: str`; `model_config = ConfigDict(extra="forbid")`
  - `class AskRequest(BaseModel)`: `question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]`, `history: list[HistoryTurn] = Field(default_factory=list, max_length=5)`
  - `class AskRouting(BaseModel)`: `tool: Tool`, `standalone_question: str`, `company: str | None = None`, `benchmark_id: str | None = None`
  - `class TransitionPlanFigures(BaseModel)`: `indicators_disclosed_count`, `walk_disclosed_count`, `talk_disclosed_count`, `walk_share_pct`, `assessment_confidence_pct` (all `float`)
  - `class OlderRun(BaseModel)`: `run_id: str`, `run_date: str`
  - `class TransitionPlanCard(BaseModel)`: `company`, `company_id`, `run_id`, `run_type: Literal["transition_plan", "extraction"]`, `run_date`, `figures: TransitionPlanFigures`, `open_review_items: int`, `older_runs: list[OlderRun]`
  - `class BenchmarkCheck(BaseModel)`: `source: str`, `as_of: str | None`, `constituents: int`, `dropped: int`, `unclassified_pct: float`, `total_pct: float`
  - `class SectorWeight(BaseModel)`: `sector: str`, `weight_pct: float`
  - `class BenchmarkCard(BaseModel)`: `benchmark_id: str | None`, `name: str`, `is_sample: bool`, `check: BenchmarkCheck`, `sectors: list[SectorWeight]`
  - `class AskResponse(BaseModel)`: `tool`, `question`, `standalone_question`, `answer_text`, `answered_at: str`, `portfolio: QAAnswer | None = None`, `smart_search: SearchAnswer | None = None`, `transition_plan: TransitionPlanCard | None = None`, `benchmark_sectors: BenchmarkCard | None = None`
  - `NONE_TEXT = "I can't answer that yet. I can answer: portfolio exposure; data issues, outputs and feeds; a company's newest transition plan assessment; a benchmark's sector weights."`
  - `def benchmark_sectors(streams_root: Path, benchmark_id: str | None) -> tuple[BenchmarkCard | None, str]` — returns `(card, answer_text)`

- [ ] **Step 1: Write the failing tests** in `tests/test_ask_tools.py`. Write benchmarks as JSON files under `tmp_path / "benchmarks"` in the shape `parse_ishares_holdings` returns plus an id (check `BenchmarkStore._path` for the file name).

```python
def test_sectors_sum_sort_and_unclassified(tmp_path):  # AC-14, AC-15
    bid = write_benchmark(tmp_path, name="iShares MSCI World ETF", as_of="Oct 20, 2026", dropped=3,
        constituents=[("A", "Information Technology", 30.0), ("B", "Information Technology", 20.004),
                      ("C", "Financials", 40.0), ("D", "", 9.996)])
    card, text = benchmark_sectors(tmp_path, bid)
    assert [(s.sector, s.weight_pct) for s in card.sectors] == [("Information Technology", 50.0), ("Financials", 40.0), ("Unclassified", 10.0)]
    assert card.check.model_dump() == {"source": "iShares holdings export", "as_of": "Oct 20, 2026", "constituents": 4, "dropped": 3, "unclassified_pct": 10.0, "total_pct": 100.0}
    assert card.is_sample is False and card.name == "iShares MSCI World ETF"
    assert text == "Sector weights of iShares MSCI World ETF as of Oct 20, 2026."

def test_unclassified_is_a_share_of_total(tmp_path):  # AC-16
    bid = write_benchmark(tmp_path, constituents=[("A", "Energy", 72.0), ("B", "", 8.0)])
    card, _ = benchmark_sectors(tmp_path, bid)
    assert (card.check.total_pct, card.check.unclassified_pct) == (80.0, 10.0)

def test_sample_when_nothing_uploaded(tmp_path):  # AC-17
    card, text = benchmark_sectors(tmp_path, None)
    assert card.is_sample and card.benchmark_id is None and card.name == "Synthetic sample"
    assert card.check.source == "synthetic sample" and card.check.as_of is None
    assert card.check.constituents == 12 and card.check.dropped == 0
    assert card.check.total_pct == round(sum(i["holding"]["index_weight_pct"] for i in sample_issuers()), 2)
    assert text.startswith("Synthetic sample: 12 fictional companies standing in for MSCI World.")

def test_unknown_or_missing_id_asks_which(tmp_path):  # AC-18
    write_benchmark(tmp_path, name="B Index"); write_benchmark(tmp_path, name="A Index")
    for bid in (None, "nope"):
        assert benchmark_sectors(tmp_path, bid) == (None, "Which benchmark do you mean: A Index, B Index?")

def test_empty_benchmark_has_no_division_by_zero(tmp_path):  # Review Focus 3
    card, _ = benchmark_sectors(tmp_path, write_benchmark(tmp_path, constituents=[]))
    assert (card.check.total_pct, card.check.unclassified_pct, card.sectors) == (0.0, 0.0, [])
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_ask_tools.py -v` — Expected: FAIL (`ModuleNotFoundError: arp.ask`).

- [ ] **Step 3: Implement the models and `benchmark_sectors`** in `arp/ask.py`. Read benchmarks with `BenchmarkStore(streams_root)`; the sample from `stewardship.process.SAMPLE_PATH` (`issuers[*].sector`, `holding.index_weight_pct`). Round every sum with `round(x, 2)`; sort sectors by `(-weight_pct, sector)`. Sample text verbatim: `Synthetic sample: 12 fictional companies standing in for MSCI World. Upload the iShares URTH holdings file under Stewardship → Benchmarks for the real index.`

- [ ] **Step 4: Run** `python3 -m pytest tests/test_ask_tools.py -v && ruff check arp/ask.py tests/test_ask_tools.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(ask): request/response models and benchmark sector tool`

---

### Task 2: The newest transition plan assessment tool

**Files:**
- Modify: `backend/arp/ask.py`
- Test: `backend/tests/test_ask_transition_plan.py`

**Interfaces:**
- Consumes: `TransitionPlanCard`, `TransitionPlanFigures`, `OlderRun` (Task 1); `decision.sources.from_transition_plan_run`, `is_transition_plan_preset_run`, `_normalised_name`; `review.items.list_open_items`.
- Produces: `def newest_transition_plan(run_store: RunStore, principal: Principal, company: str | None) -> tuple[TransitionPlanCard | None, str]`

- [ ] **Step 1: Write the failing tests.** Seed runs with `store_preset_run` / `preset_record` from `tests/test_decision_sources.py` and old runs via `JobManager(run_store).create_run("transition_plan", {}, n)` + `append_result`; set `status`, `created_at` and `params.trial` with `run_store.save_manifest(m.model_copy(update=...))`. Seed review items with `run_store.append_review_item(run_id, {..., "company_id": ...})` and decisions the way `tests/test_review_items.py` does.

| Test | Covers | Assertion |
|---|---|---|
| `test_newest_completed_run_wins_and_running_is_skipped` | AC-3 | `card.run_id == r_1020`, `card.run_date == run_store.load_manifest(r_1020).created_at`, `card.company == "BASF SE"` |
| `test_figures_come_from_the_run_row` | AC-4 | the five `card.figures` equal the BASF SE row of `from_transition_plan_run(run_store, r_1020)` (`Indicators_Disclosed_Count` … `Assessment_Confidence_pct`, as floats) |
| `test_older_runs_are_the_next_two_newest_first` | AC-5 | `[(o.run_id, o.run_date) for o in card.older_runs] == [(d3, d3_created), (d2, d2_created)]` |
| `test_partially_completed_counts` | AC-6 | `card.run_id == r_1022` |
| `test_trial_runs_never_count` | AC-7 | `card.run_id == older_non_trial` |
| `test_no_run_includes_company` | AC-8 | `(None, "No completed transition plan assessment includes BASF.")` |
| `test_open_items_count_only_this_run_and_company` | AC-9 | `card.open_review_items == 2`, `text.endswith(" 2 items still wait for review.")` |
| `test_no_open_items_text` | AC-10 | `text == f"BASF SE: newest transition plan assessment from 2026-10-20 (run {r_1020})."` |
| `test_exact_match_beats_contains` | AC-11 | rows "BASF", "BASF SE" → `card.company == "BASF"` |
| `test_contains_match_on_one_company` | AC-12 | `company="BASF Coat"` → `card.company == "BASF Coatings GmbH"` |
| `test_several_companies_ask_which` | AC-13 | `(None, 'Several companies match "Shell": Shell Midstream Partners, Shell plc. Which one do you mean?')` |
| `test_older_runs_follow_the_chosen_company` | AC-53 | d3 holds only "BASF Coatings GmbH" → `older_runs` = [d2, d1] |
| `test_missing_company_asks_which` | AC-55 | `company=None` and `company="—"` → `(None, "Which company do you mean?")` |
| `test_accented_names_match` | Review Focus 1 | `company="Nestlé"` finds row "Nestlé S.A." |
| `test_empty_completed_run_is_skipped` | Review Focus 2 | a newer completed run with no rows is ignored; the older run with BASF SE is returned |

- [ ] **Step 2: Run** `python3 -m pytest tests/test_ask_transition_plan.py -v` — Expected: FAIL (`ImportError: newest_transition_plan`).

- [ ] **Step 3: Implement `newest_transition_plan`** in `arp/ask.py`, following spec §Transition plan steps 1–9 in order. Candidates: `run_store.list_runs()` filtered to (`run_type == "transition_plan"` or `is_transition_plan_preset_run(m)`), `status in {COMPLETED, PARTIALLY_COMPLETED}`, `not m.params.get("trial")`, sorted by `(created_at, run_id)` descending. Read each lazily, newest first, catching the error `from_transition_plan_run` raises for an empty run. The run date in `answer_text` is `run_date[:10]`. Open items: `list_open_items(run_store, principal, run_id=run_id)` filtered on `item.payload.get("company_id") == row Company_Id`.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_ask_transition_plan.py tests/test_decision_sources.py -v && ruff check .` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(ask): newest transition plan assessment lookup`

---

### Task 3: `POST /api/ask` — routing, dispatch, audit, errors

**Files:**
- Create: `backend/arp/api/routers/ask.py`
- Modify: `backend/arp/api/main.py` (import and `app.include_router(ask.router, dependencies=[Depends(authorize)])`)
- Modify: `backend/arp/api/routers/security_master.py` — move the three Smart Search input lists into `def datahub_lists(settings, store, idmap, run_store, decisions, taxonomy, index, reports, today: date) -> dict[str, list[dict]]` and call it from `post_smart_search` (same behaviour)
- Test: `backend/tests/test_api_ask.py`

**Interfaces:**
- Consumes: everything in `arp/ask.py`; `qa_agent.answer_question`; `smart_search.smart_search`; `datahub_lists`; `qa_audit.record_answer`; deps `get_llm_client`, `get_run_store`, `get_portfolio_store`, `get_stream_store`, `settings_dep`, `current_user` and the Smart Search store deps.
- Produces: `router = APIRouter(prefix="/api/ask", tags=["ask"])`; `@router.post("", response_model=AskResponse) async def post_ask(req: AskRequest, ...) -> AskResponse`; `ROUTING_SYSTEM_PROMPT: str` (lists the five tools, says never to state a number, includes the uploaded benchmarks as `id: name` lines).

- [ ] **Step 1: Write the failing tests** with `TestClient(app)` and `app.dependency_overrides` as in `tests/test_smart_search.py::test_route_answers_and_audits`. The fake LLM script keys are output-model class names: `AskRouting`, `AnalyticSpec` (qa_agent), `SearchFilter` (smart search).

| Test | Covers | Assertion |
|---|---|---|
| `test_portfolio_question_matches_ask_the_portfolio` | AC-1 | BMW lines total 1,234,567.00; `r.json()["portfolio"] == client.post("/api/portfolio/ask", json={"question": q}).json()`; BMW result value `1234567.0`; `answer_text` equal to that body's |
| `test_smart_search_question_matches_smart_search` | AC-2 | `r.json()["smart_search"] == client.post("/api/smart-search", ...).json()`; `answer_text` equal |
| `test_none_tool_text` | AC-19 | body without `history` → 200, `answer_text == NONE_TEXT` |
| `test_history_limits` | AC-20 | 5 turns → 200; 6 → 422 |
| `test_question_length_limits` | AC-21 + Review Focus 4 | 1,000 chars → 200; `""`, `"   "`, 1,001 chars → 422; the fake LLM got no call for the 422s |
| `test_history_turn_rejects_extra_keys` | AC-22 | turn with `"answer"` → 422 |
| `test_viewer_is_refused` | AC-23 | drop the `authorize` override, sign in as a viewer → 403 |
| `test_one_audit_row_per_call` | AC-24 | 6 calls → 6 new rows from `GET /api/portfolio/qa-audit`, in call order `ask.portfolio, ask.smart_search, ask.transition_plan, ask.benchmark_sectors, ask.none, ask.portfolio`; follow-up row `question == "now only equities"` |
| `test_routing_failure_is_502_and_audited` | AC-25 | fake LLM raises → 502, `detail == "Ask could not answer this question. Try again."`, one row `endpoint == "ask.error"`, `error` set |
| `test_rejected_requests_leave_no_audit_row` | AC-26 | a 422 and a 403 → row count unchanged |
| `test_tool_failure_is_502_audited_under_the_tool` | AC-50 | routing → `transition_plan`, `run_store.list_runs` raises → 502, row `endpoint == "ask.transition_plan"`, `error` set |
| `test_ask_only_reads` | AC-28 | counts of runs, benchmarks, review decisions, published facts unchanged after one call per tool; audit rows +5 |

- [ ] **Step 2: Run** `python3 -m pytest tests/test_api_ask.py -v` — Expected: FAIL (404 on `/api/ask`).

- [ ] **Step 3: Implement `post_ask`.** Order: route (one `complete_structured` with `AskRouting`, prompt = history questions + question) → dispatch on `routing.tool` → build `AskResponse` with `answered_at = datetime.now(UTC).isoformat()` → `finally:` one `qa_audit.record_answer(endpoint=f"ask.{tool}" or "ask.error", question=req.question, ...)`. Wrap the body in `try/except Exception` → `HTTPException(502, "Ask could not answer this question. Try again.")`. For `portfolio`/`smart_search`, `answer_text` = the agent's `answer_text` if `resolvable` else its `clarification_needed`. Run the sync store reads with `run_in_threadpool`, as `post_smart_search` does.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_api_ask.py tests/test_smart_search.py tests/test_qa_agent.py tests/test_qa_audit.py tests/test_auth.py -v && ruff check .` — Expected: PASS, with no change to the existing test files (AC-27).

- [ ] **Step 5: Regenerate the API contract.** `cd backend && python scripts/export_openapi.py`, then `cd ../frontend && npm run gen:api`. Expected: `frontend/src/api/openapi.json` and `schema.gen.ts` gain `AskRequest`/`AskResponse`.

- [ ] **Step 6: Commit** `feat(ask): POST /api/ask routes questions to read-only tools` (include both generated files).

---

### Task 4: Frontend API, types and conversation history

**Files:**
- Modify: `frontend/src/types.ts` — `export type AskResponse = Served<S["AskResponse"]>; export type AskHistoryTurn = Served<S["HistoryTurn"]>;`
- Modify: `frontend/src/api/client.ts` — `ask: (question: string, history: AskHistoryTurn[]) => request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ question, history }) })`
- Create: `frontend/src/lib/askHistory.ts`
- Test: `frontend/src/lib/askHistory.test.ts`

**Interfaces:**
- Produces (`lib/askHistory.ts`):
  - `type AskTurn = { id: string; question: string; status: "working" | "answered" | "error"; response?: AskResponse; error?: string }`
  - `function historyFor(turns: AskTurn[]): AskHistoryTurn[]` — the newest 5 `answered` turns, oldest first, each `{question, tool, standalone_question}` from `response`
  - `function loadTurns(storage?: Storage | null): AskTurn[]`, `function saveTurns(turns: AskTurn[], storage?: Storage | null): void`, `function clearTurns(storage?: Storage | null): void` — key `"arp.ask.turns"`; default storage is `window.sessionStorage`; every access in try/catch; `working` turns are saved as `error` with no text so a reload never shows a stuck spinner

- [ ] **Step 1: Write the failing tests:** `historyFor` with 7 answered turns returns the newest 5 in order (AC-48); an `error` turn between two answered turns is left out (AC-54); `loadTurns` with a storage whose `getItem` throws returns `[]`, and `saveTurns` with one whose `setItem` throws does not throw (Review Focus 5); save → load round-trip; `clearTurns` → `loadTurns` returns `[]`.

- [ ] **Step 2: Run** `cd frontend && npx vitest run src/lib/askHistory.test.ts` — Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `lib/askHistory.ts`, the `api.ask` line and the two types.

- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — Expected: PASS. No `contract.ts` line is needed, because both types are `Served<S[...]>`.

- [ ] **Step 5: Commit** `feat(ask): frontend client and conversation history`

---

### Task 5: The panel in the app shell

**Files:**
- Create: `frontend/src/components/AskPanel.tsx`, `frontend/src/components/AskCards.tsx`
- Create: `frontend/src/components/SmartSearchRows.tsx` — the row table now inline in `pages/SmartSearch.tsx` (lines ~59–70), moved unchanged
- Modify: `frontend/src/pages/SmartSearch.tsx` (use `SmartSearchRows`), `frontend/src/App.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: `api.ask`, `AskTurn`, `historyFor`, `loadTurns`, `saveTurns`, `clearTurns` (Task 4); `AggregationResultTable`, `BarChart`, `Modal`-style focus handling from `CommandPalette`; `useMe()` for the role.
- Produces: `export function AskPanel({ open, onClose, returnFocusTo }: { open: boolean; onClose: () => void; returnFocusTo: () => HTMLElement | null })`; `export function AskCard({ response }: { response: AskResponse })`.

- [ ] **Step 1: Shell wiring in `App.tsx`.** `const canAsk = me != null && me.role !== "viewer"`. Add a "Ask ARP" button (shortcut shown as `⌘J`/`Ctrl J`, like "Jump to…") under the "Jump to…" button, and an "Ask" button in `.app-topbar`, both only when `canAsk`. Extend the existing keydown handler: Ctrl/⌘J (only when `canAsk`) → `preventDefault()` and open. Keep `turns` state in the shell (initialised from `loadTurns()`, saved on change) so it survives page changes. `returnFocusTo`: the button that opened it; for the shortcut, the top-bar button when `window.matchMedia("(max-width: 1024px)").matches`, else the sidebar button.

- [ ] **Step 2: `AskPanel`.** Right-hand panel (`role="dialog"`, `aria-label="Ask ARP"`), focus to the input on open, Esc and the close button → `onClose()` then focus `returnFocusTo()`. Input and Send are disabled while a turn is `working`, and that card reads `Working…`. On error, the card shows the response `detail` (fallback: the spec's 502 text) and Send is enabled again. "Clear" calls `clearTurns()` and empties the state. CSS: full screen (`inset: 0; width: 100%`) at `max-width: 640px`; no element wider than the viewport.

- [ ] **Step 3: `AskCard`.** Every card starts with `answer_text`. Then:
  - portfolio: the query's filters (from `spec.security_filter`, as the Ask the Portfolio page prints them) and `AggregationResultTable`;
  - smart_search: `SmartSearchRows`;
  - transition_plan: company, run link (`#/runs/<run_id>`), date, the five figures, "Open review items: N" (0 shown), older runs;
  - benchmark: the check block, then `BarChart` from `sectors`, then a table of the same numbers.

  Last line, verbatim per kind: `Source: holdings engine · holdings as of <vintage.holdings_as_of>`, `Source: Data Hub lists · <answered_at as YYYY-MM-DD HH:MM> UTC`, `Source: run <run_id> · <run_date[:10]>`, `Source: <name> · as of <as_of>` / `Source: synthetic sample`.

- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — Expected: PASS with no test file changed (AC-47).

- [ ] **Step 5: Look at it in the running app.** `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`. Then screenshot the panel with Playwright at 1280 px and 390 px, in light and dark, with one card of each kind. Check `document.documentElement.scrollWidth <= 390` at 390 px. Run `/impeccable:impeccable audit` on the panel and fix what it flags. Run `e2e_stack.sh down` when done.

- [ ] **Step 6: Commit** `feat(ask): Ask ARP panel in the app shell`

---

## Finishing

- Run the full checks listed under Global Constraints, then `/ponytail:ponytail-review` and `/code-review`.
- Open a PR against `main` with `Spec: ask-arp-panel` in the body, a `risk:` label (see `.claude/skills/steward/SKILL.md`), and every test file added. The hidden `holdout` rows are written by the `test-writer` skill in a separate session that never sees this branch. List them as owed if `HOLDOUT_TOKEN` is missing. The `evaluator` rows (AC-29 to AC-49, AC-51, AC-52, AC-54) are checked once CI is green.
- `openwiki/` needs no hand edit; the weekly `/context-refresh` picks up the new endpoint.
