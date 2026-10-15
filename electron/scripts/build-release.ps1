#requires -Version 5.1
<#
.SYNOPSIS
    Build the native release assets the desktop wizard unpacks on first run:
    the frozen API bundle, Neo4j Community + JRE, the graph dump, and the
    project_data corpus. Computes SHA-256s and updates
    electron/resources/assets.manifest.json.

.DESCRIPTION
    Decontainerized build (no Docker image). USB delivery, no download server.
    Run on a maintainer machine that has: the Python deps installed (for
    PyInstaller), a Neo4j Community 2026.08.x home staged by scripts/stage-neo4j.ps1, a JRE, and
    the aligned graph dump produced by the migration (see docs/DECONTAINERIZE_PLAN.md).

    Outputs (in -OutDir, default <repo>/release), copied onto the USB as `assets/`:
      emb-api.zip            PyInstaller one-dir bundle (emb-api.exe + _internal/ at root)
      neo4j-community.zip    Neo4j Community server (bin/, conf/, ... at root)
      jre.zip                bundled JRE (bin/java at root)
      neo4j.dump             the prebuilt graph (record/aligned format, Community-loadable)
      project_data.tar.gz    the source corpus (top-level project_data/)

    Contract with electron/lib/firstrun.js + paths.js: each zip must unpack with
    its contents at the ROOT (no extra top folder), so it lands at
    <userData>/api, <userData>/neo4j, <userData>/jre respectively.

    Records each file's name + SHA-256 in electron/resources/assets.manifest.json.
    Rebuild the installers afterward (npm run dist:win) so the manifest ships.

.PARAMETER Neo4jHome
    Path to a pre-configured Neo4j Community install (bolt/http bound to
    127.0.0.1). Its CONTENTS are zipped to neo4j-community.zip. Required.

.PARAMETER JreHome
    Path to a JRE home (contains bin/java). Zipped to jre.zip. Required.

.PARAMETER DumpPath
    The graph dump to ship. Defaults to <repo>/release/neo4j.dump (the aligned
    dump from the migration). MUST be a Community-loadable record format, not
    Enterprise `block`.

.PARAMETER Version
    App/asset version. Defaults to the version in the manifest.

.PARAMETER OutDir
    Output directory. Defaults to <repo>/release. Copy onto the USB as `assets`.

.PARAMETER Python
    Python interpreter used to run PyInstaller. Must be the environment that has
    the app's runtime deps AND PyInstaller (on the maintainer box: the pyAI conda
    env). Defaults to the active conda env's python if one is activated, else
    "python" — which on a machine with a system Python on PATH is usually the
    wrong one. The script checks before freezing and says so.

.PARAMETER CertSubject
    If given, code-sign emb-api.exe with this certificate subject via signtool
    BEFORE zipping (so the unpacked exe clears WDAC). If omitted, the bundle is
    shipped UNSIGNED and the script warns — WDAC will block it on the fleet.

