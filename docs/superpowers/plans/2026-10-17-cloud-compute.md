# Cloud compute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PDF parsing, reranking and embedding run on Cloud Run L4 GPUs whenever `backend/.env` names the services. There is no per-session step, and every call falls back to local compute on any cloud failure.

**Architecture:** A small client (`arp/compute/client.py`) is consulted first by the three existing choke points (`_extract_pdf_text`, `rerank._score`, `embed_texts`); `None` means "compute locally as today". One FastAPI app (`arp/compute/server.py`) runs the same local functions on a GPU; it is deployed twice (`arp-parse`, `arp-models`) from one image. PDFs travel through a Cloud Storage bucket mounted read-only into `arp-parse`.

**Tech Stack:** Python 3.11, httpx (installed), google-auth (installed via google-genai, made direct), FastAPI/uvicorn, fastembed-gpu in the image only, Cloud Run GPU, Cloud Build, Artifact Registry, GitHub Actions with Workload Identity Federation.

**Spec:** `docs/superpowers/specs/2026-10-17-cloud-compute-design.md` (AC numbers below refer to its Acceptance table)

## Global Constraints

- Settings unset or empty means no request to a compute URL or `storage.googleapis.com`, and today's results (AC-1, AC-2).
- New settings: `compute_parse_url: str | None`, `compute_models_url: str | None`, `compute_bucket: str | None`, `compute_credentials_file: Path | None`, all default `None`, env prefix `ARP_`. Empty string counts as unset. Parse needs the parse URL, the bucket and the key path; models need the models URL and the key path. If a URL is set but a setting it needs is empty, that capability runs locally and logs one WARNING per process naming the missing env var (AC-16).
- Exact pins in `backend/pyproject.toml`: `docling==2.140.0`, `docling-core==2.101.1`, `trafilatura==2.3.1`, `openpyxl==3.1.5`; add `google-auth>=2.40,<3.0`. One comment line on why they are exact (the cloud parser must report the same `parser_version()`).
- Constants in `arp/compute/client.py`: `COOLDOWN_S = 600.0`, `RETRY_DELAY_S = 5.0`, `CONNECT_TIMEOUT_S = 10.0`, `PARSE_TIMEOUT_S = 1800.0` (read timeout for parse and upload), `MODELS_TIMEOUT_S = 180.0`, `EMBED_BATCH = 256`, `PARSE_SLOTS = 2` (equals `arp-parse` max instances).
- Retry once after `RETRY_DELAY_S` only on `httpx.ConnectError` or status 429, 502, 503 or 504. A read timeout is not retried. Any other failure, or the second transient one, returns `None`, sets that capability's cooldown (`"parse"` or `"models"`) and logs one WARNING. Exception: a 422 from `/parse` returns `None` without a cooldown (AC-12).
- Region `europe-west1`; bucket `<project>-arp-compute`; object names `parse/<sha256 hex>.pdf`; header `X-ARP-Parser-Version`; image tag is the commit's first 7 SHA characters.
- Backend checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`. Never weaken an existing test (AC-28). PR targets `main`.

## Review Focus

1. **Two uploads of the same file at once.** The second upload gets 412 from `ifGenerationMatch=0`, which counts as success and is not a storage failure. (Task 1 test)
2. **Missing or unreadable key file.** The result is local compute plus one WARNING, never an exception reaching the run. (Task 1 test)
3. **The key file path is relative.** A relative `ARP_COMPUTE_CREDENTIALS_FILE` resolves against `backend/` (the `.env` location), not the process's working directory. That is how `uvicorn` and `arp` are both started. (Task 1 test)
4. **A huge PDF.** The parse request carries only the object name, whatever the file size. The upload streams the file from disk instead of reading it into memory twice. (Task 1 test: a 40 MiB sparse file; the `/parse` request body stays under 200 bytes)
5. **A cloud parse with no pages.** The service returns `{"text": "", "page_breaks": [], "table_spans": []}` for an empty PDF. The client returns it as is, and the caller's existing empty-text handling skips the document, as it does locally. (Task 1 test)

---

### Task 1: Settings, pins, client core and remote PDF parse

**Files:**
- Modify: `backend/arp/config.py` (four settings next to `rerank_enabled`), `backend/pyproject.toml` (pins), `backend/arp/ingestion/local_files.py` (`_extract_pdf_text`, first lines), `backend/tests/conftest.py` (autouse fixture)
- Create: `backend/arp/compute/__init__.py` (empty), `backend/arp/compute/client.py`
- Test: `backend/tests/test_compute_client.py`, `backend/tests/test_compute_parse_hook.py`

**Interfaces:**
- Produces: `parse_pdf(path: Path, parser_version: str) -> tuple[str, list[int], list[TableSpan]] | None`
- Produces (test seams, module-level): `_http: httpx.Client`, `_id_token(audience: str) -> str`, `_storage_token() -> str`, `_sleep = time.sleep`, `_now = time.monotonic`, `_cooldown_until: dict[str, float]`, `last_error: dict[str, str]` (the latest failure reason per capability, which Task 4 prints)
- Produces: `_post(capability: str, url: str, payload: dict, timeout: float, headers: dict[str, str] | None = None) -> httpx.Response | None`. It adds `Authorization: Bearer <_id_token(base url)>`, applies the retry and cooldown rules, records `last_error`, and returns `None` on failure. It hands a 422 response back to the caller without a cooldown.

- [ ] **Step 1: Write the failing tests.** An autouse fixture clears `_cooldown_until`, patches `_id_token` and `_storage_token` to `"tok"`, `_sleep` to a no-op and `client.get_settings` to a `Settings` with all four values set. It also swaps `_http` for an `httpx.Client` on a recording `MockTransport`, a helper with `route(matcher, status | exception, json=None)` and `calls(matcher)`. The matchers are `GET_OBJECT`, `UPLOAD` and `PARSE`.

```python
def test_parse_returns_service_result(tmp_path, transport):  # AC-3
    transport.route(GET_OBJECT, 404); transport.route(UPLOAD, 200)
    transport.route(PARSE, 200, json={"text": "T", "page_breaks": [0], "table_spans": []})
    assert client.parse_pdf(pdf(tmp_path, b"%PDF-1.4 x"), "v1") == ("T", [0], [])

