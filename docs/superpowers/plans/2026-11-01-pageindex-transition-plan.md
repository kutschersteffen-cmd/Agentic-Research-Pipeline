# PageIndex Transition-Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `arp pageindex` workflow. An LLM builds a table-of-contents tree per PDF, then walks it to answer the 64 transition-plan indicators. No vectors or keywords.

**Architecture:** New package `backend/arp/pageindex/` with three modules: `tree.py` builds and caches the tree, `navigate.py` runs the per-indicator walk-and-answer loop, and `golden.py` scores answers on the gold set. A Typer app in `arp/cli/pageindex.py` is registered with one line in `arp/cli/__init__.py`. LLM calls go only through `LLMClient.complete_structured`.

**Tech Stack:** Python 3, Pydantic, Typer, asyncio, existing `arp.llm`, `arp.ingestion.local_files`, `arp.grounding`.

**Spec:** `docs/superpowers/specs/2026-11-01-pageindex-transition-plan-design.md`

## Global Constraints

- No imports of embeddings, BM25, rerank, `select_evidence` or `INDEX_CACHE` in `arp/pageindex/`. Command 1 in the spec (AC-21) must not match anything.
- No `pageindex` third-party package (AC-22, AC-28).
- Only these files change: new files under `backend/arp/pageindex/`, `backend/tests/` and `docs/`, plus `backend/arp/cli/__init__.py` (AC-24). The CLI module therefore lives at `arp/pageindex/cli.py`, not under `arp/cli/`.
- Step limit 6, page budget 12, concurrency 8, batch 20 pages × 600 chars, summary ≤60 words from the first 6,000 chars.
- Exact stdout lines as the spec gives them, with 2 decimals for cost, recall and yes-rate.

## Review Focus

1. A PDF with no text layer (scanned) gives empty page heads. The tree is then one `Front matter` node, and the run still completes. Test in Task 1.
2. The LLM returns section start pages out of range or not ascending. Clamp them to 1..N, sort them, and drop duplicates. Test in Task 1.
3. The LLM opens an unknown node ID. Ignore it, and the step still counts. Test in Task 2.
4. The LLM cites pages it never opened. Keep them as returned (the scoring decides). No test.
5. A gold-set document download fails. Exit 1 with `Could not fetch <document>: <message>`. Test in Task 3.

---

### Task 1: Tree building and cache

**Files:**
- Create: `backend/arp/pageindex/__init__.py` (empty), `backend/arp/pageindex/tree.py`
- Test: `backend/tests/test_pageindex_tree.py`

**Interfaces:**
- Produces:
  - `class Node(BaseModel): node_id: str; title: str; start_page: int; end_page: int; summary: str = ""; children: list[Node] = []`
  - `PROMPT_VERSION = "1"`
  - `def page_texts(pdf: Path) -> list[str]`: splits `parse_file_to_text_with_pages` at the page offsets (1-based list index + 1 = page).
  - `async def build_tree(pages: list[str], llm: LLMClient) -> tuple[list[Node], LLMUsage]`
  - `async def load_or_build_tree(pdf: Path, llm: LLMClient) -> tuple[list[Node], LLMUsage]`: cache file `Path(f"{pdf}.pageindex.json")` holding `{sha256, prompt_version, tree}`.
  - `def leaves(tree: list[Node]) -> list[Node]`

- [ ] **Step 1: Write failing tests.** Use a fake LLM (a class with `complete_structured` that dispatches on `output_model`) and pass `pages` lists directly where possible.
  - `test_one_section_per_page`: 3 pages, the fake returns sections starting at 1, 2, 3 → 3 nodes `P1..P3`, each covering its own page.
  - `test_front_matter` (AC-10): first section at page 2 → a node `Front matter` covering 1–1.
  - `test_leaves_cover_all_pages` (AC-26): the union of leaf ranges is 1..N with no overlap, including level-2 children.
  - `test_bad_starts_clamped` (Review Focus 2): starts `[5, 2, 2, 99]` on 3 pages → nodes start at 2 and 3, plus front matter covering 1.
  - `test_empty_text` (Review Focus 1): 3 empty pages, the fake returns no sections → one `Front matter` node covering 1–3.
  - `test_cache_reused` (AC-6, AC-7): `load_or_build_tree` on a temp file whose text is stubbed with monkeypatch on `page_texts`. The second call uses a fake that raises and still returns the tree. The cache `sha256` equals `hashlib.sha256(bytes).hexdigest()`.
  - `test_cache_rebuilt_on_change` (AC-8, AC-25) and `test_cache_rebuilt_on_prompt_version` (AC-9).
- [ ] **Step 2:** Run `cd backend && python3 -m pytest tests/test_pageindex_tree.py`. Expected: fails on import.
- [ ] **Step 3: Implement.** The section call uses output model `SectionList(sections: list[{title: str, start_page: int, level: Literal[1,2]}])`. The prompt shows `[page n]\n<first 600 chars>` per page. Each node ends at the page before the next start of the same or higher level, and the last one at N. Node IDs are `"1"`, `"1.2"` and so on. Summaries come from one call per level-1 node, output model `Summary(summary: str)`, over its pages joined and cut to 6,000 chars. Sum the usages.
- [ ] **Step 4:** Run the same command. Expected: pass. Also run `ruff check arp/pageindex tests/test_pageindex_tree.py`.
- [ ] **Step 5:** Commit `feat(pageindex): tree building and cache`.

### Task 2: Navigate-and-answer loop and `run` command