.EXAMPLE
    pwsh -File electron/scripts/build-release.ps1 -Neo4jHome C:\stage\neo4j -JreHome C:\stage\jre `
      -Python "$env:USERPROFILE\.conda\envs\pyAI\python.exe"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Neo4jHome,
    [Parameter(Mandatory = $true)][string]$JreHome,
    [string]$DumpPath,
    [string]$Version,
    [string]$OutDir,
    [string]$Python = $(if ($env:CONDA_PREFIX) { Join-Path $env:CONDA_PREFIX "python.exe" } else { "python" }),
    [string]$CertSubject
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$manifestPath = Join-Path $repoRoot "electron/resources/assets.manifest.json"
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
if (-not $Version)  { $Version  = $manifest.version }
if (-not $OutDir)   { $OutDir   = Join-Path $repoRoot "release" }
if (-not $DumpPath) { $DumpPath = Join-Path $repoRoot "release/neo4j.dump" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-Sha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

# Zip a directory's CONTENTS (items land at the archive root, not under the dir).
function Compress-Contents([string]$SourceDir, [string]$Dest) {
    if (-not (Test-Path $SourceDir)) { throw "Not found: $SourceDir" }
    if (Test-Path $Dest) { Remove-Item $Dest -Force }
    Compress-Archive -Path (Join-Path $SourceDir '*') -DestinationPath $Dest -Force
}

# ── 0. Preflight: is $Python the app's environment? ─────────────────────────
# Two failure modes, one silent. A Python without PyInstaller fails loudly but
# unhelpfully. A Python WITH PyInstaller but without the app's deps is worse:
# PyInstaller only warns about unresolvable imports, so the freeze "succeeds"
# and ships a bundle that dies on first launch. Importing the app itself checks
# exactly what the freeze will pull in; the parsers are named too because the
# ingest pipeline imports them lazily, inside functions.
Write-Host "==> [0/5] Checking the Python environment ($Python) ..." -ForegroundColor Cyan
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python not found: '$Python'. Pass -Python <env>\python.exe (on this machine, the pyAI conda env)."
}
$pyiVersion = & $Python -m PyInstaller --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw ("'$Python' has no PyInstaller. Pass -Python pointing at the app's environment, e.g.`n" +
           "  -Python `"$env:USERPROFILE\.conda\envs\pyAI\python.exe`"`n" +
           "or install it there: <that python> -m pip install -r requirements-dev.txt")
}
$probe = & $Python -c "import src.main, pypdf, docx, pptx, cryptography" 2>&1
if ($LASTEXITCODE -ne 0) {
    $why = ($probe | Select-Object -Last 1)
    throw ("'$Python' cannot import the app ($why). Freezing from it would ship a broken " +
           "bundle. Use the environment the API runs in (-Python <env>\python.exe).")
}
Write-Host "    PyInstaller $pyiVersion; app imports OK" -ForegroundColor DarkGray

# ── 1. Freeze the API (PyInstaller one-dir) ─────────────────────────────────
Write-Host "==> [1/5] Freezing the API (pyinstaller emb-api.spec) ..." -ForegroundColor Cyan
& $Python -m PyInstaller (Join-Path $repoRoot "emb-api.spec") --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
$apiDist = Join-Path $repoRoot "dist/emb-api"
$apiExe  = Join-Path $apiDist "emb-api.exe"
if (-not (Test-Path $apiExe)) { throw "PyInstaller did not produce $apiExe." }

