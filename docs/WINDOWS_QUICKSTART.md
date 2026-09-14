# Running the Agentic Research Pipeline on Windows

Everything you need to get from a fresh Windows machine to the app
running in a browser.

This is the short path. [`INSTALLATION.md`](INSTALLATION.md) is the long
one — the manual step-by-step equivalent, the VS Code debug
configuration, and a troubleshooting table keyed by symptom. Start here;
go there when something needs explaining.

---

## The one-command version

```powershell
git clone https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline.git
cd Agentic-Research-Pipeline
powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap.ps1 -InstallPrerequisites
```

On a machine with nothing installed, that installs Git, Miniconda and VS
Code via winget, then stops and asks you to open a new PowerShell and run
it again — PATH changes cannot reach a shell that is already running, and
pretending otherwise just produces a confusing failure three steps later.
The second run does everything else.

On a TLS-inspecting corporate network, add your company's root CA (see
[§4](#4-corporate-networks)):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap.ps1 `
    -InstallPrerequisites -CaBundlePath C:\certs\corporate-root-ca.cer
```

Then start it:

```powershell
.\scripts\windows\run-backend.ps1     # http://localhost:8000
.\scripts\windows\run-frontend.ps1    # http://localhost:5173  (second terminal)
```

If you would rather understand each step before running it, the rest of
this document is that same sequence, explained.

---

## 1. Why the `-ExecutionPolicy Bypass` prefix

A default Windows profile refuses to run any local `.ps1` file. That
includes the script whose job is to fix exactly that, so there is no way
for the script to fix it before it runs — hence the prefix, which
bypasses the policy **for that single process only** and changes nothing
permanently.

`bootstrap.ps1` then sets the `CurrentUser` policy to `RemoteSigned`,
which needs no admin rights, affects nobody else on the machine, and
still requires a signature on anything downloaded. After that first run,
every other script in `scripts\windows\` runs normally as
`.\scripts\windows\<name>.ps1`.

If your organisation locks the policy by Group Policy, the script says so
and tells you to keep using the `-ExecutionPolicy Bypass` form. That is a
supported way to work, not a workaround.

**Files from a zip rather than a clone** also carry the
mark-of-the-web, which blocks them under `RemoteSigned` even though
they're local. `bootstrap.ps1` runs `Unblock-File` over the folder for
you; it is a no-op after a `git clone`.

---

## 2. Prerequisites

| Tool | Why | Installed by `-InstallPrerequisites` |
|---|---|---|
| **Git for Windows** | clone and the pre-commit hook | yes (`Git.Git`) |
| **Miniconda** (64-bit) | provides Python 3.11 **and** Node 22 in one environment | yes (`Anaconda.Miniconda3`) |
| **VS Code** | optional; debug configs are checked in | yes (`Microsoft.VisualStudioCode`) |

You do **not** need to install Node separately. `environment.yml` pulls
Node 22 into the same conda environment as Python, so both halves of the
app use tool versions installed the same way, in the same place, with the
same certificate and proxy configuration applied once.

`-InstallPrerequisites` needs winget, which ships with Windows 11 and
recent Windows 10. Without it, install by hand from
[git-scm.com](https://git-scm.com/download/win),
[Miniconda](https://docs.conda.io/en/latest/miniconda.html) and
[VS Code](https://code.visualstudio.com/) — the script prints these links
when a prerequisite is missing.

If you install Miniconda manually, tick **"Add Miniconda3 to my PATH
environment variable"**. The installer advises against it; these scripts
assume it. (If you skip it, run everything from an "Anaconda Prompt"
instead.)

### `conda init powershell`

Without this, `conda activate` only works in the separate "Anaconda
Prompt" shortcut, which these scripts don't use. `bootstrap.ps1` detects
whether your PowerShell profile has been initialised and runs it if not —
then stops, because a profile change also only reaches a new shell.

---

## 3. What `bootstrap.ps1` actually does

In order, because the order is not arbitrary — prerequisites must exist
before the network is configured, the network must be trusted before
conda/pip/npm touch it, and the API key is only useful once the package
that reads it is installed:

1. **Execution policy** → `CurrentUser` = `RemoteSigned`, and warns if a
   higher scope still overrides it.
2. **Mark-of-the-web** → `Unblock-File` across `scripts\windows\*.ps1`.
3. **Prerequisites** → checks `git`, `conda`, `code`; installs the
   missing ones only if you passed `-InstallPrerequisites`. Installing
   software is not something a setup script should do unasked.
4. **`conda init powershell`** → if the profile needs it.
   *(Stops here if 3 or 4 changed anything, and tells you to re-run in a
   new shell.)*
5. **`setup.ps1`** → the existing installer, unchanged. See §5.
6. **API key** → prompts for `ARP_ANTHROPIC_API_KEY` and writes it into
   `backend\.env`. Read as a `SecureString`, so it is never echoed to the
   terminal and never lands in PSReadLine history. Skipped entirely if
   the file already holds a real-looking key, or with
   `-SkipApiKeyPrompt`.
7. **`check-setup.ps1`** → the health check, and exits with its status.

Every stage is idempotent. Re-run it as often as you like.

### Flags

| Flag | Effect |
|---|---|
| `-InstallPrerequisites` | Install missing Git/Miniconda/VS Code via winget |
| `-CaBundlePath <path>` | Your corporate root CA — see §4 |
| `-HttpProxy <url>` / `-HttpsProxy <url>` | Explicit proxy; requires `-CaBundlePath` |
| `-SkipApiKeyPrompt` | Unattended run, or edit `backend\.env` yourself |
| `-SkipBackend` / `-SkipFrontend` | Set up only one half |
| `-CondaEnvName <name>` | Use something other than `arp` |

`Get-Help .\scripts\windows\bootstrap.ps1 -Full` has the rest.

---

## 4. Corporate networks

**Skip this if `pip install`, `npm install` and `git clone` already work
on this machine.** Some networks trust their internal CA in a way every
tool already picks up, or don't inspect TLS at all.

If they don't, you will see this from pip, npm or git while browsers and
`curl.exe` on the same machine work perfectly:

```
SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate
```

**What's happening:** your network routes outbound HTTPS through a proxy
that re-signs every connection with an internal root CA so it can inspect
traffic. Windows trusts that CA via Group Policy, so anything using the
Windows certificate store is fine — but **Python, Node.js and Git for
Windows each ship their own separate list of trusted roots and ignore the
Windows store by default**. This is the single most common blocker on a
corporate install, and has nothing to do with this project.

**The fix:**

1. Ask IT for the company's root CA certificate as a file — `.pem`,
   `.crt` or `.cer`, PEM or DER, the script handles both. This is a
   **public key, not a secret**; IT departments hand it out routinely for
   exactly this purpose.
2. Ask whether you also need an **explicit proxy** URL (as opposed to
   transparent interception).
3. Pass it to `bootstrap.ps1` via `-CaBundlePath` (and `-HttpProxy`), or
   run the underlying script directly:

```powershell
.\scripts\windows\configure-network.ps1 -CaBundlePath C:\certs\corporate-root-ca.cer
.\scripts\windows\configure-network.ps1 -CaBundlePath C:\certs\corporate-root-ca.cer -HttpProxy http://proxy.mycompany.com:8080
```

4. **Close and reopen VS Code and your terminal.** Environment variable
   changes only reach new processes.

It downloads the current public Mozilla CA bundle using `curl.exe` —
which already trusts your proxy via the Windows store, sidestepping the
chicken-and-egg of needing a trusted bundle before you have one — appends
your company's certificate, and points pip, conda, npm, git and Python's
own HTTPS stack at the merged file. Idempotent, so re-run it when IT
rotates the certificate.

**Alternative:** `docker compose up backend frontend --build` confines
the network requirement to the Docker build, so you never configure your
host's Python/Node/npm/git individually. You lose native VS Code
debugging into the containers.

---

## 5. What `setup.ps1` installs

The step `bootstrap.ps1` delegates to, and the one to run on its own
whenever you pull changes:

- Creates or updates the `arp` conda environment (Python 3.11 + Node 22)
  from `environment.yml`.
- `pip install -e ".[dev]"` — editable, so code changes take effect with
  no reinstall.
- Copies `backend\.env.example` → `backend\.env` and the frontend
  equivalent, **never overwriting an existing `.env`**, so your API key
  survives a re-run.
- Installs the pre-commit secret-scanning hook.
- Runs the backend test suite (informational — a failure doesn't block
  setup, but is worth investigating).
- Writes the environment's exact interpreter path into
  `.vscode\settings.json`, so VS Code picks the right interpreter without
  you running "Python: Select Interpreter".
- `npm install` for the frontend.

Every step checks its own exit code, and a certificate-shaped failure
prints a pointer to §4 rather than a raw stack trace.

---

## 6. The API key

Anthropic is currently the **only** supported LLM provider —
`backend/arp/llm/factory.py` raises immediately without a key. Get one at
[console.anthropic.com](https://console.anthropic.com/settings/keys) and
put it in `backend\.env`:

```
ARP_ANTHROPIC_API_KEY=sk-ant-...
```

`bootstrap.ps1` prompts for this and writes it for you. `.env` is
git-ignored, and the repo has a pre-commit secret-scanning hook, but the
key does live in plain text on disk — that is what the app reads.

Every agent calls through one provider-agnostic `LLMClient` interface
(`backend/arp/llm/base.py`), so adding a provider means adding a client,
not touching the agents. See `INSTALLATION.md` § "LLM provider" for the
current state.

---

## 7. Running it

```powershell
.\scripts\windows\run-backend.ps1     # http://localhost:8000
.\scripts\windows\run-frontend.ps1    # http://localhost:5173
```

Two terminals. You do **not** need to `conda activate arp` first — both
scripts use `conda run -n arp` internally and work from a plain
PowerShell window.

Open <http://localhost:5173>. The backend serves the API on port 8000;
the frontend dev server proxies to it.

From VS Code, the pre-wired launch configs do the same thing — press
**F5** and pick "Backend: FastAPI (debug, no reload)".

For large unattended batch runs, use the CLI instead of the UI:

```powershell
conda activate arp
arp --help
```

---

## 8. When something breaks

```powershell
.\scripts\windows\check-setup.ps1
```

Runs every check independently — prerequisites, the conda environment,
`.env` files, certificate and proxy configuration, and live connectivity
to `api.anthropic.com`, PyPI and the npm registry — then prints one
PASS/FAIL summary. One failure never hides the rest behind it. It is also
the fastest way to hand your network team a precise report when the
problem turns out to be on their side.

Common ones:

| Symptom | Cause | Fix |
|---|---|---|
| `.ps1` "cannot be loaded because running scripts is disabled" | Execution policy | §1 |
| `CERTIFICATE_VERIFY_FAILED` from pip/npm/git | Corporate TLS inspection | §4 |
| `conda` not recognised | `conda init powershell` never run, or shell opened before it was | §2, then a **new** terminal |
| `npm install` hangs, no certificate error | Explicit proxy needed | §4, with `-HttpProxy` |
| `ARP_ANTHROPIC_API_KEY is not set` | `.env` still has the placeholder | §6 |
| Breakpoints never hit in `backend/arp/**` | `--reload` runs your app in a subprocess the debugger isn't attached to | Use "Backend: FastAPI (debug, no reload)" |
| VS Code can't resolve `import arp` | Interpreter path not updated | Command Palette → "Python: Select Interpreter" → the `arp` env |

`INSTALLATION.md` § "Troubleshooting" has the full table.

---

## 9. Keeping up to date

```powershell
git pull
.\scripts\windows\setup.ps1
```

`conda env update --prune`, `pip install -e` and `npm install` all pick
up added, removed and changed dependencies without deleting anything.
Run it after any pull that touches `backend\pyproject.toml`,
`frontend\package.json` or `environment.yml`.
