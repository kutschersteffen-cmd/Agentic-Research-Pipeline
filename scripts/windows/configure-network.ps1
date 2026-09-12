<#
.SYNOPSIS
    Configures Python/pip, conda, npm, and git to trust your company's
    TLS-inspecting proxy certificate, and (optionally) sets the corporate
    HTTP(S) proxy for all of them.

.DESCRIPTION
    Corporate networks commonly run outbound HTTPS through a proxy that
    re-signs every connection with an internal root CA ("SSL/TLS
    inspection"). Windows itself is usually configured (via Group Policy)
    to trust that CA, so curl.exe, Edge, and Invoke-WebRequest all work
    out of the box. Python, Node.js, and Git for Windows, however, ship
    their own CA bundles and ignore the Windows certificate store by
    default -- which is why `pip install`, `npm install`, and `git clone`
    fail with errors like "CERTIFICATE_VERIFY_FAILED" or "unable to get
    local issuer certificate" on a network where a plain browser works
    fine.

    This script:
      1. Downloads the current public Mozilla CA bundle using curl.exe
         (which already trusts the corporate proxy via the Windows
         certificate store, breaking the chicken-and-egg problem of
         needing a trusted bundle before you have one).
      2. Appends your company's root CA certificate(s) to it, producing
         one merged PEM bundle that validates both public internet sites
         and internally-proxied traffic.
      3. Points pip, conda, npm, git, and every Python HTTPS client
         (requests/httpx/urllib3, used by this project) at that bundle,
         and (optionally) configures the corporate proxy itself.

.PARAMETER CaBundlePath
    Path to your company's root CA certificate, or a folder containing
    one or more of them (.pem/.crt/.cer, PEM or DER encoding both
    supported). Ask your IT/security team for this -- it is NOT a
    secret, it's a public key used to verify connections, safe to copy
    onto any machine that needs it.

.PARAMETER HttpProxy
    Corporate proxy URL, e.g. http://proxy.mycompany.com:8080. Optional
    -- only needed if your network requires an explicit proxy (as
    opposed to transparent interception). Used for both HTTP and HTTPS
    unless -HttpsProxy is also given.

.PARAMETER HttpsProxy
    Overrides -HttpProxy for HTTPS traffic specifically. Optional.

.PARAMETER NoProxy
    Comma-separated hosts that should bypass the proxy. Defaults to
    localhost/127.0.0.1 so the backend/frontend dev servers stay
    reachable even with a proxy configured.

.EXAMPLE
    .\configure-network.ps1 -CaBundlePath C:\certs\corporate-root-ca.cer

.EXAMPLE
    .\configure-network.ps1 -CaBundlePath C:\certs -HttpProxy http://proxy.mycompany.com:8080
#>
param(
    [Parameter(Mandatory = $true)][string]$CaBundlePath,
    [string]$HttpProxy,
    [string]$HttpsProxy,
    [string]$NoProxy = "localhost,127.0.0.1,::1"
)

. "$PSScriptRoot\common.ps1"

if (-not (Test-Path $CaBundlePath)) {
    Write-Fail "Path not found: $CaBundlePath"
    exit 1
}

if (-not (Test-CommandExists "curl.exe")) {
    Write-Fail "curl.exe not found. It ships with Windows 10 1803+ / Windows 11 -- if it's missing, something unusual is going on with this machine; ask IT."
    exit 1
}

$arpHome = Join-Path $env:USERPROFILE ".arp"
New-Item -ItemType Directory -Force -Path $arpHome | Out-Null
$mergedBundle = Join-Path $arpHome "corporate-ca-bundle.pem"
$publicBundle = Join-Path $arpHome "mozilla-ca-bundle.pem"

Write-Step "Downloading the current public CA bundle via curl.exe (uses the Windows certificate store, so this works even before Python/npm/git trust your proxy)"
& curl.exe -fsSL "https://curl.se/ca/cacert.pem" -o $publicBundle
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $publicBundle) -or (Get-Item $publicBundle).Length -eq 0) {
    Write-Warn "Could not download the public CA bundle (curl exit code $LASTEXITCODE)."
    Write-Warn "Falling back to your corporate certificate(s) only -- public (non-proxied) HTTPS sites may then fail to validate."
    Write-Warn "If your proxy also blocks curl.se, ask IT for the standard Mozilla CA bundle file directly and re-run with a merged copy passed as -CaBundlePath."
    Set-Content -Path $publicBundle -Value "" -Encoding ascii
} else {
    Write-Ok "Public CA bundle downloaded."
}

function ConvertTo-PemText {
    param([string]$FilePath)
    $firstLine = Get-Content -Path $FilePath -TotalCount 1 -ErrorAction SilentlyContinue
    if ($firstLine -and $firstLine.Trim().StartsWith("-----BEGIN")) {
        return Get-Content -Path $FilePath -Raw
    }
    # Not PEM text -- assume a DER-encoded .cer/.crt and convert with
    # certutil, which ships with every Windows install (no extra tooling
    # needed, unlike openssl).
    $tempPem = [System.IO.Path]::GetTempFileName()
    & certutil.exe -encode "$FilePath" "$tempPem" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "certutil could not convert '$FilePath' to PEM. Ask IT for a PEM/Base64-encoded (.pem or Base64 .cer) copy of the certificate instead of DER binary."
    }
    $text = Get-Content -Path $tempPem -Raw
    Remove-Item $tempPem -ErrorAction SilentlyContinue
    return $text
}

