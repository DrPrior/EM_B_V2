#requires -Version 5.1
<#
.SYNOPSIS
    Build the heavy release assets the desktop wizard downloads on first run:
    the prebuilt API image tar, the Neo4j graph snapshot, and the project_data
    corpus archive. Computes SHA-256s and updates electron/resources/assets.manifest.json.

.DESCRIPTION
    Run this on a maintainer machine that already has a fully built + enriched
    graph (ingest -> load_manifest -> enrich) and the project_data corpus on disk.
    Upload the three files in the output dir to your internal release host, then
    set the matching url fields in assets.manifest.json (a -BaseUrl fills them in).

    Outputs (in -OutDir):
      emb-hybrid-api-<Version>.tar.gz   docker save | gzip of the prod image
      neo4j.dump                        Neo4j snapshot (via scripts/export-graph.ps1)
      project_data.tar.gz              the source corpus

.PARAMETER Version
    Image/app version tag. The desktop compose runs emb-hybrid-api:<Version> and
    APP_VERSION must equal this. Defaults to the version already in the manifest.

.PARAMETER BaseUrl
    Optional. If given, the manifest url fields are set to
    <BaseUrl>/<filename> for you.

.PARAMETER OutDir
    Output directory. Defaults to <repo>/release.

.EXAMPLE
    pwsh -File electron/scripts/build-release.ps1 -Version 0.1.0 -BaseUrl https://host/emb-hybrid
#>
[CmdletBinding()]
param(
    [string]$Version,
    [string]$BaseUrl,
    [string]$OutDir
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$manifestPath = Join-Path $repoRoot "electron/resources/assets.manifest.json"
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
if (-not $Version) { $Version = $manifest.image.version }
if (-not $OutDir)  { $OutDir  = Join-Path $repoRoot "release" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$tag = "emb-hybrid-api:$Version"

function Get-Sha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

function Compress-Gzip([string]$Source, [string]$Dest) {
    $in  = [System.IO.File]::OpenRead($Source)
    $out = [System.IO.File]::Create($Dest)
    $gz  = New-Object System.IO.Compression.GzipStream($out, [System.IO.Compression.CompressionMode]::Compress)
    try { $in.CopyTo($gz) } finally { $gz.Dispose(); $out.Dispose(); $in.Dispose() }
}

Write-Host "==> [1/3] Building prod image $tag ..." -ForegroundColor Cyan
docker build -f Dockerfile.prod -t $tag .
if ($LASTEXITCODE -ne 0) { throw "docker build failed." }

$tmpTar   = Join-Path $OutDir "emb-hybrid-api-$Version.tar"
$imageOut = Join-Path $OutDir "emb-hybrid-api-$Version.tar.gz"
Write-Host "==> Saving + gzipping image ..." -ForegroundColor Cyan
docker save $tag -o $tmpTar
if ($LASTEXITCODE -ne 0) { throw "docker save failed." }
Compress-Gzip $tmpTar $imageOut
Remove-Item $tmpTar

Write-Host "==> [2/3] Exporting Neo4j snapshot ..." -ForegroundColor Cyan
& (Join-Path $repoRoot "scripts/export-graph.ps1")
$dumpSrc = Join-Path $repoRoot "snapshot/neo4j.dump"
if (-not (Test-Path $dumpSrc)) { throw "export-graph.ps1 did not produce snapshot/neo4j.dump" }
$dumpOut = Join-Path $OutDir "neo4j.dump"
Copy-Item $dumpSrc $dumpOut -Force

Write-Host "==> [3/3] Archiving project_data ..." -ForegroundColor Cyan
$dataOut = Join-Path $OutDir "project_data.tar.gz"
# bsdtar (Windows 10+/macOS). -C so the archive holds project_data/... paths that
# match the container's /app/project_data mount root.
tar -czf $dataOut -C $repoRoot project_data
if ($LASTEXITCODE -ne 0) { throw "tar of project_data failed." }

Write-Host "==> Updating manifest checksums ..." -ForegroundColor Cyan
$manifest.image.version = $Version
$manifest.image.sha256       = Get-Sha256 $imageOut
$manifest.snapshot.sha256    = Get-Sha256 $dumpOut
$manifest.projectData.sha256 = Get-Sha256 $dataOut
if ($BaseUrl) {
    $b = $BaseUrl.TrimEnd('/')
    $manifest.image.url       = "$b/emb-hybrid-api-$Version.tar.gz"
    $manifest.snapshot.url    = "$b/neo4j.dump"
    $manifest.projectData.url = "$b/project_data.tar.gz"
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content $manifestPath -Encoding UTF8

Write-Host ""
Write-Host "Done. Assets in $OutDir :" -ForegroundColor Green
Get-ChildItem $OutDir | Select-Object Name, @{n='SizeMB';e={[math]::Round($_.Length/1MB,1)}} | Format-Table
Write-Host "Next: upload these to your release host and (if you didn't pass -BaseUrl) set the url fields in $manifestPath." -ForegroundColor Green