def test_parse_uploads_once_by_hash(...)            # AC-4: one UPLOAD; params["name"] == f"parse/{sha256(b'%PDF-1.4 x').hexdigest()}.pdf"; body == file bytes
def test_parse_skips_upload_when_object_exists(...) # AC-5: GET_OBJECT 200 -> 0 UPLOAD; 1 PARSE with json == {"object": "parse/<sha>.pdf"}
def test_409_falls_back_once(..., caplog)           # AC-6: PARSE 409 body "parser_version mismatch: service=R client=L" -> None; 1 PARSE call; exactly 1 WARNING containing "R" and "L"
def test_cooldown_skips_for_600s(...)               # AC-7: after the 409, advance _now by 599 -> parse_pdf sends 0 requests, no new WARNING
def test_cloud_retried_after_cooldown(...)          # AC-8: after a failure, advance _now by 601, PARSE now 200 -> 1 PARSE call, cloud result returned
def test_connect_error_retried_once(...)            # AC-9: PARSE raises httpx.ConnectError -> None; 2 PARSE attempts
def test_read_timeout_not_retried(...)              # AC-10: PARSE raises httpx.ReadTimeout -> None; 1 PARSE attempt
def test_storage_500_skips_parse(...)               # AC-11: UPLOAD 500 -> None; 0 PARSE calls
def test_422_no_cooldown(...)                       # AC-12: PARSE 422 -> None; the next parse_pdf sends a PARSE request
def test_two_parses_in_flight(...)                  # AC-13: 4 threads; PARSE handler blocks on an Event and records max concurrency == 2; the second request arrives before the first returns
def test_partial_settings_warn_once(..., caplog)    # AC-16: bucket "" -> two calls both None, 0 requests, exactly 1 WARNING containing "ARP_COMPUTE_BUCKET"
def test_upload_412_counts_as_success(...)          # Review 1
def test_missing_key_file_falls_back(...)           # Review 2: real _id_token, nonexistent key path -> None, 1 WARNING, no exception
def test_relative_key_path_resolves_to_backend(...) # Review 3
def test_large_pdf_request_carries_only_name(...)   # Review 4
def test_empty_parse_passes_through(...)            # Review 5
def test_unset_settings_make_no_requests(...)       # AC-1
def test_parser_version_matches_pins():             # AC-27
    assert parser_version() == "logic=3|docling=2.140.0|docling-core=2.101.1|trafilatura=2.3.1|openpyxl=3.1.5"