Write-Step "Building the merged CA bundle at $mergedBundle"
$corporateCertFiles = @()
if (Test-Path $CaBundlePath -PathType Container) {
    # -Include/-Recurse together is unreliable on Windows PowerShell 5.1
    # unless -Path ends in a wildcard; filtering after the fact with
    # Where-Object avoids that pitfall entirely.
    $corporateCertFiles = Get-ChildItem -Path $CaBundlePath -File -Recurse |
        Where-Object { $_.Extension -in ".pem", ".crt", ".cer" } |
        Select-Object -ExpandProperty FullName
    if ($corporateCertFiles.Count -eq 0) {
        Write-Fail "No .pem/.crt/.cer files found under $CaBundlePath"
        exit 1
    }
} else {
    $corporateCertFiles = @($CaBundlePath)
}

$corporatePemText = ($corporateCertFiles | ForEach-Object {
    Write-Ok "Including corporate certificate: $_"
    ConvertTo-PemText -FilePath $_
}) -join "`n"

$publicPemText = Get-Content -Path $publicBundle -Raw
Set-Content -Path $mergedBundle -Value ($corporatePemText + "`n" + $publicPemText) -Encoding ascii
Write-Ok "Merged bundle written ($((Get-Item $mergedBundle).Length) bytes)."

Write-Step "Setting persistent environment variables (User scope -- restart VS Code / your terminal afterwards)"
$envVars = @{
    "SSL_CERT_FILE"      = $mergedBundle   # Python's ssl module, httpx, requests
    "REQUESTS_CA_BUNDLE" = $mergedBundle   # requests (also read by some LangChain/httpx setups)
    "PIP_CERT"           = $mergedBundle   # pip
    "NODE_EXTRA_CA_CERTS" = $mergedBundle  # Node.js/npm -- additive to Node's built-in bundle
    "CURL_CA_BUNDLE"     = $mergedBundle   # curl, and anything shelling out to it
}
foreach ($name in $envVars.Keys) {
    [Environment]::SetEnvironmentVariable($name, $envVars[$name], "User")
    Set-Item -Path "Env:$name" -Value $envVars[$name]   # also apply to this session
    Write-Ok "$name = $($envVars[$name])"
}

Write-Step "Configuring git to trust the corporate certificate"
if (Test-CommandExists "git") {
    git config --global http.sslCAInfo "$mergedBundle"
    Write-Ok "git config --global http.sslCAInfo set."
} else {
    Write-Warn "git not found on PATH -- skipped. Install Git for Windows first, then re-run this script."
}

Write-Step "Configuring npm to trust the corporate certificate"
if (Test-CommandExists "npm") {
    npm config set cafile "$mergedBundle" --global
    Write-Ok "npm config --global cafile set."
} else {
    Write-Warn "npm not found on PATH yet -- expected if you haven't run setup.ps1 (which installs Node via conda) yet. Run configure-network.ps1 again after setup.ps1 to apply this step (NODE_EXTRA_CA_CERTS is already set either way, which covers npm on its own)."
}

Write-Step "Configuring conda to trust the corporate certificate"
$condarcPath = Join-Path $env:USERPROFILE ".condarc"
$condarcLine = "ssl_verify: $($mergedBundle -replace '\\','/')"
if (Test-Path $condarcPath) {
    $content = Get-Content $condarcPath
    $content = $content | Where-Object { $_ -notmatch "^ssl_verify:" }
    Set-Content -Path $condarcPath -Value ($content + $condarcLine)
} else {
    Set-Content -Path $condarcPath -Value $condarcLine
}
Write-Ok "$condarcPath updated."

if ($HttpProxy -or $HttpsProxy) {
    $effectiveHttp = if ($HttpProxy) { $HttpProxy } else { $HttpsProxy }
    $effectiveHttps = if ($HttpsProxy) { $HttpsProxy } else { $HttpProxy }
    Write-Step "Configuring the corporate proxy"
    [Environment]::SetEnvironmentVariable("HTTP_PROXY", $effectiveHttp, "User")
    [Environment]::SetEnvironmentVariable("HTTPS_PROXY", $effectiveHttps, "User")
    [Environment]::SetEnvironmentVariable("NO_PROXY", $NoProxy, "User")
    $env:HTTP_PROXY = $effectiveHttp
    $env:HTTPS_PROXY = $effectiveHttps
    $env:NO_PROXY = $NoProxy
    Write-Ok "HTTP_PROXY = $effectiveHttp"
    Write-Ok "HTTPS_PROXY = $effectiveHttps"
    Write-Ok "NO_PROXY = $NoProxy"

    if (Test-CommandExists "git") {
        git config --global http.proxy $effectiveHttp
        git config --global https.proxy $effectiveHttps
        Write-Ok "git proxy configured."
    }
    if (Test-CommandExists "npm") {
        npm config set proxy $effectiveHttp --global
        npm config set https-proxy $effectiveHttps --global
        Write-Ok "npm proxy configured."
    }
    $condarcContent = Get-Content $condarcPath | Where-Object { $_ -notmatch "^proxy_servers:" -and $_ -notmatch "^\s+(http|https):" }
    $condarcContent += "proxy_servers:"
    $condarcContent += "  http: $effectiveHttp"
    $condarcContent += "  https: $effectiveHttps"
    Set-Content -Path $condarcPath -Value $condarcContent
    Write-Ok "conda proxy configured."
}

Write-Host ""
Write-Host "Done. Close and reopen VS Code / your terminal so the new environment variables take effect," -ForegroundColor Cyan
Write-Host "then run scripts\windows\setup.ps1 (or scripts\windows\check-setup.ps1 to verify)." -ForegroundColor Cyan
