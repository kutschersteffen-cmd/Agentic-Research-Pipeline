# RFP Approved Answers First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RFP auto-fill uses an approved answer unchanged where it fits, changes it as little as possible otherwise and shows the change, and falls back to reference documents in priority order.

**Architecture:** `draft_answer` becomes a chain of steps (approved answers alone, then one step per document priority). Each step is one drafting call, the existing code checks, and one call to the verifier model. The code, not the model, copies an unchanged answer and computes the word comparison with `difflib`. Reference documents are a new table parsed with the existing PDF and Word parser and chunked with the existing chunker.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, `difflib` (stdlib), the existing `arp.grounding`, `arp.ingestion` and `arp.retrieval` modules, React + TypeScript, Playwright. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-15-rfp-approved-answers-first-design.md` (slug `rfp-approved-answers-first-design`). Every test named `test_ac_<n>_...` asserts exactly the "Then" of row AC-n with the row's fixtures; the row text is the test's specification.

## Global Constraints

- Two pull requests against `main`, both `risk:high`. PR 1 is tasks 1 to 5, PR 2 is tasks 6 to 9. Each description carries `Spec: rfp-approved-answers-first-design` and the `Rows:` line from the spec's "Slices".
- Output model names are fixed: `DraftOut`, `FactCheck`, `DetectedQuestions`, `QuotedPairs`. Hidden tests supply `model/<Name>.json`.
- Every new `DraftOut` and `FactCheck` field has a default. A model answer that breaks a rule fails the step, never the run: no validator may raise on it.
- The drafting prompt still ends with `RFP question: <question>` and the verifier prompt still contains `Draft: <answer>`; existing tests key on both.
- Word comparison: split at whitespace, `difflib.SequenceMatcher(None, base_words, answer_words, autojunk=False).get_opcodes()`.
- Exact messages: `<name> is not a .pdf or .docx file.`, `<name> has no text layer; upload the original document.`, `Reference document not found`. Exact page copy: `Approved answer, unchanged`, `<n>% unchanged from the approved answer`, `From approved answers only`, `Uses documents (priority <p>)`, `p. <n>`.
- OCR is never used. A PDF for which `_has_text_layer` is false is refused.
- Schema changes go through the models only; `ensure_schema` adds tables and nullable columns. No `SCHEMA_STEPS` entry is needed.
- After changing a request or response model: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, fix `npx tsc -b`, commit both generated files.
- Existing test files change only where this plan names them. List every such change in the PR description.
- Checks before each commit: `cd backend && ruff check . && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python3 -m pytest tests/<file>`; for frontend changes `cd frontend && npm run lint && npx tsc -b && npm test`.

## Review Focus

1. A citation that names an entry or document the step did not show (a retired entry's id, another project's document): the step fails and the run ends `done`. Test in task 2 (`test_citation_to_an_entry_not_shown_fails_the_step`) and task 7 (`test_citation_to_a_document_not_shown_fails_the_step`).
2. A reference document with no text (an empty `.docx`): upload succeeds or is refused, but auto-fill never crashes on it. Test in task 7 (`test_document_without_text_is_skipped`).
3. An upper-case suffix (`STATEMENT.PDF`, `Policy.DOCX`): accepted like the lower-case one. Test in task 6 (`test_suffix_case_is_ignored`).
4. "Auto-fill again" after a document was added: a question left `no source` earlier is drafted from the new document. Test in task 7 (`test_autofill_again_uses_a_document_added_later`).
5. A long answer (2,000 words) with a base entry: reading the project stays fast, because the page polls it. Test in task 1 (`test_compare_two_thousand_words_under_half_a_second`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/arp/rfp/compare.py` (new) | Word comparison of an answer with its base entry's answer. |
| `backend/arp/rfp/draft.py` | Output models, the chain, the step checks, the second model's check. |
| `backend/arp/rfp/documents.py` (new, PR 2) | Parsing an uploaded reference document; turning stored documents into what the chain is shown. |
| `backend/arp/rfp/store.py` | Loading entries and documents for a run, storing drafts, the project as the API returns it, flags. |
| `backend/arp/rfp/golden.py`, `backend/arp/cli/rfp.py` | `expect` labels and the two new thresholds. |
| `backend/arp/db/models.py` | Two columns on `RfpQuestion`; table `RfpReferenceDocument` (PR 2). |
| `backend/arp/schemas/rfp.py` | Response and request models. |
| `backend/arp/api/routers/rfp.py` | Verifier passed to the runs; document endpoints (PR 2). |
| `frontend/src/pages/RfpAnswers.tsx`, `frontend/src/api/client.ts`, `frontend/src/api/contract.ts` | The page and its calls. |
| `backend/tests/test_rfp_compare.py`, `test_rfp_chain.py`, `test_rfp_documents.py` (new) | The spec's rows. |
| `backend/tests/rfp_fixtures.py`, `test_rfp_api.py`, `test_rfp_golden.py`, `e2e/test_rfp_page.py` | Fixtures, the stand-in, and the changes "Supersedes" allows. |

