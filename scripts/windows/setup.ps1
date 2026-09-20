<#
.SYNOPSIS
    One-shot setup for the Agentic Research Pipeline on a Windows /
    corporate machine: conda environment, backend package, frontend
    dependencies, .env files, and pre-commit hook.

.DESCRIPTION
    Mirrors the manual steps in the README's "Setup" section and
    docs\INSTALLATION.md, but checks every step's exit code and gives a
    specific, actionable message on failure (especially for the
    corporate-proxy/TLS-inspection failures that are the #1 cause of a
    "pip install" or "npm install" silently doing nothing useful on a
    locked-down network) instead of leaving you to interpret a raw
    stack trace.

    Safe to re-run: every step is idempotent (conda env update, `pip
    install -e` re-install, `npm install`, .env files only copied if
    missing).

.PARAMETER CondaEnvName
    Name of the conda environment to create/update. Default: arp.

.PARAMETER CaBundlePath
    Optional. If your network needs a corporate root CA to be trusted
    (see docs\INSTALLATION.md, "Corporate certificates"), pass it here
    and this script runs configure-network.ps1 for you before touching
    the network.

.PARAMETER HttpProxy
    Optional corporate proxy URL, forwarded to configure-network.ps1.

.PARAMETER SkipFrontend
    Skip the frontend (Node/npm) setup -- useful if you only work on the
    backend/CLI.

.PARAMETER SkipBackend
    Skip the backend (conda/pip) setup -- useful if you only work on the
    frontend.

.EXAMPLE
    .\setup.ps1

.EXAMPLE
    .\setup.ps1 -CaBundlePath C:\certs\corporate-root-ca.cer -HttpProxy http://proxy.mycompany.com:8080
#>
param(
    [string]$CondaEnvName = "arp",
    [string]$CaBundlePath,
    [string]$HttpProxy,
    [string]$HttpsProxy,
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

. "$PSScriptRoot\common.ps1"
$repoRoot = Get-RepoRoot

Write-Host "Agentic Research Pipeline -- Windows setup" -ForegroundColor Magenta
Write-Host "Repository root: $repoRoot"

if ($CaBundlePath -or $HttpProxy -or $HttpsProxy) {
    $networkArgs = @{}
    if ($CaBundlePath) { $networkArgs["CaBundlePath"] = $CaBundlePath } else {
        Write-Fail "-HttpProxy/-HttpsProxy was given without -CaBundlePath. configure-network.ps1 requires -CaBundlePath (pass your company's CA even if you don't need a bundle merge, most corporate proxies need both)."
        exit 1
    }
    if ($HttpProxy) { $networkArgs["HttpProxy"] = $HttpProxy }
    if ($HttpsProxy) { $networkArgs["HttpsProxy"] = $HttpsProxy }
    & "$PSScriptRoot\configure-network.ps1" @networkArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "configure-network.ps1 failed -- fix that first, then re-run setup.ps1."
        exit 1
    }
}

Write-Step "Checking prerequisites"
$missing = @()
if (-not (Test-CommandExists "conda")) { $missing += "conda (install Miniconda: https://docs.conda.io/en/latest/miniconda.html)" }
if (-not (Test-CommandExists "git")) { $missing += "git (install Git for Windows: https://git-scm.com/download/win)" }
if ($missing.Count -gt 0) {
    Write-Fail "Missing prerequisites:"
    $missing | ForEach-Object { Write-Fail "  - $_" }
    Write-Fail "Install these, restart your terminal (so PATH updates take effect), then re-run this script."
    exit 1
}
Write-Ok "conda and git found."

