<#
.SYNOPSIS
    Starts the Vite frontend dev server in the project's conda
    environment (needed so it uses the Node.js installed into that
    environment rather than requiring a separate system-wide Node
    install). Equivalent to the README's `npm run dev`.
#>
param(
    [string]$CondaEnvName = "arp"
)
. "$PSScriptRoot\common.ps1"
Push-Location (Join-Path (Get-RepoRoot) "frontend")
try {
    conda run --no-capture-output -n $CondaEnvName npm run dev
} finally {
    Pop-Location
}