---

# PR 1: approved answers first

### Task 1: Word comparison

**Files:**
- Create: `backend/arp/rfp/compare.py`
- Test: `backend/tests/test_rfp_compare.py`

**Interfaces:**
- Produces: `compare(base: str, answer: str) -> tuple[list[dict[str, str]], int]` returning `([{"text": str, "change": "kept" | "added" | "removed"}], kept_share)`.

- [ ] **Step 1: Write the failing tests**

```python
from arp.rfp.compare import compare

BASE = "Example AM is an independent manager founded in 2004."


def seg(*pairs):
    return [{"text": t, "change": c} for t, c in pairs]


def test_unchanged_is_one_kept_run():
    assert compare(BASE, BASE) == (seg((BASE, "kept")), 100)


def test_added_word():  # AC-5, AC-6
    assert compare(BASE, "Example AM is an independent asset manager founded in 2004.") == (
        seg(("Example AM is an independent", "kept"), ("asset", "added"), ("manager founded in 2004.", "kept")), 90)


def test_removed_word():  # AC-45
    assert compare(BASE, "Example AM is an manager founded in 2004.") == (
        seg(("Example AM is an", "kept"), ("independent", "removed"), ("manager founded in 2004.", "kept")), 89)


def test_replace_is_removed_then_added_and_rounds_half_up():  # AC-58: 2 kept, 7 added, 7 removed = 12.5
    segments, share = compare(BASE, "Example AM has been managing money for pension funds.")
    assert [s["change"] for s in segments] == ["kept", "removed", "added"]
    assert share == 13


def test_appended_sentence():  # AC-32
    assert compare(BASE, BASE + " We engage on climate, governance and human rights.")[1] == 53


def test_compare_two_thousand_words_under_half_a_second():
    import time
    a, b = " ".join(f"w{i}" for i in range(2000)), " ".join(f"w{i}" for i in range(0, 2000, 2))
    start = time.perf_counter()
    compare(a, b)
    assert time.perf_counter() - start < 0.5
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && python3 -m pytest tests/test_rfp_compare.py -q`
Expected: FAIL, `No module named 'arp.rfp.compare'`

- [ ] **Step 3: Implement `compare` in `backend/arp/rfp/compare.py`**

Opcodes map `equal` to `kept`, `insert` to `added`, `delete` to `removed`, `replace` to a `removed` run then an `added` run. A run's text is its words joined by single spaces. Share: `(200 * kept + total) // (2 * total)` with `total = kept + added + removed` (integer half-up).

- [ ] **Step 4: Run them and see them pass**

Run: `cd backend && python3 -m pytest tests/test_rfp_compare.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/arp/rfp/compare.py backend/tests/test_rfp_compare.py
git commit -m "rfp: word comparison of an answer with its base entry"
```

### Task 2: The chain's first step and the second model's check