if (-not $SkipBackend) {
    $envNamePattern = "^" + [regex]::Escape($CondaEnvName) + "\s"
    $envExists = (conda env list) -match $envNamePattern
    if ($envExists) {
        Invoke-Checked -Description "Updating existing conda environment '$CondaEnvName'" -ScriptBlock {
            conda env update -n $CondaEnvName -f (Join-Path $repoRoot "environment.yml") --prune
        }
    } else {
        Invoke-Checked -Description "Creating conda environment '$CondaEnvName' (Python 3.11 + Node 22)" -ScriptBlock {
            conda env create -n $CondaEnvName -f (Join-Path $repoRoot "environment.yml")
        }
    }

    Invoke-Checked -Description "Installing backend package (arp) in editable/dev mode" -ScriptBlock {
        conda run --no-capture-output -n $CondaEnvName python -m pip install -e "$(Join-Path $repoRoot 'backend')[dev]"
    }

    $backendEnvFile = Join-Path $repoRoot "backend\.env"
    $backendEnvExample = Join-Path $repoRoot "backend\.env.example"
    if (-not (Test-Path $backendEnvFile)) {
        Copy-Item $backendEnvExample $backendEnvFile
        Write-Ok "Created backend\.env from backend\.env.example -- edit it now and fill in ARP_ANTHROPIC_API_KEY."
    } else {
        Write-Warn "backend\.env already exists -- left untouched."
    }

    Invoke-Checked -Description "Installing the pre-commit secret-scanning hook" -ScriptBlock {
        Push-Location $repoRoot
        try {
            conda run --no-capture-output -n $CondaEnvName pre-commit install
        } finally {
            Pop-Location
        }
    }

    Write-Step "Running the backend test suite (no API key/network required)"
    Push-Location (Join-Path $repoRoot "backend")
    try {
        conda run --no-capture-output -n $CondaEnvName pytest -q
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Some backend tests failed -- see output above. This does not block setup, but investigate before relying on the pipeline."
        } else {
            Write-Ok "Backend test suite passed."
        }
    } finally {
        Pop-Location
    }

    Write-Step "Detecting the conda environment's Python interpreter (for VS Code)"
    $pythonPathLines = @(conda run --no-capture-output -n $CondaEnvName python -c "import sys; print(sys.executable)")
    $pythonPath = ($pythonPathLines | Select-Object -Last 1).Trim()
    if ($pythonPath) {
        # ConvertFrom-Json's -AsHashtable switch needs PowerShell 6+, but
        # Windows PowerShell 5.1 (still the default on many corporate
        # images) only has ConvertFrom-Json -> PSCustomObject. Setting an
        # existing NoteProperty via dot notation works on both, so
        # .vscode/settings.json ships with this key already present
        # (see that file) rather than being added here.
        $settingsPath = Join-Path $repoRoot ".vscode\settings.json"
        try {
            $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
            $settings."python.defaultInterpreterPath" = $pythonPath
            ($settings | ConvertTo-Json -Depth 10) | Set-Content -Path $settingsPath -Encoding utf8
            Write-Ok "Wrote python.defaultInterpreterPath = $pythonPath into .vscode\settings.json"
        } catch {
            Write-Warn "Could not update .vscode\settings.json automatically ($_). In VS Code, run 'Python: Select Interpreter' and pick: $pythonPath"
        }
    }
}

if (-not $SkipFrontend) {
    Invoke-Checked -Description "Installing frontend dependencies (npm install)" -ScriptBlock {
        Push-Location (Join-Path $repoRoot "frontend")
        try {
            conda run --no-capture-output -n $CondaEnvName npm install
        } finally {
            Pop-Location
        }
    }

    $frontendEnvFile = Join-Path $repoRoot "frontend\.env"
    $frontendEnvExample = Join-Path $repoRoot "frontend\.env.example"
    if (-not (Test-Path $frontendEnvFile)) {
        Copy-Item $frontendEnvExample $frontendEnvFile
        Write-Ok "Created frontend\.env from frontend\.env.example."
    } else {
        Write-Warn "frontend\.env already exists -- left untouched."
    }
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Magenta
Write-Host "  1. Edit backend\.env and set ARP_ANTHROPIC_API_KEY (see docs\INSTALLATION.md if your LLM provider differs)."
Write-Host "  2. Open this folder in VS Code, reload the window, and confirm the interpreter shown bottom-right is the '$CondaEnvName' conda environment."
Write-Host "  3. Run scripts\windows\check-setup.ps1 to verify everything end-to-end."
Write-Host "  4. Use the VS Code 'Run and Debug' panel (F5) -- 'Backend: FastAPI (debug, no reload)' and 'Frontend: Debug in browser' launch configs are pre-wired."
