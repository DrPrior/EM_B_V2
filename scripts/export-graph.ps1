#requires -Version 5.1
<#
.SYNOPSIS
    Export the Neo4j graph (all nodes, embeddings, and the vector index config)
    to a single portable snapshot/neo4j.dump so it can be shared with a coworker.

.DESCRIPTION
    The graph lives in the named Docker volume em_b_v2_neo4j_data, which is NOT
    part of the repo. To let a coworker run the app without re-running the whole
    ingest -> load_manifest -> enrich pipeline, ship them a dump of the database
    alongside the code.

    This uses Neo4j's official offline dump format (neo4j-admin database dump),
    which is version-tolerant within a Neo4j major line. Community edition
    requires the database offline, so this script stops the neo4j service, runs
    the dump in a throwaway container that shares the same data volume, then
    restarts neo4j.

    The coworker restores it with import-graph.ps1 before their first
    `docker compose up`.

    NOTE: both machines must run the SAME pinned Neo4j image (see the `image:`
    line in docker-compose.yml). A dump is portable across patch versions but
    not across major store-format changes.

.PARAMETER Database
    The database name to dump. Defaults to "neo4j" (the app's only database).

.PARAMETER KeepStopped
    Leave the neo4j service stopped after the dump instead of restarting it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\export-graph.ps1
#>
[CmdletBinding()]
param(
    [string]$Database = "neo4j",
    [switch]$KeepStopped
)

$ErrorActionPreference = "Stop"

# Run from the repo root regardless of where the script is invoked from.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$snapshotDir = Join-Path $repoRoot "snapshot"
if (-not (Test-Path $snapshotDir)) {
    New-Item -ItemType Directory -Path $snapshotDir | Out-Null
}

Write-Host "==> Stopping neo4j (dump requires the database offline)..." -ForegroundColor Cyan
docker compose stop neo4j
if ($LASTEXITCODE -ne 0) { throw "docker compose stop neo4j failed." }

try {
    Write-Host "==> Dumping database '$Database' to snapshot/$Database.dump ..." -ForegroundColor Cyan
    # Throwaway container shares the neo4j_data volume; --no-deps so it doesn't
    # drag the api service up. Mount the host snapshot dir as the dump target.
    docker compose run --rm --no-deps -v "${snapshotDir}:/snapshot" neo4j `
        neo4j-admin database dump $Database --to-path=/snapshot --overwrite-destination=true
    if ($LASTEXITCODE -ne 0) { throw "neo4j-admin database dump failed." }
}
finally {
    if (-not $KeepStopped) {
        Write-Host "==> Restarting neo4j..." -ForegroundColor Cyan
        docker compose start neo4j
    }
}

$dump = Join-Path $snapshotDir "$Database.dump"
if (Test-Path $dump) {
    $sizeMB = [math]::Round((Get-Item $dump).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Done. Wrote $dump ($sizeMB MB)." -ForegroundColor Green
    Write-Host "Share it with your coworker (it is gitignored; use Git LFS or send it out-of-band)." -ForegroundColor Green
    Write-Host "They restore it with: .\scripts\import-graph.ps1" -ForegroundColor Green
}
else {
    throw "Expected dump not found at $dump."
}
