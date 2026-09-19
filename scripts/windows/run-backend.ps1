<#
.SYNOPSIS
    Starts the FastAPI backend (uvicorn, auto-reload) in the project's
    conda environment. Equivalent to the README's
    `uvicorn arp.api.main:app --reload`, without needing to manually
    activate conda first.
#>
param(
    [string]$CondaEnvName = "arp"
)
. "$PSScriptRoot\common.ps1"
Push-Location (Join-Path (Get-RepoRoot) "backend")
try {
    conda run --no-capture-output -n $CondaEnvName uvicorn arp.api.main:app --reload
} finally {
    Pop-Location
}