```

In `test_compute_parse_hook.py`:

```python
def test_pdf_uses_remote_result(monkeypatch, tmp_path):  # AC-3 through the real entry point
    monkeypatch.setattr(compute_client, "parse_pdf", lambda p, v: ("T", [0], []))
    assert local_files.parse_file_to_text_with_pages(tmp_path / "x.pdf") == ("T", [0], [])
def test_cache_hit_sends_nothing(...)  # AC-14: DocumentContentStore pre-filled for the file under parser_version(); parse_pdf patched to pytest.fail
def test_docx_stays_local(...)         # AC-15: parse_pdf patched to pytest.fail; an existing DOCX fixture parses to the same text as before
```

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_compute_client.py tests/test_compute_parse_hook.py -v`. Expected: FAIL, `ModuleNotFoundError: arp.compute`.

- [ ] **Step 3: Implement** the settings, pins and `arp/compute/client.py`. Then add these first lines to `_extract_pdf_text`, ahead of `_convert`, so `_DOCLING_LOCK` is never taken for a remote parse: `remote = compute_client.parse_pdf(path, parser_version())`, and `if remote is not None: return remote`. Pass the version in rather than importing it, because `local_files` imports the client. Approach:
  - Upload: `GET https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(name, safe='')}` first (200 = skip). Otherwise `POST https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&name={name}&ifGenerationMatch=0`, with the open file as the streamed body and `Content-Type: application/pdf`. Both use `Authorization: Bearer <_storage_token()>`.
  - Parse: inside `with _parse_slots:` (a `threading.Semaphore(PARSE_SLOTS)`), call `_post("parse", f"{url}/parse", {"object": name}, PARSE_TIMEOUT_S, {"X-ARP-Parser-Version": parser_version})`, then validate `table_spans` with `TableSpan.model_validate`.
  - `_id_token`: `google.oauth2.service_account.IDTokenCredentials.from_service_account_file(file, target_audience=audience)`. `_storage_token`: `service_account.Credentials.from_service_account_file(file, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])`. Cache both per audience/scope and refresh with `google.auth.transport.requests.Request()` when `not creds.valid`.
  - Every exception from auth or I/O is a failure: it leads to a cooldown, `last_error` is set, and the function returns `None`, never a raise. The WARNING reads `Cloud {capability} unavailable ({reason}); computing locally for 600 s.`, where `reason` is the status code plus the first 200 characters of the body, or the exception's type and message.
  - conftest: add an autouse fixture `_no_remote_compute` that sets `ARP_COMPUTE_PARSE_URL` and `ARP_COMPUTE_MODELS_URL` to `""`, in the style of `_disable_rerank_by_default`, so a developer's `.env` never sends tests to the cloud.

- [ ] **Step 4: Run** `cd backend && ruff check . && python3 -m pytest -q`. Expected: all pass, with no change to existing test files (AC-28).

- [ ] **Step 5: Commit** `feat(compute): remote PDF parse with local fallback`

### Task 2: Remote rerank and embeddings

**Files:**
- Modify: `backend/arp/compute/client.py`, `backend/arp/retrieval/rerank.py` (`_score`), `backend/arp/retrieval/embeddings.py` (`embed_texts`, after the empty check)
- Test: `backend/tests/test_compute_models.py`

**Interfaces:**
- Consumes: `_post`, the seams from Task 1
- Produces: `rerank_scores(query: str, texts: list[str]) -> list[float] | None`, which posts `{"query", "texts"}` to `{models_url}/rerank` and reads `"scores"`
- Produces: `embed(texts: list[str]) -> np.ndarray | None`, which posts `{"texts": batch}` to `{models_url}/embed` in batches of `EMBED_BATCH` and returns a float32 `(n, EMBED_DIM)` array. If any batch fails it returns `None` (AC-22).

- [ ] **Step 1: Write the failing tests**