# Code signing (WDAC): sign the exe BEFORE zipping so the unpacked file runs on
# the fleet. Deferred until the UALR certificate is available.
if ($CertSubject) {
    Write-Host "==> Signing emb-api.exe ($CertSubject) ..." -ForegroundColor Cyan
    signtool sign /fd sha256 /n $CertSubject `
        /tr "http://timestamp.digicert.com" /td sha256 $apiExe
    if ($LASTEXITCODE -ne 0) { throw "signtool failed on emb-api.exe." }
} else {
    Write-Warning ("emb-api.exe is UNSIGNED. WDAC enforcement will refuse to run it on " +
        "managed machines. Re-run with -CertSubject once the UALR code-signing " +
        "certificate is available (may also need to sign _internal\*.dll depending on policy).")
}

$apiOut = Join-Path $OutDir "emb-api.zip"
Write-Host "==> Zipping API bundle -> emb-api.zip ..." -ForegroundColor Cyan
Compress-Contents $apiDist $apiOut

# ── 2. Neo4j Community + JRE ────────────────────────────────────────────────
Write-Host "==> [2/5] Zipping Neo4j Community -> neo4j-community.zip ..." -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $Neo4jHome "bin"))) { throw "$Neo4jHome does not look like a Neo4j home (no bin/)." }

# The zip takes this home's CONTENTS, so anything under data\ ships to every
# user. Refuse the two that matter rather than discovering them in the field:
# an auth.ini is a credential in the bundle (`dbms set-initial-password` ignores
# --additional-config and always writes into the Neo4j home), and a populated
# store is ~140 MB duplicating the neo4j.dump that snapshot.js loads over it
# anyway. scripts/stage-neo4j.ps1 leaves the home clean; this is the backstop.
$authIni = Join-Path $Neo4jHome "data\dbms\auth.ini"
if (Test-Path $authIni) {
    throw ("$Neo4jHome carries data\dbms\auth.ini — that credential would ship to every user. " +
           "Delete data\ and re-stage (scripts/stage-neo4j.ps1).")
}
$stagedStore = Join-Path $Neo4jHome "data\databases\neo4j"
if ((Test-Path $stagedStore) -and @(Get-ChildItem $stagedStore -Force -ErrorAction SilentlyContinue).Count -gt 0) {
    throw ("$Neo4jHome carries a populated data\databases\neo4j — the graph already ships as " +
           "neo4j.dump, and first run overwrites this copy. Delete data\ and re-stage.")
}

$neo4jOut = Join-Path $OutDir "neo4j-community.zip"
Compress-Contents $Neo4jHome $neo4jOut

Write-Host "==> [3/5] Zipping JRE -> jre.zip ..." -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $JreHome "bin"))) { throw "$JreHome does not look like a JRE home (no bin/)." }
$jreOut = Join-Path $OutDir "jre.zip"
Compress-Contents $JreHome $jreOut

# ── 3. Graph dump (must be record/aligned, not block) ───────────────────────
Write-Host "==> [4/5] Staging graph dump -> neo4j.dump ..." -ForegroundColor Cyan
if (-not (Test-Path $DumpPath)) { throw "Dump not found: $DumpPath. Produce it via the block->aligned migration first." }
$dumpOut = Join-Path $OutDir "neo4j.dump"
if ($DumpPath -ne $dumpOut) { Copy-Item $DumpPath $dumpOut -Force }

# ── 4. Source corpus ────────────────────────────────────────────────────────
Write-Host "==> [5/5] Archiving project_data -> project_data.tar.gz ..." -ForegroundColor Cyan
$dataOut = Join-Path $OutDir "project_data.tar.gz"
tar -czf $dataOut -C $repoRoot project_data
if ($LASTEXITCODE -ne 0) { throw "tar of project_data failed." }

# Drop any stale Docker image tar from a previous (containerized) build.
Get-ChildItem $OutDir -Filter "emb-hybrid-api-*.tar.gz" -ErrorAction SilentlyContinue | Remove-Item -Force

# ── 5. Update the manifest ──────────────────────────────────────────────────
Write-Host "==> Updating manifest (filenames + checksums) ..." -ForegroundColor Cyan
$manifest.version           = $Version
$manifest.apiBundle.file    = "emb-api.zip"
$manifest.apiBundle.sha256  = Get-Sha256 $apiOut
$manifest.neo4j.file        = "neo4j-community.zip"
$manifest.neo4j.sha256      = Get-Sha256 $neo4jOut
$manifest.jre.file          = "jre.zip"
$manifest.jre.sha256        = Get-Sha256 $jreOut
$manifest.snapshot.file     = "neo4j.dump"
$manifest.snapshot.sha256   = Get-Sha256 $dumpOut
$manifest.projectData.file  = "project_data.tar.gz"
$manifest.projectData.sha256 = Get-Sha256 $dataOut
$manifest | ConvertTo-Json -Depth 6 | Set-Content $manifestPath -Encoding UTF8

Write-Host ""
Write-Host "Done. Assets in $OutDir :" -ForegroundColor Green
Get-ChildItem $OutDir | Select-Object Name, @{n='SizeMB';e={[math]::Round($_.Length/1MB,1)}} | Format-Table
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "  1. Rebuild installers (cd electron; npm run dist:win) so the updated manifest ships." -ForegroundColor Green
Write-Host "  2. Stage onto the USB: pwsh -File scripts/stage-usb.ps1 -Destination E:\ -Verify" -ForegroundColor Green
if (-not $CertSubject) {
    Write-Warning "Shipped bundle is UNSIGNED - it will not run under WDAC. Sign before distribution."
}