**Files:**
- Modify: `backend/arp/rfp/draft.py` (`Cited`, `DraftOut`, `Draft`, `draft_answer`; `FactCheck` and the verifier prompt move here from `golden.py`)
- Modify: `backend/arp/rfp/golden.py` (import `FactCheck` from `draft`; pass `verifier` to `draft_answer`)
- Modify: `backend/arp/rfp/store.py` (`autofill`, `detect_and_fill` take `verifier`; store the two new columns)
- Modify: `backend/arp/api/routers/rfp.py:146-148,181-196` (the run closures pass their third argument on)
- Modify: `backend/arp/db/models.py` (`RfpQuestion`)
- Modify: `backend/tests/test_rfp_api.py:39-55` (`Standin` answers `FactCheck`), `backend/tests/test_rfp_golden.py:46-48` (expected counts)
- Test: `backend/tests/test_rfp_chain.py`

**Interfaces:**
- Produces:
  - `class Cited(BaseModel)`: `entry_id: int | None = None`, `document_id: int | None = None`, `quote: str`
  - `class DraftOut(BaseModel)`: `use_entry: int | None = None`, `answer: str = ""`, `base_entry_id: int | None = None`, `citations: list[Cited] = []`, `missing: list[str] = []`
  - `class FactCheck(BaseModel)`: `unsupported: list[str] = []`, `unanswered: list[str] = []`
  - `@dataclass class Draft`: today's fields plus `base_entry_id: int | None = None`, `document_priority: int | None = None`
  - `async def draft_answer(question: str, entries: list[Entry], llm: LLMClient, verifier: LLMClient, *, today: date, settings=None, documents: Sequence = ()) -> Draft` (`documents` is used from task 7 on)
  - `async def autofill(project_id: int, llm: LLMClient, verifier: LLMClient, settings=None) -> None`, `async def detect_and_fill(project_id: int, data: bytes, suffix: str, llm: LLMClient, verifier: LLMClient, settings=None) -> None`
  - `RfpQuestion.base_entry_id: Mapped[int | None]` (`BigInteger`), `RfpQuestion.document_priority: Mapped[int | None]` (`Integer`)

- [ ] **Step 1: Write the failing tests in `backend/tests/test_rfp_chain.py`**

Reuse `env`, `_import`, `_entry_id`, `_q` and `Standin` from `tests/test_rfp_api.py` (import them). Add this helper and the first test; write the others the same way, each asserting its row's "Then" and `project["run_status"] == "done"`.

```python
def one_question(env, question, draft, check=None):
    """A project from rfp_one.xlsx whose one question the stand-in drafts with `draft`; returns the question's JSON."""
    env.llm = Standin(questions=[("RFP!A1", question, "RFP!B1")], drafts={question: draft})
    env.llm.check = check or FactCheck()
    r = env.as_("alice").post("/api/rfp/projects", data={"investor": "Pension Fund"},
                              files={"file": ("rfp_one.xlsx", fx.rfp_one_xlsx(question))})
    env.run_jobs()
    project = env.as_("bob").get(f"/api/rfp/projects/{r.json()['id']}").json()
    assert project["run_status"] == "done"
    return project["questions"][0]


def test_ac_1_use_entry_copies_the_approved_answer(env, tmp_path):
    _import(tmp_path)
    q = one_question(env, Q_FIRM, DraftOut(use_entry=_entry_id(FIRM)))
    assert (q["status"], q["answer"]) == ("drafted", FIRM)
```

Further tests in this task: `test_ac_3_use_entry_source_is_the_whole_answer`, `test_ac_4_use_entry_unknown_id`, `test_ac_9_missing_parts`, `test_ac_10_second_model_unsupported`, `test_ac_11_second_model_unanswered`, `test_ac_47_unsupported_fails_an_unchanged_answer`, `test_citation_to_an_entry_not_shown_fails_the_step` (the draft cites `entry_id=999999`; status `no source`, `run_status` `done`), `test_citation_with_neither_id_fails_the_step`.

Add to `backend/tests/rfp_fixtures.py`: `rfp_one_xlsx(question: str) -> bytes` (one sheet `RFP`, `A1` the question, `B1` empty).

- [ ] **Step 2: Change the stand-in and the superseded test**