```python
def test_rerank_uses_cloud_scores(monkeypatch, transport):  # AC-18
    transport.route(RERANK, 200, json={"scores": [0.1, 0.9, 0.5]})
    assert [c.chunk_id for c in rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)] == ["b", "c"]

def test_rerank_503_falls_back_to_local(...)        # AC-20: RERANK 503 always; rerank._get_model patched to a fake local model -> its order; 2 RERANK calls
def test_token_refreshed_after_expiry(...)          # AC-17: real _id_token with fake creds valid for 3600 s on the stubbed _now; calls at t and t+3601 carry different Authorization headers
def test_rerank_off_sends_nothing(...)              # AC-19: ARP_RERANK_ENABLED default; run select_relevant_chunks on the fixture; 0 RERANK calls
def test_embed_batches_and_order(transport):        # AC-21: handler returns [[float(i)] * 384 for "t<i>" in texts]
    out = embeddings.embed_texts([f"t{i}" for i in range(600)])
    assert [len(json.loads(r.content)["texts"]) for r in transport.calls(EMBED)] == [256, 256, 88]
    assert out.shape == (600, 384) and out.dtype == np.float32 and (out[599] == 599.0).all()
def test_embed_batch_failure_recomputes_all_locally(...)  # AC-22: batch 2 -> 503 twice; result equals the patched local model's output for all 600
def test_emerging_themes_embeds_in_cloud(...)       # AC-23: the clustering entry point on fixture tags -> >= 1 EMBED call
def test_models_unset_makes_no_requests(...)        # AC-1
```

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_compute_models.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** both client functions. In `_score`, add `remote = compute_client.rerank_scores(query, texts)` and return it if it is not `None`. In `embed_texts`, do the same with `compute_client.embed(texts)`.
- [ ] **Step 4: Run** `cd backend && ruff check . && python3 -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(compute): remote rerank and embeddings with local fallback`

### Task 3: The compute service

**Files:**
- Create: `backend/arp/compute/server.py`
- Test: `backend/tests/test_compute_server.py`

**Interfaces:**
- Consumes: `parse_file_to_text_with_pages`, `parser_version` (`arp.ingestion.local_files`), `EMBED_MODEL_NAME`, `TableSpan`
- Produces: `app: FastAPI` with `GZipMiddleware(minimum_size=1000)`, and these endpoints:
  - `POST /parse`, body `{"object": str}` with pattern `^parse/[0-9a-f]{64}\.pdf$` and an **optional** header `X-ARP-Parser-Version`. A missing header is a mismatch.
    - 409 `{"detail": "parser_version mismatch: service=<S> client=<C or missing>"}` on a mismatch.
    - 404 if the file is missing under `_gcs_root()`.
    - 422 `{"detail": "parse failed: <Type>: <msg>"}` when parsing raises.
    - 200 `{"text", "page_breaks", "table_spans"}` otherwise.
  - `POST /rerank`, body `{"query": str, "texts": list[str]}`, returns `{"scores": list[float]}`.
  - `POST /embed`, body `{"texts": list[str]}` with at most 1024 items (else 422), returns `{"vectors": list[list[float]]}`.
  - `GET /healthz` returns `{"parser_version": str, "cuda": bool}` (`torch.cuda.is_available()`).
- Produces: `GPU_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"`, and `_gcs_root() -> Path` (env `ARP_COMPUTE_GCS_ROOT`, default `/gcs`). Model factories `_reranker()` and `_embedder()` are `lru_cache`d and built with `cuda=True`. `_reranker()` first runs `import torch  # noqa: F401`, a one-line comment explaining that it loads the CUDA/cuDNN libraries onnxruntime-gpu needs.

- [ ] **Step 1: Write the failing tests** (`TestClient(app)`, with `ARP_COMPUTE_GCS_ROOT=tmp_path`, `parser_version` patched to `"v1"`, and the model factories and the parse function patched to fakes)

