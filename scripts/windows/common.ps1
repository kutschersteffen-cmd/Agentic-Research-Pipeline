# Shared helpers for the scripts in this folder. Dot-sourced, never run
# directly: `. "$PSScriptRoot\common.ps1"`.

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "   [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "   [WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "   [FAIL] $Message" -ForegroundColor Red
}

# A textbook corporate-network failure signature: a TLS-inspecting proxy
# replaces the real certificate chain with one signed by an internal root
# CA that pip/npm/conda don't trust out of the box. Every network step in
# setup.ps1 pipes its output through this so a first-time user gets a
# pointer to configure-network.ps1 instead of a bare stack trace.
$script:CertErrorPatterns = @(
    "CERTIFICATE_VERIFY_FAILED",
    "unable to get local issuer certificate",
    "self signed certificate",
    "SSL: CERTIFICATE_VERIFY_FAILED",
    "unable to verify the first certificate",
    "SELF_SIGNED_CERT_IN_CHAIN",
    "certificate has expired"
)

function Test-CertificateErrorHint {
    param([string]$Output)
    foreach ($pattern in $script:CertErrorPatterns) {
        if ($Output -match [regex]::Escape($pattern)) {
            Write-Warn "This looks like a corporate TLS-interception certificate problem (matched: `"$pattern`")."
            Write-Warn "Run scripts\windows\configure-network.ps1 with your company's root CA certificate, then re-run this script."
            Write-Warn "See docs\INSTALLATION.md, section 'Corporate certificates', for details."
            return $true
        }
    }
    return $false
}

# Runs an external command, streams its output, and turns a non-zero exit
# code into a terminating error with a clear message -- PowerShell does
# NOT stop on a failing native command by default (unlike a failing
# cmdlet), so without this a broken `pip install` would be silently
# followed by the next step as if nothing happened.
#
# $ErrorActionPreference is switched to "Continue" for the duration of the
# call: with it left at "Stop" (the module default, set below), a native
# command's routine stderr lines (pip/npm print plenty of harmless
# warnings there) become terminating PowerShell errors on Windows
# PowerShell 5.1 the moment they're merged in via 2>&1, aborting a command
# that actually succeeded.
function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock
    )
    Write-Step $Description
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $lines = @(& $ScriptBlock 2>&1)
    $ErrorActionPreference = $previousEap
    $lines | ForEach-Object { Write-Host "   $_" }
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        Test-CertificateErrorHint -Output ($lines | Out-String) | Out-Null
        Write-Fail "$Description failed (exit code $LASTEXITCODE)."
        throw "Step failed: $Description"
    }
    Write-Ok "$Description done."
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
