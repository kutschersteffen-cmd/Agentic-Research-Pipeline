<#
.SYNOPSIS
    One-command bootstrap for the Agentic Research Pipeline on a fresh
    Windows machine: execution policy, prerequisites, corporate
    certificates, environment setup, API key, and a final health check.

.DESCRIPTION
    setup.ps1 assumes you have already cleared three hurdles that come
    before it and that it deliberately does not touch: PowerShell's
    execution policy (which blocks running any .ps1 at all on a default
    profile), the mark-of-the-web on files extracted from a zip, and
    having git + conda installed and on PATH. This script covers those,
    then hands over to the existing scripts for everything else.

    It is the "I just got this machine" entry point. If your environment
    already works, run setup.ps1 directly instead -- this adds nothing
    for you.

    Ordering matters and is not arbitrary: prerequisites must exist
    before the network is configured, the network must be trusted before
    conda/pip/npm touch it, and the API key is only useful once the
    package that reads it is installed. Each stage is idempotent and
    safe to re-run.

    IMPORTANT -- the chicken-and-egg problem: on a default Windows
    profile you cannot run this script by double-clicking or by typing
    .\bootstrap.ps1, because the execution policy it is meant to fix is
    what blocks it. Launch it once like this, which bypasses the policy
    for that single process only and changes nothing permanently:

        powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap.ps1

    After that first run every other script in this folder runs normally.

.PARAMETER CondaEnvName
    Conda environment name to create/update. Default: arp. Forwarded to
    setup.ps1 and check-setup.ps1.

.PARAMETER CaBundlePath
    Your company's root CA certificate (.pem/.crt/.cer). Required if your
    network does TLS inspection -- see docs\INSTALLATION.md. Forwarded to
    configure-network.ps1 via setup.ps1.

.PARAMETER HttpProxy
    Explicit corporate proxy URL, e.g. http://proxy.mycompany.com:8080.
    Requires -CaBundlePath.

.PARAMETER HttpsProxy
    As -HttpProxy, for HTTPS traffic if it differs.

.PARAMETER InstallPrerequisites
    Install missing prerequisites (Git, Miniconda, VS Code) via winget.
    Off by default: installing software is not something a setup script
    should do without being asked. Requires winget (ships with Windows 11
    and recent Windows 10; otherwise install them by hand from the links
    this script prints).

.PARAMETER SkipApiKeyPrompt
    Do not prompt for ARP_ANTHROPIC_API_KEY. Use this for an unattended
    run, or if you would rather edit backend\.env yourself.

.PARAMETER SkipFrontend
    Backend only. Forwarded to setup.ps1.

.PARAMETER SkipBackend
    Frontend only. Forwarded to setup.ps1.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap.ps1

