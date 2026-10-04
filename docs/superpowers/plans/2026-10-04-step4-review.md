# Step 4: Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reviewer decides from one decision-ready view, through constrained decisions (accept, correct with its own grounded citation, reject, escalate) with a structured reason. Second-reviewer rules are enforced from the append-only log. What the reviewer saw is stored with each decision. Values, sector codes, ambiguous identities, held documents and restatement candidates arrive in one workbench queue under the same rules.

**Architecture:**
- The decision log stays `runs/<id>/review_decisions.jsonl`: append-only, human-only, one row per decision. New rows add `reason_code`, `corrected_value`, `correction_citation`, `snapshot_id`, `step` (`first` | `second` | `resolution`) and `second_required`/`second_reasons`. `record_review_decision` and the rows it writes are unchanged, so voting keeps its byte-identical path.
- The item state (`pending`, `first_done`, `second_done`, `disagreed`, `final`) is derived from the log on every read (`item_state` in `arp/orchestration/review_queue.py`). No mutable state file. `effective_decisions` returns only the items in a final state (`second_done` or `final`), so the projection, `RunHistory`, `prior.rejected` and the identity enriched universe publish nothing that still waits on a second reviewer.
- A new package `arp/review/` holds the workbench: `items.py` turns each run's queue, held documents and restatement candidates into `ReviewItem`s (E60); `context.py` builds the decision bundle and its snapshots (E52, E58); `decide.py` runs the decision rules (E53, E54). One router, `arp/api/routers/review.py`, serves them under `/api/review`.
- The step 1 co-sign is subsumed. A new correction gets its second signature as a `second` decision row. A legacy `edit` row is read as a `correct` without a citation that needs a second signature, which a legacy row in `review_cosigns.jsonl` or a new agreeing `second` row supplies.
- Frontend: `RunReviewList` and the Review Queue page each make one fetch (`GET /api/review/items`). `ReviewControls` gains a decision mode that loads the bundle. `SourcePanel` gains a text mode that renders the stored parsed text with the span highlighted, and a text selection becomes the correction citation.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, stdlib `hashlib`/`json`/`math`, pytest with `FakeLLMClient` (`tests/conftest.py`); React + TypeScript (Vite), node test runner.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4`, section B4. This step covers E52, E53, E54, E58 and E60. E56, E57, E59 and E61 are step 7. Paths are relative to `backend/` unless they start with `frontend/`. It builds on step 1 (`docs/superpowers/plans/2026-10-03-step1-identity-review-keys.md`), step 2 (`docs/superpowers/plans/2026-10-04-step2-capture-and-typing.md`) and step 3 (`docs/superpowers/plans/2026-10-04-step3-checks-and-routing.md`).

**Deviations from the spec text, decided here:**
- The context route is run-scoped: `GET /api/review/runs/{run_id}/items/{item_key}/context`, not `/api/extraction/items/{item_key}/context`. Decisions live per run, the same `item_key` recurs across runs, and the bundle serves all five kinds.
- The new request model is `ItemDecisionRequest` (in `arp/schemas/review.py`). The existing `ReviewDecisionRequest` in `api/review_endpoints.py` stays as it is for the five run kinds outside the workbench (theme activities, financials, TNFD, transition plan, transition barrier), so their contracts do not move.
- `reason_code` is a new `DecisionReason` enum. `ReasonCode` keeps its step 1–3 meaning (why an item was flagged, which drives routing).
- `corrected_value` is a `dict` validated per kind (there is no `ExtractedValue` type in the codebase).
- A citation is required for a correction only where a stored document exists: `value` and `restatement_candidate`. Identity and sector-code corrections have no source document, so they require a `comment` instead. Every other rule (second reviewer, blind view, escalation) is the same for all five kinds.

## Global Constraints

- **Voting is frozen.** Do not change `arp/api/routers/voting.py`, `arp/voting/`, `arp/cli/voting.py`, `arp/stewardship/voting_feed.py`, `frontend/src/components/BallotReview.tsx`, `ReviewerField.tsx`, `ConfirmDecision.tsx`, the voting pages, or any voting test. `useReviewer` stays unchanged. The voting router stays unauthenticated. The workbench excludes voting runs entirely.
- Shared code that voting calls keeps voting's path byte-identical: `record_review_decision`, `latest_decisions`, `decision_history`, `get_review_queue`, `get_review_history`, `submit_review`, `ReviewDecisionRequest`, `VALID_DECISIONS`, and the frontend `DecisionBar`, `CitationList`, `CommentField`, `ProposedTag`, `lib/cardKeys`. `SourcePanel` changes only additively: an `ActiveSource` without `text` renders exactly as today.
- No new dependencies, backend or frontend.
- **The grounding gate is never weakened.** A correction citation is grounded server-side with `ground_citations` against the stored text of one of the item's documents. Any `grounded`, `char_start`, `char_end` or `span_text` the client sends is discarded. An ungrounded citation, a citation to a document outside the item, an unavailable source text, or (for numeric fields) a corrected number not found in the grounded span is refused with 422.
- **Old data loads and behaves the same:**
  - Legacy decision rows have no `step`. `approve` and `reject` are `final` (effective at once, as today). `edit` in an extraction run (`cosign_required={"edit"}`) is read as `correct` without a citation that needs a second signature: `first_done` until a co-sign row in `review_cosigns.jsonl` binds to its `decided_at`, or until an agreeing `second` row follows; either makes it `second_done`. `edit` in any other run (identity) stays `final`, as today.
  - The one intended behaviour change: a legacy `escalate` row (API-only, never sent by the UI) is now `pending`. Before, extraction projected it as `rejected`.
  - Old queue rows: company-level extraction rows (`item_key` = `company_id`) are `value` items; rows with and without `route`, `route_reasons` or `reason_codes` load unchanged. Old results rows without `extractor_confidence`, `verifier_confidence`, `alternatives` or `documents` load with defaults.
  - Theme, financials, TNFD, transition-plan and transition-barrier review keep their endpoints, decisions and response shapes.
- `review_decisions.jsonl` stays human-only. Every new row comes from `append_decision` with a `Principal`; system routes stay on the results row (step 3).
- **Clients never see `user_id`.** The `/api/review/*` responses and the extraction `review-decisions`/`review-history` responses carry public decisions only: role and decision date, never `user_id` and never the reviewer's name. A server-computed `mine: bool` replaces the frontend's `user_id` comparison. Rows keep `user_id`, `role` and `reviewer` (name) internally; the Postgres projection still fills `reviewer` from the name. The legacy kinds' endpoints are unchanged (out of scope).
- Step 3's auto-accept, hold and trial semantics are unchanged. `RunHistory`, `prior.rejected` and the projection read `correct` as an edit and `escalate` as pending, and count a decision only once its item is in a final state.
- Dev auth mode stays the default; tests use the `conftest.py` principal override and build other principals explicitly.
- Exact strings:
  - Decisions: `approve`, `correct`, `reject`, `escalate`. Legacy rows may also hold `edit`.
  - Decision reasons (`DecisionReason`): `confirmed`, `wrong_value`, `wrong_unit_or_scale`, `wrong_period`, `wrong_entity`, `not_disclosed`, `bad_source`, `needs_expert`, `other`. `approve` requires `confirmed`; every other decision forbids it.
  - States: `pending`, `first_done`, `second_done`, `disagreed`, `final`. `FINAL_STATES = {"second_done", "final"}`.
  - Steps: `first`, `second`, `resolution`.
  - Second-review reasons: `correction`, `high_risk`, `published_change`, `first_audit_pending`, `sample`.
  - Item kinds: `value`, `sector_code`, `identity`, `quarantined_document`, `restatement_candidate`, plus `other` for the legacy kinds' rows, which keep their own decision endpoints.
  - Item keys: value `"{issuer_key}:{field_id}:{period}"` (unchanged); identity `company_id` (unchanged); held document `"held:{company_id}:{doc_id}"`; sector code `"isic:{company_id}"`; restatement candidate its `candidate_id` (`rst_…`).
- HTTP status codes for decisions: 404 unknown item; 400 an `other`-kind item; 422 an invalid body or a citation refused; 403 a role too low (escalated or disagreed items need an approver); 409 the same person as a second reviewer or resolver, or a stale `context_etag`.
- Backend checks: `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest -q && ruff check arp tests`. The baseline is 45 failures that already exist (Chromium, pdftoppm, postgres factories, the nltk hardlink sandbox, botocore). There must be no new failures.
- Frontend checks: `cd frontend && npm run lint && npm test && npm run build`. The baseline is 0 errors and 13 warnings; add no new errors or warnings.

## Review Focus

1. **A legacy correction keeps its meaning.** An uncosigned extraction `edit` stays pending in the projection and in `RunHistory`, a co-signed one stays `edited`, and an identity `edit` with no co-sign still feeds the enriched universe. Tests: Task 1 (`test_legacy_extraction_edit_needs_cosign`), Task 2 (`test_legacy_identity_edit_still_included`, `test_legacy_cosigned_edit_still_edited`).
2. **The same person, twice.** The second reviewer and the resolver are compared on `user_id`, not name (`"Alice"` vs `"alice "`), and are refused with 409. Test in Task 6 (`test_same_user_refused_as_second_reviewer`).
3. **The blind view leaking through a side door.** For a high-risk item in `first_done`, the first decision is hidden from other non-approvers on every surface: the context bundle, `GET /api/review/items`, extraction `review-decisions` and `review-history`. Tests in Task 4 (`test_blind_item_hides_decision_in_list`) and Task 5 (`test_blind_view_hides_first_decision`, `test_blind_history_and_decisions_hidden`).
4. **A correction citation that does not support the value.** A quote that is not in the stored text, from a document outside the item, or holding a different number, is refused with 422 and never stored. Tests in Task 6 (`test_ungrounded_correction_citation_is_422`, `test_correction_citation_from_foreign_doc_is_422`, `test_correction_number_not_in_span_is_422`).
5. **Two reviewers on one item at once.** Decisions take the run lock, and a decision on a context that changed since it was loaded is refused with 409, so a second "second review" cannot silently start a new round. Test in Task 6 (`test_stale_context_etag_is_409`).

---

### Task 1: Decision shape and item state machine (E53, E54 core)

**Files:**
- Modify: `arp/schemas/review.py`: `DecisionKind`, `DecisionReason`, `ReviewDecision`, `held_item_key`, `sector_item_key`
- Modify: `arp/orchestration/review_queue.py`: `FINAL_STATES`, `ItemState`, `same_value`, `agrees`, `item_state`, `item_states`, `effective_decisions` (rewritten, same signature), `append_decision`, `public_decision`, `blind_for`
- Test: `tests/test_review_state.py` (new)

**Interfaces:**
- Produces, in `arp/schemas/review.py`:
  - `class DecisionKind(StrEnum)`: `APPROVE="approve"`, `CORRECT="correct"`, `REJECT="reject"`, `ESCALATE="escalate"`
  - `class DecisionReason(StrEnum)`: the nine values in Global Constraints
  - `class ReviewDecision(BaseModel)` (the stored row): `item_key: str`, `decision: DecisionKind`, `reason_code: DecisionReason`, `reviewer: str` (name, internal), `user_id: str` (internal), `role: str`, `corrected_value: dict | None = None`, `correction_citation: Citation | None = None`, `snapshot_id: str`, `comment: str | None = None`, `step: Literal["first", "second", "resolution"]`, `second_required: bool = False`, `second_reasons: list[str] = []`, `decided_at: str = Field(default_factory=now_iso)`
  - `def held_item_key(company_id: str, doc_id: str) -> str` returns `f"held:{company_id}:{doc_id}"`
  - `def sector_item_key(company_id: str) -> str` returns `f"isic:{company_id}"`
- Produces, in `arp/orchestration/review_queue.py` (existing functions unchanged unless named):
  - `FINAL_STATES = frozenset({"second_done", "final"})`
  - `@dataclass class ItemState`: `state: str = "pending"`, `escalated: bool = False`, `first: dict | None = None`, `second: dict | None = None`, `effective: dict | None = None`, `rows: list[dict] = field(default_factory=list)` (every row of the item, oldest first)
  - `def same_value(a, b) -> bool`: both parse as non-bool floats → `math.isclose(rel_tol=1e-9)`; else `str(a).strip() == str(b).strip()`.
  - `def agrees(first: dict, second: dict) -> bool`: the decision kinds match (a legacy `edit` counts as `correct`), and for `correct` the values match by `same_value` (the first row's value is `(corrected_value or edited_value or {}).get("value")`).
  - `def item_state(rows: list[dict], *, cosigned_at: set[str], cosign_required: set[str]) -> ItemState`: folds the rows in order:
    - Legacy row (no `step`): `escalate` → `pending`, `escalated=True`, `effective=None`. A decision in `cosign_required` → `first_done` (`first` = the row), or `second_done` (`effective` = the row) when its `decided_at` is in `cosigned_at`. Anything else → `final`, `effective` = the row.
    - `step == "first"`: `escalated = (decision == "escalate")`; `escalate` → `pending`; otherwise `first_done` when `second_required`, else `final`, with `effective` = the row. `first` = the row, `second = None`.
    - `step == "second"`: `agrees(first, row)` → `second_done`, `effective = first`; otherwise `disagreed`, `effective = None`. `second` = the row.
    - `step == "resolution"`: `final`, `effective` = the row, `escalated=False`.
  - `def item_states(run_store, run_id, *, cosign_required: set[str]) -> dict[str, ItemState]`: reads the decisions and `review_cosigns.jsonl` once.
  - `def effective_decisions(run_store, run_id, *, cosign_required: set[str]) -> dict[str, dict]`: for every item whose state is in `FINAL_STATES`, its `effective` row; a `correct` row is returned as `{**row, "edited_value": row["corrected_value"]}`, so readers of `edited_value` keep working. The signature is unchanged; all three callers keep passing `cosign_required={"edit"}`.
  - `def append_decision(run_store, run_id, d: ReviewDecision) -> None`: appends `d.model_dump(mode="json")` to `review_decisions.jsonl`.
  - `PUBLIC_KEYS = ("item_key", "decision", "reason_code", "role", "decided_at", "comment", "corrected_value", "correction_citation", "snapshot_id", "step", "edited_value")`
  - `def public_decision(row: dict, principal: Principal | None) -> dict`: `{k: row.get(k) for k in PUBLIC_KEYS}` plus `mine = principal is not None and row.get("user_id") == principal.user_id`. Never `user_id`, never `reviewer`.
  - `def blind_for(s: ItemState, principal: Principal, *, high_risk: bool) -> bool`: True when `high_risk`, `s.state == "first_done"`, `principal.role != "approver"` and `principal.user_id != s.first.get("user_id")`.
- `record_review_decision`, `latest_decisions`, `decision_history` and `record_cosign` keep their current code in this task.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_state.py`. Rows are written with `append_decision` (new shape) or `record_review_decision` (legacy):
  - `test_first_approve_without_second_is_final`: `state == "final"`, `effective["decision"] == "approve"`.
  - `test_first_correct_requiring_second_is_first_done`: `effective_decisions` has no entry for the key.
  - `test_agreeing_second_is_second_done_and_effective`: `effective_decisions[k]["edited_value"] == {"value": 1050}`, and `effective["user_id"]` is the first reviewer's.
  - `test_disagreeing_second_is_disagreed_not_effective`: the second row is `approve` after a first `correct`; also a second `correct` with `value` 1060 against 1050.
  - `test_resolution_is_final_and_effective`: after `disagreed`, a `resolution` row by an approver is the effective row.
  - `test_escalate_is_pending_and_flags_escalated`: also a `first` `correct` with `second_required` after an escalate gives `first_done` with `escalated is False`.
  - `test_new_round_after_final`: `final` approve, then a `first` correct with `second_required` gives `first_done`.
  - `test_legacy_extraction_edit_needs_cosign`: a legacy `edit` with `cosign_required={"edit"}` is `first_done`; after `record_cosign` it is `second_done` and effective.
  - `test_legacy_edit_with_agreeing_second_row_is_second_done`: a legacy `edit` `{"value": 5}`, then a `second` `correct` with `{"value": "5"}`.
  - `test_legacy_identity_edit_is_final`: `cosign_required=set()` gives `final`.
  - `test_legacy_approve_reject_final_and_escalate_pending`
  - `test_public_decision_has_no_user_id_or_name`: the keys are exactly `PUBLIC_KEYS + ("mine",)`; `mine` is True for the same principal and False for another one.
  - `test_blind_for`: True for another analyst on a high-risk `first_done`; False for the first reviewer, for an approver, for a field that is not high-risk, and in `second_done`.
  - `test_record_review_decision_row_unchanged`: the legacy row's keys are exactly `{"item_key", "decision", "reviewer", "user_id", "role", "edited_value", "comment", "decided_at"}` (voting's path).
  - `test_same_value_numeric_and_text`: `same_value(1050, "1050.0")` is True, `same_value("ACME", " ACME ")` is True, `same_value(True, 1)` is False.

- [ ] **Step 2: Run** `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_review_state.py -v`. Expect FAIL (`ImportError: append_decision`).

- [ ] **Step 3: Implement as in Interfaces.** Keep the `TYPE_CHECKING` import of `Principal` (the runtime import would cycle).

- [ ] **Step 4: Run** the full backend check. Expect no new failures (`test_cosign.py` passes unchanged: uncosigned `edit` stays out of `effective_decisions`).

- [ ] **Step 5: Commit** with `feat(review): decision rows with reason and step; item state derived from the log (E53, E54)`.

---

### Task 2: Readers of the new decision shapes

**Files:**
- Modify: `arp/storage/postgres_company_facts_projection.py` (`resolve_fact`, `resolve_extraction_fact`)
- Modify: `arp/extraction/history.py` (`_add_run`, `_decided_value`)
- Modify: `arp/discovery/identity_pipeline.py` (`enriched_universe`)
- Modify: `arp/orchestration/review_queue.py` (`record_cosign` guard)
- Test: `tests/test_postgres_company_facts_projection.py`, `tests/test_checks_prior_period.py`, `tests/test_identity_pipeline.py`, `tests/test_cosign.py` (extend all four)

**Interfaces:**
- Consumes: `effective_decisions`, `append_decision`, `ReviewDecision` (Task 1).
- Changes:
  - `resolve_fact`: `outcome in ("edit", "correct")` → the edited value, status `"edited"`.
  - `resolve_extraction_fact`: the outcome map becomes `{"approve": "approved", "edit": "edited", "correct": "edited"}`; the merge branch runs for `edit` or `correct` with an `edited_value`. For `correct` with a `correction_citation`, the merged field gets `citations = [correction_citation]` and `grounded = True` (the published correction carries its own grounded source).
  - `materialize_run`: the extraction branch widens to `run_type in ("extraction", "identity")` and reads `effective_decisions(..., cosign_required=cosign_rule(run_type))` (identity: `set()`), so an identity run no longer projects through `latest_decisions`. Non-final items are pending through `queued_item_keys |= set(latest_decisions) - set(effective)`. That set now includes `first_done`, `disagreed` and escalated items.
  - `RunHistory._add_run`: `kind in ("approve", "edit", "correct")` clears a rejection; `_decided_value` treats `correct` like `edit` (reads `edited_value`, which `effective_decisions` fills). `escalate` never reaches them (not effective).
  - `enriched_universe`: reads `effective_decisions(run_store, run_id, cosign_required=set())` instead of `latest_decisions`; `included = decision["decision"] in ("approve", "edit", "correct")`. An identity correction now publishes only after its second review; legacy identity rows behave as before.
  - `record_cosign`: raises `ValueError("use a second review")` when the latest decision has a `step` (new rows get their second signature as a decision, not a co-sign). The route already maps `ValueError` to 400.

- [ ] **Step 1: Write the failing tests:**
  - `test_correct_projects_as_edited_with_its_citation` (projection, pure `resolve_extraction_fact` with an effective `correct`): status `"edited"`, the field `value == 1050`, `citations == [citation]`, `grounded is True`, `canonical_value is None`.
  - `test_first_done_correction_projects_pending`: `materialize_run`'s decision view (`effective_decisions` + `queued_item_keys`) gives `"pending_review"` for a `first_done` key.
  - `test_escalated_item_projects_pending`
  - `test_identity_first_done_correction_projects_pending`: an identity run with a `first_done` `correct` projects the item as pending, not `edited`.
  - `test_legacy_cosigned_edit_still_edited` and `test_legacy_uncosigned_edit_still_pending`
  - `test_correct_counts_as_decided_value` (history): a prior non-trial run with an agreed `correct` gives `last_decided(k).value == 1050`, `decided_by == "human"`.
  - `test_first_done_reject_not_counted_as_rejected`: a high-risk reject still in `first_done` gives `last_rejected_value(k) is None`.
  - `test_identity_correct_needs_second_review_before_enriched`: a `first` `correct` with `second_required=True` leaves the company out; after an agreeing `second` it is in, with the corrected CIK.
  - `test_legacy_identity_edit_still_included`: a legacy `edit` without a co-sign is included, as today.
  - `test_cosign_refused_for_new_shape_decision` (in `test_cosign.py`): 400 from `POST /api/extraction/runs/{id}/cosign`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_postgres_company_facts_projection.py tests/test_checks_prior_period.py tests/test_identity_pipeline.py tests/test_cosign.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures; `test_legacy_rows_without_route_unchanged` (step 3) still passes.

- [ ] **Step 5: Commit** with `feat(review): projection, run history and identity read correct, escalate and second reviews`.

---

### Task 3: Decision-ready data captured at extraction time (E52 inputs)

**Files:**
- Modify: `arp/schemas/datapoints.py`: `Alternative`; `ExtractedField.extractor_confidence`, `verifier_confidence`, `alternatives`; `ExtractionRecord.documents`
- Modify: `arp/extraction/aggregator.py` (`build_extracted_fields`)
- Modify: `arp/extraction/pipeline.py` (`_extract_company`: `record.documents`, `content_key` on held documents, released documents not held)
- Modify: `arp/extraction/history.py` (`released_documents`)
- Test: `tests/test_aggregator.py`, `tests/test_entity_check.py`, `tests/test_checks_prior_period.py` (extend)

**Interfaces:**
- Consumes: `held_item_key` (Task 1); `effective_decisions` (Task 1).
- Produces:
  - `class Alternative(BaseModel)`: `value: str | float | bool | None`, `raw_value_text: str | None = None`, `source: Literal["extractor", "duplicate"]`, `citations: list[Citation] = []`
  - `ExtractedField.extractor_confidence: float | None = None`, `ExtractedField.verifier_confidence: float | None = None` (`draft.confidence` and `verifier.confidence`; None on rows written before this step and on `no_evidence_field`)
  - `ExtractedField.alternatives: list[Alternative] = []`, filled in `build_extracted_fields`:
    - When the verifier disagrees and its corrected value replaces the extractor's, the extractor's typed value with `pv.raw_value_text` and `ground_citations(pv.citations, ...)` becomes an `Alternative(source="extractor")`.
    - Each further value for an already-kept period (today dropped, with the "more than one value" note) becomes an `Alternative(source="duplicate")` on the kept row, its citations grounded the same way (with `passages`).
  - `ExtractionRecord.documents: list[dict] = []`: one `{"doc_id", "doc_type", "title", "company_id", "content_key", "parser_version", "source_filename"}` per document kept for extraction (not held). These are the documents a reviewer may cite in a correction.
  - Held document dicts gain `"content_key"`, `"parser_version"` and `"doc_type"`.
  - `RunHistory.released_documents() -> set[str]`: in `_add_run`, for each results row's `held_documents`, when `effective_decisions` has an `approve` for `held_item_key(company_id, doc_id)` and the dict has a `content_key`, add it. A later `reject` or a new round removes it.
  - In `_extract_company`, after `confirm_entity`: a document whose `content_key` is in `history.released_documents()` gets `match_status = MatchStatus.CONFIRMED` (a human released it). The step 3 checks then treat it as confirmed. A release decided in a trial run does not count (`RunHistory` skips trial runs).

- [ ] **Step 1: Write the failing tests:**
  - `test_confidence_components_recorded` (aggregator): draft 0.9, verifier 0.8 gives `confidence == 0.8`, `extractor_confidence == 0.9`, `verifier_confidence == 0.8`.
  - `test_verifier_disagreement_keeps_extractor_value_as_alternative`: `alternatives[0].source == "extractor"`, `alternatives[0].value == 4210.0`, and its citation is grounded.
  - `test_duplicate_period_value_kept_as_alternative`: two values for `2024-12-31` give one row, with `alternatives[0].source == "duplicate"`.
  - `test_old_row_loads_without_new_fields`: an `ExtractedField` dict without the three fields, and an `ExtractionRecord` dict without `documents`, validate with the defaults.
  - `test_record_lists_kept_documents` (`test_entity_check.py`, `_extract_company` with the subsidiary and parent docs): `record.documents` holds only the parent, with its `content_key`; `record.held_documents[0]["content_key"]` is the subsidiary's.
  - `test_released_document_not_held_next_run`: history from a prior run whose held subsidiary doc has an effective `approve`; `_extract_company` keeps it (`held_documents == []`, an evidence block from it reaches the model).
  - `test_released_documents_ignores_unagreed_release`: an `approve` in `first_done` releases nothing.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_aggregator.py tests/test_entity_check.py tests/test_checks_prior_period.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures. Step 3's input-hash reuse copies rows whole, so reused rows keep their alternatives.

- [ ] **Step 5: Commit** with `feat(extraction): record confidence components, conflict alternatives and cited documents; released documents are not held (E52)`.

---

### Task 4: One workbench queue (E60)

**Files:**
- Modify: `arp/schemas/review.py`: `ReviewItemKind`, `ReviewItem`
- Create: `arp/review/__init__.py` (empty), `arp/review/items.py`
- Create: `arp/api/routers/review.py`; Modify: `arp/api/main.py` (mount it with `dependencies=[Depends(authorize)]`)
- Modify: `arp/research/pipeline.py` (`CompanyMatchesResult.isic_code`, `isic_from_model`; `theme_review_items`)
- Modify: `arp/api/routers/themes.py` (`submit_theme_review` refuses `isic:` keys)
- Test: `tests/test_review_items.py` (new), `tests/test_research_pipeline.py` (extend)

**Interfaces:**
- Consumes: `item_states`, `public_decision`, `blind_for`, `FINAL_STATES`, `held_item_key`, `sector_item_key` (Task 1); `load_run_schema` (`arp/extraction/pipeline.py`); `RestatementCandidate` rows (`restatement_candidates.jsonl`, step 3).
- Produces, in `arp/schemas/review.py`:
  - `class ReviewItemKind(StrEnum)`: `VALUE="value"`, `SECTOR_CODE="sector_code"`, `IDENTITY="identity"`, `QUARANTINED_DOCUMENT="quarantined_document"`, `RESTATEMENT_CANDIDATE="restatement_candidate"`, `OTHER="other"`
  - `class ReviewItem(BaseModel)`: `item_key: str`, `kind: ReviewItemKind`, `run_id: str`, `run_type: str`, `payload: dict`, `state: str = "pending"`, `escalated: bool = False`, `high_risk: bool = False`, `decision: dict | None = None` (a `public_decision`, None when blind or undecided)
- Produces, in `arp/review/items.py`:
  - `REVIEWABLE_RUN_TYPES = ("theme", "extraction", "financials", "identity", "transition_plan", "tnfd")` (the Review Queue page's set today; never `voting`)
  - `LEGACY_COSIGN = {"extraction": {"edit"}}`; `def cosign_rule(run_type: str) -> set[str]` returns `LEGACY_COSIGN.get(run_type, set())`
  - `def run_items(run_store, manifest: RunManifest, principal: Principal) -> list[ReviewItem]`: every item of one run, in any state:
    - `extraction`: each queue row is a `value` item when it has `field` or `fields` (per-field and old company-level rows), else `other` (a `PreStepFailed` report). Each results row's `held_documents` entry is a `quarantined_document` item keyed `held_item_key(company_id, doc_id)`, with payload `{**held_doc, "company_id", "name", "issuer_key"}`. Each `restatement_candidates.jsonl` row is a `restatement_candidate` item keyed by its `candidate_id`.
    - `identity`: each queue row is an `identity` item.
    - `theme`: a queue row with `payload["kind"] == "sector_code"` is a `sector_code` item; other rows are `other`.
    - `financials`, `tnfd`, `transition_plan`: `other`.
    - The state comes from `item_states(..., cosign_required=cosign_rule(run_type))`. For `other` items, the state is `final` when `latest_decisions` has the key, else `pending` (today's rule).
    - `high_risk`: for `value` and `restatement_candidate` items, `FieldDefinition.high_risk` of the field in the run's `schema.json` (False when there is no snapshot).
    - `decision`: `public_decision(state.first if state.state == "first_done" else state.effective or state.second, principal)`, or None when `blind_for(state, principal, high_risk=item.high_risk)`.
  - `def list_open_items(run_store, principal, *, run_id: str | None = None) -> list[ReviewItem]`: items whose state is not in `FINAL_STATES`, over one run or over every run of a type in `REVIEWABLE_RUN_TYPES`. Mark `# ponytail: reads every reviewable run's files per call; keep an open-items index if run count makes this slow`.
  - `def get_item(run_store, run_id, item_key, principal) -> ReviewItem | None`
- Route, in `arp/api/routers/review.py` (`prefix="/api/review"`, `tags=["review"]`): `GET /api/review/items?run_id=` → `{"items": [ReviewItem...]}`; principal from `current_user`.
- In `arp/research/pipeline.py`:
  - `CompanyMatchesResult.__init__(..., isic_code: str | None = None, isic_from_model: bool = False)`; `_match_company` sets `isic_from_model = company_isic is not None and company.isic_code != company_isic` (the model chose it).
  - `def theme_review_items(company: CompanyRef, r: CompanyMatchesResult) -> list[tuple[str, dict]]`: today's activity rows, plus `(sector_item_key(c.company_id), {"kind": "sector_code", "company_id", "name", "isic_code", "source": "model"})` when `r.isic_from_model`. It replaces the inline lambda passed to `run_company_batch`. Rules before models: a model-chosen sector code always goes to review.
- `POST /api/themes/runs/{id}/review` (legacy theme route) refuses an `isic:` item key with 400 `"decide sector codes through the review workbench"`; sector codes decide only through the workbench rules.
- Decision effects per kind (wired in Task 6 and Task 3): a `value` decision feeds the projection and `RunHistory`. A `quarantined_document` approve releases the document for later runs. An `identity` decision feeds the enriched universe. A `restatement_candidate` or `sector_code` decision is recorded; publishing a restatement is step 5, and nothing reads a sector-code decision yet.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_items.py`. Fixture `five_kinds(run_store)` writes, with `RunStore` directly: an extraction run (manifest; one per-field queue row; a results row with one `held_documents` entry; one `restatement_candidates.jsonl` row; one `PreStepFailed` queue row), an identity run (one queue row), a theme run (one `sector_code` queue row and one activity row), and a voting run (one queue row).
  - `test_all_five_kinds_in_one_list`: `GET /api/review/items` returns the kinds `{"value", "quarantined_document", "restatement_candidate", "identity", "sector_code", "other"}`, and every item has `state == "pending"`.
  - `test_voting_run_excluded`: no item has `run_type == "voting"`.
  - `test_run_filter`: `?run_id=<identity run>` returns only the identity item.
  - `test_final_items_not_listed_first_done_listed`: a final approve removes the item; a `first` correct with `second_required=True` keeps it, with `state == "first_done"` and `decision["decision"] == "correct"`.
  - `test_blind_item_hides_decision_in_list`: a high-risk field (`schema.json` with `high_risk=True`) corrected by `u_alice`; for `u_bob` (analyst) the item has `decision is None` and `state == "first_done"`; for `u_alice` and for an approver it has the decision.
  - `test_legacy_company_level_row_is_value_item`: a queue row keyed `company_id` with `fields` is `kind == "value"`.
  - `test_no_user_id_in_items_response`: the JSON text has no `"user_id"` and no reviewer name.
  - `test_model_chosen_isic_queues_sector_code_item` (in `test_research_pipeline.py`): `theme_review_items` with `isic_from_model=True` returns a row keyed `"isic:C1"` with `kind == "sector_code"`; with a supplied code it returns no such row.
  - `test_theme_review_route_refuses_isic_keys` (in `test_review_items.py`): `POST /api/themes/runs/{id}/review` with item key `"isic:C1"` gives 400.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_review_items.py tests/test_research_pipeline.py -v`. Expect FAIL (`ModuleNotFoundError: arp.review`).

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(review): one workbench queue across values, sector codes, identities, held documents and restatements (E60)`.

---

### Task 5: Decision-ready context bundle and snapshots (E52, E58)

**Files:**
- Create: `arp/review/context.py`
- Modify: `arp/storage/run_store.py` (`snapshot_path`)
- Modify: `arp/api/routers/review.py` (context, source and snapshot routes)
- Modify: `arp/api/routers/extraction.py`: `review-decisions` and `review-history` return public, blind-filtered decisions
- Test: `tests/test_review_context.py` (new), `tests/test_cosign.py` (update the `review-decisions` assertion)

**Interfaces:**
- Consumes: `get_item`, `cosign_rule` (Task 4); `item_states`, `public_decision`, `blind_for` (Task 1); `Alternative`, `ExtractionRecord.documents` and the confidence fields (Task 3); `RunHistory.last_decided` (step 3); `SchemaRegistry.quality` (step 3); `DocumentContentStore.lookup` (`arp/storage/document_store.py`); `load_run_schema`.
- Produces, in `arp/storage/run_store.py`: `snapshot_path(run_id, snapshot_id) -> Path` = `run_dir / "snapshots" / f"{safe_id(snapshot_id, label='snapshot_id')}.json"`.
- Produces, in `arp/review/context.py`:
  - `CHECK_WORDS: dict[str, str]`, the plain words per check id:
    - `format.data_type` "The value is not of the field's type."
    - `format.allowed_values` "The value is not one of the allowed values."
    - `numeric.in_span` "The number is not in the quoted source text."
    - `numeric.caption_scale` "The table caption gives a different scale than the value uses."
    - `numeric.row_label` "The table row the number comes from does not name this field."
    - `plausibility.range` "The value is outside the field's allowed range."
    - `plausibility.sign` "The value is negative but the field cannot be."
    - `plausibility.percentage` "The percentage is not between 0 and 100."
    - `plausibility.part_of_whole` "This part is larger than its total."
    - `plausibility.sum_identity` "The total does not equal the sum of its parts."
    - `prior.comparative_jump` "The value changed more than expected from the previous period."
    - `prior.last_decided` "The value differs from the one decided in an earlier run."
    - `prior.rejected` "A reviewer rejected this same value before."
    - `consistency.entity` "The source document may cover a different company."
    - `consistency.period` "The source document does not report this period."
  - `PAGE_CHARS = 10_000`. `def page_window(text: str, page_breaks: list[int], page: int) -> tuple[int, int, int]` returns `(start, end, pages)`. With `page_breaks` (`page_breaks[i]` is the start of page i+1, so `page_breaks[0] == 0`), page N spans `[page_breaks[N-1], page_breaks[N] if N < len(page_breaks) else len(text))` and `pages = len(page_breaks)`. Without them, synthetic pages of `PAGE_CHARS` cut at the last newline before the limit. Mark `# ponytail: synthetic 10k-char pages for unpaginated text; use parser sections once they carry offsets`.
  - `def page_of(text, page_breaks, char_start) -> int`: the page holding an offset; for paginated text it reuses `grounding._page_for_offset`.
  - `def build_context(run_store, run_id: str, item_key: str, principal: Principal, *, settings: Settings, content_store: DocumentContentStore | None) -> dict | None` returns the bundle (None when there is no such item):
    - `item`: the `ReviewItem` dump.
    - `field_definition`: the field's `FieldDefinition` from the run's `schema.json` as `model_dump(mode="json")`, plus `"first_audit_passed"` from `SchemaRegistry(settings.schema_registry_dir).quality(field_id, version)`; None for kinds without a field, or with no snapshot.
    - `value`: the field row (`payload["field"]`, or for a restatement candidate the row in `results.jsonl` with the candidate's `item_key`); None otherwise.
    - `evidence`: one entry per grounded citation of `value` that has `char_start`: `{"doc_id", "doc_type", "title", "company_id", "source_filename", "page", "quote", "char_start", "char_end", "page_start", "page_text"}`. `page_text` and `page_start` come from `page_window` over `content_store.lookup(content_key, parser_version)`. Both are None when the text is unavailable (cache disabled or pruned).
    - `documents`: the results row's `documents` (Task 3), plus each cited document not already listed (old rows), each with `"pages"`; `[]` for identity and sector-code items. For a `quarantined_document` item the list is `[payload]` (the held document itself, so the reviewer can open what they release).
    - `failed_checks`: `[{"check_id", "severity", "plain": CHECK_WORDS.get(check_id, detail), "detail"}]` for each `is_failing` check of `value`.
    - `route_reasons`: `value.route_reasons` (`[]` when absent).
    - `conflict`: `{"conflicting_sources": value.conflicting_sources, "alternatives": value.alternatives}`.
    - `prior_period`: the record row with the same `field_id` and the next older `period_end`: `{"value", "period_end"}`, or None.
    - `published`: `RunHistory.load(run_store, exclude_run_id=run_id).last_decided(key)` as `{"value", "run_id", "decided_by"}`, where `key` is `payload["item_key"]` for a `restatement_candidate` (its field key; the `rst_…` id is never a RunHistory key) and the item key otherwise, or None. "Published" means decided in an earlier non-trial run; there is no published-fact store yet. Mark `# ponytail: full RunHistory scan per bundle; cache per run once review traffic shows it`.
    - `confidence`: `{"final": confidence, "extractor": extractor_confidence, "verifier": verifier_confidence, "grounded", "match_methods": [c.match_method for grounded citations], "auto_accept_min": field_definition.auto_accept_min}`, or None without `value`.
    - `state`, `escalated`: from the item.
    - `decisions`: `[public_decision(r, principal) for r in state.rows]`, or, when `blind_for(...)`, the rows before the current round's `first` row only; `blind: bool`.
    - `etag`: `sha256(json.dumps(bundle_without_etag, sort_keys=True, separators=(",", ":"), default=str)).hexdigest()[:16]`. The bundle holds no build-time timestamps, so two loads of an unchanged item give the same etag.
  - `def item_source(run_store, run_id, item_key, doc_id, page, principal, *, content_store) -> dict | None`: `{"doc_id", "doc_type", "title", "company_id", "source_filename", "page", "pages", "page_start", "page_text"}` for a document in the bundle's `documents`; None when the doc is not the item's or its text is unavailable.
  - `def visible_history(run_store, run_id, item_key, principal, *, high_risk: bool) -> list[dict]`: the same filter as `decisions`.
  - `def write_snapshot(run_store, run_id, bundle: dict) -> str`: `snapshot_id = new_id("snap")`; writes `json.dumps(bundle, sort_keys=True)` with `atomic_write_text` to `snapshot_path`; returns the id.
  - `def read_snapshot(run_store, run_id, snapshot_id) -> bytes | None`: the file's bytes.
- Routes, in `arp/api/routers/review.py`:
  - `GET /api/review/runs/{run_id}/items/{item_key}/context` → the bundle; 404 when there is no item.
  - `GET /api/review/runs/{run_id}/items/{item_key}/source?doc_id=&page=1` → `item_source`; 404 when None.
  - `GET /api/review/runs/{run_id}/snapshots/{snapshot_id}` → `Response(content=bytes, media_type="application/json")`, the stored bytes as written; 404 when missing; 400 for an unsafe id.
- In `arp/api/routers/extraction.py`:
  - `GET /runs/{run_id}/review-decisions` returns `{"decisions": {k: public_decision(effective)} for final items, "states": {k: {"state", "escalated"}} for every decided key}`. The old `cosigned` flag goes; a co-signed legacy edit is simply in `decisions`.
  - `GET /runs/{run_id}/review-history` returns `{"item_key", "history": visible_history(...)}`.
  - Both take `principal: Principal = Depends(current_user)`.
- The table-cell highlight is the honest minimum: the parser exposes no table structure (`Citation.table_ref` is always None), so the bundle gives the exact span and the page text, and `SourcePanel` (Task 8) highlights the span inside its text line, which for a table is the row.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_context.py`. Fixture: a `DocumentContentStore` on `tmp_path` with one stored text `"Emissions (in thousands of tonnes)\nScope 1  1,234  1,100\nScope 2  500  400\n"` (no page breaks); an extraction run whose queue row and results row hold a field citing `"1,234"`, grounded with that `content_key`/`parser_version` at its offsets; the dependency `get_document_content_store` overridden to return that store.
  - `test_table_value_highlights_cell`: `e = bundle["evidence"][0]`; `e["page_text"][e["char_start"] - e["page_start"] : e["char_end"] - e["page_start"]] == "1,234"`, and the line around it is `"Scope 1  1,234  1,100"`.
  - `test_failed_checks_in_plain_words`: a `numeric.in_span` `fail`/`block` gives `plain == "The number is not in the quoted source text."`; a passing check is absent.
  - `test_conflict_alternatives_with_sources`: one `extractor` alternative with its grounded citation.
  - `test_prior_and_published_values`: a FY2023 row in the record gives `prior_period == {"value": 1000, "period_end": "2023-12-31"}`; a prior non-trial run's approved value for the same key gives `published["run_id"]`.
  - `test_confidence_components`: `extractor` and `verifier` present; a legacy row gives None for both.
  - `test_field_definition_from_run_snapshot`: `field_definition["description"]` equals the run's `schema.json`, and includes `first_audit_passed`.
  - `test_text_unavailable_gives_none`: a store with the cache disabled gives `page_text is None`; the bundle still loads.
  - `test_paginated_text_page_window_and_page_of`: text with `page_breaks=[0, 20, 45]`: page 1 is `[0, 20)`, page 3 is `[45, len)`, `pages == 3`, and `page_of` gives 2 for an offset of 25.
  - `test_source_page_endpoint`: `GET .../source?doc_id=<doc>&page=1` returns the whole text as `page_text` with `pages == 1`; an unknown `doc_id` gives 404.
  - `test_blind_view_hides_first_decision`: a high-risk field; `u_alice` (analyst) has a `first` `correct` row; for `u_bob` (analyst) the bundle has `decisions == []` and `blind is True`; for `u_alice` and for `u_carol` (approver) it has one decision with `blind is False`.
  - `test_blind_history_and_decisions_hidden`: for `u_bob`, `GET /api/extraction/runs/{id}/review-history?item_key=k` returns `history == []`, and `review-decisions` has no entry for `k` (not final), with `states[k]["state"] == "first_done"`.
  - `test_no_user_id_in_review_responses`: the context, `review-decisions` and `review-history` JSON text holds no `"user_id"` and no reviewer name.
  - `test_snapshot_reopens_identical_after_field_definition_change`: `sid = write_snapshot(run_store, run_id, bundle)`; then rewrite the run's `schema.json` with a new `description` and `high_risk=True`. `GET .../snapshots/{sid}` returns bytes equal to the first read, its `field_definition.description` is the old one, and a fresh context shows the new one.
  - `test_etag_stable_and_changes_with_state`: two loads give the same `etag`; after a decision row is appended the etag differs.
  - Update `tests/test_cosign.py`'s `review-decisions` test: the key is absent before the co-sign and present after it (the `cosigned` field is gone).

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_review_context.py tests/test_cosign.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(review): decision-ready context bundle with stored-text spans; snapshots reopen byte-identical (E52, E58)`.

---

### Task 6: Constrained decisions and second-reviewer rules (E53, E54)

**Files:**
- Modify: `arp/schemas/review.py` (`ItemDecisionRequest`)
- Modify: `arp/config.py` (`second_review_sample_rate`)
- Modify: `arp/checks/numeric.py` (export `_candidates` as `candidates`; `numeric.in_span` calls it)
- Create: `arp/review/decide.py`
- Modify: `arp/api/routers/review.py` (`POST` decision route)
- Modify: `arp/api/routers/extraction.py` (remove `POST /runs/{run_id}/review` and `GET /runs/{run_id}/review-queue`), `arp/api/routers/identity.py` (remove both routes of the same names)
- Modify: `arp/cli/identity.py` (the review command decides through `decide`)
- Test: `tests/test_review_decide.py` (new), `tests/test_review_identity.py` (move the spoof test to the new route; keep the `submit_review` unknown-decision assertion)

**Interfaces:**
- Consumes: `build_context`, `write_snapshot` (Task 5); `get_item` (Task 4); `item_states`, `append_decision`, `agrees`, `ReviewDecision` (Task 1); `ground_citations` (`arp/grounding.py`); `candidates` (the `_candidates` helper of `numeric.in_span`, renamed public), `parse_number` (`arp/checks/numeric.py`); `RunHistory`, `SchemaRegistry.quality`.
- Produces, in `arp/schemas/review.py`:
  - `class ItemDecisionRequest(BaseModel)`, `model_config = ConfigDict(extra="ignore")` (an old client's `reviewer` is ignored):
    - `decision: Literal["approve", "correct", "reject", "escalate"]` (`edit` is a 422)
    - `reason_code: DecisionReason`
    - `corrected_value: dict | None = None`
    - `correction_citation: Citation | None = None`
    - `comment: str | None = None`
    - `context_etag: str = Field(min_length=1)`
    - `model_validator(mode="after")`: `approve` requires `reason_code == "confirmed"`, and every other decision forbids it. `correct` requires `corrected_value`; every other decision requires `corrected_value` and `correction_citation` to be None.
- Produces, in `arp/config.py`: `second_review_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)`.
- Produces, in `arp/review/decide.py`:
  - `class DecisionError(Exception)`: `status: int`, `message: str`.
  - `ALLOWED = {"value": {"approve", "correct", "reject", "escalate"}, "restatement_candidate": <same>, "identity": <same>, "sector_code": <same>, "quarantined_document": {"approve", "reject", "escalate"}}`.
  - `CORRECTED_KEYS = {"value": {"value", "unit", "period_end"}, "restatement_candidate": {"value", "unit", "period_end"}, "identity": {"value", "resolved_website", "resolved_cik"}, "sector_code": {"isic_code"}}`; `value` and `restatement_candidate` require `"value"`; `sector_code` requires `"isic_code"`; extra keys are a 422.
  - `def sampled(item_key: str, rate: float) -> bool`: `int(sha256(item_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < rate`. Reproducible per key.
  - `def second_review_reasons(decision: str, *, kind: str, item_key: str, high_risk: bool, first_audit_passed: bool | None, current_value, corrected_value, prior: PriorValue | None, sample_rate: float) -> list[str]`, empty for `escalate`, otherwise in this order:
    - `"correction"` when `decision == "correct"`
    - `"high_risk"` when `high_risk`
    - `"published_change"` when `kind == "restatement_candidate"`, or when `prior` is set and the decision changes it: `reject`; `approve` with `not same_value(prior.value, current_value)`; `correct` with `not same_value(prior.value, corrected_value["value"])`
    - `"first_audit_pending"` when `first_audit_passed is False` (None means no definition to check: an old run without `schema.json`, or a kind without a field)
    - `"sample"` when `decision == "approve"` and `sampled(item_key, sample_rate)`
  - `def ground_correction(citation: Citation, bundle: dict, *, content_store, data_type: str | None, corrected_value) -> Citation`, which raises `DecisionError(422, ...)`:
    - `"correction citation must cite one of this item's documents"` when `citation.doc_id` is not in `{d["doc_id"] for d in bundle["documents"]}`
    - `"source text unavailable"` when `content_store.lookup` gives None
    - otherwise builds a `SourceDocument` (`doc_id`, `company_id`, `doc_type`, `title`, `full_text`, `page_breaks`, `content_key`, `parser_version`) and runs `ground_citations([citation], {doc_id: doc})`; `"correction citation is not in the source text"` when not grounded
    - for numeric data types: `"corrected number not in the cited text"` when `parse_number(str(corrected_value["value"]))` matches no number in `numbers_in(span_text)` by absolute value (`math.isclose`), using the same candidate helper as `numeric.in_span` (`_candidates` in `arp/checks/numeric.py`, exported as `candidates` and called by both, so "1 234"-style thousands are judged as in step 3)
    - returns the grounded citation (server-set `char_start`, `char_end`, `span_text`, `page`, `match_method`).
  - `def decide(run_store, run_id: str, item_key: str, req: ItemDecisionRequest, principal: Principal, *, settings: Settings, content_store: DocumentContentStore | None) -> dict`, all inside `with run_store.lock(run_id):`
    1. `item = get_item(...)`: None → 404; `kind == "other"` → 400 `"decide this item through its run's review endpoint"`.
    2. `req.decision not in ALLOWED[kind]` → 422. `correct`: `corrected_value` keys are checked against `CORRECTED_KEYS[kind]` (422); `value`/`restatement_candidate` need a `correction_citation` (422 `"a correction needs a citation"`); `identity`/`sector_code` need a non-empty `comment` (422 `"a correction needs a comment naming its source"`).
    3. `s = item_states(...)[item_key]` (or a fresh `ItemState`). The step and person rules:
       - `first_done` → `step = "second"`; `principal.user_id == s.first["user_id"]` → 409 `"second review must be a different person"`.
       - `disagreed` → `step = "resolution"`; role below approver → 403 `"a disagreement is resolved by an approver"`; `principal.user_id` in the first or second reviewer's ids → 409 `"the resolver must not be a reviewer of this item"`; `escalate` → 422.
       - `pending` with `s.escalated` → `step = "first"`; role below approver → 403 `"an escalated item is decided by an approver"`.
       - otherwise (`pending`, `second_done`, `final`) → `step = "first"`: a new round.
    4. `bundle = build_context(..., principal, ...)`; `bundle["etag"] != req.context_etag` → 409 `"this item changed since you loaded it; reload"`.
    5. For `correct` with a citation: `citation = ground_correction(...)`.
    6. For `step == "first"`: `second_reasons = second_review_reasons(...)`, using the field definition from the bundle, `quality.first_audit_passed`, the row's value, and `RunHistory.load(run_store, exclude_run_id=run_id).last_decided(key)` for `value`/`restatement_candidate`, with `key = payload["item_key"]` for a restatement candidate (None otherwise). `second_required = bool(second_reasons)`. A `second` or `resolution` row stores `second_required=False` and `[]`.
    7. `snapshot_id = write_snapshot(run_store, run_id, bundle)`.
    8. `append_decision(run_store, run_id, ReviewDecision(item_key, decision, reason_code, reviewer=principal.name, user_id=principal.user_id, role=principal.role, corrected_value, correction_citation=citation, snapshot_id, comment, step, second_required, second_reasons))`.
    9. Returns `{"state": <new state>, "snapshot_id": snapshot_id, "second_reasons": second_reasons}`.
- Route: `POST /api/review/runs/{run_id}/items/{item_key}/decision`, body `ItemDecisionRequest`, principal from `current_user` (analyst+ through the router's `authorize`), `content_store` from `get_document_content_store`; `DecisionError` → `HTTPException(status, message)`.
- Removed routes, superseded by `/api/review`: extraction and identity `POST /runs/{run_id}/review` and `GET /runs/{run_id}/review-queue`. The legacy extraction cosign route stays, for legacy `edit` rows only (Task 2).
- `arp/cli/identity.py` review: `--decision` accepts `approve|correct|reject|escalate` and `--reason`; it calls `build_context` for the etag, then `decide` with `cli_principal(...)`. `correct` sends `corrected_value={"resolved_website": ..., "resolved_cik": ...}` and requires `--comment`. `review-queue` lists `list_open_items(run_store, principal, run_id=...)`, so escalated and `first_done` items show as pending.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_decide.py`. Principals `ALICE` (analyst, `u_alice`), `ALICE2` (analyst, `user_id="u_alice"`, `name="alice "`), `BOB` (analyst), `CAROL` (approver), `DAVE` (approver). The text fixture is from Task 5; its field is released and has a recorded first audit, and `second_review_sample_rate` is overridden to 0.0, so only the rule under test asks for a second review. A helper `ctx(client, key)` gets the bundle and its etag.
  - `test_correction_without_citation_is_422`
  - `test_edit_decision_is_422`: `decision="edit"` fails the `Literal`.
  - `test_approve_needs_confirmed_reason`: `approve` with `wrong_value` → 422; `reject` with `confirmed` → 422.
  - `test_ungrounded_correction_citation_is_422`: quote `"Scope 1  9,999"` → 422, and no decision row is written.
  - `test_correction_citation_from_foreign_doc_is_422`
  - `test_correction_number_not_in_span_is_422`: `corrected_value={"value": 1300}` citing `"Scope 1  1,234"` → 422.
  - `test_grounded_correction_stored_with_server_offsets`: the client sends `grounded=True`, `char_start=0`; the stored `correction_citation` has the real offset of `"1,234"` and `match_method == "exact"`.
  - `test_same_user_refused_as_second_reviewer`: `ALICE` corrects (state `first_done`); `ALICE2` → 409; `BOB` agreeing → state `second_done`.
  - `test_disagreement_goes_to_approver`: `ALICE` corrects, `BOB` approves → `disagreed`; `BOB` again → 403 (analyst); `CAROL` → `final` and effective.
  - `test_resolver_cannot_be_a_reviewer`: `CAROL` corrects, `BOB` disagrees, `CAROL` resolves → 409; `DAVE` → 200.
  - `test_escalate_keeps_pending_and_needs_approver`: `ALICE` escalates → `pending` (in `GET /api/review/items`, `escalated is True`); `BOB` → 403; `CAROL` approve → `final`.
  - `test_second_required_reasons`: parametrized over `second_review_reasons`: `correct` → `["correction"]`; `approve` on `high_risk` → `["high_risk"]`; `approve` of a value differing from `prior` → `["published_change"]`; `reject` with a prior → `["published_change"]`; `first_audit_passed=False` → `["first_audit_pending"]`; `approve` with rate 1.0 → `["sample"]`, and with rate 0.0 → `[]`; `escalate` → `[]`; `restatement_candidate` approve → `["published_change"]`.
  - `test_sample_is_deterministic_per_item_key`: `sampled(k, 0.5)` is equal across calls; over 1000 keys the share at rate 0.1 is between 0.05 and 0.15.
  - `test_stale_context_etag_is_409`: `BOB` loads the context; `ALICE` decides; `BOB` submits with the old etag → 409.
  - `test_decision_writes_snapshot_of_context`: the row's `snapshot_id` file equals the bundle `ALICE` loaded (etag included).
  - `test_quarantined_document_correct_is_422`
  - `test_release_held_document_needs_second_when_sampled`: with the rate at 1.0, an `approve` on a `held:` item gives `first_done` with `second_reasons == ["sample"]`; with 0.0 it gives `final`.
  - `test_identity_correct_without_citation_needs_comment`: no comment → 422; with a comment → `first_done` (`correction`).
  - `test_other_kind_refused_400`: a theme activity row.
  - `test_spoofed_reviewer_body_is_ignored` (moved from `test_review_identity.py`): the body `{"reviewer": "Mallory", ...}` stores `user_id == "u_test"`, `reviewer == "Test"`.
  - `test_cli_identity_correct_without_comment_exits_1`: `arp identity review --decision correct` without `--comment` exits 1.
  - `test_old_review_routes_removed`: `POST /api/extraction/runs/r1/review` and `GET /api/identity/runs/r1/review-queue` give 404 or 405.
  - `test_submit_review_rejects_unknown_decision` (kept from `test_unknown_decision_is_400`): `submit_review(..., "maybe")` raises `ValueError` (voting's shared `VALID_DECISIONS` path). Delete only the HTTP half of `test_unknown_decision_is_400` from `test_review_identity.py`; `test_edit_decision_is_422` replaces it.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_review_decide.py tests/test_review_identity.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** Update any existing CLI test for `arp identity review` to the new options.

- [ ] **Step 4: Run** the full backend check. Expect no new failures; no `test_voting*` file and no existing voting test function is changed.

- [ ] **Step 5: Commit** with `feat(review): accept, correct with a grounded citation, reject or escalate; second-reviewer rules (E53, E54)`.

---

### Task 7: Frontend: types, client and pure review helpers

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api/client.ts`
- Modify: `frontend/src/lib/reviewKeys.ts`, `frontend/src/lib/stagedFlow.ts`
- Create: `frontend/src/lib/sourceText.ts`
- Test: `frontend/tests/reviewKeys.test.ts`, `frontend/tests/stagedFlow.test.ts` (extend), `frontend/tests/sourceText.test.ts` (new)

**Interfaces:**
- Produces, in `types.ts`:
  - `type ReviewItemKind = "value" | "sector_code" | "identity" | "quarantined_document" | "restatement_candidate" | "other"`
  - `type ItemState = "pending" | "first_done" | "second_done" | "disagreed" | "final"`
  - `ReviewDecision.decision` becomes `"approve" | "edit" | "correct" | "reject" | "escalate"`; new optional fields `reason_code`, `corrected_value?: { value?: unknown } | null`, `correction_citation?: Citation | null`, `snapshot_id`, `step`, `mine?: boolean`. `reviewer`, `user_id` and `cosigned` stay optional (the legacy kinds still send `reviewer`).
  - `interface ReviewItem { item_key: string; kind: ReviewItemKind; run_id: string; run_type: ReviewableRunKind; payload: Record<string, unknown>; state: ItemState; escalated: boolean; high_risk: boolean; decision: ReviewDecision | null }`
  - `interface EvidenceSpan { doc_id; doc_type; title: string | null; company_id: string | null; source_filename: string | null; page: number | null; quote: string; char_start: number; char_end: number; page_start: number | null; page_text: string | null }`
  - `interface ItemSource { doc_id; doc_type; title; company_id; source_filename; page: number; pages: number; page_start: number; page_text: string }`
  - `interface ItemContext { item: ReviewItem; field_definition: Record<string, unknown> | null; value: ExtractedField | null; evidence: EvidenceSpan[]; documents: { doc_id: string; doc_type: string; title: string; pages?: number }[]; failed_checks: { check_id: string; severity: string; plain: string; detail: string }[]; route_reasons: string[]; conflict: { conflicting_sources: boolean; alternatives: { value: unknown; raw_value_text: string | null; source: string; citations: Citation[] }[] } | null; prior_period: { value: unknown; period_end: string } | null; published: { value: unknown; run_id: string; decided_by: string } | null; confidence: { final: number; extractor: number | null; verifier: number | null; grounded: boolean; match_methods: string[]; auto_accept_min: number | null } | null; state: ItemState; escalated: boolean; decisions: ReviewDecision[]; blind: boolean; etag: string }`
  - `interface ItemDecisionBody { decision: "approve" | "correct" | "reject" | "escalate"; reason_code: string; corrected_value: Record<string, unknown> | null; correction_citation: { doc_id: string; doc_type: string; quote: string } | null; comment: string | null; context_etag: string }`
  - `ExtractedField` gains `extractor_confidence?`, `verifier_confidence?`, `alternatives?`.
- Produces, in `api/client.ts`: `listReviewItems(runId?: string)` → `{ items: ReviewItem[] }`; `getItemContext(runId, itemKey)` → `ItemContext`; `getItemSource(runId, itemKey, docId, page)` → `ItemSource`; `decideItem(runId, itemKey, body: ItemDecisionBody)` → `{ state: ItemState; snapshot_id: string; second_reasons: string[] }`; `getSnapshot(runId, snapshotId)`. Item keys go through `encodeURIComponent`.
- Produces, in `lib/reviewKeys.ts`:
  - `ITEM_KIND_LABEL: Record<ReviewItemKind, string>`: `value` "Value", `sector_code` "Sector code", `identity` "Identity", `quarantined_document` "Held document", `restatement_candidate` "Restatement", `other` "Other"
  - `DECISION_REASONS`: the nine `DecisionReason` strings in order
  - `decisionChoices(kind: ReviewItemKind): ItemDecisionBody["decision"][]`: `quarantined_document` → `["approve", "reject", "escalate"]`; `other` → `[]`; every other kind → all four
  - `needsCitation(kind)`: true for `value` and `restatement_candidate`
  - `decideBlock(item: Pick<ReviewItem, "state" | "escalated" | "decision">, me: Me | null): string | null`, the reason the signed-in person cannot decide, or null:
    - no `me` or a `viewer` → `"Sign in as an analyst or approver to decide."`
    - `first_done` with `decision?.mine` → `"Waiting for a second reviewer."`
    - `disagreed` and not an approver → `"Reviewers disagree; an approver decides."`
    - `escalated` and not an approver → `"Escalated; an approver decides."`
- Produces, in `lib/stagedFlow.ts`: `editedText`, `valueOrigin`, `reviewCounts` and `TILE_DECISION`/`matchesTile` treat `correct` like `edit` (`editedText` reads `corrected_value?.value ?? edited_value?.value`).
- Produces, in `lib/sourceText.ts`: `highlightParts(text: string, start: number, end: number): { before: string; lineBefore: string; mark: string; lineAfter: string; after: string } | null`. The line is the text between the newline before `start` and the newline after `end`. It returns null when `0 <= start < end <= text.length` does not hold.
- `canCosign` stays in this task (Task 9 removes it with its last user).

- [ ] **Step 1: Write the failing tests:**
  - `sourceText.test.ts`: on `"Emissions (in thousands)\nScope 1  1,234  1,100\nScope 2  500  400\n"`, with the offsets of `"1,234"`, the result is `before == "Emissions (in thousands)\n"`, `lineBefore == "Scope 1  "`, `mark == "1,234"`, `lineAfter == "  1,100"`, `after == "\nScope 2  500  400\n"`; a span on the first line gives `before == ""`; `(5, 5)` and `(0, 999)` give null.
  - `reviewKeys.test.ts`: `decisionChoices("quarantined_document")` has no `"correct"`; `decisionChoices("other")` is empty; `needsCitation("identity") === false`. `decideBlock`: `first_done` with `mine: true` → `"Waiting for a second reviewer."`; with `mine: false` → null; `disagreed` for an analyst → the message, for an approver → null; `escalated` for an analyst → the message; null `me` → the sign-in message.
  - `stagedFlow.test.ts`: `editedText({ decision: "correct", corrected_value: { value: 5 } })` is `"5"`; `reviewCounts` counts a `correct` decision as `edited`.

- [ ] **Step 2: Run** `cd frontend && npm test`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** `cd frontend && npm run lint && npm test && npm run build`. Expect 0 errors, 13 warnings.

- [ ] **Step 5: Commit** with `feat(frontend): review item types, workbench client and decision helpers`.

---

### Task 8: Frontend: decision view, highlighted source, constrained controls

**Files:**
- Modify: `frontend/src/components/SourcePanel.tsx` (text mode)
- Modify: `frontend/src/components/ReviewTiles.tsx` (`CheckResults`)
- Modify: `frontend/src/components/ReviewControls.tsx` (decision mode)
- Modify: the stylesheet that holds `.source-panel` (`.source-text`, `.source-line-hit`, `mark`)

**Interfaces:**
- Consumes: `highlightParts`, `decisionChoices`, `needsCitation`, `decideBlock`, `DECISION_REASONS`, the client calls (Task 7).
- Produces:
  - `ActiveSource` gains optional `text?: { run_id: string; item_key: string; doc_id: string; doc_type: string; page: number | null; pages?: number; page_start: number; page_text: string; char_start?: number; char_end?: number }` and `onSelectQuote?: (c: { doc_id: string; doc_type: string; quote: string }) => void`.
  - `SourcePanel`, when `source.text` is set, renders `<pre className="source-text">` with `highlightParts(page_text, char_start - page_start, char_end - page_start)`: the line in `<span className="source-line-hit">`, the span in `<mark>`. Without a span it shows the plain page text. On `mouseup` inside the `<pre>`, a non-empty `window.getSelection()` string calls `onSelectQuote({ doc_id, doc_type, quote })`, with the hint `"Select text to use it as the correction's source."`. An "Open original" link uses `source.src`. Page buttons call `api.getItemSource` when `pages > 1`. Without `text`, the existing JSX path is unchanged (BallotReview).
  - `ReviewTiles.tsx` adds `export function CheckResults({ checks }: { checks: ItemContext["failed_checks"] })`: a list of `plain`, each with a `badge-high` (block) or `badge-mid` (warn) badge, and `detail` as a `title`. It renders nothing when empty.
  - `ReviewControls` gains optional props `item?: Pick<ReviewItem, "kind" | "state" | "escalated" | "decision">` and `onOpenSource?: (s: ActiveSource) => void`. With `item` (decision mode):
    - The status line shows the state: `first_done` "Awaiting a second review", `disagreed` "Reviewers disagree — approver decides", escalated "Escalated", final states show the decision with `by {role}` (and "(you)" when `mine`).
    - A "Review" button loads `api.getItemContext(runId, itemKey)` and shows the decision view: the field definition (name, description, unit; `details` for instructions), the value and its confidence components, `CheckResults`, `route_reasons`, conflict alternatives (each with `CitationList`), prior-period and published values, and the evidence spans. Each span's "Show in source" calls `onOpenSource({ title, src: api.documentRawUrl(...), quote, text: {run_id, item_key, ...span}, onSelectQuote })`, passing `text` only when the span's `page_text` is not null (otherwise today's PDF path). A document picker for `documents` calls `getItemSource(..., page 1)` and opens it the same way. A blind bundle shows "Earlier decision hidden (blind second review)".
    - Controls: one button per `decisionChoices(kind)` (`Accept`, `Correct…`, `Reject`, `Escalate`) and a reason `<select>` (fixed to `confirmed` for Accept, otherwise the other reasons). `Correct…` opens the corrected-value input (`isic_code` for `sector_code`; website/CIK for `identity`). For `needsCitation(kind)` it shows `"Source: \"{quote}\""` from `onSelectQuote`, and Submit stays disabled until a quote is chosen. Identity and sector code need a comment instead.
    - `decideBlock(item, me)`, when non-null, disables the controls and is shown.
    - Submit calls `api.decideItem(runId, itemKey, { ..., context_etag: ctx.etag })`. A 409 shows the message with a "Reload" button that refetches the context. On success it announces `"{Accepted|Corrected|Rejected|Escalated}; {state}."` and calls `onDone({ item_key, decision, reason_code, corrected_value, edited_value: corrected_value, role: me.role, mine: true, decided_at, step })`.
    - History in decision mode lists `ctx.decisions` (role and date, never a name).
  - Without `item`, `ReviewControls` behaves as today, minus the co-sign block (Task 9 removes it), for TransitionPlanResults, financials and the legacy kinds.
  - `decisionLabel` handles `correct` (`corrected → {value}`) and `escalate` (`escalated`); `decisionBadgeClass("correct")` is `badge badge-mid`.

- [ ] **Step 1: No new pure logic beyond Task 7.** The behaviour rests on `highlightParts`, `decisionChoices`, `needsCitation` and `decideBlock`, which Task 7 tests. Check by hand that `BallotReview` still type-checks against the unchanged `SourcePanel` props.

- [ ] **Step 2: Implement as in Interfaces.**

- [ ] **Step 3: Run** `cd frontend && npm run lint && npm test && npm run build`. Expect 0 errors, 13 warnings.

- [ ] **Step 4: Commit** with `feat(frontend): decision-ready view with highlighted source span and constrained decisions (E52, E53)`.

---

### Task 9: Frontend: one fetch for the workbench

**Files:**
- Modify: `frontend/src/components/RunReviewList.tsx` (delete `QUEUE_FNS` and `FILTER_DECISION`; filter with `matchesTile(filter, true, d)`; one fetch; `QueueItem.review`; `SUBMIT_FNS` becomes `Partial<Record<ReviewableRunKind, …>>`)
- Modify: `frontend/src/pages/ReviewQueue.tsx` (one `listReviewItems()` call; runs from the items)
- Modify: `frontend/src/components/IdentityStage.tsx` (drop the `kind` prop)
- Modify: `frontend/src/components/ReviewControls.tsx` (drop the `cosignFn` prop, the co-sign block, the `canCosign` import and the `submitFn` default; every legacy caller passes `submitFn`)
- Modify: `frontend/src/components/ExtractionResults.tsx`, `frontend/src/pages/extraction/JobReview.tsx` (decision mode for field rows; `states` from `review-decisions`)
- Modify: `frontend/src/components/ReviewTiles.tsx` (`OriginTag`: `decision.reviewer ?? decision.role ?? "unknown"`)
- Modify: `frontend/src/api/client.ts` (remove `getExtractionReviewQueue`, `submitExtractionReview`, `getIdentityReviewQueue`, `submitIdentityReview`, `cosignExtraction`)
- Modify: `frontend/src/lib/reviewKeys.ts`, `frontend/tests/reviewKeys.test.ts` (remove `canCosign` and its tests)

**Interfaces:**
- Consumes: `listReviewItems`, `ReviewItem`, `ITEM_KIND_LABEL` (Task 7); `ReviewControls` decision mode (Task 8).
- Produces:
  - `interface QueueItem { kind: ReviewableRunKind; runId: string; item: Record<string, unknown>; review: ReviewItem }`, where `item = review.payload` and `kind = review.run_type`. `fromReviewItem(r: ReviewItem): QueueItem`.
  - `RunReviewList({ runId, reviewer, onOpenSource, filter, onCounts })`: one `api.listReviewItems(runId)` call.
  - `ReviewItems`: for `review.kind !== "other"`, `<ReviewControls item={review} onOpenSource={onOpenSource} .../>`, with `ITEM_KIND_LABEL[review.kind]` beside the run label, and decided cards showing `by {d.role}`. For `other`, today's legacy controls with `SUBMIT_FNS[q.kind]` and `HISTORY_FNS[q.kind]` (only `theme`, `financials`, `transition_plan` and `tnfd` remain in `SUBMIT_FNS`). `QUEUE_FNS` is deleted.
  - `ReviewQueue`: `api.listReviewItems()` once; the run filter options are the distinct `(run_type, run_id)` of the items; it no longer calls `api.listRuns` for this page. Sorting stays lowest confidence first (`payload.confidence ?? payload.field.confidence`).
  - `ExtractionResults` field rows: `ReviewControls` gets `item={{ kind: "value", state: states[itemKey]?.state ?? "pending", escalated: states[itemKey]?.escalated ?? false, decision: reviewDecisions[itemKey] ?? null }}` and `onOpenSource`; `cosignFn` is removed. Financials rows are unchanged. `JobReview` stores `states` from the same `review-decisions` response and passes it down. A first-done item shows "Awaiting a second review" and no edited value (only final decisions change the shown value).

- [ ] **Step 1: Update the tests:** remove the four `canCosign` tests from `reviewKeys.test.ts` (no voting test touched).

- [ ] **Step 2: Implement as in Interfaces.** Check with `grep -rn "QUEUE_FNS\|cosignExtraction\|submitExtractionReview\|submitIdentityReview\|getExtractionReviewQueue\|getIdentityReviewQueue\|canCosign" frontend/src`, which must return nothing.

- [ ] **Step 3: Run** `cd frontend && npm run lint && npm test && npm run build`. Expect 0 errors, 13 warnings.

- [ ] **Step 4: Commit** with `feat(frontend): one workbench fetch for every review kind; extraction rows decide through the review rules (E60)`.

---

### Task 10: Documentation

**Files:**
- Modify: `docs/TECHNICAL_REFERENCE.md`: §2 module map (`review/`, `api/routers/review.py`), §3.3 (the decision bundle, constrained decisions, second-reviewer rules, the snapshot), §3.5 (identity review through the workbench), §3.18 (one workbench with five kinds plus legacy kinds, states, blind view, roles, the removed routes), §7 data layout (`runs/<id>/snapshots/<snapshot_id>.json`, the new decision row keys), §8 CLI (`arp identity review` options)

**Interfaces:** none.

- [ ] **Step 1: Write** the sections from this plan's Architecture, Global Constraints and Interfaces. Each section covers:
  - the decision strings, the reason codes, the five states and the five second-review reasons with their rule
  - that the sample is reproducible per item key (`second_review_sample_rate`)
  - that a legacy `edit` maps to `correct` and still needs its co-sign, and that a legacy `escalate` now reads as pending
  - that clients see role and date only
  - that the table-cell highlight is the span inside its text line (no parsed table structure)
  - that a correction is refused unless its citation grounds in the item's stored source text
  - that a sector-code decision has no consumer yet, and that publishing a restatement is step 5

- [ ] **Step 2: Run** the backend and frontend checks once more. Expect no new failures.

- [ ] **Step 3: Commit** with `docs: review workbench, decisions, second-reviewer rules and snapshots (step 4)`.
