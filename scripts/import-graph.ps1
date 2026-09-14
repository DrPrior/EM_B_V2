#requires -Version 5.1
<#
.SYNOPSIS
    Restore a shared Neo4j graph snapshot (snapshot/neo4j.dump) into the local
    native Neo4j store, so the app runs with a populated graph without re-running
    the ingest -> load_manifest -> enrich pipeline.

.DESCRIPTION
    Native (decontainerized) counterpart to export-graph.ps1: drives the host's
    `neo4j-admin database load` directly. Neo4j must be OFFLINE for the load, and
    this script does NOT manage the server lifecycle — stop the database yourself
    first (it refuses to run while bolt 127.0.0.1:7687 is open). `--overwrite-
    destination=true` REPLACES the local database, so any existing local graph is
    discarded. Start Neo4j again afterward; the vector index rebuilds on startup.

    You still need host-native Ollama to *query* the app — the snapshot only skips
    the rebuild. The dump must match the Neo4j major line and, for Community, be a
    record format (aligned/standard), not `block`.

.PARAMETER Neo4jAdmin
    Path to neo4j-admin (.bat on Windows). Required.

.PARAMETER JavaHome
    JAVA_HOME for neo4j-admin (pass Neo4j Desktop's bundled JRE if java isn't on PATH).

.PARAMETER Database
    Database to load into. Defaults to "neo4j".

.EXAMPLE
    pwsh -File scripts/import-graph.ps1 `
      -Neo4jAdmin "$env:USERPROFILE\.Neo4jDesktop2\Data\dbmss\dbms-XXId\bin\neo4j-admin.bat" `
      -JavaHome  "$env:USERPROFILE\.Neo4jDesktop2\Cache\runtime\zulu21..."
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Neo4jAdmin,
    [string]$JavaHome,
    [string]$Database = "neo4j"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$snapshotDir = Join-Path $repoRoot "snapshot"
$dump = Join-Path $snapshotDir "$Database.dump"
if (-not (Test-Path $dump)) {
    throw "No dump at $dump. Put the shared $Database.dump in a 'snapshot' folder at the repo root first."
}
$sizeMB = [math]::Round((Get-Item $dump).Length / 1MB, 1)
Write-Host "==> Found $dump ($sizeMB MB)." -ForegroundColor Cyan

$boltUp = (Test-NetConnection 127.0.0.1 -Port 7687 -WarningAction SilentlyContinue).TcpTestSucceeded
if ($boltUp) { throw "Neo4j is running (bolt 127.0.0.1:7687 is open). Stop the database first — an offline load is required." }
if (-not (Test-Path $Neo4jAdmin)) { throw "neo4j-admin not found at $Neo4jAdmin." }
if ($JavaHome) { $env:JAVA_HOME = $JavaHome }

Write-Host "==> Loading '$Database' (existing local data is overwritten)..." -ForegroundColor Cyan
& $Neo4jAdmin database load $Database --from-path=$snapshotDir --overwrite-destination=true
if ($LASTEXITCODE -ne 0) { throw "neo4j-admin database load failed." }

Write-Host ""
Write-Host "Done. Graph restored. Start Neo4j again (the vector index rebuilds on startup); host Ollama must be running to query." -ForegroundColor Green
