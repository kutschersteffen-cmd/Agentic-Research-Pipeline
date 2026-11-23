# Remove the GCP deploy path

Status: **approved by the owner on 23 Nov 2026** (button in the dispatcher thread, after three spec-critic rounds)
Slug: `remove-gcp-deploy`
Risk: this spec PR is `risk:low`. The build is 1 PR, `risk:high` (it deletes a workflow under `.github/workflows/`
and edits `.claude/skills/steward/SKILL.md`), so the owner merges it on GitHub.
Size: S

## Decisions for the owner

1. **Only the GCP-specific deploy path goes.** The deploy workflow, the Workload Identity and service-account setup,
   Cloud Build and the gcloud deploy script are removed. Every Dockerfile and `docker-compose.yml` stays, because the
   owner may deploy with Docker images on another system (owner, 23 Nov 2026); `backend/Dockerfile.compute` keeps
   building the same image, only its comments stop pointing at the deleted scripts. The compute client and service code in `backend/arp/compute/` stay as they are: with no
   `ARP_COMPUTE_*` URLs set (today's state) the backend already parses, reranks and embeds locally, and that code
   is woven into ingestion, retrieval, preflight and the `arp compute` CLI. Removing it is a separate, larger
   change the owner can ask for later.
2. **Vertex AI stays.** `ARP_GEMINI_USE_VERTEX`, `ARP_GCP_PROJECT`, `ARP_GCP_LOCATION` and
   `scripts/launch_jupyter.sh` serve the owner's hand-started gcloud sandbox and are not part of the deploy path.
3. **The `arp-gcp` repository is not touched.**
4. **GCP resources are not touched by any agent.** Deleting code does not delete what `setup_compute.sh` may have
   created; the PR description lists those resources for the owner to delete by hand (see "Owner's manual
   clean-up").

## Why

The owner will not deploy ARP to GCP for now. The deploy workflow is dead weight with a security cost: the
Workload Identity binding in `setup_compute.sh` lets any branch of the repo act as `arp-deployer`, which holds
project-wide `roles/run.admin` and `roles/storage.admin` (antigravity patch review, Part C item 12). It also makes
eight ordinary code paths (ingestion, rerank, embeddings, `pyproject.toml` …) `risk:high` only because a merge
there could trigger a deploy, so the factory cannot auto-merge routine changes to them.

## What the user can do afterwards that they cannot do today

- Merge a routine change to ingestion, rerank, embeddings, `schemas/common.py` or `pyproject.toml` through the
  normal factory auto-merge (`risk:low`/`risk:normal`), since those paths no longer trigger a deploy.
- Read a README and a steward table that no longer point at a GCP setup that does not exist.

## Change

Delete:

- `.github/workflows/deploy-compute.yml`
- `scripts/gcp/` (`setup_compute.sh`, `deploy_compute.sh`, `cloudbuild.yaml`), the whole folder
- `backend/tests/test_deploy_compute_workflow.py` (it only tests the deleted workflow; rows AC-38 and AC-49 of the
  cloud-compute spec, superseded below)

Edit:

- `README.md`: remove the `## Cloud compute (optional)` section (heading, text and code block) entirely. Leave
  the `CORPORATE_READINESS_PLAN.md` line in the docs table as it is.
- `.claude/skills/steward/SKILL.md`, `risk:high` row: replace `anything that triggers a deploy (the
  `deploy-compute.yml` paths: … `scripts/gcp/**`)` with `anything that triggers a deploy`. Everything else in
  the row stays word for word.
- `backend/arp/config.py` line 231 comment: drop `, set up by scripts/gcp/setup_compute.sh`.
- `backend/Dockerfile.compute`: replace lines 1 and 2, and only those, with exactly these two lines:

  ```
  # A GPU image for arp/compute/server.py (the arp-parse and arp-models services), listening on $PORT
  # (default 8080). It installs backend/ from the same pyproject.toml as a local install,
  ```

  Every other line, including the comments that mention Cloud Run's GPU driver (lines 4 and 18), stays byte for
  byte.
- `backend/arp/compute/server.py` docstring: keep it, except any mention of `deploy_compute.sh` or `scripts/gcp`
  (there is none today; nothing to do unless that changes).
- `docs/superpowers/specs/2026-10-17-cloud-compute-design.md`: retire the superseded rows (below) the way
  `2026-10-18-company-site-and-report-identification-design.md` line 308 does:
  `| ~~AC-n~~ | ~~<Given>~~ | ~~<When>~~ | Superseded by remove-gcp-deploy: no GCP deployment. Was: <old Then> | <type> |`.
  Change nothing else in it.

Keep (must not change): `backend/arp/compute/**`, the `arp compute` CLI, every `ARP_COMPUTE_*` and Vertex setting
in `backend/arp/config.py`, `backend/.env.example`, `scripts/launch_jupyter.sh`, `docker-compose.yml`,
`backend/Dockerfile`, `frontend/Dockerfile`, the non-comment lines of `backend/Dockerfile.compute`, the `backend/.gcp/` lines in `.gitignore` and `.dockerignore` (they keep any client key
already on a machine out of git and out of images), `google-auth` in `backend/pyproject.toml`.

Historical documents are left as they are: the other files in `docs/superpowers/specs/` and
`docs/superpowers/plans/`, `docs/FACTORY_PLAYBOOK_GAP_REVIEW.md`, `docs/FACTORY_RETRO_LOG.md`, and `openwiki/`
(regenerated by `/context-refresh`, never edited by hand).

## Supersedes

| Spec | Rows | Why |
|---|---|---|
| `cloud-compute-design` (`2026-10-17-cloud-compute-design.md`) | AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-44 (`evaluator`) | they need services deployed by `setup_compute.sh`, which is deleted |
| `cloud-compute-design` | AC-38, AC-49 (`unit`) | they test `deploy-compute.yml`, which is deleted; their test file is deleted with it |

No `holdout` test covers these rows (none in `regression/` or `specs/` names `deploy-compute`, `scripts/gcp` or
`Dockerfile.compute`), so the holdout repo needs no retirement.

## Acceptance

All rows run against a checkout of the PR head. "Tracked files" means the output of `git ls-files`.
"Historical paths" means files under `docs/superpowers/specs/`, `docs/superpowers/plans/` or `openwiki/`, and the
files `docs/FACTORY_PLAYBOOK_GAP_REVIEW.md` and `docs/FACTORY_RETRO_LOG.md`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | the PR checkout | tracked files are listed | no tracked file has the path `.github/workflows/deploy-compute.yml` | holdout |
| AC-2 | the PR checkout | every tracked file under `.github/workflows/` is read | none contains the text `google-github-actions/` | holdout |
| AC-3 | the PR checkout | every tracked file under `.github/workflows/` is read | none contains the text `workload_identity_provider` | holdout |
| AC-4 | the PR checkout | tracked files are listed | no tracked file path starts with `scripts/gcp/` | holdout |
| ~~AC-5~~ | | | ~~no tracked file has the path `backend/Dockerfile.compute`~~ retired before approval: the owner keeps every Dockerfile (23 Nov 2026) | |
| AC-6 | the PR checkout | every tracked file that is not under a historical path is read | none contains any of the texts `scripts/gcp`, `setup_compute`, `deploy_compute`, `deploy-compute`, `cloudbuild` | holdout |
| AC-7 | the PR checkout | `README.md` is read | no line starts with `## Cloud compute` | holdout |
| AC-8 | the PR checkout | the line of `.claude/skills/steward/SKILL.md` whose first table cell is `` `risk:high` `` is read | it equals exactly the line shown under "Steward row after the change" below | holdout |
| AC-9 | the PR checkout | the same `risk:high` line is read | it contains none of `` `backend/arp/ingestion/**` ``, `` `backend/arp/retrieval/rerank.py` ``, `` `backend/pyproject.toml` `` | holdout |
| AC-10 | the PR checkout | tracked files are listed | `backend/Dockerfile`, `backend/Dockerfile.compute`, `frontend/Dockerfile`, `docker-compose.yml`, `scripts/launch_jupyter.sh` and `backend/arp/compute/client.py` are all tracked | holdout |
| AC-11 | the PR checkout | `docker-compose.yml` is parsed as YAML | the keys of `services` are exactly `backend`, `frontend`, `postgres`, `neo4j`, `opensearch`, `opensearch-dashboards`, `minio`, `superset` | holdout |
| AC-12 | the PR checkout | `.gitignore` and `.dockerignore` are read | each has a line that is exactly `backend/.gcp/` | holdout |
| AC-13 | backend installed from the PR checkout; `ARP_GEMINI_USE_VERTEX`, `ARP_GEMINI_API_KEY`, `ARP_GCP_PROJECT`, `ARP_GCP_LOCATION`, `ARP_STANDINS_DIR` and every `ARP_COMPUTE_*` env var unset; settings built with `_env_file=None` | `arp.config.Settings(_env_file=None, gemini_use_vertex=True, gcp_project=None)` is built | it raises an error whose message contains `ARP_GEMINI_USE_VERTEX is true but ARP_GCP_PROJECT is not set.` | holdout |
| AC-14 | as AC-13 | `arp.config.Settings(_env_file=None, gemini_use_vertex=True, gcp_project="p")` is built | no error; `.gcp_project == "p"` and `.gcp_location == "global"` | holdout |
| AC-15 | backend installed from the PR checkout | `arp compute check --help` is run | exit code 0 | holdout |
| AC-16 | as AC-13 | `arp.config.Settings(_env_file=None)` is built | it has attributes `compute_parse_url`, `compute_models_url`, `compute_bucket` and `compute_credentials_file`, each `None` | holdout |
| AC-17 | the PR checkout | `backend/pyproject.toml` is parsed as TOML | `project.dependencies` has an entry starting `google-auth` | holdout |
| AC-18 | the PR checkout | tracked files are listed | `backend/arp/compute/server.py` and `backend/.env.example` are both tracked | holdout |
| AC-21 | the PR checkout | `backend/.env.example` is read | it has a line that is exactly `# ARP_GEMINI_USE_VERTEX=true` | holdout |
| AC-19 | the PR checkout | `README.md` is read | it has a line containing `CORPORATE_READINESS_PLAN.md` | holdout |
| AC-20 | the PR checkout and `main` at the PR's merge base | `docs/superpowers/specs/2026-10-17-cloud-compute-design.md` is compared | each line for AC-29 to AC-38, AC-44 and AC-49 starts with `\| ~~AC-n~~ \|` (n its number; a pipe, a space, the struck ID, a space, a pipe) and contains `Superseded by remove-gcp-deploy`; every other line equals the merge base's (one-time diff check, see below) | unit |
| AC-22 | the PR checkout and `main` at the PR's merge base | `backend/Dockerfile.compute` is compared | lines 1 and 2 equal the two lines given under Change; every other line equals the merge base's, same count and order (one-time diff check) | unit |
| AC-23 | the PR checkout and `main` at the PR's merge base | `backend/Dockerfile`, `frontend/Dockerfile` and `docker-compose.yml` are compared | each equals the merge base's file byte for byte; `git diff` prints nothing for them (one-time diff check) | unit |
| AC-24 | the PR checkout | `README.md` is read | it contains neither `Cloud Run` nor `arp-compute` | holdout |

AC-20, AC-22 and AC-23 are one-time diff checks against `main` at the PR's merge base, not tests: a kept test
would either pass forever after merge or block later legitimate edits to these files. The builder pastes the
`git diff origin/main...HEAD --` output for these files into the PR description; the stage-4 code review re-runs it
and checks each row. No test is added for them. All other rows are checked on the PR head alone.

Must not change: the compute client, service, settings and CLI (AC-10, AC-15, AC-16, AC-18), local Docker Compose
and the Dockerfiles (AC-10, AC-11, AC-22, AC-23), the key-file ignore lines (AC-12), the Vertex settings the gcloud
sandbox uses (AC-13, AC-14, AC-21), `google-auth` (AC-17), the rest of the README (AC-19).

### Steward row after the change

```
| `risk:high` | Auth, permissions, secrets; database schema or data migrations; money, portfolio weights or index maths; deleting stored data; `.github/workflows/**`, `.github/scripts/**`, `.gitleaksignore`; anything that triggers a deploy; any file a session loads at start (`.claude/**`, `.claude-plugin/**`, `.mcp.json`) | Reads the acceptance matrix and the diff, then merges on GitHub |
```

## Slices

One slice, one PR: all rows AC-1 to AC-24 except the retired AC-5.

## Owner's manual clean-up (not checked by any row)

The builder copies this list into the PR description. Only the owner acts on it; no agent touches GCP or the
repository settings. Names come from `scripts/gcp/setup_compute.sh`; `<project>` is the project id it was run with.
If it was never run, most of these will not exist (as of 22 Nov 2026 the workflow had never deployed).

- GitHub repo settings: the `production` environment; the Actions variables `GCP_PROJECT`, `GCP_REGION`,
  `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, if set.
- Workload Identity: pool `github` (location `global`) and its OIDC provider `github`.
- Service accounts `arp-deployer@`, `arp-compute@`, `arp-client@<project>.iam.gserviceaccount.com`, with their
  project-level role bindings (`arp-deployer`: `roles/run.admin`, `roles/cloudbuild.builds.editor`,
  `roles/artifactregistry.writer`, `roles/storage.admin`, `roles/logging.logWriter`, `roles/logging.viewer`,
  `roles/serviceusage.serviceUsageConsumer`) and any keys of `arp-client`.
- Cloud Run services `arp-parse` and `arp-models` (region `europe-west1` unless overridden).
- Artifact Registry repository `arp` (same region); bucket `gs://<project>-arp-compute`.
- Billing budget `arp-compute` on the project's billing account.
- Locally: `backend/.gcp/arp-client.json` and the `ARP_COMPUTE_*` lines in `backend/.env`, if present.

## Defaults decided by the dispatcher

- README section removed outright rather than replaced by a note.
- Steward row keeps the generic "anything that triggers a deploy" so a future deploy workflow is still `risk:high`.
- `google-auth` stays a dependency: the compute client still imports it.

## Next step up (not in this spec)

Remove the Cloud Run compute client, service and `arp compute` CLI as well (`backend/arp/compute/`, the
`ARP_COMPUTE_*` settings, their tests, and the `google-auth` dependency).
