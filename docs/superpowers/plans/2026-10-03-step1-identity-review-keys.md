# Step 1: Sign-in, Named Review, Per-Field Review Keys, LEI Key, Provider Seam — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every API call is signed in, every review decision is recorded against the signed-in user with a second signer where required, extraction review items are per field and keyed by issuer LEI, and the model client sits behind a provider switch.

**Architecture:** One FastAPI dependency (`authorize`) resolves a `Principal` from a bearer token held in a local users file and checks a minimum role per HTTP method; it is attached to every router in `api/main.py`. Review persistence (`orchestration/review_queue.py`) takes a `Principal` instead of a free-text name, and second sign-offs live in their own append-only file so `latest_decisions()` keeps its meaning. Extraction queues one review row per flagged field with reason codes computed in the aggregator.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest (+ pytest-asyncio), React + TypeScript (Vite), node test runner.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4` — sections A (E1, E2, E11), B1 (E9), "Issuer key: LEI, switchable", migration step 1. Paths below are relative to `backend/` unless they start with `frontend/`.

## Global Constraints

- No new dependencies (backend or frontend). Stdlib, FastAPI, Pydantic and what `pyproject.toml` / `package.json` already list.
- Roles, lowest to highest: `viewer`, `analyst`, `approver`.
- Issuer key: `issuer_key` + `issuer_scheme`; scheme `LEI` when a valid LEI is known, else `ARP_PROVISIONAL` with key `ARP:<uuid>`.
- Code compares `issuer_key`, never parses it.
- Extraction review `item_key` = `"{issuer_key}:{field_id}:{period}"`; `period` is the literal `unspecified` until E30 adds periods.
- Reason codes (exact strings): `not_grounded`, `verifier_disagrees`, `conflict`, `low_confidence`, `check_failed`, `match_ambiguous`, `not_applicable_by_rule`.
- Decision values accepted by the shared review endpoint: `approve`, `edit`, `reject`, `escalate` (E53 renames `edit` to `correct` later; not in this step).
- `llm_provider` accepts only `anthropic`; the Anthropic client (`llm/langchain_client.py`) is not changed.
- `GET /api/health` stays unauthenticated.
- The dev bypass is honoured only for requests whose client address is loopback (`127.0.0.1`, `::1`).
- Old run directories (queue rows keyed by `company_id`, decision rows with only `reviewer`) must still load.
- Backend checks: `cd backend && ruff check arp tests && pytest -q`. Frontend checks: `cd frontend && npm run lint && npm test && npm run build`.

## Review Focus

1. **Missing or malformed `Authorization` header** (no `Bearer ` prefix, empty token, unknown token) → 401, never a 500. Test in Task 1.
2. **Users file absent or invalid JSON** in `auth_mode=local` → the app refuses to start with a message naming the path, not a 401 on every call. Test in Task 1.
3. **Same person signing twice under different spelling** (`Alice` vs `alice `) → co-sign is compared on `user_id`, so it is refused. Test in Task 3.
4. **Company with an LEI in lower case or with spaces** → normalised (upper-case, stripped) before the checksum; a checksum failure falls back to a provisional key and is not silently accepted. Test in Task 5.
5. **Old run with company-level queue rows** opened in the new review UI → still listed and decidable by its stored `item_key`. Test in Task 6.

---

### Task 1: Sign-in dependency, roles, CORS from settings

**Files:**
- Create: `arp/api/auth.py`
- Modify: `arp/config.py` (new settings), `arp/api/main.py` (attach dependency to all 28 routers, CORS, `/api/me`, startup check)
- Modify: `tests/conftest.py` (autouse override so existing API tests keep passing)
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces:
  - `class Principal(BaseModel): user_id: str; name: str; role: Literal["viewer", "analyst", "approver"]`
  - `ROLE_RANK: dict[str, int] = {"viewer": 0, "analyst": 1, "approver": 2}`
  - `def load_users(path: Path) -> dict[str, Principal]` — token → principal; raises `RuntimeError` naming the path when missing or invalid.
  - `async def current_user(request: Request) -> Principal` — FastAPI dependency.
  - `def require_role(min_role: str) -> Callable` — dependency factory returning the `Principal`, 403 when the role ranks lower.
  - `async def authorize(request: Request) -> Principal` — router-level dependency: `viewer` for `GET`/`HEAD`/`OPTIONS`, `analyst` for every other method.
  - Settings: `auth_mode: Literal["local", "dev"] = "local"`, `users_file: Path = REPO_ROOT / "config" / "users.json"`, `dev_user: str = "dev"`, `allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]`.
  - Users file format: `{"users": [{"token": "...", "user_id": "u_alice", "name": "Alice", "role": "approver"}]}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_auth.py` using a `TestClient` over a minimal FastAPI app that mounts one GET and one POST route with `dependencies=[Depends(authorize)]` and a tmp users file:
  - `test_missing_header_is_401`, `test_malformed_header_is_401` (`"Token abc"`, `"Bearer "`), `test_unknown_token_is_401`
  - `test_viewer_can_get_but_not_post` (GET 200, POST 403)
  - `test_analyst_can_post`
  - `test_require_role_approver_rejects_analyst` (403)
  - `test_dev_bypass_only_from_loopback`: `auth_mode="dev"`, client host `127.0.0.1` → 200 as `Principal(user_id="dev", name="dev", role="approver")`; client host `10.0.0.5` → 401
  - `test_missing_users_file_raises` and `test_invalid_users_json_raises`: `load_users(path)` raises `RuntimeError` whose message contains `str(path)`
  - `test_health_open_and_me_returns_principal` against the real `arp.api.main.app` with the conftest override removed for this test: `/api/health` → 200 without header; `/api/me` with a valid token → `{"user_id": ..., "name": ..., "role": ...}`

- [ ] **Step 2: Run** `cd backend && pytest tests/test_auth.py -v` — expect FAIL (`ModuleNotFoundError: arp.api.auth`).

- [ ] **Step 3: Implement `arp/api/auth.py`** as in Interfaces. `load_users` is cached per path (`functools.lru_cache`). The client address comes from `request.client.host`. In `arp/api/main.py`, replace every `app.include_router(x.router)` with `app.include_router(x.router, dependencies=[Depends(authorize)])`. Read CORS origins from `settings_dep().allowed_origins`. Add `GET /api/me` returning the `Principal`. In `lifespan`, call `load_users(settings.users_file)` when `auth_mode == "local"` so a bad file stops startup. Add `config/users.example.json` with one user per role and add `config/users.json` to `.gitignore`.

- [ ] **Step 4: Add the autouse fixture to `tests/conftest.py`.** It sets `app.dependency_overrides[authorize] = lambda: Principal(user_id="u_test", name="Test", role="approver")` and `[current_user]` likewise, then clears both after the test. Import the app lazily inside the fixture so tests that never touch the API stay import-light.

- [ ] **Step 5: Run** `cd backend && pytest -q` — expect all pass, including the pre-existing API tests.

- [ ] **Step 6: Commit** — `git add arp/api/auth.py arp/api/main.py arp/config.py tests/test_auth.py tests/conftest.py ../config/users.example.json ../.gitignore && git commit -m "feat(api): sign-in dependency with roles on every router (E1)"`

---

### Task 2: Review decisions recorded against the signed-in user

**Files:**
- Modify: `arp/orchestration/review_queue.py`, `arp/api/review_endpoints.py`
- Modify (callers): `arp/api/routers/{themes,extraction,financials,tnfd,transition_plan,transition_barrier,identity,voting,replication}.py`, `arp/cli/voting.py`, `arp/cli/identity.py`, `arp/cli/_shared.py`
- Modify (other name fields, filled from the principal): `arp/api/routers/{decision,engagement,index,portfolio,replication,stewardship,voting}.py` — every request-model field named `reviewer`, `approved_by`, `decided_by`, `updated_by`, `activated_by`, `created_by`, `author` or `by` (23 today; `grep -nE "^\s+(reviewer|approved_by|decided_by|updated_by|activated_by|created_by|author|by)\s*:" arp/api/routers/*.py`)
- Test: `tests/test_review_queue.py` (extend), `tests/test_review_identity.py` (new)

**Interfaces:**
- Consumes: `Principal`, `current_user` (Task 1).
- Produces:
  - `record_review_decision(run_store, run_id, item_key, decision, principal: Principal, edited_value, comment=None) -> None`. The row gains `user_id` and `role`; `reviewer` is kept and set to `principal.name`, so existing readers such as `storage/postgres_company_facts_projection.py` keep working.
  - `submit_review(run_store, run_id, *, item_key, decision, principal: Principal, edited_value, comment=None) -> dict`. It raises `ValueError` when `decision` is not in `{"approve", "edit", "reject", "escalate"}`; the app maps that to 400.
  - `ReviewDecisionRequest` drops `reviewer`. It sets `model_config = ConfigDict(extra="ignore")`, so old clients that still send `reviewer` are not rejected, and the value is ignored.
  - CLI: `def cli_principal(settings: Settings) -> Principal` in `cli/_shared.py`. It resolves env `ARP_CLI_TOKEN` through `load_users`. With no token it exits with an error. The `--by` options are removed.

- [ ] **Step 1: Write failing tests:**
  - `test_decision_row_records_user_id_and_role`
  - `test_spoofed_reviewer_body_is_ignored`: POST to `/api/extraction/runs/{id}/review` with `{"reviewer": "Mallory", ...}` under principal `u_test` stores `user_id == "u_test"` and `reviewer == "Test"`
  - `test_unknown_decision_is_400`
  - `test_old_decision_rows_without_user_id_still_load` (`latest_decisions` on a hand-written row with only `reviewer`)
  - `test_cli_principal_requires_token`
  - One test per other name field family: `test_stewardship_approved_by_comes_from_principal` (a body value is ignored, the stored value is the principal's name)

- [ ] **Step 2: Run** `pytest tests/test_review_identity.py tests/test_review_queue.py -v`. Expect FAIL.

- [ ] **Step 3: Implement.** Change both functions to the new signatures and add `principal: Principal = Depends(current_user)` to every review route. Remove the name fields listed above from the request models and set them from `principal.name` (or `principal.user_id` where the stored value is an id) inside the route. Keep the voting `co_signed_by` field for now; Task 3 replaces it.

- [ ] **Step 4: Run** `pytest -q && ruff check arp tests`. Expect all pass.

- [ ] **Step 5: Commit** with `feat(review): decisions recorded against the signed-in user (E2)`.

---

### Task 3: Second sign-off for extraction corrections and ballots

**Files:**
- Modify: `arp/storage/run_store.py` (`review_cosigns_path`), `arp/orchestration/review_queue.py`
- Modify: `arp/api/routers/extraction.py`, `arp/api/routers/voting.py`, `arp/voting/pipeline.py` (`cast_approved_votes`), `arp/storage/postgres_company_facts_projection.py`, plus any extraction results or export path that applies `edited_value` (`grep -rn "edited_value" arp`)
- Test: `tests/test_cosign.py`

**Interfaces:**
- Consumes: `Principal`, `require_role` (Task 1); `record_review_decision` (Task 2).
- Produces:
  - `RunStore.review_cosigns_path(run_id) -> Path`. The file is `runs/<id>/review_cosigns.jsonl`.
  - `record_cosign(run_store, run_id, item_key, principal) -> None`. It raises `ValueError("co-sign must be a different person")` when `principal.user_id` equals the `user_id` on the latest decision for `item_key`, and `ValueError("nothing to co-sign")` when there is no decision. Row: `{item_key, user_id, name, role, decision_decided_at, cosigned_at}`. The co-sign binds to the decision it signed, so a later decision invalidates it.
  - `effective_decisions(run_store, run_id, *, cosign_required: set[str]) -> dict[str, dict]`. This is `latest_decisions` minus any decision whose `decision` is in `cosign_required` and that has no matching co-sign.
  - Routes, both behind `require_role("approver")`: `POST /api/extraction/runs/{run_id}/cosign` and `POST /api/voting/runs/{run_id}/cosign`, each with body `{item_key}`.
  - Extraction treats `edit` as final only once co-signed: `cosign_required={"edit"}`. Voting: a ballot item with `engagement_alignment_flag` is cast only once co-signed. This replaces `co_signed_by`, which is removed from `VoteReviewDecisionRequest`.

- [ ] **Step 1: Write failing tests:**
  - `test_cosign_by_same_user_refused`
  - `test_cosign_compares_user_id_not_name`: same `user_id`, different `name` casing, is refused
  - `test_uncosigned_edit_not_effective`
  - `test_cosigned_edit_effective`
  - `test_new_decision_after_cosign_needs_new_cosign`
  - `test_cosign_route_requires_approver` (an analyst gets 403)
  - `test_flagged_ballot_not_cast_without_cosign`

- [ ] **Step 2: Run** `pytest tests/test_cosign.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** Switch every reader that applies `edited_value` for extraction to `effective_decisions(..., cosign_required={"edit"})`.

- [ ] **Step 4: Run** `pytest -q`. Expect all pass.

- [ ] **Step 5: Commit** with `feat(review): enforced second sign-off for corrections and flagged ballots (E2)`.

---

### Task 4: Four-eyes on index calibrations

**Files:**
- Modify: `arp/api/routers/index.py` (the create and update routes at lines ~63–102 currently accept `approved_by: list[str]`), plus the calibration store it calls (follow the calls from those routes)
- Test: `tests/test_index_calibration_approval.py`

**Interfaces:**
- Consumes: `Principal`, `require_role` (Task 1).
- Produces:
  - Create and update record `created_by = principal.user_id` and drop `approved_by` from the request.
  - New `POST /api/index/calibrations/{calibration_id}/approve` behind `require_role("approver")`. It appends `principal.user_id` to `approved_by` and returns 400 when the approver is `created_by`.
  - The existing "not yet approved" check (near line 218) treats a calibration as approved only when `approved_by` holds at least one user other than `created_by`.

- [ ] **Step 1: Write failing tests:**
  - `test_creator_cannot_approve_own_calibration`
  - `test_other_approver_approves`
  - `test_unapproved_calibration_blocks_review_run`
  - `test_approved_by_in_body_ignored`

- [ ] **Step 2: Run the tests.** Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** `pytest -q`. Expect all pass.

- [ ] **Step 5: Commit** with `feat(index): calibration needs approval by a second person (E2)`.

---

### Task 5: LEI issuer key

**Files:**
- Create: `arp/schemas/issuer.py`
- Modify: `arp/schemas/common.py` (`CompanyRef.lei: str | None = None`), `arp/schemas/datapoints.py` (`ExtractionRecord.issuer_key: str = ""`, `issuer_scheme: str = ""`), `arp/extraction/pipeline.py` (fill both on the record)
- Test: `tests/test_issuer_key.py`

**Interfaces:**
- Produces:
  - `def normalise_lei(raw: str) -> str` — strips spaces and upper-cases.
  - `def lei_is_valid(lei: str) -> bool` — 20 characters `[A-Z0-9]`, ISO 17442 check digits. Map letters to numbers (A=10 … Z=35), read the result as an integer, and require it mod 97 == 1.
  - `def issuer_key(company: CompanyRef) -> tuple[str, str]`:
    - A valid LEI returns `(lei, "LEI")`.
    - Otherwise it returns `(f"ARP:{uuid.uuid5(ARP_NAMESPACE, company.company_id)}", "ARP_PROVISIONAL")`.
    - The provisional key is derived from the company id, so it is stable across runs without a store.
    - `ARP_NAMESPACE` is a fixed `uuid.UUID` constant in this module.

- [ ] **Step 1: Write failing tests:**
  - `test_valid_lei_accepted`: `5493001KJTIIGC8Y1R12` (checked: mod 97 == 1).
  - `test_lowercase_and_spaces_normalised`
  - `test_bad_check_digits_falls_back_to_provisional`
  - `test_provisional_key_is_stable`: the same `company_id` gives the same key twice
  - `test_extraction_record_carries_issuer_key`: run `_extract_company` with `FakeLLMClient`

- [ ] **Step 2: Run** `pytest tests/test_issuer_key.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** `pytest -q`. Expect all pass.

- [ ] **Step 5: Commit** with `feat(schemas): LEI issuer key with provisional fallback`.

---

### Task 6: Per-field review items with reason codes (E9)

**Files:**
- Create: `arp/schemas/review.py`
- Modify: `arp/schemas/datapoints.py` (`ExtractedField.review_reasons: list[ReasonCode] = []`), `arp/extraction/aggregator.py`, `arp/extraction/pipeline.py` (the `review_items` lambda in `execute_extraction_run`, today one row keyed by `company_id`), `arp/orchestration/review_queue.py` (docstring: per-field key)
- Test: `tests/test_aggregator.py` (extend), `tests/test_extraction_pipeline.py` (extend)

**Interfaces:**
- Consumes: `issuer_key()` (Task 5).
- Produces:
  - `class ReasonCode(StrEnum)` with the seven values from Global Constraints.
  - `build_extracted_field` keeps returning `(field, needs_review)`. `field.review_reasons` lists every reason that applied, using the four existing conditions in order: `not_grounded`, `verifier_disagrees`, `conflict`, `low_confidence`. `needs_review == bool(field.review_reasons)`.
  - `def field_item_key(issuer_key: str, field_id: str, period: str = "unspecified") -> str`.
  - Queue row for each flagged field:
    ```
    {item_key, issuer_key, issuer_scheme, company_id, name, schema_id, run_id,
     field_id, field: ExtractedField dump, reason_codes}
    ```
    Fields that need no review are not queued.

- [ ] **Step 1: Write failing tests:**
  - `test_reasons_for_ungrounded_value`
  - `test_reasons_for_verifier_disagreement_and_conflict`: both codes present, in order
  - `test_no_reasons_means_no_review`
  - `test_pipeline_queues_one_row_per_flagged_field`: a 3-field schema with 2 flagged gives 2 rows, with keys `"{issuer_key}:{field_id}:unspecified"`
  - `test_old_company_level_queue_rows_still_listed`: `get_review_queue` over a hand-written run with a row keyed `company_id` returns it in `pending`

- [ ] **Step 2: Run** `pytest tests/test_aggregator.py tests/test_extraction_pipeline.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** `pytest -q`. Expect all pass. Review counts in the manifest now count fields rather than companies, so update any test that asserted the old count.

- [ ] **Step 5: Commit** with `feat(extraction): per-field review items with reason codes (E9)`.

---

### Task 7: Frontend: signed-in user, per-field keys, co-sign

**Files:**
- Modify: `frontend/src/api/client.ts`:
  - `request()` (line ~129) sends `Authorization: Bearer <token>`.
  - Add `getMe()`.
  - Add `cosignExtraction(runId, itemKey)` and `cosignVoting(runId, itemKey)`.
- Modify: `frontend/src/lib/reviewer.ts`. It stores the access token, not a name: `useToken()`, plus `useMe()` loading `/api/me`.
- Modify: `frontend/src/components/ReviewerField.tsx`. It becomes "Signed in as {name} ({role})", with a token input shown only when there is no valid token.
- Modify: drop the `reviewer` field from submit payloads in these 17 users (from `grep -rln "useReviewer\|ReviewerField" frontend/src`):
  - `ConfirmDecision`, `BallotReview`, `LevelOverrides`, `App`
  - `ProcessHub`, `JobRun`, `Extraction`, `MonitoringAlerts`, `GovernanceAudit`
  - `steward/common`, `StewardWorkflow`, `DataLibrary`, `IdentityResolution`, `DecisionStudio`, `ReviewQueue`
- Modify: `frontend/src/components/ExtractionResults.tsx`. Decide with the queue row's `item_key` instead of building `${company_id}:${field_id}`. Show `reason_codes`. Show a "Co-sign" button on an `edit` decision, visible to approvers who are not the decision's `user_id`.
- Modify: `frontend/src/types.ts`. `ReviewDecision` gains `user_id` and `role`; add `ReviewQueueRow.reason_codes: string[]`.
- Test: `frontend/tests/reviewKeys.test.ts` (new), for the pure helpers. Put helpers that need a test in `frontend/src/lib/reviewKeys.ts`:
  - `canCosign(decision, me): boolean`
  - `itemKeyOf(row): string`. It returns `row.item_key`, so old company-level rows still work.

- [ ] **Step 1: Write failing tests:**
  - `canCosign` is false for the same `user_id`, false for a non-approver, and true for a different approver.
  - `itemKeyOf` returns the stored key for both an old-style row and a new-style row.

- [ ] **Step 2: Run** `cd frontend && npm test`. Expect FAIL.

- [ ] **Step 3: Implement as in Files.** A 401 from any call clears the stored token and shows the token input.

- [ ] **Step 4: Run** `cd frontend && npm run lint && npm test && npm run build`. Expect all pass.

- [ ] **Step 5: Commit** with `feat(frontend): signed-in reviewer, per-field review keys, co-sign`.

---

### Task 8: Model provider seam, prepared only (E11)

**Files:**
- Modify: `arp/config.py`: `llm_provider: Literal["anthropic"] = "anthropic"`. Pydantic rejects other values at startup.
- Modify: `arp/llm/factory.py`: `build_llm_client` dispatches on `settings.llm_provider` through `_BUILDERS: dict[str, Callable[..., LLMClient]] = {"anthropic": _build_anthropic}`. The current body moves into `_build_anthropic` unchanged.
- Modify: `arp/llm/base.py`: `LLMUsage.provider: str = ""`.
- Modify: `arp/llm/langchain_client.py`: set `provider="anthropic"` on the usage it returns. This is the only change in that file.
- Modify: `arp/schemas/datapoints.py` (`ProvenanceInfo.provider: str = ""`) and `arp/extraction/aggregator.py` / `field_graph._aggregate` (fill it from the usage).
- Test: `tests/test_llm_contract.py` (new).

**Interfaces:**
- Produces: `def assert_llm_contract(client: LLMClient) -> Awaitable[None]` in `tests/test_llm_contract.py`. Any future client must pass it. It checks that `complete_structured` returns `(instance of output_model, LLMUsage)` with `usage.provider` set.

- [ ] **Step 1: Write failing tests:**
  - `test_fake_client_passes_contract`: give `FakeLLMClient` in `conftest.py` a `provider="fake"` on its usage.
  - `test_unknown_provider_rejected`: `Settings(llm_provider="vertex")` raises `ValidationError`.
  - `test_factory_builds_anthropic`: with a dummy key, the factory returns a `LangChainAnthropicClient`, with no network call.
  - `test_provenance_records_provider`.

- [ ] **Step 2: Run** `pytest tests/test_llm_contract.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Files.**

- [ ] **Step 4: Run** `pytest -q && ruff check arp tests`. Expect all pass.

- [ ] **Step 5: Commit** with `feat(llm): provider seam, anthropic only (E11)`.
