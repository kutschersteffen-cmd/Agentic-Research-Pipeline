# Cloud compute: parsing and local models on Cloud Run GPUs

Status: draft, awaiting owner approval. The owner skipped the brainstorming questions; every decision
below marked *(my call)* was made by the agent and is open to change.

## Intent

ARP's slow work runs on the owner's machine: docling PDF parsing (hours for a universe, one file at a time
under `_DOCLING_LOCK`), the cross-encoder reranker (~47 s per field on CPU, so it stays off) and fastembed
embeddings. The Colab notebook (`arp_colab.ipynb`) moved the first two onto a free GPU, but every session
needs clicks: mount Drive, run cells, copy a tunnel URL and token into `.env`, restart the backend.

Goal: the same work runs on Google Cloud GPUs **with no manual step when the app runs**. Start the backend
as today; parsing, reranking and embedding go to the cloud on their own, and fall back to local compute on
their own when the cloud is unreachable.

## Goals

1. Every PDF parse, rerank and embedding call goes to Google Cloud when the cloud settings are present.
2. Nothing to do per session: no URL, token or notebook. One-time setup is a single script.
3. A deploy follows `main` automatically, so the cloud parser matches the local code.
4. No cloud, a cloud error, or a version mismatch never fails a run: the call computes locally, as today.
5. Cost is bounded: scale to zero when idle; at most 3 GPU instances (the project's default L4 quota).

## Non-goals

- Running the backend, Postgres or the frontend in the cloud. Only the compute moves.
- LLM calls (already remote), DOCX/HTML/XLSX/text parsing (cheap, stay local), emerging-themes UMAP/HDBSCAN
  (CPU, small inputs; its embeddings move because it calls `embed_texts`) and the signal lab's research embedder.
- Replacing the content cache: remote parse results land in the same local `DocumentContentStore`.
- Pre-warming instances, a UI indicator of local vs cloud, multi-user or multi-project setups.

## Anti-goals (fails even if it works)

- A run fails or stalls because the cloud is down.
- A cloud parse is stored under a `parser_version` that did not produce it (mixed cache entries).
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

**Two Cloud Run services from one image** *(my call)*, region `europe-west1`, IAM-only (no unauthenticated access):

| Service | Endpoints used | Concurrency | Max instances | Timeout |
|---|---|---|---|---|
| `arp-parse` | `POST /parse` | 1 | 2 | 3600 s |
| `arp-models` | `POST /rerank`, `POST /embed` | 8 | 1 | 300 s |

Parse gets concurrency 1 so parallel parses fan out to separate GPUs; models gets one shared instance.
Both have min instances 0, 1 × L4, 4 CPU, 16 GiB, no zonal redundancy. 2 + 1 = the 3-GPU default quota.
The backend keeps at most 2 remote parses in flight; more callers wait for a slot instead of getting 429.

**Settings.** `ARP_COMPUTE_PARSE_URL`, `ARP_COMPUTE_MODELS_URL`, `ARP_COMPUTE_BUCKET`,
`ARP_COMPUTE_CREDENTIALS_FILE` (path to the service-account key). Empty counts as unset. Remote parse needs
the parse URL, the bucket and the key path; remote models need the models URL and the key path. When a URL
is set but another setting it needs is empty, that capability runs locally and logs one WARNING naming the
missing setting *(my call: never block startup)*.

**Parse path.** Only PDFs go to the cloud; every other file type parses locally as today. The cache lookup
in `DocumentContentStore` happens first, as today, so a cached document sends no request. A remote parse
does not take `_DOCLING_LOCK`. The backend hashes the PDF (sha256), uploads it to
`gs://<bucket>/parse/<sha256>.pdf` unless that object exists, and calls `POST /parse {"object": "parse/<sha256>.pdf"}`
with header `X-ARP-Parser-Version: <local parser_version()>`. The service accepts only objects matching
`^parse/[0-9a-f]{64}\.pdf$` (422 otherwise). It answers 409 when the header is missing or differs from
its own `parser_version()`, with the body `parser_version mismatch: service=<S> client=<C or missing>`.
Otherwise it reads the file from its read-only bucket mount and runs `parse_file_to_text_with_pages` on the GPU,
returning exactly the keys `text`, `page_breaks`, `table_spans`. A parse that raises is 422
`parse failed: <Type>: <msg>`; the backend then parses that file locally (raising today's error) without a
cooldown, since a broken file is not an outage. A bucket lifecycle rule deletes objects after 1 day.

**Models path.** `POST /rerank {"query", "texts"} -> {"scores"}` uses `BAAI/bge-reranker-v2-m3` (full
precision) on CUDA *(my call: the local int8 variant's quantized operators run poorly on the CUDA provider)*.
Reranking stays behind the existing `ARP_RERANK_ENABLED` switch *(my call)*; setup prints
`ARP_RERANK_ENABLED=true`. `POST /embed {"texts"} -> {"vectors"}` uses the same `EMBED_MODEL_NAME` as local,
so stored vectors stay comparable. The backend sends embeddings in batches of at most 256 texts; if any
batch fails, the whole call is computed locally (never a mix of cloud and local rows).

**Auth.** One service account `arp-client` with `run.invoker` on both services and object create/read on
the bucket. Its JSON key lives at the path in `ARP_COMPUTE_CREDENTIALS_FILE` (default location
`backend/.gcp/arp-client.json`, gitignored). The backend mints a Google ID token per service URL and an
OAuth token for Cloud Storage with `google-auth` (already installed through `google-genai`; made a direct
dependency), refreshing each token once it is no longer valid (they last 1 h).

**Timeouts and fallback** *(my call)*. Connect timeout 10 s everywhere. Read timeout: parse and upload
1800 s, rerank and embed 180 s (above a cold start). A connect error or status 429, 502, 503 or 504 is
retried once after 5 s; a read timeout is not retried. Any other failure, or the second transient one,
falls back to the local computation for that call, skips the cloud for that capability (`parse` or
`models`) for 600 s, and logs one WARNING. After 600 s the next call tries the cloud again, so recovery
needs no restart. A Cloud Storage failure counts as a `parse` failure.

**Version lock** *(my call)*. The cloud and local parser must report the same `parser_version()`. `docling`,
`docling-core`, `trafilatura` and `openpyxl` get exact pins in `backend/pyproject.toml` (the versions
installed today: 2.140.0, 2.101.1, 2.3.1, 3.1.5). The image installs from the same file, so after a local
`pip install -e backend` both sides match. A mismatch is the 409 fallback above, never a mixed cache. If
the owner's machine has other versions installed today, re-installing changes its `parser_version()` once
and existing cache entries get re-parsed (now in the cloud).

**Deploy.** `.github/workflows/deploy-compute.yml` builds the image with Cloud Build and deploys both
services, authenticating with Workload Identity Federation (no stored key). It runs on every push to `main`
touching `backend/arp/ingestion/**`, `backend/arp/compute/**`, `backend/arp/retrieval/rerank.py`,
`backend/arp/retrieval/embeddings.py`, `backend/arp/schemas/common.py`, `backend/pyproject.toml`,
`backend/Dockerfile.compute` or `scripts/gcp/**`, and on `workflow_dispatch` for any branch (how the
evaluator deploys a PR head). The image tag is the commit's first 7 SHA characters. Without the GCP repo
variables the job logs a `::warning::` and succeeds, like the golden-set job.

**One-time setup.** `scripts/gcp/setup_compute.sh <project-id>`: enables the APIs, creates the bucket (with
the 1-day rule), the Artifact Registry repo, the service accounts, the GitHub WIF binding, a budget alert,
deploys once, writes the client key to `backend/.gcp/arp-client.json` and prints the `.env` lines. It is
idempotent: a re-run creates nothing that exists and reuses the key file.

**Check.** `arp compute check` prints one line per capability (`parse`, `rerank`, `embed`): `<cap> OK` or
`<cap> FAIL: <reason>`, and exits 1 if any line fails. OK means: parse, the cloud text of a generated
one-page PDF equals the local parse's text and `/healthz` reports CUDA; rerank, the cloud and local
rerankers rank the same text first for a fixed 3-text sample; embed, cosine(cloud, local) ≥ 0.99.

## Left to the builder

File layout inside `arp/compute/`, log wording beyond the rows below, Dockerfile base image and layer
order (the CUDA libraries come from the PyTorch wheels), and the exact gcloud commands.

## Acceptance

`unit` rows need stubbed Google auth and storage, which only the implementer's test seams provide, so
they stay `unit` rather than `holdout` *(my call)*. `evaluator` rows run against services deployed by a
`workflow_dispatch` of the deploy workflow on the PR branch.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | all `ARP_COMPUTE_*` settings unset or empty | a PDF is parsed, chunks reranked, texts embedded | no request is sent to either compute URL or to `storage.googleapis.com` | unit |
| AC-2  | as AC-1 | the same calls on the fixture PDF and texts | parse text, page_breaks, table_spans, rerank order and embedding vectors equal `origin/main`'s output | unit |
| AC-3  | parse settings set; no object for the file; `/parse` stub answers 200 `{"text": "T", "page_breaks": [0], "table_spans": []}` | `parse_file_to_text_with_pages(x.pdf)` | returns `("T", [0], [])` | unit |
| AC-4  | as AC-3 | the same parse | exactly one upload; its name is `parse/<sha256 hex of the file bytes>.pdf` and its body equals the file bytes | unit |
| AC-5  | as AC-3, but the object already exists | the same parse | zero uploads; exactly one `POST /parse` with body `{"object": "parse/<sha256>.pdf"}` | unit |
| AC-6  | `/parse` answers 409 naming versions L and R | a PDF is parsed | the local result is returned; exactly 1 `POST /parse` sent; exactly 1 WARNING, containing L and R | unit |
| AC-7  | after AC-6, clock stubbed | a second PDF is parsed 599 s later | zero HTTP requests; no further WARNING | unit |
| AC-8  | parse failed at time t (clock stubbed); `/parse` now answers 200 | a PDF is parsed at t + 601 s | exactly 1 `POST /parse` sent; the cloud result is returned | unit |
| AC-9  | `/parse` refuses connections | a PDF is parsed | the local result is returned; exactly 2 `POST /parse` attempted | unit |
| AC-10 | `/parse` accepts the connection and never answers (read timeout set to 1 s in the test) | a PDF is parsed | the local result is returned within 1 s + 5 s; exactly 1 `POST /parse` sent | unit |
| AC-11 | the storage upload answers 500 | a PDF is parsed | the local result is returned; zero `POST /parse` sent | unit |
| AC-12 | `/parse` answers 422 `parse failed: ValueError: bad` | a PDF is parsed, then another | the first is parsed locally; the second sends a `POST /parse` (no cooldown) | unit |
| AC-13 | the parse stub takes 2 s | 4 PDFs are parsed concurrently | the second `POST /parse` is sent before the first returns; never more than 2 in flight | unit |
| AC-14 | parse settings set; the store holds the file under the current `parser_version()` | the file is parsed | zero HTTP requests; the cached text is returned | unit |
| AC-15 | parse settings set | `x.docx` is parsed | zero HTTP requests; result equals `origin/main`'s | unit |
| AC-16 | `ARP_COMPUTE_PARSE_URL` set, `ARP_COMPUTE_BUCKET` empty | two PDFs are parsed | both parse locally; exactly 1 WARNING, naming `ARP_COMPUTE_BUCKET` | unit |
| AC-17 | token source stubbed to issue tokens valid for 3600 s | rerank at t and again at t + 3601 s | the two `POST /rerank` carry different `Authorization` headers; both return the cloud result | unit |
| AC-18 | models URL set, rerank enabled; `/rerank` answers `{"scores": [0.1, 0.9, 0.5]}` | `rerank("q", [a, b, c], top_n=2)` | returns `[b, c]` | unit |
| AC-19 | models URL set, `ARP_RERANK_ENABLED` at its default (false) | one extraction run on the fixture | zero `POST /rerank` sent | unit |
| AC-20 | `/rerank` answers 503 to everything | `rerank("q", [a, b, c], top_n=2)` | returns the local reranker's result for the same input; exactly 2 `POST /rerank` sent | unit |
| AC-21 | for each text `t<i>` the `/embed` stub returns 384 copies of float(i) | `embed_texts` with 600 texts | 3 requests of 256, 256 and 88 texts; shape (600, 384), float32; row i equals [i] × 384 | unit |
| AC-22 | batch 2 of 600 texts gets 503 twice | `embed_texts` with 600 texts | shape (600, 384); every row equals local `embed_texts` output for that text | unit |
| AC-23 | models URL set (stub) | an emerging-themes clustering run on the fixture tags | ≥ 1 `POST /embed` sent | unit |
| AC-24 | the compute service app | `POST /parse` with object `../etc/passwd`, or any object not matching `^parse/[0-9a-f]{64}\.pdf$` | 422 | unit |
| AC-25 | the compute service app | `POST /parse` with the header absent, or different from the service's `parser_version()` | 409; body contains the service's version and the received one (or `missing`) | unit |
| AC-26 | the compute service app; matching header; `parse/<sha>.pdf` exists in the mount | `POST /parse` | 200; body has exactly the keys `text`, `page_breaks`, `table_spans` | unit |
| AC-27 | `pip install -e backend` on this branch | `python -c "from arp.ingestion.local_files import parser_version as v; print(v())"` | prints `logic=3\|docling=2.140.0\|docling-core=2.101.1\|trafilatura=2.3.1\|openpyxl=3.1.5` | unit |
| AC-28 | this branch | `cd backend && python3 -m pytest` | exits 0; `git diff origin/main -- backend/tests` shows no modified or deleted lines in existing files | unit |
| AC-29 | a fresh project; only `scripts/gcp/setup_compute.sh <id>` was run and its printed lines added to `backend/.env` | `arp compute check` | prints exactly `parse OK`, `rerank OK`, `embed OK`; exits 0 | evaluator |
| AC-30 | `ARP_COMPUTE_PARSE_URL` points at a nonexistent `run.app` URL | `arp compute check` | a line starting `parse FAIL: `, then `rerank OK` and `embed OK`; exits 1 | evaluator |
| AC-31 | setup done | `setup_compute.sh` run again | exits 0; `gcloud iam service-accounts keys list --iam-account arp-client@<id>.iam.gserviceaccount.com` count unchanged | evaluator |
| AC-32 | setup done | `gcloud storage buckets describe gs://<id>-arp-compute --format='json(lifecycle_config)'` | exactly one rule: action Delete, condition age 1 | evaluator |
| AC-33 | the deployed services | an unauthenticated `POST` to each service URL | HTTP 403 | evaluator |
| AC-34 | both services at 0 instances, idle ≥ 20 min, no other traffic | 5 unauthenticated requests | `run.googleapis.com/container/instance_count` stays 0 over the next 5 min | evaluator |
| AC-35 | the deployed services idle ≥ 20 min | the first rerank call from the backend | the cloud result is returned within 120 s; no fallback WARNING logged | evaluator |
| AC-36 | the deployed services | `gcloud run services describe` | min instances 0; max instances 2 (`arp-parse`) and 1 (`arp-models`); 1 `nvidia-l4` GPU each | evaluator |
| AC-37 | GCP repo variables set | a push to `main` touching `backend/pyproject.toml` | each service's latest ready revision runs image tag = that commit's first 7 SHA characters | evaluator |
| AC-38 | GCP repo variables unset | the deploy workflow runs | the log has a `::warning::` line; the job concludes `success` | evaluator |

Must not change: AC-1, AC-2, AC-14, AC-15, AC-19, AC-28.