In `tests/test_rfp_api.py` `Standin`: add `check = FactCheck()` and a branch `elif output_model is FactCheck: out = self.check`, before the drafting branch, so `shown` keeps holding drafting prompts only. In `tests/test_rfp_golden.py` `test_golden_drafts_counts`: the expected tuple becomes `(0, 14, 8, 8, 0)`: the Harbour draft answers an answerable question and is now `no source`, so nothing is drafted and nothing is left for the after-check to call unsupported.

- [ ] **Step 3: Run the new tests and see them fail**

Run: `cd backend && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python3 -m pytest tests/test_rfp_chain.py -q`
Expected: FAIL, `DraftOut` has no field `use_entry`

- [ ] **Step 4: Implement**

`draft_answer` runs step 0 when `entries` is not empty: rank (as today), call the model, then apply the spec's section 2 conditions in order (missing; `use_entry`; citations with exactly one id, grounding, numbers), then the verifier (`FactCheck`). The verifier prompt is `Question: <question>`, the support (each cited entry's whole answer as `[E<id>] <answer>`), then `Draft: <answer>`. The system prompt for drafting gains the spec's section 1 instruction (name an entry that answers as it is; otherwise start from the closest and change as little as possible; say what is missing). With `use_entry`, the source is `{"entry_id": id, "quote": <whole answer>}`. The base entry follows section 2's last paragraph. `document_priority` is 0 for every draft in this PR. `autofill` writes `base_entry_id` and `document_priority` in the same guarded `UPDATE` as the other draft fields.

- [ ] **Step 5: Run the RFP suites**

Run: `cd backend && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python3 -m pytest tests/test_rfp_chain.py tests/test_rfp_api.py tests/test_rfp_golden.py tests/test_rfp_fill.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/arp/rfp backend/arp/api/routers/rfp.py backend/arp/db/models.py backend/tests
git commit -m "rfp: use an approved answer unchanged, check every draft with the second model"
```

### Task 3: What the API returns

**Files:**
- Modify: `backend/arp/schemas/rfp.py`, `backend/arp/rfp/store.py` (`project_out`)
- Modify (generated): `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/test_rfp_chain.py`

**Interfaces:**
- Consumes: `compare` (task 1), the two columns (task 2).
- Produces:
  - `class RfpSegment(BaseModel)`: `text: str`, `change: Literal["kept", "added", "removed"]`
  - `RfpSourceOut` gains `kind: Literal["entry", "document"]`; `entry_id`, `entry_question`, `source` become optional; new optional `document_id: int`, `title: str`, `priority: int`, `page: int` (used from task 7 on)
  - `RfpQuestionOut` gains `document_priority: int | None`, `base_entry_id: int | None`, `kept_share: int | None`, `segments: list[RfpSegment]`

- [ ] **Step 1: Write the failing tests**

