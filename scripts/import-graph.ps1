#requires -Version 5.1
<#
.SYNOPSIS
    Restore a shared Neo4j graph snapshot (snapshot/neo4j.dump) into the local
    Docker volume, so the app runs with a fully-populated graph without having to
    re-run the ingest -> load_manifest -> enrich pipeline.

.DESCRIPTION
    Counterpart to export-graph.ps1. Run this ONCE after cloning the repo and
    dropping the shared neo4j.dump into a `snapshot/` folder at the repo root,
    BEFORE (or instead of) your first `docker compose up`.

    It loads the dump into the em_b_v2_neo4j_data volume using neo4j-admin
    database load in a throwaway container. --overwrite-destination=true means an
    existing local database is REPLACED, so anything currently in your local
    graph is discarded.

    You still need host-native Ollama running to *query* the app afterward — the
    snapshot only saves you the rebuild, not the chat-time LLM dependency. See
    docs/HYBRID_SETUP.md.

    NOTE: this must run the SAME pinned Neo4j image the dump was created with (see
    docker-compose.yml `image:` line).

.PARAMETER Database
    The database name to load into. Defaults to "neo4j".

.PARAMETER Up
    After loading, bring the full stack up (`docker compose up -d`).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\import-graph.ps1 -Up
#>
[CmdletBinding()]
param(
    [string]$Database = "neo4j",
    [switch]$Up
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$snapshotDir = Join-Path $repoRoot "snapshot"
$dump = Join-Path $snapshotDir "$Database.dump"
if (-not (Test-Path $dump)) {
    throw "No dump at $dump. Put the shared $Database.dump in a 'snapshot' folder at the repo root first."
}
$sizeMB = [math]::Round((Get-Item $dump).Length / 1MB, 1)
Write-Host "==> Found $dump ($sizeMB MB)." -ForegroundColor Cyan

Write-Host "==> Stopping neo4j if it is running (load requires the database offline)..." -ForegroundColor Cyan
docker compose stop neo4j 2>$null

Write-Host "==> Loading '$Database' into the local volume (existing data is overwritten)..." -ForegroundColor Cyan
docker compose run --rm --no-deps -v "${snapshotDir}:/snapshot" neo4j `
    neo4j-admin database load $Database --from-path=/snapshot --overwrite-destination=true
if ($LASTEXITCODE -ne 0) { throw "neo4j-admin database load failed." }

Write-Host ""
Write-Host "Done. Graph restored into em_b_v2_neo4j_data." -ForegroundColor Green

if ($Up) {
    Write-Host "==> Bringing the stack up..." -ForegroundColor Cyan
    docker compose up -d
}
else {
    Write-Host "Next: start the stack with  docker compose up -d  (host Ollama must be running)." -ForegroundColor Green
}
