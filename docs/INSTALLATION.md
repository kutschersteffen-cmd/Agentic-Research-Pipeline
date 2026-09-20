# Installation Guide (Windows / Corporate Network / VS Code / conda)

This guide is for setting up the Agentic Research Pipeline on a **Windows**
machine, in **VS Code**, using **conda with Python 3.11**, on a **corporate
network** that terminates outbound HTTPS through an inspecting proxy and
requires an internal root certificate to be trusted. It complements (does
not replace) the quick-start "Setup" section in the root [`README.md`](../README.md);
this document goes deeper on exactly the steps that tend to fail on a
locked-down corporate laptop, and ships automation for them.

If you're on macOS/Linux, or not behind a corporate proxy, the plain
`README.md` "Setup" section is all you need — skip this file.

## Table of contents

1. [What gets installed, and why](#what-gets-installed-and-why)
2. [Prerequisites](#prerequisites)
3. [Corporate certificates and proxy](#corporate-certificates-and-proxy)
4. [Automated setup (recommended)](#automated-setup-recommended)
5. [Manual setup (step by step)](#manual-setup-step-by-step)
6. [VS Code integration](#vs-code-integration)
7. [Running the app](#running-the-app)
8. [Verifying your setup](#verifying-your-setup)
9. [LLM provider: current state and Gemini](#llm-provider-current-state-and-gemini)
10. [Troubleshooting](#troubleshooting)
11. [Keeping your setup up to date](#keeping-your-setup-up-to-date)

## What gets installed, and why

| Component | Tool | Why |
|---|---|---|
| Backend (`backend/arp`) | Python 3.11, installed editable (`pip install -e`) into a conda environment | FastAPI API + Typer CLI, all agent pipelines |
| Frontend (`frontend/`) | Node.js 22 + npm, installed via the same conda environment | React/Vite UI |
| Package manager for both | **conda** (Python) via `environment.yml`, **pip** (Python deps) via `backend/pyproject.toml`, **npm** (JS deps) via `frontend/package.json` | conda's only job here is providing Python 3.11 and Node 22 in one reproducible environment; the actual dependency versions are pinned in `pyproject.toml`/`package.json`, not duplicated in `environment.yml` |
| Editor | VS Code, with `.vscode/settings.json` / `launch.json` / `tasks.json` / `extensions.json` already checked in | Correct interpreter auto-selected, pytest wired up, debug configs for the backend and frontend, one-click tasks for setup/tests/dev servers |

Nothing here is containerized by default — see the root README's "Docker
(optional)" section if you'd rather run everything in containers instead
(that path sidesteps most of the certificate issues below, since only the
Docker build step needs the corporate CA, not your host Python/Node/npm
install — see the [Docker note](#docker-alternative) further down).

## Prerequisites

Install these first, in this order (each installer needs the previous one on `PATH`):

1. **Git for Windows** — <https://git-scm.com/download/win>. Accept the
   installer defaults; they add Git and a `git bash`/`git cmd` to `PATH`.
2. **Miniconda (Python 3.11+, 64-bit)** — <https://docs.conda.io/en/latest/miniconda.html>.
   During install, check **"Add Miniconda3 to my PATH environment
   variable"** (the installer warns against it, but for a single-user dev
   laptop it's the simplest path and what the scripts in this repo
   assume; if you skip it, run everything from an "Anaconda Prompt"
   instead of a plain PowerShell window). Full Anaconda also works — only
   `conda` itself and Python 3.11 are needed, its extra pre-installed
   packages aren't used here.
3. After installing, open a **new** PowerShell window (PATH changes don't
   apply to already-open windows) and run once:
   ```powershell
   conda init powershell
   ```
   Close and reopen PowerShell again. This is what makes `conda` and
   `conda activate` work inside PowerShell (and inside VS Code's
   integrated terminal, which defaults to PowerShell) — without it,
   `conda` only works from the separate "Anaconda Prompt" shortcut, which
   the scripts in this repo don't use.
4. **VS Code** — <https://code.visualstudio.com/>.
5. Open this repository folder in VS Code (`File > Open Folder...`). VS
   Code will prompt to install the recommended extensions from
   `.vscode/extensions.json` (Python, Pylance, the debugger, Ruff, the
   Oxc/oxlint linter, PowerShell, and Docker) — click **Install All**.

You do **not** need to separately install Node.js — `environment.yml`
pulls Node 22 into the same conda environment as Python, so both the
backend and frontend end up using tool versions installed the same way,
in the same place, with the same certificate/proxy configuration applied
once (see next section).

## Corporate certificates and proxy

**Skip this section if `pip install`/`npm install`/`git clone` already
work on this machine without errors** (some corporate networks trust
their internal CA at the OS level in a way every tool already picks up,
or route traffic without TLS inspection at all).

**What's actually going wrong**, if it is: a corporate network commonly
routes all outbound HTTPS through a proxy that re-signs every TLS
connection with an internal root CA ("TLS/SSL inspection"), so it can
inspect traffic content. Windows itself usually trusts that CA (via Group
Policy), so a plain browser, `curl.exe`, and PowerShell's
`Invoke-WebRequest` all work fine. **Python, Node.js, and Git for Windows
each ship their own separate list of trusted root certificates and ignore
the Windows certificate store by default** — so `pip install`,
`npm install`, and `git clone` fail with an error like:

```
SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate
```

even though everything else on the same machine works. This is the single
most common blocker on a corporate install and has nothing to do with
this project specifically — the fix below is the same one used for any
Python/Node project on such a network.

### The fix

1. Ask your IT/security team for your company's **root CA certificate**
   (the one used for TLS inspection) as a file — `.pem`, `.crt`, or `.cer`
   (either PEM/Base64 text or binary DER is fine, the script below handles
   both). This is a **public key**, not a secret — it's safe to have on
   any machine that needs to trust the proxy, and IT departments hand
   this out routinely for exactly this purpose.
2. Also ask whether your network needs an **explicit proxy** configured
   (as opposed to fully transparent interception) — if so, get the proxy
   URL, e.g. `http://proxy.mycompany.com:8080`.
3. Run:
   ```powershell
   .\scripts\windows\configure-network.ps1 -CaBundlePath C:\path\to\corporate-root-ca.cer
   # ...or, if you also need an explicit proxy:
   .\scripts\windows\configure-network.ps1 -CaBundlePath C:\path\to\corporate-root-ca.cer -HttpProxy http://proxy.mycompany.com:8080
   ```
4. **Close and reopen VS Code / your terminal** (environment variable
   changes only apply to new processes).

What this script does (see its own `Get-Help` comment header for full
detail): downloads the current public Mozilla CA bundle using `curl.exe`
(which already trusts your proxy via the Windows certificate store —
this is how the script avoids the chicken-and-egg problem of needing a
trusted bundle before you have one), appends your company's certificate
to it, and points pip, conda, npm, git, and Python's own HTTPS stack
(`requests`/`httpx`, which this project's `langchain-anthropic` client
uses) at the merged bundle via environment variables and each tool's own
config file. It's idempotent — safe to re-run if IT rotates the
certificate.

Run `Get-Help .\scripts\windows\configure-network.ps1 -Full` for every
parameter and exactly which files/env vars it touches.

### Docker alternative

If you use the Docker path instead (`docker compose up backend frontend
--build`), only the Docker **build** needs to reach the network, and
Docker Desktop has its own proxy/certificate settings under **Settings →
Resources → Proxies** and **Settings → Docker Engine** (for a custom CA,
mount it into the build or use `docker build --build-arg` — outside the
scope of this project's own scripts). This sidesteps configuring your
host's Python/Node/npm/git individually, at the cost of losing native
VS Code debugging into the running containers.

## Automated setup (recommended)

Once prerequisites are installed (and certificates configured, if
needed):

```powershell
.\scripts\windows\setup.ps1
```

This single command (see [`scripts/windows/setup.ps1`](../scripts/windows/setup.ps1)):

- Checks that `conda` and `git` are on `PATH` and fails fast with a clear
  message if not, instead of failing confusingly several steps later.
- Creates (or updates, if it already exists) a conda environment named
  `arp` with Python 3.11 and Node 22, from [`environment.yml`](../environment.yml).
- Installs the backend package in editable/dev mode
  (`pip install -e ".[dev]"`), so code changes take effect immediately
  without reinstalling.
- Copies `backend/.env.example` → `backend/.env` and
  `frontend/.env.example` → `frontend/.env` if they don't already exist
  (never overwrites an existing `.env`, so your API key survives a
  re-run).
- Installs the `pre-commit` secret-scanning hook (see the root README's
  "Contributing" section).
- Runs the backend test suite (informational — a failure here doesn't
  block the rest of setup, but is worth investigating before relying on
  the pipeline).
- Detects the conda environment's exact Python interpreter path and
  writes it into `.vscode/settings.json`, so VS Code selects the right
  interpreter automatically without you needing to run "Python: Select
  Interpreter" by hand.
- Installs frontend dependencies (`npm install`).

Every step checks its own exit code; a real failure stops the script with
a specific message (and, for a certificate-shaped error, a pointer back
to the previous section) instead of silently continuing with a broken
environment. It's safe to re-run any time — every step is idempotent.

Useful flags (see `Get-Help .\scripts\windows\setup.ps1 -Full`):

- `-SkipFrontend` / `-SkipBackend` — set up only one half of the app.
- `-CondaEnvName <name>` — use a different environment name than `arp`.
- `-CaBundlePath` / `-HttpProxy` — run `configure-network.ps1` (see
  above) as the first step, in one command.

After it finishes, fill in `backend\.env` (at minimum
`ARP_ANTHROPIC_API_KEY`) and see [Running the app](#running-the-app).

## Manual setup (step by step)

Equivalent to what `setup.ps1` automates, if you'd rather run each step
yourself (e.g. to understand exactly what's happening, or because the
script hit something it doesn't handle):

```powershell
# 1. Create the conda environment (Python 3.11 + Node 22)
conda env create -f environment.yml
conda activate arp

# 2. Install the backend package (editable, with dev extras: pytest, ruff, pre-commit)
cd backend
pip install -e ".[dev]"
Copy-Item .env.example .env
# now edit backend\.env and fill in ARP_ANTHROPIC_API_KEY

# 3. Sanity-check: run the unit tests (no API key/network required)
pytest -q

# 4. Install the pre-commit secret-scanning hook
cd ..
pre-commit install

# 5. Install frontend dependencies
cd frontend
npm install
Copy-Item .env.example .env
cd ..
```

If any of these fail with an SSL/certificate error, go back to
[Corporate certificates and proxy](#corporate-certificates-and-proxy)
first — that's almost always the cause on a corporate machine, not a
problem with this project's dependencies.

## VS Code integration

This repository ships a `.vscode/` folder, so most of the usual manual
VS Code setup (selecting an interpreter, wiring up pytest, writing debug
configs) is already done:

- **`settings.json`** — points at the `arp` conda environment's Python
  interpreter (filled in automatically by `setup.ps1`; if you renamed the
  environment or skipped the script, run **"Python: Select Interpreter"**
  from the Command Palette and pick the one under
  `...\envs\arp\python.exe`), enables pytest discovery
  (`backend/tests`), and turns on Ruff as the formatter/linter for Python
  on save.
- **`extensions.json`** — the recommended extensions listed in
  [Prerequisites](#prerequisites) above.
- **`tasks.json`** (Command Palette → **"Tasks: Run Task"**):
  - `Setup: Full automated setup` / `Setup: Check (diagnostics)` — run
    the two PowerShell scripts from inside VS Code.
  - `Backend: Run tests`, `Frontend: Lint`.
  - `Backend: Start (auto-reload)`, `Frontend: Start dev server` —
    equivalent to `scripts\windows\run-backend.ps1` /
    `run-frontend.ps1`, run as background tasks.
- **`launch.json`** (Run and Debug panel, or **F5**):
  - **"Backend: FastAPI (debug, no reload)"** — runs uvicorn under the
    debugger so breakpoints in `backend/arp/**` actually hit. Deliberately
    without `--reload`: uvicorn's auto-reloader runs your app in a
    *subprocess* the debugger never attaches to, so breakpoints silently
    never fire under `--reload` — use the `Backend: Start (auto-reload)`
    task instead for day-to-day dev without breakpoints, and this launch
    config specifically when you need to step through code.
  - **"Backend: pytest (current file)"** — debug the test file currently
    open in the editor.
  - **"Frontend: Debug in browser (attaches to running dev server)"** —
    starts the Vite dev server (via the background task) and opens it in
    a debugger-attached browser tab, so breakpoints set in `frontend/src`
    `.tsx`/`.ts` files hit directly in VS Code.
  - **"Backend + Frontend (debug)"** — both of the above together.

## Running the app

```powershell
conda activate arp

# Terminal 1
.\scripts\windows\run-backend.ps1     # http://localhost:8000

# Terminal 2
.\scripts\windows\run-frontend.ps1    # http://localhost:5173
```

(or use the VS Code tasks/launch configs above, which do the same thing
without needing a manually-activated terminal).

## Verifying your setup

```powershell
.\scripts\windows\check-setup.ps1
```

Runs every check independently — prerequisites, the conda environment,
`.env` files, certificate/proxy configuration, and live connectivity to
`api.anthropic.com`, PyPI, and the npm registry — and prints a PASS/FAIL
summary at the end, so one failing check doesn't hide the others behind
it. Run this any time something doesn't work and you're not sure which
step is the problem; it's also the fastest way to hand a precise report
to whoever set up your corporate network policy, if the issue turns out
to be on that side.

## LLM provider: current state and Gemini

**As of this version, the codebase only supports Anthropic Claude as the
LLM provider** — the client is `backend/arp/llm/langchain_client.py`
(`LangChainAnthropicClient`, built on `langchain-anthropic`), wired up in
`backend/arp/llm/factory.py`, which raises immediately if
`ARP_ANTHROPIC_API_KEY` is missing. Every agent in the codebase calls
through the single `LLMClient.complete_structured` interface
(`backend/arp/llm/base.py`), which is provider-agnostic by design — but
today only one implementation of it exists.

If your organization's policy ends up mandating **Gemini** instead of (or
alongside) Claude, that's a real code change, not a config toggle:

- A new `LLMClient` implementation (e.g. `LangChainGeminiClient`, using
  `langchain-google-genai` or Vertex AI's SDK) matching the same
  `complete_structured` contract, including its structured-output/schema
  enforcement, validation-retry loop, and usage/cost accounting fields
  (`LLMUsage`).
- A provider switch in `backend/arp/config.py` /
  `backend/arp/llm/factory.py` (e.g. `ARP_LLM_PROVIDER=anthropic|gemini`),
  since `ARP_ANTHROPIC_API_KEY` and the Anthropic-specific prompt-caching
  logic (`_CACHE_CONTROL` in `langchain_client.py`) don't carry over
  as-is.
- If your org uses **Vertex AI** rather than a plain Gemini API key,
  authentication would go through Google Application Default Credentials
  (a service account JSON, or `gcloud auth application-default login`)
  instead of an API key in `.env` — a different corporate setup step from
  everything above (typically its own certificate/proxy considerations
  for `*.googleapis.com`, handled the same way as
  `api.anthropic.com`/PyPI/npm above once you know the provider's
  hostname).
- This is a good-sized, self-contained change — worth its own task rather
  than folding into environment setup. This document intentionally
  doesn't attempt it, so that adding Gemini support doesn't silently
  regress the existing, tested Anthropic path.

Until that lands, plan on `ARP_ANTHROPIC_API_KEY` for actually running
the pipelines end-to-end; `pytest -q` in `backend/` needs no API key at
all (every LLM call is mocked in the unit test suite).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `CERTIFICATE_VERIFY_FAILED` / `unable to get local issuer certificate` from pip, npm, or git | Corporate TLS inspection not yet trusted by that tool | [Corporate certificates and proxy](#corporate-certificates-and-proxy) |
| `conda` / `conda activate` not recognized in a PowerShell window | `conda init powershell` was never run, or you're in a window opened before running it | Run `conda init powershell`, then open a **new** terminal window |
| `pip install -e ".[dev]"` fails resolving/building a package (e.g. a compiler error) | A transitive dependency needs a C/C++ build toolchain not present on Windows | Prefer the prebuilt wheel path: make sure you're on Python 3.11 exactly (`python --version` inside the `arp` env) — the pinned versions in `backend/pyproject.toml` are chosen to have Windows wheels on 3.11; a different Python minor version can fall back to a source build |
| `npm install` hangs or times out, no certificate error shown | An explicit corporate proxy is required but not configured | Re-run `configure-network.ps1` with `-HttpProxy` |
| VS Code shows the wrong Python interpreter / `import arp` unresolved in the editor | `.vscode/settings.json`'s interpreter path wasn't updated (e.g. you renamed the conda env, or skipped `setup.ps1`) | Command Palette → "Python: Select Interpreter" → pick the `arp` conda environment |
| Breakpoints in `backend/arp/**` never hit while using "Backend: Start (auto-reload)" | uvicorn's `--reload` runs your app in a subprocess VS Code isn't attached to | Use the **"Backend: FastAPI (debug, no reload)"** launch config instead |
| `ARP_ANTHROPIC_API_KEY is not set` at runtime | `backend/.env` still has the placeholder, or wasn't created | `Copy-Item backend\.env.example backend\.env` (if missing), then fill in the real key |
| `check-setup.ps1` reports `api.anthropic.com` unreachable but a browser can load anthropic.com fine | Python/curl aren't using the corporate CA bundle the browser (via Windows) already trusts | [Corporate certificates and proxy](#corporate-certificates-and-proxy) |
| Everything above passes but a real pipeline run (e.g. `arp theme run`) still fails on an HTTPS call | A different internal/allowlisted domain than the ones this guide checks (e.g. a company proxy that only allows specific domains) | Ask IT to allowlist `api.anthropic.com`; `check-setup.ps1`'s connectivity checks only cover the services this project talks to by default (see the root README's "Data handling" section for the full list) |

## Keeping your setup up to date

After pulling changes that touch `backend/pyproject.toml`,
`frontend/package.json`, or `environment.yml`, re-run:

```powershell
.\scripts\windows\setup.ps1
```

It's idempotent — `conda env update --prune`, `pip install -e` and
`npm install` all pick up added/removed/changed dependencies without
needing to delete and recreate anything.