`test_ac_2_unchanged_answer_fields`, `test_ac_5_changed_answer_kept_share`, `test_ac_6_changed_answer_segments`, `test_ac_7_edit_keeps_the_base_entry`, `test_ac_8_hand_written_answer_has_no_base`, `test_ac_14_source_without_kind_reads_as_entry` (write a question row with `sources=[{"entry_id": id, "quote": "x"}]` directly, then `GET`), `test_ac_45_removed_word_segments`, `test_ac_58_rounds_half_up`, `test_base_entry_retired_still_compares` (retire `FIRM` after drafting; `kept_share` is still 100).

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && ARP_TEST_POSTGRES_DSN=... python3 -m pytest tests/test_rfp_chain.py -q -k "ac_2 or ac_5 or ac_6 or ac_7 or ac_8 or ac_14 or ac_45 or ac_58 or retired"`
Expected: FAIL, `KeyError: 'kept_share'`

- [ ] **Step 3: Implement**

`project_out` loads the base entries by id whatever their status, calls `compare(base.answer, q.answer)` for each question with a base, and returns `kind` from the stored source (`"document"` when it has `document_id`, else `"entry"`).

- [ ] **Step 4: Regenerate the API contract**

Run: `cd backend && python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b`
Expected: `tsc` reports only the nullable `entry_question` and `source` uses in `RfpAnswers.tsx`; fix those two reads.

- [ ] **Step 5: Run and commit**

Run: `cd backend && ARP_TEST_POSTGRES_DSN=... python3 -m pytest tests/test_rfp_chain.py tests/test_rfp_api.py -q`
Expected: all pass

```bash
git add backend/arp backend/tests frontend/src
git commit -m "rfp: return the base entry, the comparison and the source kind"
```

### Task 4: The page shows the change

**Files:**
- Modify: `frontend/src/pages/RfpAnswers.tsx` (`QuestionCard`)
- Test: `backend/tests/e2e/test_rfp_page.py`

**Interfaces:**
- Consumes: `RfpQuestion.base_entry_id`, `kept_share`, `segments`, `document_priority`; the base entry's question is the `entry_question` of the source whose `entry_id` equals `base_entry_id`.

- [ ] **Step 1: Write the failing browser tests**

`test_ac_12_changed_answer_shows_share_and_marks`, `test_ac_13_unchanged_answer`, `test_ac_46_removed_word_is_struck`, `test_ac_56_full_share_with_an_added_word_is_not_unchanged`. Each stubs `**/api/rfp/projects/1` with `project("done")` plus one question carrying the row's fields, opens `/#/rfp/1`, and asserts the row's texts with `page.get_by_text(...)` and the marks with `page.locator("ins", has_text="asset")` / `page.locator("del", has_text="independent")`.

- [ ] **Step 2: Run them and see them fail**

Run: `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up && cd backend && ARP_E2E_URL=http://localhost:5173 ARP_CHROMIUM_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux*/chrome | head -1) pytest -m e2e tests/e2e/test_rfp_page.py -q`
Expected: the four new tests FAIL (text not found)

- [ ] **Step 3: Implement in `QuestionCard`**

Under the chips, when `q.base_entry_id !== null && q.segments.length > 0`: a line with the base entry's question and `Approved answer, unchanged` when every segment is `kept`, else `` `${q.kept_share}% unchanged from the approved answer` ``; then the segments in a read-only paragraph, `added` in `<ins>`, `removed` in `<del>`, `kept` as plain text. When `q.document_priority === 0`: `From approved answers only`. Reuse the existing `muted` and `help-text` classes; no new CSS file.

- [ ] **Step 4: Run, screenshot, audit, commit**

Run the command of step 2. Expected: all pass. Screenshot the project page with Playwright and run `/impeccable:impeccable audit` on it; fix what it flags in this card. Then `bash backend/scripts/e2e_stack.sh down`.

```bash
git add frontend/src/pages/RfpAnswers.tsx backend/tests/e2e/test_rfp_page.py
git commit -m "rfp page: show what changed against the approved answer"
```

### Task 5: Golden check for unchanged answers

**Files:**
- Modify: `backend/arp/rfp/golden.py` (`score_drafts`), `backend/arp/cli/rfp.py` (`golden_drafts`), `.github/workflows/golden-set.yml:160`
- Create: `backend/arp/golden_set/data/rfp_unchanged_drafts.json`
- Test: `backend/tests/test_rfp_golden.py`

**Interfaces:**
- Produces: `score_drafts` counts gain `unchanged`, `unchanged_total`, `library_first`, `library_first_total`. A question is answerable when `q.get("expect", "library" if q.get("answerable") else "none") != "none"`. CLI options `--min-unchanged` and `--min-library-first` (both optional floats; a threshold is checked only when its `_total` is above 0).

- [ ] **Step 1: Write the failing test**

`test_golden_unchanged_counts`: a three-question case built in the test (one `unchanged`, one `library`, one `none`) with a stand-in that returns `use_entry` for the first, a cited draft for the second and an empty draft for the third; assert `(c["unchanged"], c["unchanged_total"], c["drafted"], c["blank"]) == (1, 1, 2, 1)`. `test_golden_unchanged_case_file_is_well_formed`: the new file loads, every question has an `expect` in `{"unchanged", "library", "none"}`, and there are at least 10 of each.

- [ ] **Step 2: Run, implement, run**

