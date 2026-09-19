<#
.SYNOPSIS
    Diagnoses the local setup: prerequisites, conda environment, backend
    package, frontend dependencies, .env files, certificate/proxy
    configuration, and connectivity to the services this project talks to.

.DESCRIPTION
    Run this any time something doesn't work and you're not sure why --
    it runs each check independently (one failing check doesn't stop the
    others) and prints a final PASS/FAIL summary, so you get the full
    picture in one go instead of fixing one error only to hit the next.

.PARAMETER CondaEnvName
    Name of the conda environment to check. Default: arp.
#>
param(
    [string]$CondaEnvName = "arp"
)

. "$PSScriptRoot\common.ps1"
$ErrorActionPreference = "Continue"
$repoRoot = Get-RepoRoot
$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param([string]$Name, [bool]$Passed, [string]$Detail = "")
    $results.Add([PSCustomObject]@{ Name = $Name; Passed = $Passed; Detail = $Detail })
    if ($Passed) { Write-Ok "$Name $Detail" } else { Write-Fail "$Name $Detail" }
}

Write-Host "Agentic Research Pipeline -- setup diagnostics" -ForegroundColor Magenta

Write-Step "Prerequisites"
Add-Result "conda on PATH" (Test-CommandExists "conda")
Add-Result "git on PATH" (Test-CommandExists "git")

Write-Step "Conda environment '$CondaEnvName'"
$envNamePattern = "^" + [regex]::Escape($CondaEnvName) + "\s"
$envExists = (conda env list 2>&1) -match $envNamePattern
Add-Result "conda env '$CondaEnvName' exists" ([bool]$envExists)

if ($envExists) {
    $pyVersionLines = @(conda run --no-capture-output -n $CondaEnvName python --version 2>&1)
    $pyVersion = ($pyVersionLines | Select-Object -Last 1)
    Add-Result "Python version" ($pyVersion -match "3\.11") $pyVersion

    $arpImport = @(conda run --no-capture-output -n $CondaEnvName python -c "import arp; print('ok')" 2>&1)
    Add-Result "backend package 'arp' importable" (($arpImport | Select-Object -Last 1) -eq "ok") ($arpImport | Select-Object -Last 1)

    $nodeVersionLines = @(conda run --no-capture-output -n $CondaEnvName node --version 2>&1)
    $nodeVersion = ($nodeVersionLines | Select-Object -Last 1)
    Add-Result "Node.js available in env" ($nodeVersion -match "^v\d+") $nodeVersion
} else {
    Write-Warn "Skipping Python/Node checks -- run scripts\windows\setup.ps1 first."
}

Write-Step "Config files"
$backendEnv = Join-Path $repoRoot "backend\.env"
$backendEnvExists = Test-Path $backendEnv
Add-Result "backend\.env exists" $backendEnvExists
if ($backendEnvExists) {
    $envContent = Get-Content $backendEnv -Raw
    $hasKey = $envContent -match "ARP_ANTHROPIC_API_KEY=\s*sk-ant-"
    Add-Result "ARP_ANTHROPIC_API_KEY looks filled in" $hasKey $(if (-not $hasKey) { "(still a placeholder, or a different provider is configured -- see docs\INSTALLATION.md)" })
}
Add-Result "frontend\.env exists" (Test-Path (Join-Path $repoRoot "frontend\.env"))

Write-Step "Frontend dependencies"
Add-Result "frontend\node_modules exists" (Test-Path (Join-Path $repoRoot "frontend\node_modules"))

Write-Step "Certificate / proxy configuration"
$certVars = @("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "PIP_CERT", "NODE_EXTRA_CA_CERTS")
$anyCertVarSet = $false
foreach ($v in $certVars) {
    $val = [Environment]::GetEnvironmentVariable($v, "User")
    if ($val) {
        $anyCertVarSet = $true
        Add-Result "$v set" (Test-Path $val) $val
    }
}
if (-not $anyCertVarSet) {
    Write-Warn "No corporate CA bundle env vars set. That's fine on an unrestricted network; if pip/npm install fail with a certificate error, run scripts\windows\configure-network.ps1 -- see docs\INSTALLATION.md."
}
$proxyVal = [Environment]::GetEnvironmentVariable("HTTPS_PROXY", "User")
if ($proxyVal) { Write-Ok "HTTPS_PROXY set: $proxyVal" } else { Write-Warn "HTTPS_PROXY not set (fine if your network doesn't require an explicit proxy)." }

Write-Step "Connectivity"
function Test-Https {
    param([string]$Url)
    try {
        $extraArgs = @()
        $bundle = [Environment]::GetEnvironmentVariable("CURL_CA_BUNDLE", "User")
        if ($bundle) { $extraArgs += @("--cacert", $bundle) }
        # "NUL" (Windows' null device), not PowerShell's $null -- passed
        # through to a native exe, $null stringifies to an empty argument
        # ("") rather than being omitted, which curl rejects as an empty
        # output filename.
        & curl.exe -fsSL --max-time 10 @extraArgs -o "NUL" $Url
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}
Add-Result "Reach api.anthropic.com" (Test-Https "https://api.anthropic.com") "(needed for the default Anthropic/Claude LLM provider)"
Add-Result "Reach pypi.org" (Test-Https "https://pypi.org")
Add-Result "Reach registry.npmjs.org" (Test-Https "https://registry.npmjs.org")
Add-Result "Reach www.sec.gov (EDGAR)" (Test-Https "https://www.sec.gov") "(optional -- only needed for the SEC EDGAR/XBRL data sources)"

Write-Host ""
Write-Host "Summary" -ForegroundColor Magenta
$failed = $results | Where-Object { -not $_.Passed }
foreach ($r in $results) {
    $marker = if ($r.Passed) { "[OK]  " } else { "[FAIL]" }
    $color = if ($r.Passed) { "Green" } else { "Red" }
    Write-Host "$marker $($r.Name)" -ForegroundColor $color
}
Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$($failed.Count) check(s) failed -- see docs\INSTALLATION.md, section 'Troubleshooting', for each of these." -ForegroundColor Red
    exit 1
}