**Files:**
- Create: `backend/arp/pageindex/navigate.py`, `backend/arp/pageindex/cli.py`
- Modify: `backend/arp/cli/__init__.py` (import `pageindex_app` from `arp.pageindex.cli`, then `app.add_typer(pageindex_app, name="pageindex")` next to `transition-plan`)
- Test: `backend/tests/test_pageindex_run.py`

**Interfaces:**
- Consumes: Task 1 `Node`, `page_texts`, `load_or_build_tree`.
- Produces:
  - `class Result(BaseModel): identifier: str; answer: Literal["YES","NO","ERROR"]; pages: list[int] = []; pages_opened: list[int] = []; quotes: list[str] = []; reasoning: str = ""; steps: int = 0; error: str | None = None` (`error` is dumped only when set, `exclude_none`)
  - `async def answer_indicator(ind: TransitionPlanIndicator, tree: list[Node], pages: list[str], llm: LLMClient) -> tuple[Result, LLMUsage]`
  - `async def run_document(pdf: Path, indicators: list[TransitionPlanIndicator], llm: LLMClient) -> tuple[dict, LLMUsage]`: returns the output JSON dict `{document, sha256, model, tree_nodes, results}`.
  - `def make_llm() -> LLMClient`: `build_llm_client(get_settings())`. Tests monkeypatch `arp.pageindex.cli.make_llm`.
- [ ] **Step 1: Write failing tests** through Typer's `CliRunner` against `arp.cli.app`, with `make_llm` monkeypatched and `page_texts` monkeypatched to return 3 (or 20) strings.
  - `test_run_64_results` (AC-1), `test_all_yes_page1` (AC-2), `test_stdout_line` (AC-3: exactly `PageIndex: 64 indicators, 64 YES, 0 pages read, $0.00`), `test_output_keys` (AC-4), `test_indicator_filter` (AC-5).
  - `test_forced_answer_at_step6` (AC-11): 20 one-page sections; the fake opens the next node unless `output_model` is the answer-only model → `steps == 6`, `answer == "NO"`.
  - `test_partial_open_budget` (AC-12): `pages_opened == list(range(1, 13))`.
  - `test_error_isolated` (AC-13, AC-27), `test_error_summary` (AC-14: stdout ends with `, 1 errors`), `test_retry_once` (AC-15: `steps == 1`).
  - `test_tree_failure` (AC-16): exit 1, stderr `Could not build page tree: boom`, no out file.
  - `test_unknown_node_ignored` (Review Focus 3).
- [ ] **Step 2:** Run `python3 -m pytest tests/test_pageindex_run.py`. Expected: fails.
- [ ] **Step 3: Implement.** Each step's output model is `Step(action: Literal["open","answer"], open: list[str] = [], answer: Literal["YES","NO"] | None, pages, quotes, reasoning)`. When forced (step 6 or budget reached), use `Answer` (answer fields only). The prompt holds the question, guideline, tree rendered as `id | title | pp a–b | summary`, and the opened pages' text as `[page n]` blocks. Opening adds the node's pages in order until 12 distinct pages are open. A step that raises is retried once (the retry does not count as a step); a second failure gives `ERROR` with `str(exc)`. Run the indicators with `asyncio.Semaphore(8)`. Cost uses `estimate_cost_usd(model, usage)` from `arp.orchestration.cost_tracker`, formatted `$%.2f`. `--indicator` is repeatable and matches `identifier`.
- [ ] **Step 4:** Run the tests and ruff. Expected: pass.
- [ ] **Step 5:** Commit `feat(pageindex): navigate-and-answer loop and run command`.

### Task 3: `golden` command

**Files:**
- Create: `backend/arp/pageindex/golden.py`; add the `golden` command to `backend/arp/pageindex/cli.py`
- Test: `backend/tests/test_pageindex_golden.py`

**Interfaces:**
- Consumes: Task 2 `run_document`, Task 1 `page_texts`; `arp.grounding._normalize` (reuse it, don't copy it).
- Produces: `def ensure_document(cases_file: Path, documents_dir: Path, company_id: str, document: str) -> Path`, and `def score(cases: list[dict], results_by_doc: dict[str, dict], pages_by_doc: dict[str, list[str]]) -> tuple[int, int, int, float]` returning (hit, total, stale, yes_rate).
- Mapping: case `field_id` `tp_a_headline_1` ↔ indicator `identifier.lower()` with the `tp_` prefix. Only indicators that have cases are run.
- [ ] **Step 1: Write failing tests.** `test_hit` (AC-17), `test_miss` (AC-18), `test_stale` (AC-19, recall `0.00 (0/0)`), `test_hash_mismatch` (exit 1, `Document d.pdf does not match its recorded hash.`) and `test_fetch_failure` (Review Focus 5). Use a temp `documents.json` and a monkeypatched `httpx.get` for the fetch case.
- [ ] **Step 2:** Run. Expected: fails.
- [ ] **Step 3: Implement.** A case is stale when the normalised span is not in the normalised whole-document text. It is a hit when the answer is YES and the normalised span is in the normalised text of a cited page. Recall is `hit/total`, or `0.00` when `total == 0`. Exit 1 when recall < `--min-recall` (default 0).
- [ ] **Step 4:** Run all three test files and ruff, then Command 1 and Command 2 from the spec (both must exit 1) and `git diff --name-status origin/main` (AC-24).
- [ ] **Step 5:** Commit `feat(pageindex): golden-set scoring`.

### Task 4: Real-model run (AC-20, AC-23)

- [ ] Run `arp pageindex golden --cases tests/golden/retrieval/cases.json --min-recall 0.30` with `ARP_ANTHROPIC_API_KEY` set. Record the recall in the PR next to today's recall@12. If there is no key, mark AC-20 as owed in the PR.