Run: `cd backend && python3 -m pytest tests/test_rfp_golden.py -q` (FAIL, then PASS after implementing).
The case file: a fictitious firm ("Example AM" must not be reused; pick another invented name), 12 library entries, and 30 questions: 10 worded so an entry answers as it is, 10 needing a small change (a narrower or combined question), 10 the library cannot answer.

- [ ] **Step 3: Add the workflow line and commit**

In the RFP golden step add: `arp rfp golden drafts --cases arp/golden_set/data/rfp_unchanged_drafts.json --min-drafted 0.90 --min-blank 0.95 --min-unchanged 0.90 | tee -a "$GITHUB_STEP_SUMMARY"`

```bash
git add backend/arp backend/tests .github/workflows/golden-set.yml
git commit -m "rfp golden: unchanged answers threshold"
```

- [ ] **Step 4: Open PR 1**

Title `RFP auto-fill: approved answers first`. Body: `Spec: rfp-approved-answers-first-design`, `Rows: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-36, AC-38, AC-39, AC-45, AC-46, AC-47, AC-56, AC-58`, the test-file changes of task 2 step 2, and whether `openwiki/` needs an update (yes: the RFP drafting flow). Label `risk:high`. Follow `.claude/skills/steward/SKILL.md`.

---

# PR 2: reference documents and the chain

Branch from `main` after PR 1 has merged.

### Task 6: Reference documents

**Files:**
- Modify: `backend/arp/db/models.py` (new model), `backend/arp/schemas/rfp.py`, `backend/arp/api/routers/rfp.py`
- Create: `backend/arp/rfp/documents.py`
- Modify (generated): `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`
- Modify: `backend/tests/rfp_fixtures.py`
- Test: `backend/tests/test_rfp_documents.py`

**Interfaces:**
- Produces:
  - `class RfpReferenceDocument(Base)`, table `rfp_reference_documents`: `id`, `title`, `filename`, `content_key`, `full_text`, `page_breaks` (JSONB list of ints), `document_date`, `review_by`, `priority` (Integer, default 1), `status` (`active` | `retired`), `uploaded_by`
  - `documents.parse(name: str, data: bytes) -> tuple[str, list[int]]` (text, page starts); raises `ClientInputError` with the two exact 400 messages
  - `class RfpDocumentOut(BaseModel)`: `id`, `title`, `filename`, `document_date`, `review_by`, `priority`, `status`, `uploaded_by`, `pages: int | None`
  - `class RfpDocumentEdit(BaseModel)`: `title: str | None = Field(None, min_length=1)`, `review_by: date | None = None`, `priority: int | None = Field(None, ge=1)`
  - Routes `GET /api/rfp/documents`, `POST /api/rfp/documents`, `PUT /api/rfp/documents/{id}`, `POST /api/rfp/documents/{id}/retire`
  - Fixtures `ref_stmt_docx()`, `ref_stmt_pdf()` (reportlab, two pages), `ref_policy_docx()`, `ref_scan_pdf()` (one page, one image, no text), each returning bytes

- [ ] **Step 1: Write the failing tests**

