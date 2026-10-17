# Cloud compute: parsing and local models on Cloud Run GPUs

Status: draft, awaiting owner approval. The owner skipped the brainstorming questions; every decision
below marked *(my call)* was made by the agent and is open to change.

## Intent

ARP's slow work runs on the owner's machine: docling PDF parsing (hours for a universe, one file at a time
under `_DOCLING_LOCK`), the cross-encoder reranker (~47 s per field on CPU, so it stays off) and fastembed
embeddings. The Colab notebook (`arp_colab.ipynb`) moved the first two onto a free GPU, but every session
needs clicks: mount Drive, run cells, copy a tunnel URL and token into `.env`, restart the backend.

Goal: the same work runs on Google Cloud GPUs **with no manual step when the app runs**. Start the backend
as today; parsing, reranking and embedding go to the cloud on their own, and fall back on their own when
the cloud is unreachable.

## Goals

1. Every PDF parse, every rerank and every `embed_texts` call goes to Google Cloud when the cloud settings are present.
2. Nothing to do per session: no URL, token or notebook. One-time setup is a single script.
3. A deploy follows `main` automatically, so the cloud parser matches the local code.
4. No cloud, a cloud error, or a version mismatch never fails a run.
5. Cost is bounded: scale to zero when idle; at most 3 GPU instances (the project's default L4 quota).

## Non-goals

- Running the backend, Postgres or the frontend in the cloud. Only the compute moves.
- LLM calls (already remote), DOCX/HTML/XLSX/text parsing (cheap, stay local), emerging-themes UMAP/HDBSCAN
  (CPU, small inputs; its embeddings move because it calls `embed_texts`) and the signal lab's research
  embedder (`default_embedder`, stays local).
- The Colab notebook's `ARP_RERANK_URL` / `ARP_RERANK_TOKEN` lines: nothing on `main` reads them, and this
  replaces that workflow without adding support for it.
- Replacing the content cache: remote parse results land in the same local `DocumentContentStore`.
- Pre-warming instances, a UI indicator of local vs cloud, multi-user or multi-project setups.

## Anti-goals (fails even if it works)

- A run fails, or stalls: no call waits on the cloud longer than one read timeout plus one retry, and after
  a failure later calls skip the cloud for 600 s.
- A cloud parse is stored under a `parser_version` that did not produce it, or vectors from another model
  are stored as `EMBED_MODEL_NAME`.
- A public endpoint anyone can call: an unauthenticated request must never start a GPU instance.
- Documents kept in the cloud longer than needed.

## Constraints (verified 2026-10-17 on docs.cloud.google.com)

- Cloud Run GPU: NVIDIA L4 in `europe-west1` and `europe-west4`; minimum 4 CPU and 16 GiB per instance;
  scales to zero; instance-based billing required; new projects get 3 L4 (no zonal redundancy) without a
  quota request.
- Cloud Run HTTP/1 request body limit is 32 MiB; request timeout max 60 min. Annual reports exceed 32 MiB,
  so documents travel through Cloud Storage, not the request body.
- A Cloud Storage bucket can be mounted read-only into a Cloud Run service (`--add-volume type=cloud-storage`).

## Design

**Two Cloud Run services from one image** *(my call)*, region `europe-west1`, IAM-only (no `allUsers` invoker):

| Service | Endpoints used | Concurrency | Max instances | Timeout |
|---|---|---|---|---|
| `arp-parse` | `POST /parse` | 1 | 2 | 3600 s |
| `arp-models` | `POST /rerank`, `POST /embed` | 8 | 1 | 300 s |

Parse gets concurrency 1 so parallel parses fan out to separate GPUs; models gets one shared instance.
Both have min instances 0, 1 × L4, 4 CPU, 16 GiB, no zonal redundancy. 2 + 1 = the 3-GPU default quota.

**Settings.** `ARP_COMPUTE_PARSE_URL`, `ARP_COMPUTE_MODELS_URL`, `ARP_COMPUTE_BUCKET`,
`ARP_COMPUTE_CREDENTIALS_FILE` (absolute path to the service-account key). All default to empty, and
empty counts as unset. Remote parse needs the parse URL, the bucket and the key file; remote models need
the models URL and the key file. When a URL is set but another setting it needs is empty, or the key file
is missing or unreadable, that capability runs as if the URL were unset and logs one WARNING per process
naming the setting or path *(my call: never block startup)*.

**Parse path.** Only PDFs go to the cloud; every other file type parses locally as today. The
`DocumentContentStore` lookup happens first, as today, so a cached document sends no request, and a cloud
result is stored there under the local `parser_version()`. A remote parse does not take `_DOCLING_LOCK`.
At most 2 remote parses are in flight; more callers wait for a slot, and the cooldown is checked after a
slot is acquired, so queued callers do not each wait out a hung service.

The backend hashes the PDF (sha256), uploads it to `gs://<bucket>/parse/<sha256>.pdf` unless that object
exists (an upload that loses a race with `ifGenerationMatch=0` counts as success), and calls
`POST /parse {"object": "parse/<sha256>.pdf"}` with header `X-ARP-Parser-Version: <local parser_version()>`.
The service checks, in this order:
1. The object must match `^parse/[0-9a-f]{64}\.pdf$`, else 422.
2. The header must be present and equal its own `parser_version()`, else 409 `parser_version mismatch:
   service=<S> client=<C or missing>`.
3. The object must exist in its read-only bucket mount, else 404 `object not found: <object>`.
4. It runs `parse_file_to_text_with_pages` on the GPU and returns exactly the keys `text`, `page_breaks`,
   `table_spans`. A parse that raises is 422 `parse failed: <Type>: <msg>`.

On a 404 the backend retries once after 5 s (the mount can lag a fresh upload), then parses that file
locally. On a `parse failed` 422 it parses that file locally (raising today's error). Neither sets the
cooldown, since one file is not an outage. A bucket lifecycle rule deletes objects after 1 day, and soft
delete and versioning are off.

**Models path.** `POST /rerank {"query", "texts"} -> {"scores"}` uses `BAAI/bge-reranker-v2-m3` (full
precision) on CUDA *(my call: the local int8 variant's quantized operators run poorly on the CUDA provider)*.
`POST /embed {"texts"} -> {"vectors"}` uses `EMBED_MODEL_NAME`. Both requests carry `X-ARP-Model` with the
model the backend expects; a different value is 409, handled as a failure. Reranking stays behind the
existing `ARP_RERANK_ENABLED` switch *(my call)*; setup prints `ARP_RERANK_ENABLED=true`. When the models URL
is set and the cloud reranker fails, `rerank` keeps the retrieval order, as it already does when its model
is unavailable. The ~47 s/field local reranker is never the fallback *(my call: it would stall the run)*.
Embeddings are sent in batches of at most 256 texts; if any batch fails, the whole call is computed
locally (never a mix of cloud and local rows).

**Auth.** One service account `arp-client` with `run.invoker` on both services and object create/read on
the bucket. Setup writes its JSON key to `backend/.gcp/arp-client.json` (gitignored) and prints that file's
absolute path for `ARP_COMPUTE_CREDENTIALS_FILE`. The backend mints a Google ID token per service URL and
an OAuth token for Cloud Storage with `google-auth` (already installed through `google-genai`; made a
direct dependency), refreshing each token once it is no longer valid (they last 1 h).

**Timeouts and fallback** *(my call)*. Connect timeout 10 s everywhere. Read timeout: parse and upload
1800 s, rerank and embed 180 s (above a cold start). A connect error or status 429, 502, 503 or 504 is
retried once after 5 s; a read timeout is not retried. Any other failure, or the second transient one,
falls back for that call (parse and embed: computed locally; rerank: retrieval order), skips the cloud for
that capability (`parse` or `models`) for 600 s, and logs one WARNING. After 600 s the next call tries the
cloud again, so recovery needs no restart. A Cloud Storage failure counts as a `parse` failure.

**Version lock** *(my call)*. The cloud and local parser must report the same `parser_version()`.
`docling==2.140.0`, `docling-core==2.101.1`, `docling-ibm-models==4.0.3`, `docling-parse==7.22.3`,
`trafilatura==2.3.1` and `openpyxl==3.1.5` get exact pins in `backend/pyproject.toml` (the versions
installed today). The image installs from the same file, so after a local `pip install -e backend` both
sides match. `parser_version()` itself is unchanged. A mismatch is the 409 fallback, never a mixed cache.
Accepted: GPU and CPU inference, and the CUDA vs CPU torch builds, can differ in the last digits of model
outputs under one `parser_version()`, as two local machines can today. If the owner's machine has other
versions installed today, re-installing changes its `parser_version()` once and existing cache entries get
re-parsed (now in the cloud).

**Deploy.** `.github/workflows/deploy-compute.yml` builds the image with Cloud Build and deploys both
services, authenticating with Workload Identity Federation (no stored key). It runs on every push to `main`
touching `backend/arp/ingestion/**`, `backend/arp/compute/**`, `backend/arp/retrieval/rerank.py`,
`backend/arp/retrieval/embeddings.py`, `backend/arp/schemas/common.py`, `backend/pyproject.toml`,
`backend/Dockerfile.compute` or `scripts/gcp/**`, and on `workflow_dispatch` for any branch. The image tag
is the deployed commit's first 7 SHA characters. It reads the repo variables `GCP_PROJECT`, `GCP_REGION`,
`GCP_WIF_PROVIDER` and `GCP_DEPLOY_SA`; when any is empty the job logs a `::warning::` and succeeds, like
the golden-set job. Accepted: a `workflow_dispatch` of a PR branch replaces the live services until the
next `main` deploy; the version and model headers keep a mismatched branch out of the cache.

**One-time setup.** `scripts/gcp/setup_compute.sh <project-id>` enables the APIs, then creates:
- the bucket (1-day lifecycle rule, soft delete 0, versioning off) and the Artifact Registry repo;
- the service accounts and the GitHub WIF binding;
- a budget named `arp-compute` of `${BUDGET_AMOUNT:-50}` per month, in the billing account's currency, on
  the project's billing account, alerting billing admins at 50, 90 and 100 %.

It then deploys once from the checked-out commit (image tag = first 7 characters of `git rev-parse HEAD`,
the same rule as the workflow), writes the client key and prints the `.env` lines and repo variables. It is
idempotent: a re-run creates nothing that exists (bucket, repo, accounts, binding, budget) and reuses the
key file.

**Check.** `arp compute check` prints one line per capability (`parse`, `rerank`, `embed`): `<cap> OK` or
`<cap> FAIL: <reason>`, and exits 1 if any line fails. OK means:
- parse: the cloud text of a generated one-page PDF equals the local parse's text, and `/healthz` reports CUDA;
- rerank: the cloud and local rerankers rank the same text first for a fixed 3-text sample;
- embed: cosine(cloud, local) ≥ 0.99.

## Left to the builder

File layout inside `arp/compute/`, log wording beyond the rows below, Dockerfile base image and layer
order (the CUDA libraries come from the PyTorch wheels), and the exact gcloud commands.

## Acceptance

`unit` rows need stubbed Google auth and storage, which only the implementer's test seams provide, so
they stay `unit` rather than `holdout` *(my call)*. `evaluator` rows run on the owner's project in this
order: `setup_compute.sh` run from a checkout of the PR head SHA S, the repo variables set, then the checks.
(`workflow_dispatch` only runs workflow files on the default branch, so the workflow cannot deploy a PR
head before merge; its trigger and gating are covered statically by AC-38 and AC-49.)

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | all `ARP_COMPUTE_*` empty; `ARP_RERANK_ENABLED=true` | a PDF is parsed, chunks reranked, texts embedded | zero HTTP requests to any host ending in `run.app` or `googleapis.com` | unit |
| AC-2  | all `ARP_COMPUTE_*` empty | the same calls on the fixture PDF and texts | parse text, page_breaks, table_spans, rerank order and embedding vectors equal `origin/main`'s output | unit |
| AC-3  | parse settings set; no object for the file; `/parse` stub answers 200 `{"text": "T", "page_breaks": [0], "table_spans": []}` | `parse_file_to_text_with_pages(x.pdf)` | returns `("T", [0], [])` | unit |
| AC-4  | as AC-3 | the same parse | exactly one upload; its name is `parse/<sha256 hex of the file bytes>.pdf` and its body equals the file bytes | unit |
| AC-5  | as AC-3, but the object already exists | the same parse | zero uploads; exactly one `POST /parse` with body `{"object": "parse/<sha256>.pdf"}` | unit |
| AC-6  | `/parse` answers 409 naming versions L and R | a PDF is parsed | the local result is returned; exactly 1 `POST /parse` sent; exactly 1 WARNING, containing L and R | unit |
| AC-7  | after AC-6, clock stubbed | a second PDF is parsed 599 s later | zero HTTP requests; no further WARNING | unit |
| AC-8  | parse failed at time t (clock stubbed); `/parse` now answers 200 | a PDF is parsed at t + 601 s | exactly 1 `POST /parse` sent; the cloud result is returned | unit |
| AC-9  | `/parse` refuses connections | a PDF is parsed | the local result is returned; exactly 2 `POST /parse` attempted | unit |
| AC-10 | `/parse` accepts the connection and never answers; read timeout 1 s; the local parser stubbed to return `L` at once | a PDF is parsed | returns `L` in under 3 s; exactly 1 `POST /parse` sent | unit |
| AC-11 | the storage upload answers 500 | a PDF is parsed | the local result is returned; zero `POST /parse` sent | unit |
| AC-12 | `/parse` answers 422 `parse failed: ValueError: bad` | a PDF is parsed, then another | the first is parsed locally; the second sends a `POST /parse` (no cooldown) | unit |
| AC-13 | the parse stub takes 2 s | 4 PDFs are parsed concurrently | the second `POST /parse` is sent before the first returns; never more than 2 in flight | unit |
| AC-14 | parse settings set; the store holds the file under the current `parser_version()` | the file is parsed | zero HTTP requests; the cached text is returned | unit |
| AC-15 | parse settings set | `x.docx` is parsed | zero HTTP requests; result equals `origin/main`'s | unit |
| AC-16 | `ARP_COMPUTE_PARSE_URL` set, `ARP_COMPUTE_BUCKET` empty | two PDFs are parsed | both parse locally; exactly 1 WARNING, naming `ARP_COMPUTE_BUCKET` | unit |
| AC-17 | token source stubbed to issue tokens valid for 3600 s | rerank at t and again at t + 3601 s | the two `POST /rerank` carry different `Authorization` headers; both return the cloud result | unit |
| AC-18 | models URL set, rerank enabled; `/rerank` answers `{"scores": [0.1, 0.9, 0.5]}` | `rerank("q", [a, b, c], top_n=2)` | returns `[b, c]` | unit |
| AC-19 | models URL set, `ARP_RERANK_ENABLED` at its default (false) | one extraction run on the fixture | zero `POST /rerank` sent | unit |
| AC-20 | models URL set, rerank enabled; `/rerank` answers 503 to everything | `rerank("q", [a, b, c], top_n=2)` | returns `[a, b]` (retrieval order); exactly 2 `POST /rerank` sent | unit |
| AC-21 | for each text `t<i>` the `/embed` stub returns 384 copies of float(i) | `embed_texts` with 600 texts | 3 requests of 256, 256 and 88 texts; shape (600, 384), float32; row i equals [i] × 384 | unit |
| AC-22 | batch 2 of 600 texts gets 503 twice | `embed_texts` with 600 texts | shape (600, 384); every row equals local `embed_texts` output for that text | unit |
| AC-23 | models URL set (stub) | an emerging-themes clustering run on the fixture tags | ≥ 1 `POST /embed` sent | unit |
| AC-24 | the compute service app; a matching `X-ARP-Parser-Version` header | `POST /parse` with object `../etc/passwd`, or any object not matching `^parse/[0-9a-f]{64}\.pdf$` | 422 | unit |
| AC-25 | the compute service app; object `parse/<64 hex>.pdf` | `POST /parse` with the header absent, or different from the service's `parser_version()` | 409; body contains the service's version and the received one (or `missing`) | unit |
| AC-26 | the compute service app; matching header; `parse/<sha>.pdf` exists in the mount | `POST /parse` | 200; body has exactly the keys `text`, `page_breaks`, `table_spans` | unit |
| AC-27 | `pip install -e backend` on this branch | `python -c "from arp.ingestion.local_files import parser_version as v; print(v())"` | prints `logic=3\|docling=2.140.0\|docling-core=2.101.1\|trafilatura=2.3.1\|openpyxl=3.1.5` | unit |
| AC-28 | this branch | `cd backend && python3 -m pytest` | exits 0; `git diff origin/main -- backend/tests` shows no modified or deleted lines in existing files | unit |
| AC-29 | the evaluator order above, with the printed lines in `backend/.env` | `arp compute check` | prints exactly `parse OK`, `rerank OK`, `embed OK`; exits 0 | evaluator |
| AC-30 | as AC-29, but `ARP_COMPUTE_PARSE_URL` points at a nonexistent `run.app` URL | `arp compute check` | a line starting `parse FAIL: `, then `rerank OK` and `embed OK`; exits 1 | evaluator |
| AC-31 | setup done | `setup_compute.sh` run again | exits 0; the counts from `gcloud iam service-accounts keys list --iam-account arp-client@<id>.iam.gserviceaccount.com` and `gcloud billing budgets list --billing-account <acct>` are unchanged | evaluator |
| AC-32 | setup done | `gcloud storage buckets describe gs://<id>-arp-compute --format='json(lifecycle_config)'` | exactly one rule: action Delete, condition age 1 | evaluator |
| AC-33 | the deployed services | a `POST` with no `Authorization` header to each service URL | HTTP 403 | evaluator |
| AC-34 | both services at 0 instances, idle ≥ 20 min, no other traffic | 5 `POST`s with no `Authorization` header | `run.googleapis.com/container/instance_count` stays 0 over the next 5 min | evaluator |
| AC-35 | the deployed services idle ≥ 20 min | the first rerank call from the backend | the cloud result is returned within 120 s; no fallback WARNING logged | evaluator |
| AC-36 | the deployed services | `gcloud run services describe` and `gcloud run services get-iam-policy` for each | region `europe-west1`; min instances 0; max instances 2 / 1; concurrency 1 / 8; timeout 3600 s / 300 s; 1 `nvidia-l4` GPU; `get-iam-policy` lists no `allUsers` member (`arp-parse` / `arp-models`) | evaluator |
| AC-37 | `setup_compute.sh` run from a checkout of PR head SHA S | `gcloud run services describe` for each service | the latest ready revision runs image tag = the first 7 characters of S | evaluator |
| AC-38 | `deploy-compute.yml` | parsed as YAML | the deploy steps run only when all four GCP variables are non-empty; otherwise a step echoes `::warning::` and the job has no failing step | unit |
| AC-39 | parse settings set; x.pdf not in the store; `/parse` stub answers 200 with text `T` | x.pdf is parsed through the store twice | exactly 1 `POST /parse`; the store entry for x.pdf has text `T` and `parser_version` = local `parser_version()` | unit |
| AC-40 | `/parse` never answers; read timeout 1 s; local parser stubbed | 4 PDFs are parsed concurrently | exactly 2 `POST /parse` sent; all 4 return the local result | unit |
| AC-41 | the compute service app; matching header; `parse/<sha>.pdf` absent from the mount | `POST /parse` | 404 with detail `object not found: parse/<sha>.pdf` | unit |
| AC-42 | `/parse` answers 404 | a PDF is parsed | the local result is returned; exactly 2 `POST /parse` sent | unit |
| AC-43 | after AC-42 | a second PDF is parsed at once | a `POST /parse` is sent (no cooldown) | unit |
| AC-44 | setup done | `gcloud storage buckets describe gs://<id>-arp-compute --format='value(soft_delete_policy.retentionDurationSeconds,versioning_enabled)'` | prints `0` and a false/empty versioning value | evaluator |
| AC-45 | the compute service app | `POST /embed` or `POST /rerank` with an `X-ARP-Model` header different from the service's model | 409 | unit |
| AC-46 | models URL set; `/embed` answers 409 | `embed_texts` with 3 texts | equals local `embed_texts` output; exactly 1 `POST /embed` sent | unit |
| AC-47 | parse URL and bucket set; `ARP_COMPUTE_CREDENTIALS_FILE` points at a missing path | two PDFs are parsed | both parse locally; exactly 1 WARNING, containing that path | unit |
| AC-48 | models URL set (stub) | the signal lab's `default_embedder()` embeds 2 texts | zero `POST /embed` sent | unit |
| AC-49 | `deploy-compute.yml` | parsed as YAML | `on.push.branches` is `[main]`; `on.push.paths` is exactly the 8 paths under Deploy; `on.workflow_dispatch` is present | unit |

Must not change: AC-1, AC-2, AC-14, AC-15, AC-19, AC-28, AC-48.
