#requires -Version 5.1
<#
.SYNOPSIS
    Export the Neo4j graph (all nodes, embeddings, and the vector-index config)
    to a portable snapshot/neo4j.dump so it can be shared or shipped.

.DESCRIPTION
    Native (decontainerized) port of the former docker-compose version: drives
    the host's `neo4j-admin database dump` directly. Neo4j must be OFFLINE for the
    dump, and this script does NOT manage the server lifecycle (Neo4j Desktop or a
    bundled server owns it) — stop the database yourself first. The script refuses
    to run while bolt (127.0.0.1:7687) is still open.

    Version note: a dump loads into the SAME Neo4j major line it was taken from,
    and into Neo4j Community only if it is a record format (aligned/standard), not
    Enterprise `block`. See docs/DECONTAINERIZE_PLAN.md.

.PARAMETER Neo4jAdmin
    Path to neo4j-admin (.bat on Windows). For a Neo4j Desktop DBMS this is
    <...>/Data/dbmss/dbms-<id>/bin/neo4j-admin.bat. Required.

.PARAMETER JavaHome
    JAVA_HOME for neo4j-admin. Neo4j Desktop bundles a JRE under
    <...>/Cache/runtime/<zulu...> — pass it here if `java` isn't already on PATH.

.PARAMETER Database
    Database to dump. Defaults to "neo4j" (the app's only database).

.EXAMPLE
    pwsh -File scripts/export-graph.ps1 `
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
New-Item -ItemType Directory -Force -Path $snapshotDir | Out-Null

# Guard: the dump requires the database offline.
$boltUp = (Test-NetConnection 127.0.0.1 -Port 7687 -WarningAction SilentlyContinue).TcpTestSucceeded
if ($boltUp) { throw "Neo4j is running (bolt 127.0.0.1:7687 is open). Stop the database first — an offline dump is required." }
if (-not (Test-Path $Neo4jAdmin)) { throw "neo4j-admin not found at $Neo4jAdmin." }
if ($JavaHome) { $env:JAVA_HOME = $JavaHome }

Write-Host "==> Dumping database '$Database' to snapshot/$Database.dump ..." -ForegroundColor Cyan
& $Neo4jAdmin database dump $Database --to-path=$snapshotDir --overwrite-destination=true
if ($LASTEXITCODE -ne 0) { throw "neo4j-admin database dump failed." }

$dump = Join-Path $snapshotDir "$Database.dump"
if (-not (Test-Path $dump)) { throw "Expected dump not found at $dump." }
$sizeMB = [math]::Round((Get-Item $dump).Length / 1MB, 1)
Write-Host ""
Write-Host "Done. Wrote $dump ($sizeMB MB)." -ForegroundColor Green
Write-Host "It is gitignored — share via Git LFS or out-of-band. Restore with scripts/import-graph.ps1. Start Neo4j again when finished." -ForegroundColor Green
