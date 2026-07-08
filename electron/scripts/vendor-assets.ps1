#requires -Version 5.1
<#
.SYNOPSIS
    Refresh the vendored front-end scripts (Tailwind runtime + marked) that
    src/static/index.html loads locally so the desktop UI works offline.
.DESCRIPTION
    These were previously loaded from cdn.tailwindcss.com and jsdelivr. Re-run
    this to pull newer versions, then rebuild the API image so the change ships.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$vendorDir = Join-Path $repoRoot "src/static/vendor"
New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null

$assets = @{
    "tailwind.js"    = "https://cdn.tailwindcss.com"
    "marked.min.js"  = "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
}

foreach ($name in $assets.Keys) {
    $dest = Join-Path $vendorDir $name
    Write-Host "==> Downloading $name ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $assets[$name] -OutFile $dest -UseBasicParsing
}
Write-Host "Vendored assets refreshed in $vendorDir." -ForegroundColor Green