`test_ac_15_upload_lists_the_document`, `test_ac_16_analyst_cannot_upload`, `test_ac_17_wrong_file_type`, `test_ac_18_scanned_pdf_is_refused`, `test_ac_19_pdf_page_count` (replace `arp.ingestion.local_files._extract_pdf_text` with a stand-in returning the fixture text and `[0, <start of page 2>]`, as `tests/test_local_files_pdf_pages.py` does), `test_ac_20_replaces_retires_the_old_one`, `test_ac_21_replaces_unknown_id`, `test_ac_22_analyst_cannot_retire`, `test_ac_35_put_priority_only`, `test_ac_43_put_unknown_id`, `test_ac_44_upload_without_date`, `test_ac_49_priority_zero_on_upload`, `test_ac_50_retire_unknown_id`, `test_ac_51_list_order`, `test_ac_54_priority_zero_on_put`, `test_suffix_case_is_ignored` (`STATEMENT.DOCX` uploads with 200).

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && ARP_TEST_POSTGRES_DSN=... python3 -m pytest tests/test_rfp_documents.py -q`
Expected: FAIL, 404 on `/api/rfp/documents`

- [ ] **Step 3: Implement**

`documents.parse` writes the bytes to a temporary file with the original suffix, checks `_has_text_layer` for a PDF, and calls `parse_file_to_text_with_pages`. The upload stores the original through `upload_or_fail` under its sha256, as `create_project` does. `pages` is `len(page_breaks)` for a PDF, `None` for Word. `POST` takes `priority: int = Form(1, ge=1)` and `document_date: date = Form(...)`. `replaces` is looked up and retired in the same transaction as the insert. The list is ordered by `priority`, then `id`.

- [ ] **Step 4: Regenerate the contract, run, commit**

Run: `cd backend && python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b`, then the tests of step 2. Expected: all pass.

```bash
git add backend/arp backend/tests frontend/src/api
git commit -m "rfp: reference documents with a priority"
```

### Task 7: Documents in the chain

**Files:**
- Modify: `backend/arp/rfp/draft.py`, `backend/arp/rfp/documents.py`, `backend/arp/rfp/store.py`, `backend/arp/api/routers/rfp.py` (`edit_answer`, retire, upload with `replaces`)
- Test: `backend/tests/test_rfp_chain.py`

**Interfaces:**
- Consumes: `RfpReferenceDocument` (task 6), `draft_answer(..., documents=)` (task 2).
- Produces:
  - `@dataclass(frozen=True) class RefDoc`: `id: int`, `title: str`, `file: str`, `priority: int`, `review_by: date`, `retired: bool`, `source: SourceDocument` (its `doc_id` is `f"rfpdoc-{id}"`, with `full_text` and `page_breaks`)
  - `documents.active(s) -> list[RefDoc]`
  - Stored document source: `{"document_id": int, "quote": str, "page": int | None, "priority": int}`
  - `store.source_flags(s, sources: list[dict], answer: str) -> list[str]`, used by drafting, `edit_answer` and the retire paths
  - `documents.flag_stale(s, document_id: int) -> None`: adds `stale source` to every `drafted` or `edited` question citing the document

- [ ] **Step 1: Write the failing tests**

`test_ac_23_retired_document_is_not_used`, `test_ac_24_draft_from_a_document`, `test_ac_25_pdf_page` (PDF parse stood in as in task 6), `test_ac_26_quote_not_in_the_document`, `test_ac_27_number_outside_the_quote`, `test_ac_28_stale_document`, `test_ac_29_second_priority`, `test_ac_30_first_priority_wins`, `test_ac_31_library_first`, `test_ac_32_entry_and_document`, `test_ac_33_retire_flags_the_answer`, `test_ac_34_replace_flags_the_answer`, `test_ac_48_later_step_without_a_document`, `test_ac_52_shared_priority`, `test_ac_53_citation_with_both_ids`, `test_ac_55_lower_priority_is_not_shown_early`, `test_ac_57_two_priorities_cited`, `test_citation_to_a_document_not_shown_fails_the_step`, `test_document_without_text_is_skipped` (an empty `.docx` is active; auto-fill ends `done`), `test_autofill_again_uses_a_document_added_later`.

AC-32, AC-48 and AC-55 need a stand-in whose answer depends on the step: give `Standin.drafts` a list per question and pop one per drafting call.

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && ARP_TEST_POSTGRES_DSN=... python3 -m pytest tests/test_rfp_chain.py -q`
Expected: the new tests FAIL with status `no source`

- [ ] **Step 3: Implement**

After step 0, `draft_answer` runs one step per distinct priority of `documents`, lowest first. Step p shows the top 8 entries and the top 8 chunks (`chunk_document(doc.source)`) of the documents with priority p or lower, ranked together with `select_relevant_chunks`. Document quotes are grounded with `ground_claim(..., passages={chunk_id: chunk})` over the chunks shown at this step. The numbers allowed from a document are the numbers of each grounded citation's `span_text`. The verifier's support lists each cited document as `[D<id>] <span_text>`, next to the entries. `page` comes from the grounded citation. `document_priority` is the largest `priority` among cited documents, 0 when none. `store.autofill` loads `documents.active(s)` once per run. `source_flags` gives `check figure` by the existing rule and `stale source` when a cited entry or document has `review_by` before today or a cited document is retired.

