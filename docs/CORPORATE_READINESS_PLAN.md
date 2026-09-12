# Corporate Readiness Plan

How to take this app from a solo, locally-run research tool to something an
enterprise IT/security/compliance function will sign off on — first for
local development and pilot use, then for a production deployment on GCP.
Written against this repository's actual state as of this commit, not a
generic checklist.

**Why this needs more than the usual "add a login page" treatment:** the
codebase (see [`docs/SPEC_GAP_ANALYSIS.md`](SPEC_GAP_ANALYSIS.md)) is built
against an asset manager's stewardship/investment-intelligence spec —
proxy-vote casting (`backend/arp/voting/`), engagement escalation records
(`backend/arp/engagement/`), and non-public portfolio holdings
(`backend/arp/portfolio/`). That's regulated financial-services data with
real record-keeping obligations (e.g. SEC 17a-4 / MiFID II-style
communication and decision retention) and information-barrier concerns
(who may see which fund's holdings or draft engagement dossiers before
they're public), not just "internal tooling." The plan below is scoped
accordingly — IT hardening alone (auth, secrets, logging) is necessary but
not sufficient; a few items need a decision from Compliance/Legal, called
out explicitly rather than guessed at.

## 1. Current state (evidence-based)

| Area | Current state | File(s) |
|---|---|---|
| AuthN/AuthZ | **None.** No middleware, no session/token concept anywhere in the API. Any client that can reach the port can run pipelines, read portfolio/engagement data, and (per the CLI) cast ballots. | `backend/arp/api/main.py` |
| CORS | Hardcoded allow-list of two `localhost` origins; no env-based config for a deployed frontend origin. | `backend/arp/api/main.py:69-75` |
| Secrets | `.env` file only, loaded via `pydantic-settings`; correctly gitignored (`.gitignore:16-18`) and never logged. No secret manager integration, no rotation. | `backend/arp/config.py`, `backend/.env.example` |
| Storage | File-based JSON/JSONL under the repo tree by default (`runs/`, `engagements/`, `ballots/`, `portfolios/`, `data/documents/`) — no encryption-at-rest control of its own; inherits whatever the host filesystem provides. Optional Postgres/pgvector backend exists but is opt-in and unauthenticated at the app layer either way. | `arp/config.py:36-49`, README "Optional Postgres/pgvector store" |
| Packaging | **No Dockerfile, no docker-compose, no container image anywhere in the repo.** Both backend and frontend are run directly from source (`uvicorn --reload`, `npm run dev`). | repo root |
| CI | GitHub Actions runs `ruff` + `pytest` (backend) and `npm run lint` + `npm run build` (frontend). No dependency vulnerability scan, no SAST, no secret scanning, no SBOM, no container build/scan (nothing to scan). | `.github/workflows/ci.yml` |
| Third-party data egress | Calls to the Anthropic API (document/company text leaves the network), SEC EDGAR, GDELT, regulatory RSS feeds, and an open-ended same-domain web crawl for document discovery (`arp/discovery/crawler.py`). No egress allow-list, no DLP/redaction layer before the Anthropic call. | `arp/llm/langchain_client.py`, `arp/discovery/` |
| Audit trail | Strong *within* the app for what it already tracks: extraction field decisions, engagement events, and (per README) run manifests are append-only. But none of it is tied to an authenticated identity — every write records whatever free-text `--by "jane.pm"` string was typed in, not a verified user. | `arp/extraction/`, `arp/engagement/` |
| Observability | Root `logging.basicConfig(level=logging.INFO)` only; no structured logs, no request IDs/tracing, no metrics, no alerting hook beyond an optional discovery webhook. | `arp/api/main.py:41` |
| Dependency pinning | Good: upper-bounded version ranges with a documented policy (`backend/pyproject.toml` comment block). | `backend/pyproject.toml:6-11` |

**Bottom line:** the *analytical* precision controls (grounding, dual-model
verification, audit trails, golden-set regression) are mature. The
*operational* IT layer around them — who is allowed to do what, where
secrets live, how it's packaged/deployed, what gets logged and to whom —
doesn't exist yet. That's expected for a tool built local-first; it's the
gap this plan closes.

## 2. Requirement domains (what "typical corporate IT requirements" means here)

Use this as the checklist IT/security/compliance will actually apply. Each
maps to a phase in §3.

1. **Identity & access management** — every user and every service call is
   an authenticated identity; authorization is role-based, not "whoever has
   the URL." Non-negotiable for anything that touches holdings or ballots.
2. **Secrets management** — no long-lived credential ever lives in a file
   checked into git, a container image, or a shell history; rotation is
   possible without a redeploy of application code.
3. **Data classification & handling** — portfolio holdings, draft
   engagement dossiers, and unratified taxonomies are internal-confidential
   at minimum; some (pre-vote positions, escalation plans) may be
   information-barrier-sensitive. Classification drives who gets which
   role and what's allowed to leave the network (see #7).
4. **Network security** — TLS everywhere, no service listens on a public
   interface without a reason, egress from the backend is restricted to
   the specific hosts it actually needs (Anthropic, EDGAR, etc.), not open.
5. **Logging, monitoring & audit** — structured, centrally shipped logs;
   every state-changing action is attributable to an authenticated
   identity; alerting on failures and anomalous access.
6. **Backup & disaster recovery** — defined RPO/RTO for run history,
   engagement records, and portfolio data; tested restore, not just backup.
7. **Third-party/vendor & AI risk** — a signed data-processing agreement
   with Anthropic (and any other external API) covering what's sent
   (company disclosures, not client PII, but still non-public in the
   engagement/voting case), retention, and training-use opt-out; equivalent
   review for EDGAR/GDELT/web-crawl egress.
8. **Supply chain / dependency security** — SBOM generation, automated
   vulnerability scanning (Python + npm + base container image), a patching
   SLA.
9. **Change management & environments** — separate dev/staging/prod with
   promotion gates; no direct-to-prod pushes; infra-as-code, not manual
   console changes, once on GCP.
10. **Regulatory record-keeping** — engagement and voting records likely
    fall under communications/decision retention rules (retention period,
    immutability, e-discovery access) that are a Compliance/Legal call, not
    an engineering default (see §5, open decisions).
11. **Cost governance** — LLM spend is usage-based and this system is
    designed for 4,000-company batches; budget alerts and per-run cost caps
    are an IT-finance requirement once anyone but you is running it.

## 3. Phased roadmap

Phases 0–2 are local-dev-only and should happen regardless of whether/when
GCP is greenlit — they're the difference between "my laptop" and "a tool a
team can use." Phases 3+ target GCP specifically.

### Phase 0 — Local dev hygiene (do now, no infra needed) — ✅ implemented

- [x] Add `pip-audit` (Python) and `npm audit` (frontend) as CI jobs,
      non-blocking at first (`.github/workflows/ci.yml`,
      `backend-supply-chain`/`frontend-supply-chain` jobs) — flip
      `continue-on-error` to `false` once the current dependency set has
      been triaged.
- [x] Add a secret-scanning pre-commit hook (`.pre-commit-config.yaml`,
      gitleaks) plus the same check in CI (`secret-scan` job) for
      contributors who haven't run `pre-commit install` locally.
- [x] Generate an SBOM on each CI run (`cyclonedx-py` / `npm sbom
      --sbom-format cyclonedx`) and publish it as a build artifact
      (`sbom-backend`/`sbom-frontend`).
- [x] Document a data-handling note in the README (`README.md` "Data
      handling").

### Phase 1 — Containerize — ✅ implemented

- [x] `backend/Dockerfile`: multi-stage build (install deps → slim runtime
      image), non-root user (`arp`, uid 1000), `uvicorn` entrypoint,
      `HEALTHCHECK` hitting `/api/health`.
- [x] `frontend/Dockerfile`: build stage (`npm run build`) → nginx static
      serve (`frontend/nginx.conf`, SPA fallback); `VITE_API_BASE` is a
      build arg (Vite bakes `VITE_*` vars in at build time; the built JS
      runs in the viewer's browser, not the container, so a runtime
      env-injection trick would need a real reason to justify the added
      complexity — not attempted here).
- [x] `docker-compose.yml` for local dev: backend + frontend + an opt-in
      `postgres` profile (`docker compose --profile postgres up`) folding
      in the standalone `docker run pgvector/pgvector` command from the
      README's Postgres section; named volumes persist `runs/`,
      `taxonomies/`, `portfolios/`, `data/documents/`, `engagements/`,
      `ballots/`, and the backend's caches across restarts.
- [x] Add container image scanning to CI (`container-scan` job, Trivy),
      non-blocking for the same reason as the dependency scans above.

Not yet verified: an actual `docker build`/`docker compose up` run against
these images — this environment had no Docker daemon available to test
against. Review the Dockerfiles and run a real build before relying on
them; the heavier optional extras (`docling`, `fastembed`,
`emerging_themes`'s `hdbscan`/`umap-learn`) are the most likely source of a
missing system library on a build.

### Phase 2 — AuthN/AuthZ (the biggest functional gap)

This is the one item that meaningfully changes application code, so plan
for it explicitly rather than bolting it on later:

- [ ] Put an auth dependency in front of every router in
      `arp/api/main.py` — a FastAPI dependency validating a JWT (from
      whatever corporate IdP is chosen, see §5) added via `app.include_router(..., dependencies=[Depends(require_auth)])`
      or a global middleware.
- [ ] Define roles matching what the CLI already implies by convention
      (`--by "jane.pm"` free text): at minimum **viewer**, **analyst**
      (can run pipelines, review/override extractions), **approver**
      (engagement escalation sign-off, ballot casting — the two places a
      wrong actor has real external consequences). Replace every free-text
      `--by`/actor field with the authenticated principal from the token,
      not user-supplied input.
- [ ] Local dev fallback: an `ARP_AUTH_DISABLED=true` (dev-only, refuses to
      start if set alongside a non-localhost bind address) so local
      iteration isn't blocked on having an IdP wired up.
- [ ] Tighten CORS (`arp/api/main.py:71`) to read allowed origins from
      settings instead of a hardcoded localhost list.

### Phase 3 — Data protection & audit hardening

- [ ] Encrypt at rest: if staying file-based, this is a disk/volume-level
      control (LUKS locally, encrypted persistent disk on GCP); if adopting
      the Postgres backend, enable encryption there too.
- [ ] Tie every audit-trail write (extraction review decisions, engagement
      events, ballot casts) to the authenticated identity from Phase 2
      instead of the current free-text actor field.
- [ ] Define and implement retention/deletion policy for `runs/`,
      `engagements/`, `ballots/`, `portfolios/` — this needs the Compliance
      answer from §5 before engineering picks a number.

### Phase 4 — Observability

- [ ] Structured JSON logging (`structlog` or stdlib `logging` with a JSON
      formatter) with request-ID correlation across the FastAPI request
      lifecycle and into LangGraph pipeline steps.
- [ ] Ship logs somewhere centrally queryable — Cloud Logging once on GCP;
      any local equivalent (even just a file + `jq`) beforehand.
- [ ] Metrics: run counts/durations/failures, LLM call volume and cost
      (already tracked implicitly via the disk-backed cache and provenance
      fields — surface it), review-queue backlog size.
- [ ] Alerting on: run failures, discovery crawl unreachable-company spikes
      (the README already surfaces this per-run; wire it to a real alert
      channel, not just the CLI warning block), and the existing
      Continuous Monitoring & Alerting module's alerts
      (`arp/portfolio/monitoring/`) reaching an actual on-call channel
      instead of only the API/UI.

### Phase 5 — GCP target architecture

Once Phases 0–4 are done locally, the same containers move to GCP with no
new application-level surprises:

```
                         ┌─────────────────────────┐
   Corporate SSO/IdP ──► │  Identity-Aware Proxy /  │
   (OIDC)                │  Cloud Load Balancer     │
                         └───────────┬──────────────┘
                                     │
                         ┌───────────▼──────────────┐
                         │  Cloud Run (frontend)     │  static/served build
                         └───────────┬──────────────┘
                                     │ HTTPS (internal)
                         ┌───────────▼──────────────┐
                         │  Cloud Run / GKE (backend)│  FastAPI + CLI jobs
                         │  - Phase 2 auth dependency│
                         │  - VPC connector          │
                         └───┬───────────┬───────────┘
                             │           │
                ┌────────────▼──┐   ┌────▼─────────────────┐
                │ Cloud SQL /    │   │ Cloud Storage         │
                │ AlloyDB        │   │ (documents, run       │
                │ (+pgvector)    │   │  artifacts if moved   │
                │ opt-in backend │   │  off local disk)      │
                └────────────────┘   └───────────────────────┘
                             │
                ┌────────────▼──────────────┐
                │ Secret Manager             │  Anthropic key, DB creds
                └────────────────────────────┘
                             │
                ┌────────────▼──────────────┐
                │ VPC egress via Cloud NAT / │  allow-list: Anthropic API,
                │ restricted egress rules    │  SEC EDGAR, GDELT, IR sites
                └────────────────────────────┘
```

- [ ] **Compute:** Cloud Run for the API (scales to zero, fits the
      batch/on-demand usage pattern) unless long-running discovery/portfolio
      monitoring schedulers need a persistent process — in that case a
      small GKE deployment or a Cloud Run service with `min-instances: 1`
      for the scheduler process specifically.
- [ ] **Identity:** Identity-Aware Proxy (IAP) in front of Cloud Run,
      federated to the corporate IdP, so Phase 2's app-level auth is
      layered *behind* a network-level identity check, not the only line
      of defense.
- [ ] **Secrets:** Secret Manager for `ARP_ANTHROPIC_API_KEY` and the
      Postgres DSN; the backend service account gets `secretAccessor` on
      exactly those secrets, nothing broader.
- [ ] **Storage:** Cloud Storage for `data/documents/` if the current local
      filesystem store needs to survive container restarts/scale-out
      (Cloud Run's local disk is ephemeral) — this is a real code change to
      `arp/ingestion/local_files.py` and the run/engagement/ballot file
      stores, not just an infra move; scope it as its own task once GCP is
      confirmed.
- [ ] **Database:** Cloud SQL for Postgres or AlloyDB (pgvector support) if
      the opt-in Postgres backend is adopted for portfolio holdings.
- [ ] **Network:** VPC Service Controls around the project; egress
      allow-listed to the specific external hosts this app actually calls
      (Anthropic API, SEC EDGAR, GDELT, and IR-site domains discovered at
      runtime — the last one is inherently open-ended, so route discovery
      crawl traffic through a dedicated NAT/proxy with logging rather than
      trying to allow-list arbitrary IR sites).
- [ ] **CI/CD:** Cloud Build (or keep GitHub Actions, pushing to Artifact
      Registry) with a promotion gate — dev → staging → prod, each its own
      GCP project or at least its own VPC, so a bad batch run in dev can't
      touch prod portfolio data.
- [ ] **IaC:** Terraform for all of the above from day one — "click it in
      the console" for a financial-services deployment is itself an audit
      finding.

### Phase 6 — Vendor/AI risk & compliance sign-off

Run in parallel with engineering, not after — these are the items only
Compliance/Legal/IT-Security can close, and several block earlier phases:

- [ ] Anthropic: confirm the applicable data-processing terms (retention,
      no-training-on-API-data commitment, region if relevant) cover the
      document content this app sends (annual reports, sustainability
      reports, earnings-call transcripts, proxy statements — public
      company disclosures, but engagement/voting *context* around them may
      not be).
- [ ] Same review, lighter weight, for SEC EDGAR/GDELT/regulatory-RSS
      (public data, low risk) and the document-discovery crawler (crawls
      arbitrary third-party IR sites — confirm this is acceptable under
      the corporate acceptable-use/robots.txt policy; the crawler already
      respects `robots.txt` per the README).
- [ ] Decide the SSO/IdP integration point (Okta/Azure AD/Google Workspace
      — whichever the org already standardizes on) — blocks Phase 2.
- [ ] Decide record-retention periods for engagement and voting records —
      blocks part of Phase 3. Ask whether these fall under an existing
      regulatory record-keeping policy the firm already has for other
      stewardship tooling.
- [ ] Confirm information-barrier requirements: does any role need to be
      blocked from seeing certain funds'/portfolios' data, or certain
      engagement dossiers pre-disclosure? This shapes the Phase 2 role
      model beyond the generic viewer/analyst/approver split above.
- [ ] Cost governance: set a budget alert and, if required, a per-run
      LLM-spend cap enforced in `arp/llm/` before the first real
      corporate-scale (4,000-company) batch runs anywhere but a
      developer's own key.

## 4. What can start immediately vs. what waits on a decision

**No blockers, start now:** Phase 0 entirely; Phase 1 containerization;
most of Phase 4 observability groundwork (structured logging doesn't need
an IdP decision).

**Needs an IT/Compliance decision first:** Phase 2 auth (needs the IdP
choice), the retention piece of Phase 3, and all of Phase 6 — flagged above
rather than defaulted, since guessing a retention period or role model for
regulated stewardship records is the kind of thing worth getting from the
people who own that risk.

**Needs the GCP decision confirmed:** all of Phase 5 — the plan above is
written so nothing in Phases 0–4 is wasted work if GCP timing slips; the
same containers and auth layer work equally well on any other host in the
meantime.

## 5. Suggested order of operations

1. Phase 0 (days) → 2. Phase 1 (days) → 3. Phase 2 app-side work in
parallel with the Phase 6 IdP/retention/vendor decisions (these gate each
other, so start the conversation with IT/Compliance as soon as this plan is
reviewed, not after Phase 1 finishes) → 4. Phase 3–4 → 5. Phase 5 GCP
migration once environments/IaC/budget are approved.