```python
@pytest.mark.parametrize("obj", ["../etc/passwd", "parse/abc.pdf", f"parse/{'a' * 64}.docx"])
def test_parse_rejects_bad_object(c, obj): assert c.post("/parse", json={"object": obj}, headers=V1).status_code == 422  # AC-24
@pytest.mark.parametrize("headers,client_v", [({"X-ARP-Parser-Version": "v0"}, "v0"), ({}, "missing")])
def test_parse_version_mismatch(c, headers, client_v):  # AC-25
    r = c.post("/parse", json={"object": OBJ}, headers=headers)
    assert r.status_code == 409 and "service=v1" in r.json()["detail"] and f"client={client_v}" in r.json()["detail"]
def test_parse_ok(c)                 # AC-26: file at tmp_path/OBJ, fake parse ("T", [0], []) -> 200, set(r.json()) == {"text", "page_breaks", "table_spans"}
def test_parse_error_is_422(c)       # fake parse raises ValueError("bad") -> 422, detail == "parse failed: ValueError: bad"
def test_parse_missing_file_is_404(c)
def test_rerank_and_embed_shapes(c)  # len(scores) == len(texts); 1025 texts to /embed -> 422
```

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_compute_server.py -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `server.py`. The parse endpoint calls `parse_file_to_text_with_pages(_gcs_root() / object)`. Settings are unset inside the service, so this path runs locally on the GPU.
- [ ] **Step 4: Run** `cd backend && ruff check . && python3 -m pytest tests/test_compute_server.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(compute): GPU compute service app`

### Task 4: `arp compute check`

**Files:**
- Create: `backend/arp/cli/compute.py` (`compute_app = typer.Typer(help="Cloud compute (arp/compute/).")`)
- Modify: `backend/arp/cli/__init__.py` (`app.add_typer(compute_app, name="compute")`)
- Test: `backend/tests/test_compute_cli.py`

**Interfaces:**
- Consumes: `parse_pdf`, `rerank_scores`, `embed`, `last_error` from the client, plus the local `parse_file_to_text_with_pages`, `rerank._get_model`, `embeddings._get_model`
- Produces: the command `check`. It prints one line per capability, in the order parse, rerank, embed, then exits 1 if any line is a FAIL. The lines are:
  - `<cap> OK`
  - `<cap> FAIL: <last_error[cap] or the comparison that failed>`
  - `<cap> FAIL: ARP_COMPUTE_<PARSE|MODELS>_URL not set`

  The checks follow the spec's definition of OK:
  - **parse:** a one-page PDF written with reportlab to a temp dir, with the text `ARP compute check`. It passes when the cloud text equals the local text and `/healthz` reports `"cuda": true`.
  - **rerank:** the query `revenue` against `["Revenue grew 5% in 2025.", "The cat sat on the mat.", "Weather was mild."]`. It passes when the cloud and local rerankers rank the same text first.
  - **embed:** one text. It passes when cosine(cloud, local) is at least 0.99.

  The local side always calls the local model directly, so the fallback cannot hide a failure.

- [ ] **Step 1: Write the failing tests** with typer's `CliRunner` and the client functions patched:
  - All three succeed: stdout is exactly `parse OK\nrerank OK\nembed OK\n` and the exit code is 0 (AC-29, unit half).
  - `parse_pdf` returns `None` with `last_error["parse"] = "ConnectError: ..."`: a line starts with `parse FAIL: `, rerank and embed still print `OK`, and the exit code is 1 (AC-30, unit half).
  - URLs unset: stdout contains `parse FAIL: ARP_COMPUTE_PARSE_URL not set` and the exit code is 1.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_compute_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the command.
- [ ] **Step 4: Run** `cd backend && ruff check . && python3 -m pytest tests/test_compute_cli.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(compute): arp compute check`

### Task 5: Image, one-time setup, auto-deploy, docs

**Files:**
- Create: `backend/Dockerfile.compute`, `scripts/gcp/cloudbuild.yaml`, `scripts/gcp/deploy_compute.sh`, `scripts/gcp/setup_compute.sh`, `.github/workflows/deploy-compute.yml`
- Modify: `.gitignore` (add `backend/.gcp/`), `README.md` (a short "Cloud compute (optional)" section after "Optional backends")

**Interfaces:**
- Consumes: `arp.compute.server:app`
- Produces: the GitHub repo variables `GCP_PROJECT`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, read by the workflow and printed by the setup script.

