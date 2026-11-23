# Portable Docker images

Status: **draft, waiting for the owner's approval**
Slug: `portable-docker-images`
Risk: this spec PR is `risk:low`. The build is `risk:high` (a new `.github/workflows/` file, and
`backend/arp/compute/**` and `backend/Dockerfile.compute`, all in the steward table's `risk:high` row): the
owner merges every build PR on GitHub.
Size: M (3 PRs, see `## Slices`)

## Decisions for the owner

1. **Images are public on GitHub Container Registry** (default chosen by the dispatcher). The repository is
   public, so any server can `docker pull` without signing in. A new ghcr package starts private, so after
   the first run of the new workflow pushes, the owner sets each of the three packages to public once
   (github.com, Packages, `arp-backend` / `arp-frontend` / `arp-compute`, Package settings, Change
   visibility). The alternative is private images: every server then needs `docker login ghcr.io`.
2. **The GPU build of the compute image is an extra, opt-in tag** (`…-cuda`, Intel/AMD only), not the
   default. The default compute image runs on any CPU and uses a GPU only if one is visible.

## Why

Steffen wants to deploy ARP soon with Docker on a server whose CPU type (Intel/AMD or ARM) and GPU he does
not know yet. Today:

- No image is published anywhere: every machine must clone the repo and build.
- Images are built for the CPU type of the machine that builds them, so an image built on an ARM laptop does
  not run on an Intel server, and the other way round.
- `backend/Dockerfile.compute` only works with an NVIDIA GPU: it installs `onnxruntime-gpu` and
  `fastembed-gpu`, loads models with `cuda=True` / `.to("cuda")` / `device="cuda"`, and
  `arp/compute/server.py` answers 503 (`model not on the GPU`, `CUDA not available`) on a CPU-only machine.
  `arp compute check` reports `parse FAIL: the service reports no GPU` whenever `/healthz` `cuda` is false.
- The frontend image bakes the API address in at build time (`VITE_API_BASE`, default
  `http://localhost:8000`), so a built image only works where the API is at exactly that address.

The backend image already runs fully on CPU: the compute service is optional, and without
`compute_parse_url` / `compute_models_url` the backend parses and ranks in-process.

## What the user can do afterwards that they cannot do today

- On any Linux server with Docker, Intel/AMD or ARM, with or without a GPU: copy `docker-compose.yml` and a
  `backend/.env`, run `docker compose pull backend frontend && docker compose up -d backend frontend`, and
  have ARP running without cloning the repo or building anything.
- Run the compute service (rerank, embeddings, spans, tags, classify, parse) on a server with no GPU, and on
  an NVIDIA server get the GPU speed-up by pulling the `-cuda` tag.
- Pin a deployment to an exact commit (`sha-<7 chars>`) or a release (`1.2.3`) and roll back by changing
  one tag.

Next step up (not in this spec): signed images with SBOMs, and a one-command install that also sets up TLS
and real sign-in. That needs a decision on the target host and on auth, which Steffen does not have yet.

## Change

### 1. Compute service runs on CPU, GPU optional (`backend/arp/compute/server.py`, `backend/arp/cli/compute.py`, `backend/Dockerfile.compute`)

- New env `ARP_COMPUTE_DEVICE`: `auto` (default, also for an unknown value), `cpu` or `cuda`. The server
  reads it on every request, not once at import. `auto` uses CUDA when `torch.cuda.is_available()` is true,
  else CPU; `cpu` always uses CPU.
- Every model the server loads goes to that device: fastembed embed / rerank / late-interaction (`cuda=`
  follows the device), bge-m3 (`float16` on CUDA, `float32` on CPU), GLiNER spans, NLI classify, taggers
  and docling parse. On CPU no model endpoint answers 503 for lack of a GPU.
- `cuda` means "GPU required": if no GPU is visible, every model endpoint (`/parse`, `/rerank`, `/embed`,
  `/classify`, `/spans`, `/tag`) answers **503** with JSON `detail` exactly
  `ARP_COMPUTE_DEVICE=cuda but no GPU is visible`, before loading any model. This check comes first, before
  the existing `X-ARP-Model` / `X-ARP-Parser-Version` 409 checks and the missing-object 404.
- `GET /healthz` returns `{"parser_version": …, "cuda": <torch.cuda.is_available()>, "device": "cpu"|"cuda"}`.
  `cuda` keeps today's meaning (is a GPU visible) whatever `ARP_COMPUTE_DEVICE` says; `device` is where
  models load.
- `arp compute check`: the parse line no longer fails because `/healthz` `cuda` is false. Each line that
  passes ends with ` (device=<device from /healthz>)`, for example `embed OK (device=cpu)`.
- `backend/Dockerfile.compute` gets a build arg `VARIANT` = `cpu` (default) or `cuda`.
  - `cpu`: CPU-only `torch` (PyTorch CPU wheel index, version string ends in `+cpu` on amd64), plain
    `onnxruntime` and `fastembed`, no `onnxruntime-gpu`; builds for `linux/amd64` and `linux/arm64`.
  - `cuda`: today's GPU install (`torch==2.14.1`, `onnxruntime-gpu==1.31.0`, `fastembed-gpu`); `linux/amd64`
    only (no `onnxruntime-gpu` wheels for ARM). It leaves `ARP_COMPUTE_DEVICE` at `auto`, so the same image
    still starts and serves on a host whose GPU is missing.
  - Both keep baking the models in, so a cold start downloads nothing.

### 2. Frontend image works behind any address (`frontend/Dockerfile`, `frontend/nginx.conf`)

- `frontend/Dockerfile`'s `VITE_API_BASE` build arg defaults to the empty string, so the built page calls
  the API on its own origin (`/api/...`). `frontend/src/api/client.ts` is unchanged: with the variable unset
  (as in `npm run dev`) it still uses `http://localhost:8000`.
- nginx in the image forwards `/api/` to `ARP_BACKEND_URL` (env, default `http://backend:8000`), filled in at
  container start through nginx's `/etc/nginx/templates/*.template`. The upstream is resolved per request
  (`resolver` from the container's `/etc/resolv.conf` plus a variable `proxy_pass`), so nginx starts and
  serves `/` even when the backend host does not resolve yet; `/api/` then answers 502.
- Proxied responses are not buffered (`proxy_buffering off`), so streamed answers arrive as produced.
- Toward the backend, the proxy sends `Host: localhost` (accepted by the backend's default
  `ARP_TRUSTED_HOSTS` wherever the server lives) and the original host in `X-Forwarded-Host`.
- Origin: when the request's `Origin` equals the page's own origin (`$scheme://$http_host`), the proxy
  sends `Origin: http://localhost:5173` (in the backend's default `ARP_ALLOWED_ORIGINS`), so dev sign-in
  works behind any address. Any other `Origin` is passed through unchanged, so a foreign site still gets no
  dev bypass (401). No `Origin` header stays absent.
- The cross-origin isolation headers stay on every page and asset response.

### 3. Build and publish workflow (`.github/workflows/images.yml`, new)

- Builds, with Docker Buildx, one multi-arch manifest (`linux/amd64` + `linux/arm64`) for each of:
  - `ghcr.io/kutschersteffen-cmd/arp-backend` from `backend/Dockerfile` (context: repo root)
  - `ghcr.io/kutschersteffen-cmd/arp-frontend` from `frontend/Dockerfile` (context: `frontend/`)
  - `ghcr.io/kutschersteffen-cmd/arp-compute` from `backend/Dockerfile.compute`, `VARIANT=cpu`
  and `ghcr.io/kutschersteffen-cmd/arp-compute` with `VARIANT=cuda`, `linux/amd64` only, under every tag
  below with `-cuda` appended.
- Each platform builds on a native runner: `ubuntu-latest` for amd64, `ubuntu-24.04-arm` for arm64 (free for
  public repositories); the per-platform digests are then merged into one manifest. No QEMU. Each build job
  has `timeout-minutes: 120`.
- Tags:
  - push to `main`: `main`, `latest`, `sha-<first 7 chars of the commit>`. `latest` always means the newest
    `main`.
  - pushed git tag `v<semver>`: `<semver>` without the `v` (for example `v1.2.3` gives `1.2.3`); `latest` is
    not moved by a release.
  - pull request from this repository: `pr-<number>`.
  - pull request from a fork: builds both platforms without pushing, runs no smoke step.
- `concurrency: images-${{ github.ref }}` with `cancel-in-progress: false`, so two quick pushes to `main`
  finish in order and `latest` ends on the newer commit.
- Triggers: push to `main`; push of tags `v*`; pull requests that change any `Dockerfile*`,
  `docker-compose.yml`, `frontend/nginx.conf`, `frontend/package*.json`, `backend/pyproject.toml`,
  `backend/arp/compute/**` or the workflow itself; `workflow_dispatch`.
- Logs in to ghcr with `GITHUB_TOKEN` (`permissions: contents: read, packages: write`); no other secret.
- After pushing, it prints `docker buildx imagetools inspect <image>:<tag>` for each pushed tag.
- Smoke step, after the push, per image and per platform, on that platform's native runner. It prints one
  line per check, exactly `smoke <name> <platform>: <check> ok` or
  `smoke <name> <platform>: <check> FAILED <detail>`, and the job fails on any `FAILED`. `<name>` is
  `arp-backend`, `arp-frontend`, `arp-compute` or `arp-compute-cuda`; `<platform>` is `linux/amd64` or
  `linux/arm64`. Checks, by name:
  - `arp-backend`: `api-health` (`GET /api/health` → 200).
  - `arp-frontend`, run on a Docker network with the `arp-backend` image of the same tag as host `backend`
    (that backend container started with `ARP_DEV_TRUSTED_NETWORKS` set to the network's subnet, as compose
    does) and no `ARP_BACKEND_URL` set:
    `root` (`GET /` → 200), `coop` (`/` has `Cross-Origin-Opener-Policy: same-origin` and
    `Cross-Origin-Embedder-Policy: require-corp`), `api-proxy` (`GET /api/health` on the frontend's port →
    200 with `"status": "ok"`), `api-proxy-other-host` (same request with `Host: arp.example.test` and
    `Origin: http://arp.example.test` → 200 from `/api/me`), `foreign-origin` (`GET /api/me` with
    `Origin: http://evil.example.test` → 401).
  - `arp-compute`: `healthz-device-cpu` (`GET /healthz` → 200 with `"device": "cpu"`), `embed`
    (`POST /embed` `{"texts": ["hello"]}` with header `X-ARP-Model: <EMBED_MODEL_NAME>` → 200, `vectors` has 1 item), `no-onnxruntime-gpu`
    (`pip show onnxruntime-gpu` in the container exits non-zero), `torch-cpu` (amd64 only: `torch.__version__`
    ends in `+cpu`).
  - `arp-compute-cuda` (`linux/amd64` only; the runner has no GPU): `healthz-device-cpu`.
- It is a new file and does not reuse `deploy-compute.yml`, which the GCP-removal change deletes.

### 4. Compose can run the published images (`docker-compose.yml`)

- `backend` and `frontend` get `image: ghcr.io/kutschersteffen-cmd/arp-<name>:${ARP_IMAGE_TAG:-latest}`
  next to their existing `build:`. `docker compose pull` then fetches the published image;
  `docker compose up --build` still builds locally as today.
- The `frontend` service's `build.args.VITE_API_BASE` becomes `""`, so a local build behaves like the
  published image (same-origin API through nginx).
- New service `compute`, in compose profile `compute` only (a plain `docker compose up` does not start it),
  `image: ghcr.io/kutschersteffen-cmd/arp-compute:${ARP_COMPUTE_IMAGE_TAG:-${ARP_IMAGE_TAG:-latest}}`,
  `build` with `VARIANT: cpu`, port `127.0.0.1:8080:8080`, `ARP_COMPUTE_DEVICE: auto`. A commented-out
  `deploy.resources.reservations.devices` GPU block shows the `-cuda` setup.
- `backend`'s `env_file` entry becomes `- path: backend/.env` with `required: false`, so `docker compose
  config` works on a fresh checkout.
- With an image already pulled, `docker compose up -d backend frontend` uses it and does not build, so a
  server directory needs no build contexts. A server needs exactly: `docker-compose.yml`, `backend/.env`
  and an empty `config/` directory (for the `./config` mount).
- Every published port stays bound to `127.0.0.1` (the dev sign-in rule in the file's comments stays).

### 5. Docs (`docs/DEPLOY_WITH_DOCKER.md`, new; README "Setup" links to it)

With these `##` headings, in this order:

- `Pull and run`: the files a server needs (`docker-compose.yml`, `backend/.env` from
  `backend/.env.example`, an empty `config/`), `docker compose pull backend frontend`, `docker compose up -d postgres
  backend frontend`, `docker compose exec backend arp db init-postgres`.
- `Choosing a tag`: `latest`, `main`, `sha-…`, `<semver>`, `pr-<n>`, `-cuda`; how to cut a release
  (`git tag v1.2.3 && git push origin v1.2.3`).
- `GPU`: what `ARP_COMPUTE_DEVICE` does; the NVIDIA Container Toolkit is needed for `-cuda`; ARM servers use
  the CPU image; `ARP_COMPUTE_IMAGE_TAG`.
- `Reaching ARP from another machine`: ports are loopback-only on purpose; use an SSH tunnel, or put TLS in
  front and switch to real sign-in (README "Sign-in").
- `Building offline`: `# syntax=docker/dockerfile:1` makes BuildKit fetch its Dockerfile frontend from Docker
  Hub when building, so building (not pulling) without internet needs that line removed or the
  `docker/dockerfile` image mirrored. Pulling published images needs no build.
- `Private images`: `docker login ghcr.io -u <user>` with a token that has `read:packages`, if the packages
  are ever made private.

## Defaults chosen by the dispatcher (no owner question needed)

- Superset (`superset/Dockerfile`) is not published: it is optional BI on the stock `apache/superset` image,
  and compose keeps building it locally.
- `sandbox/` has no Dockerfile today and is not part of this spec.
- Image names use the `arp-` prefix under the owner's account.
- Old `pr-<n>` tags are not cleaned up automatically.
- Fork PRs are not an acceptance row: nothing in the factory can open one. The owner can open one by hand
  to check the "no push" rule.

## Non-goals

- Deploying anywhere (no host, no Kubernetes, no GCP: see `remove-gcp-deploy`).
- TLS, real sign-in setup, or opening ports beyond loopback.
- Changing how `npm run dev` reaches the API.
- Non-NVIDIA accelerators (Apple, AMD ROCm).

## Coordination

The GCP-removal spec (`docs/superpowers/specs/2026-11-23-remove-gcp-deploy.md`, spec PR #679, slug
`remove-gcp-deploy`) changes `backend/Dockerfile.compute`, `backend/arp/compute/**` comments and deletes
`.github/workflows/deploy-compute.yml`. Slice 2 starts only after the implementing PR of `remove-gcp-deploy`
has merged (its PR description has `Spec: remove-gcp-deploy`), and branches from that `main`.

## Slices

1. **Frontend same-origin image** (`frontend/Dockerfile`, `frontend/nginx.conf`, compose `frontend` build
   arg): AC-5, AC-6, AC-8, AC-16, AC-17, AC-23.
2. **Compute on CPU** (`backend/arp/compute/server.py`, `backend/arp/cli/compute.py`,
   `backend/Dockerfile.compute`): AC-1, AC-2, AC-3, AC-4, AC-7, AC-9, AC-24, AC-25, AC-30.
3. **Publish workflow, compose images, docs** (`.github/workflows/images.yml`, `docker-compose.yml`,
   `docs/DEPLOY_WITH_DOCKER.md`, README link): AC-10 to AC-15, AC-18 to AC-22, AC-26 to AC-29.

## Acceptance

Holdout rows run the compute app in-process: `fastapi.testclient.TestClient(arp.compute.server.app)` with
`torch.cuda.is_available` patched to return False (or True where the row says so) and `ARP_COMPUTE_DEVICE`
set in the environment before the request. They load no model.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | No GPU, `ARP_COMPUTE_DEVICE` unset | `GET /healthz` | 200; JSON `device` = `"cpu"`, `cuda` = `false`, `parser_version` a non-empty string | holdout |
| AC-2 | No GPU, `ARP_COMPUTE_DEVICE=cuda` | `POST /embed` with `{"texts": ["hello"]}` and no `X-ARP-Model` header | 503; JSON `detail` = `ARP_COMPUTE_DEVICE=cuda but no GPU is visible` | holdout |
| AC-3 | No GPU, `ARP_COMPUTE_DEVICE=cuda` | `POST /rerank` with `{"query": "q", "texts": ["a"]}` and header `X-ARP-Model` = `arp.compute.client.CLOUD_RERANK_MODEL` | 503; JSON `detail` = `ARP_COMPUTE_DEVICE=cuda but no GPU is visible` | holdout |
| AC-4 | GPU patched as available, `ARP_COMPUTE_DEVICE=cpu` | `GET /healthz` | 200; JSON `device` = `"cpu"`, `cuda` = `true` | holdout |
| AC-5 | `frontend/` with `VITE_API_BASE` unset | Vitest reads `API_BASE` from `src/api/client.ts` | it equals `http://localhost:8000` (unchanged) | unit |
| AC-6 | `frontend/` built with `VITE_API_BASE=""` | Vitest reads `API_BASE` | it equals `""` | unit |
| AC-7 | No GPU, `ARP_COMPUTE_DEVICE` unset, the embed model replaced by a stand-in returning one 384-float vector | `POST /embed` with `{"texts": ["hello"]}` and header `X-ARP-Model` = `EMBED_MODEL_NAME` | 200; JSON `vectors` is a list of 1 list of 384 floats | unit |
| AC-8 | The slice-1 frontend image built locally, run alone with `ARP_BACKEND_URL` unset (no host `backend`) | `curl -si` `/` and `/api/health`, output quoted in the builder's PR description | 200 for `/`, 502 for `/api/health` (nginx started without a backend) | evaluator |
| AC-9 | No GPU, `ARP_COMPUTE_DEVICE` unset, loaders for `/rerank`, `/spans`, `/tag`, `/classify` replaced by stand-ins | `POST` each endpoint with a valid body | each answers 200 (none 503); the stand-ins were asked for device `cpu`, and bge-m3's loader for dtype `float32` | unit |
| AC-10 | The slice-3 PR's `images.yml` run (tag `pr-<n>`) | read its log | `imagetools inspect` of `arp-backend:pr-<n>`, `arp-frontend:pr-<n>` and `arp-compute:pr-<n>` each lists `linux/amd64` and `linux/arm64` | evaluator |
| AC-11 | Same run | read its log | `imagetools inspect` of `arp-compute:pr-<n>-cuda` lists `linux/amd64` and no `linux/arm64` | evaluator |
| AC-12 | Same run | read its log | it has all 20 lines `smoke arp-backend <p>: api-health ok`, `smoke arp-frontend <p>: root ok` / `coop ok` / `api-proxy ok` / `api-proxy-other-host ok` / `foreign-origin ok`, `smoke arp-compute <p>: healthz-device-cpu ok` / `embed ok` / `no-onnxruntime-gpu ok` for `<p>` = `linux/amd64` and `linux/arm64`, plus `smoke arp-compute linux/amd64: torch-cpu ok` and `smoke arp-compute-cuda linux/amd64: healthz-device-cpu ok` | evaluator |
| AC-13 | Same run | read its log | no line contains `FAILED`; the `images.yml` check is green | evaluator |
| AC-14 | Same run | read the workflow file and log | the arm64 build jobs ran on `ubuntu-24.04-arm` and no step set up QEMU | evaluator |
| AC-15 | Slice 3 merged; the `images.yml` run on that `main` commit | read its log | it pushed tags `main`, `latest` and `sha-<7>` for all three images, and `-cuda` versions of each for `arp-compute` | evaluator |
| AC-16 | Must not change: the repo checked out, `backend/.env` filled, Docker available | `docker compose up -d --build backend frontend` | exits 0; `docker compose ps` shows `backend` and `frontend` running | evaluator |
| AC-17 | AC-16's stack, then `docker compose exec backend arp db init-postgres` | open `http://localhost:5173/` in a browser | the start page shows the workspace list, and every `/api/` request the page makes goes to `http://localhost:5173/api/...` (none to port 8000) with status 200 | evaluator |
| AC-18 | The repo checked out (no `backend/.env`) | `docker compose --profile compute config` | every published port in the output has `host_ip: 127.0.0.1` | holdout |
| AC-19 | The repo checked out (no `backend/.env`) | `docker compose config --services` | `compute` is not listed; with `--profile compute` it is | holdout |
| AC-20 | The repo checked out (no `backend/.env`), `ARP_IMAGE_TAG=1.2.3`, `ARP_COMPUTE_IMAGE_TAG` unset | `docker compose --profile compute config` | images `ghcr.io/kutschersteffen-cmd/arp-backend:1.2.3`, `arp-frontend:1.2.3`, `arp-compute:1.2.3` | holdout |
| AC-21 | The repo checked out (no `backend/.env`), `ARP_IMAGE_TAG=1.2.3`, `ARP_COMPUTE_IMAGE_TAG=1.2.3-cuda` | `docker compose --profile compute config` | backend and frontend images end in `:1.2.3`, compute's in `:1.2.3-cuda` | holdout |
| AC-22 | `docs/DEPLOY_WITH_DOCKER.md` on the PR head | read its `##` headings | exactly, in order: `Pull and run`, `Choosing a tag`, `GPU`, `Reaching ARP from another machine`, `Building offline`, `Private images` | holdout |
| AC-23 | The frontend image of slice 1, built locally by the builder, on a Docker network with the backend image (started with `ARP_DEV_TRUSTED_NETWORKS` = that network's subnet) as host `backend` | the builder's PR description | it quotes the output of `curl -si` for `/`, `/api/health` and `/api/me` with `Host: arp.example.test` / `Origin: http://arp.example.test`, and `/api/me` with `Origin: http://evil.example.test`: 200, 200, 200, 401 | evaluator |
| AC-24 | A compute app with no GPU, `ARP_COMPUTE_DEVICE` unset, `ARP_COMPUTE_MODELS_URL` pointing at it, embed and rerank stand-ins | `arp compute check` | the `rerank` and `embed` lines read `rerank OK (device=cpu)` and `embed OK (device=cpu)`; no line says `no GPU` | unit |
| AC-25 | `backend/Dockerfile.compute` | read it | it declares `ARG VARIANT=cpu`, and the `cuda` path installs `onnxruntime-gpu==1.31.0` and `torch==2.14.1` | unit |
| AC-26 | README on the PR head | read the "Setup" section | it links to `docs/DEPLOY_WITH_DOCKER.md` | holdout |
| AC-27 | `docs/DEPLOY_WITH_DOCKER.md` | read `Building offline` | it names the line `# syntax=docker/dockerfile:1` and says a build without internet needs it removed or the `docker/dockerfile` image mirrored | evaluator |
| AC-28 | The three packages set to public (Decision 1), Docker logged out of ghcr.io, a directory with only `docker-compose.yml`, `backend/.env` (from `.env.example`) and an empty `config/` | `ARP_IMAGE_TAG=main docker compose pull backend frontend` | exits 0 | evaluator |
| AC-29 | AC-28's images, `docker compose up -d postgres backend frontend`, then `docker compose exec backend arp db init-postgres` | `GET http://localhost:8000/api/health` and open `http://localhost:5173/` | 200 for `/api/health`; on the page, every `/api/` request goes to `http://localhost:5173/api/...` with status 200, and no image was built (`docker compose up` printed no `Building` line) | evaluator |
| AC-30 | No GPU, `ARP_COMPUTE_DEVICE=cuda` | `POST /parse` with header `X-ARP-Parser-Version` = `parser_version()` and `{"object": "parse/<64 zeros>.pdf"}` | 503; JSON `detail` = `ARP_COMPUTE_DEVICE=cuda but no GPU is visible` | holdout |

AC-15, AC-28 and AC-29 can only be checked after slice 3 merges (and, for AC-28, after the owner made the
packages public). The slice-3 PR owes them as a follow-up, which the evaluator checks on `main` and posts
on the merged PR; they are not merge gates for that PR.

Must not change: `npm run dev` reaching `http://localhost:8000` (AC-5); local `docker compose up --build`
(AC-16, AC-17); all compose ports bound to `127.0.0.1` (AC-18); `/healthz`'s `parser_version` and `cuda`
keys and the meaning of `cuda` (AC-1, AC-4); a foreign `Origin` gets no dev bypass (AC-12 `foreign-origin`).