- [ ] **Step 4: Run the RFP suites and commit**

Run: `cd backend && ARP_TEST_POSTGRES_DSN=... python3 -m pytest tests/test_rfp_chain.py tests/test_rfp_documents.py tests/test_rfp_api.py tests/test_rfp_golden.py -q`
Expected: all pass

```bash
git add backend/arp backend/tests
git commit -m "rfp: fall back to reference documents in priority order"
```

### Task 8: The page shows documents

**Files:**
- Modify: `frontend/src/pages/RfpAnswers.tsx`, `frontend/src/api/client.ts`, `frontend/src/api/contract.ts`, `frontend/src/types.ts`
- Test: `backend/tests/e2e/test_rfp_page.py`

**Interfaces:**
- Produces: `api.listRfpDocuments()`, `api.uploadRfpDocument(file: File, title: string, documentDate: string, priority: number, replaces: number | null)`, `api.retireRfpDocument(id: number)`; type `RfpDocument = Served<S["RfpDocumentOut"]>`; one `contract.ts` line per new `request<T>()`.

- [ ] **Step 1: Write the failing browser test**

`test_ac_40_document_source_and_priority` (stubbed project; asserts `Uses documents (priority 2)`, `Stewardship Statement 2025`, `p. 2`, `512 engagement meetings`).

- [ ] **Step 2: Implement**

A section "Reference documents" below "Answer library": a table with the columns Priority, Title, File, Document date, Review by, Status; for approvers an upload form (file `accept=".pdf,.docx"`, title, document date, priority defaulting to 1, an optional "Replaces" select of active documents) and a Retire button on active rows, built like the library section. In `QuestionCard`, a document source renders its title, `p. <n>` when `page` is not null, and the quote; `document_priority > 0` renders `Uses documents (priority <p>)`.

- [ ] **Step 3: Run, check AC-41 and AC-42 by hand, screenshot, audit, commit**

Run the e2e command of task 4 step 2. In the running app upload a `.docx` with priority 2 and retire it; confirm the rows of AC-41 and AC-42. Screenshot the page and run `/impeccable:impeccable audit`.

```bash
git add frontend/src backend/tests/e2e/test_rfp_page.py
git commit -m "rfp page: reference documents and document sources"
```

### Task 9: Golden check for the chain

**Files:**
- Modify: `backend/arp/rfp/golden.py` (`score_drafts` builds `RefDoc`s from the case's `documents`), `.github/workflows/golden-set.yml`
- Create: `backend/arp/golden_set/data/rfp_chain_drafts.json`
- Test: `backend/tests/test_rfp_golden.py`

- [ ] **Step 1: Write the failing test**

`test_golden_library_first_counts`: a case with one entry, one document and two questions (`library`, `documents`); the stand-in cites the entry for the first and the document for the second; assert `(c["library_first"], c["library_first_total"], c["drafted"]) == (1, 1, 2)`. `test_golden_chain_case_file_is_well_formed`: at least 10 questions of each of the four `expect` values, two documents with priorities 1 and 2.

- [ ] **Step 2: Implement, run, add the workflow line, commit**

Workflow line: `arp rfp golden drafts --cases arp/golden_set/data/rfp_chain_drafts.json --min-drafted 0.90 --min-blank 0.95 --min-unchanged 0.90 --min-library-first 0.95 | tee -a "$GITHUB_STEP_SUMMARY"`

```bash
git add backend/arp backend/tests .github/workflows/golden-set.yml
git commit -m "rfp golden: library-first threshold with documents"
```

- [ ] **Step 3: Open PR 2**

Title `RFP auto-fill: reference documents in priority order`. Body: `Spec: rfp-approved-answers-first-design` and no `Rows:` line (the last slice drops it). Label `risk:high`. State whether `openwiki/` needs an update (yes).