- [ ] **Step 1: Write `Dockerfile.compute`.** It runs `python:3.11-slim`, plus the `libgl1 libglib2.0-0` system libraries, plus `pip install ./backend`. It then replaces `onnxruntime` and `fastembed` with `fastembed-gpu` at the installed fastembed version. It bakes the docling models and both fastembed models into the image (`HF_HOME=/models/hf`, `FASTEMBED_CACHE_PATH=/models/fastembed`), so a cold start downloads nothing. The command is `uvicorn arp.compute.server:app --host 0.0.0.0 --port ${PORT:-8080}`. `cloudbuild.yaml` builds it from the repo root on `E2_HIGHCPU_8` with a 100 GB disk and pushes `europe-west1-docker.pkg.dev/$PROJECT_ID/arp/compute:$_TAG`.
- [ ] **Step 2: Write `deploy_compute.sh`.** It reads `PROJECT`, `REGION`, `BUCKET` and `TAG` from the environment, runs `gcloud builds submit --config scripts/gcp/cloudbuild.yaml --substitutions _TAG=$TAG`, then deploys both services. Shared flags: `--no-allow-unauthenticated --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy --cpu 4 --memory 16Gi --no-cpu-throttling --min-instances 0 --service-account arp-compute@$PROJECT.iam.gserviceaccount.com`. `arp-parse` adds `--max-instances 2 --concurrency 1 --timeout 3600 --add-volume name=docs,type=cloud-storage,bucket=$BUCKET,readonly=true --add-volume-mount volume=docs,mount-path=/gcs`. `arp-models` adds `--max-instances 1 --concurrency 8 --timeout 300`.
- [ ] **Step 3: Write `setup_compute.sh <project-id>`.** It is idempotent: each create is skipped when the resource exists, and the key file is reused (AC-31). In order, it:
  1. Enables the run, cloudbuild, artifactregistry, storage, iam, iamcredentials, sts and billingbudgets APIs.
  2. Creates the bucket in `europe-west1` with uniform access and exactly one lifecycle rule: Delete at age 1 (AC-32).
  3. Creates the Artifact Registry repo `arp`.
  4. Creates the service accounts. `arp-compute` gets `storage.objectViewer` on the bucket. `arp-client` gets `storage.objectCreator` and `storage.objectViewer` on the bucket. `arp-deployer` gets `run.admin`, `cloudbuild.builds.editor`, `artifactregistry.writer`, `storage.admin` and `iam.serviceAccountUser` on `arp-compute`.
  5. Creates the WIF pool `github` and provider `github`, with the condition `assertion.repository == '<owner/repo from git remote>'`, and gives `arp-deployer` the `workloadIdentityUser` role for that repo.
  6. Creates a budget alert of `${BUDGET_AMOUNT:-50EUR}` at 50% and 100%.
  7. Runs the first deploy with `deploy_compute.sh`, using `TAG=$(git rev-parse --short=7 HEAD)`.
  8. Gives `arp-client` `run.invoker` on both services.
  9. Creates the key `backend/.gcp/arp-client.json` unless it already exists. If an organisation policy blocks key creation, it prints that the key is the blocker and stops.
  10. Prints the `.env` lines (`ARP_COMPUTE_PARSE_URL`, `ARP_COMPUTE_MODELS_URL`, `ARP_COMPUTE_BUCKET`, `ARP_COMPUTE_CREDENTIALS_FILE=.gcp/arp-client.json`, `ARP_RERANK_ENABLED=true`) and the four repo variables.
- [ ] **Step 4: Write `deploy-compute.yml`.** It runs on `push` to `main` filtered to the spec's Deploy paths, plus `workflow_dispatch` (any branch). It has `permissions: {id-token: write, contents: read}` and `concurrency: deploy-compute`. When `vars.GCP_PROJECT` is empty it logs `::warning::GCP repo variables not set; skipping the compute deploy` and succeeds (AC-38). Otherwise it runs `google-github-actions/auth@v2` (WIF) and `setup-gcloud@v2`, then `deploy_compute.sh` with `TAG=${GITHUB_SHA::7}` (AC-37).
- [ ] **Step 5: Verify locally.** `bash -n scripts/gcp/*.sh` exits 0. `shellcheck scripts/gcp/*.sh` shows no errors, if shellcheck is installed. `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-compute.yml'))"` exits 0.
- [ ] **Step 6: Commit** `feat(compute): Cloud Run image, one-time setup and auto-deploy`
- [ ] **Step 7: Owner, once.** Run `bash scripts/gcp/setup_compute.sh <project-id>`, paste the printed lines into `backend/.env` and the repo variables, then run `pip install -e backend` (the pins). The evaluator then runs the deploy workflow on the PR branch and checks AC-29 to AC-36 against the live services.
