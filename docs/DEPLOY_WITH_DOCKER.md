# Deploy ARP with Docker

Every push to `main` publishes ready-made images to GitHub Container Registry
(`.github/workflows/images.yml`), each for Intel/AMD (`linux/amd64`) and ARM (`linux/arm64`) servers:

| Image | What it is |
|---|---|
| `ghcr.io/kutschersteffen-cmd/arp-backend` | the API and the `arp` CLI |
| `ghcr.io/kutschersteffen-cmd/arp-frontend` | the web app (nginx), forwarding `/api/` to the backend |
| `ghcr.io/kutschersteffen-cmd/arp-compute` | optional model service: rerank, embeddings, spans, tags, classify (and parse, which needs a `/gcs` mount and `ARP_COMPUTE_BUCKET`) |

A server pulls them and runs; it needs no checkout of this repository and builds nothing.

## Pull and run

On any Linux server with Docker and Docker Compose 2.24 or newer (for the optional `backend/.env` entry), create a directory with exactly these files:

- `docker-compose.yml`, copied from the root of this repository;
- `backend/.env`, copied from [`backend/.env.example`](../backend/.env.example) and filled in (at least
  `ARP_ANTHROPIC_API_KEY`; compose sets the database address itself);
- an empty `config/` directory (`mkdir config`; it is mounted for sign-in users, README "Sign-in").

Then:

```bash
docker compose pull backend frontend
docker compose up -d postgres
docker compose run --rm backend arp db init-postgres   # once, before the backend first starts
docker compose up -d backend frontend
```

The backend refuses to start on an uninitialised database, so run `arp db init-postgres` once before the
first `up`, and again after each upgrade. Open `http://localhost:5173/` on the server (see
[Reaching ARP from another machine](#reaching-arp-from-another-machine)). `docker compose up` uses the pulled
images and builds nothing. Upgrade with the same four commands.

## Choosing a tag

Compose pulls the tag in `ARP_IMAGE_TAG` (default `latest`), for example
`ARP_IMAGE_TAG=sha-1a2b3c4 docker compose pull backend frontend`, or put `ARP_IMAGE_TAG=...` in a `.env` file
next to `docker-compose.yml`.

| Tag | Means |
|---|---|
| `latest` | the newest commit on `main` (a release does not move it) |
| `main` | the same as `latest` |
| `sha-<7 chars>` | one exact commit on `main`, for example `sha-1a2b3c4`: pin a deployment to it, roll back by changing it |
| `<semver>` | a release, for example `1.2.3` from the git tag `v1.2.3` |
| `pr-<n>` | the images built for pull request `<n>`, to try a change before it merges |
| `…-cuda` | `arp-compute` only: the NVIDIA GPU build of any tag above, for example `latest-cuda` (see [GPU](#gpu)) |

To cut a release, tag a commit on `main` and push the tag:

```bash
git tag v1.2.3 && git push origin v1.2.3
```

The workflow then publishes `1.2.3` for all three images (and `1.2.3-cuda` for `arp-compute`).

## GPU

ARP runs fully on CPU. Only the optional compute service uses a GPU. Start it with
`docker compose --profile compute up -d compute` and call it directly over HTTP (port 8080 on the server,
`http://compute:8080` from other containers). The backend cannot use a self-hosted compute container yet:
its compute client also expects Google credentials (`ARP_COMPUTE_CREDENTIALS_FILE`), so setting
`ARP_COMPUTE_MODELS_URL` alone changes nothing and the backend keeps ranking and embedding in-process.

`ARP_COMPUTE_DEVICE` (set in `docker-compose.yml`) picks where its models load:

- `auto` (default): the GPU when one is visible, else the CPU;
- `cpu`: always the CPU;
- `cuda`: GPU required; without a visible GPU every model endpoint answers 503.

Which image:

- **Any server, any CPU, ARM included:** the default `arp-compute:<tag>`. It runs on the CPU; it has no GPU
  libraries.
- **Intel/AMD server with an NVIDIA GPU:** the `-cuda` image. Install the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  on the server, set `ARP_COMPUTE_IMAGE_TAG=<tag>-cuda` (for example `latest-cuda`; without it compute uses
  `ARP_IMAGE_TAG`) and uncomment the `deploy.resources.reservations.devices` block under `compute` in
  `docker-compose.yml`. The `-cuda` image still starts on a host without a GPU and then uses the CPU.
- **ARM servers** have no `-cuda` image (no GPU onnxruntime for ARM): use the default image.

To use the GPU with `auto`, run the `-cuda` image. The default image has CPU-only torch and onnxruntime: it
never sees the GPU, so `auto` runs it on the CPU, and `cuda` makes every model endpoint answer 503. The same
goes for any other install that pairs a GPU torch with the plain (CPU-only) onnxruntime, such as a
`pip install ".[models]"` on a GPU machine: `auto` then picks the GPU, and `/embed` and `/rerank` answer 503
(`model not on the GPU`) because their onnxruntime cannot use it. Use the `-cuda` image, or set
`ARP_COMPUTE_DEVICE: cpu` there.

The compute service has no sign-in of its own. Keep it on the compose network, with its port bound to
`127.0.0.1` as `docker-compose.yml` has it, and never publish it to another network.

## Reaching ARP from another machine

Every port in `docker-compose.yml` is bound to `127.0.0.1` on purpose. The app runs in dev sign-in mode: every
request that reaches it through those ports is signed in as the dev approver, so publishing them on the
network would make every machine on it an approver. Two ways in:

- **SSH tunnel** (nothing changes on the server):
  `ssh -L 5173:127.0.0.1:5173 user@server`, then open `http://localhost:5173/` on your own machine.
- **TLS and real sign-in**: put a TLS proxy in front of port 5173 and switch the backend to real sign-in
  (README "Sign-in": `config/users.json`, `ARP_AUTH_MODE=local`, drop `ARP_DEV_TRUSTED_NETWORKS`) before you
  open any port beyond loopback.

The frontend forwards `/api/` only for the host names in `ARP_PUBLIC_HOSTS` (space-separated, default
`localhost 127.0.0.1`); any other name gets 421. Add each new host name you reach ARP under, for example
`ARP_PUBLIC_HOSTS: "localhost 127.0.0.1 arp.example.com"` under `frontend` → `environment` in
`docker-compose.yml`.

## Building offline

Pulling published images needs no build. Building them yourself (`docker compose up --build`, or
`docker build`) is different: `backend/Dockerfile` and `frontend/Dockerfile` start with the line
`# syntax=docker/dockerfile:1`, which makes BuildKit fetch its Dockerfile frontend, the `docker/dockerfile`
image, from Docker Hub at build time. A build without internet therefore needs that line removed, or the
`docker/dockerfile` image mirrored into a registry the build machine can reach. The builds also download
packages (pip, npm, apt, models), which need a reachable mirror too.

## Private images

The images are public, so `docker compose pull` needs no sign-in. If the packages are ever made private, sign
in on each server first:

```bash
docker login ghcr.io -u <user>
```

with a GitHub personal access token (classic) that has the `read:packages` scope as the password.