.EXAMPLE
    # Fresh machine on a TLS-inspecting corporate network:
    powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap.ps1 `
        -InstallPrerequisites -CaBundlePath C:\certs\corporate-root-ca.cer
#>
param(
    [string]$CondaEnvName = "arp",
    [string]$CaBundlePath,
    [string]$HttpProxy,
    [string]$HttpsProxy,
    [switch]$InstallPrerequisites,
    [switch]$SkipApiKeyPrompt,
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

. "$PSScriptRoot\common.ps1"
$repoRoot = Get-RepoRoot

Write-Host ""
Write-Host "Agentic Research Pipeline -- Windows bootstrap" -ForegroundColor Magenta
Write-Host "Repository root: $repoRoot"
Write-Host ""

# A prerequisite installed during this run lands on the machine's PATH,
# but not in the PATH this already-running process inherited. Rather than
# pretend otherwise, we stop and say so.
$restartRequired = $false

# ---------------------------------------------------------------------------
# 1. Execution policy
# ---------------------------------------------------------------------------
# Only CurrentUser is touched: it needs no admin rights and cannot affect
# anyone else on the machine. RemoteSigned lets local scripts run while
# still requiring a signature on anything downloaded -- the usual
# recommendation, and strictly narrower than Unrestricted or Bypass.
Write-Step "Checking PowerShell execution policy"
$userPolicy = Get-ExecutionPolicy -Scope CurrentUser
if ($userPolicy -in @("RemoteSigned", "Unrestricted", "Bypass")) {
    Write-Ok "CurrentUser execution policy is '$userPolicy' -- scripts in this folder can run."
} else {
    try {
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
        Write-Ok "Set CurrentUser execution policy to RemoteSigned (was '$userPolicy')."
    } catch {
        Write-Warn "Could not set the execution policy: $($_.Exception.Message)"
        Write-Warn "This is often locked by corporate Group Policy. You can still run each"
        Write-Warn "script with:  powershell -ExecutionPolicy Bypass -File .\scripts\windows\<script>.ps1"
    }
}

# A machine-wide policy set by Group Policy overrides the user scope, so
# report it rather than let the user think the step above was enough.
$effectivePolicy = Get-ExecutionPolicy
if ($effectivePolicy -in @("Restricted", "AllSigned")) {
    Write-Warn "The *effective* policy is still '$effectivePolicy' (set at a higher scope, usually Group Policy)."
    Write-Warn "Keep using the -ExecutionPolicy Bypass form above for every script in this folder."
}

# ---------------------------------------------------------------------------
# 2. Mark-of-the-web
# ---------------------------------------------------------------------------
# Files extracted from a downloaded zip carry a Zone.Identifier stream;
# PowerShell then refuses them under RemoteSigned even though they are
# local. A git clone never sets this, so this is usually a no-op.
Write-Step "Clearing the mark-of-the-web from scripts\windows"
try {
    Get-ChildItem -Path $PSScriptRoot -Filter *.ps1 | Unblock-File -ErrorAction Stop
    Write-Ok "Scripts unblocked (no-op if they came from a git clone)."
} catch {
    Write-Warn "Could not unblock scripts: $($_.Exception.Message)"
}

# ---------------------------------------------------------------------------
# 3. Prerequisites
# ---------------------------------------------------------------------------
Write-Step "Checking prerequisites"

$prereqs = @(
    @{ Name = "git";   Command = "git";   WingetId = "Git.Git";               Url = "https://git-scm.com/download/win";                    Required = $true  },
    @{ Name = "conda"; Command = "conda"; WingetId = "Anaconda.Miniconda3";   Url = "https://docs.conda.io/en/latest/miniconda.html";      Required = $true  },
    @{ Name = "VS Code"; Command = "code"; WingetId = "Microsoft.VisualStudioCode"; Url = "https://code.visualstudio.com/";                Required = $false }
)

$missing = @($prereqs | Where-Object { -not (Test-CommandExists $_.Command) })
$missingRequired = @($missing | Where-Object { $_.Required })

if ($missing.Count -eq 0) {
    Write-Ok "git, conda and VS Code are all on PATH."
} else {
    foreach ($p in $missing) {
        $label = if ($p.Required) { "missing" } else { "missing (optional)" }
        Write-Warn "$($p.Name) is $label -- $($p.Url)"
    }

    if ($InstallPrerequisites) {
        if (-not (Test-CommandExists "winget")) {
            Write-Fail "-InstallPrerequisites was given but winget is not available on this machine."
            Write-Fail "Install the tools above by hand from their URLs, then re-run this script."
            exit 1
        }
        foreach ($p in $missing) {
            Invoke-Checked -Description "Installing $($p.Name) via winget" -ScriptBlock {
                winget install --id $p.WingetId --exact --silent `
                    --accept-package-agreements --accept-source-agreements
            }
        }
        $restartRequired = $true
    } elseif ($missingRequired.Count -gt 0) {
        Write-Fail "Install the required prerequisites above, then re-run this script."
        Write-Fail "Or re-run with -InstallPrerequisites to install them via winget."
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 4. conda init
# ---------------------------------------------------------------------------
# Without this, `conda activate` only works from the separate "Anaconda
# Prompt". It edits the PowerShell profile, so it needs a new shell too.
if (-not $restartRequired -and (Test-CommandExists "conda")) {
    Write-Step "Checking conda's PowerShell integration"
    $profileHasConda = (Test-Path $PROFILE) -and
                       (Select-String -Path $PROFILE -Pattern "conda" -Quiet -ErrorAction SilentlyContinue)
    if ($profileHasConda) {
        Write-Ok "conda is already initialised for PowerShell."
    } else {
        Invoke-Checked -Description "Initialising conda for PowerShell (conda init powershell)" -ScriptBlock {
            conda init powershell
        }
        Write-Warn "conda edited your PowerShell profile -- that only takes effect in a new shell."
        $restartRequired = $true
    }
}

if ($restartRequired) {
    Write-Host ""
    Write-Host "----------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host " Close this window, open a NEW PowerShell, and re-run this script." -ForegroundColor Yellow
    Write-Host " PATH and profile changes do not reach an already-running shell," -ForegroundColor Yellow
    Write-Host " so continuing now would fail in a confusing way." -ForegroundColor Yellow
    Write-Host "----------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

# ---------------------------------------------------------------------------
# 5. Environment setup (delegated)
# ---------------------------------------------------------------------------
# setup.ps1 runs configure-network.ps1 itself when handed -CaBundlePath,
# so the certificate is trusted before conda/pip/npm reach the network.
Write-Step "Handing over to setup.ps1"
$setupArgs = @{ CondaEnvName = $CondaEnvName }
if ($CaBundlePath) { $setupArgs["CaBundlePath"] = $CaBundlePath }
if ($HttpProxy)    { $setupArgs["HttpProxy"]    = $HttpProxy }
if ($HttpsProxy)   { $setupArgs["HttpsProxy"]   = $HttpsProxy }
if ($SkipFrontend) { $setupArgs["SkipFrontend"] = $true }
if ($SkipBackend)  { $setupArgs["SkipBackend"]  = $true }

# Reset first: $LASTEXITCODE is global and sticky, so without this a
# non-zero value left by some earlier native command would look like a
# setup.ps1 failure. setup.ps1 ends with an explicit `exit 0` so that the
# check below means what it says.
$global:LASTEXITCODE = 0
try {
    & "$PSScriptRoot\setup.ps1" @setupArgs
} catch {
    Write-Fail "setup.ps1 failed: $($_.Exception.Message)"
    Write-Fail "Nothing below this point has run."
    exit 1
}
if ($LASTEXITCODE -ne 0) {
    Write-Fail "setup.ps1 failed -- see its output above. Nothing below this point has run."
    exit 1
}

# ---------------------------------------------------------------------------
# 6. API key
# ---------------------------------------------------------------------------
# Read as a SecureString so it is never echoed to the terminal and never
# lands in PSReadLine history. It is still written to backend\.env in
# plain text -- that is what the app reads, and .env is git-ignored.
if (-not $SkipApiKeyPrompt -and -not $SkipBackend) {
    Write-Step "Anthropic API key"
    $envFile = Join-Path $repoRoot "backend\.env"

    if (-not (Test-Path $envFile)) {
        Write-Warn "backend\.env not found -- setup.ps1 should have created it. Skipping."
    } else {
        $envLines = @(Get-Content $envFile)
        $keyLine = $envLines | Where-Object { $_ -match "^\s*ARP_ANTHROPIC_API_KEY\s*=" } | Select-Object -First 1
        $currentValue = if ($keyLine) { ($keyLine -split "=", 2)[1].Trim().Trim('"') } else { "" }
        # A real key is long and starts with the Anthropic prefix; the
        # shipped placeholder and the usual hand-typed stand-ins are not.
        $looksReal = $currentValue.StartsWith("sk-ant-") -and
                     $currentValue.Length -gt 20 -and
                     $currentValue -notmatch "x{4,}"

        if ($looksReal) {
            Write-Ok "ARP_ANTHROPIC_API_KEY already set in backend\.env -- left untouched."
        } else {
            Write-Host "   Anthropic is currently the only supported LLM provider; the app"
            Write-Host "   raises immediately without this key. Get one at:"
            Write-Host "     https://console.anthropic.com/settings/keys"
            Write-Host "   Press Enter to skip and fill in backend\.env yourself later."
            $secure = Read-Host "   ARP_ANTHROPIC_API_KEY" -AsSecureString
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try {
                $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            } finally {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
            }

            if ([string]::IsNullOrWhiteSpace($plain)) {
                Write-Warn "No key entered -- edit backend\.env before running the app."
            } else {
                # Built line by line rather than with -replace: in a
                # replacement string `$` introduces a capture-group
                # reference, so a key containing one would be silently
                # mangled.
                $newLine = "ARP_ANTHROPIC_API_KEY=" + $plain
                if ($keyLine) {
                    $updated = @($envLines | ForEach-Object {
                        if ($_ -match "^\s*ARP_ANTHROPIC_API_KEY\s*=") { $newLine } else { $_ }
                    })
                } else {
                    $updated = @($envLines) + $newLine
                }
                # UTF8 without BOM: a BOM on the first line would become part
                # of the first variable's name for some .env readers.
                [IO.File]::WriteAllLines($envFile, $updated, (New-Object Text.UTF8Encoding $false))
                Write-Ok "Wrote ARP_ANTHROPIC_API_KEY to backend\.env (the value was never printed)."
            }
            $plain = $null
        }
    }
}

# ---------------------------------------------------------------------------
# 7. Health check
# ---------------------------------------------------------------------------
Write-Step "Running the health check"
$global:LASTEXITCODE = 0
& "$PSScriptRoot\check-setup.ps1" -CondaEnvName $CondaEnvName
$checkExit = $LASTEXITCODE

Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
if ($checkExit -eq 0) {
    Write-Host " Bootstrap complete." -ForegroundColor Green
} else {
    Write-Host " Bootstrap finished, but check-setup.ps1 reported problems." -ForegroundColor Yellow
    Write-Host " Read its PASS/FAIL summary above -- docs\INSTALLATION.md has a" -ForegroundColor Yellow
    Write-Host " troubleshooting table keyed by symptom." -ForegroundColor Yellow
}
Write-Host ""
Write-Host " Start the app in two terminals:"
Write-Host "   .\scripts\windows\run-backend.ps1     # http://localhost:8000"
Write-Host "   .\scripts\windows\run-frontend.ps1    # http://localhost:5173"
Write-Host "================================================================" -ForegroundColor Magenta

exit $checkExit
