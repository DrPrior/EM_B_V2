#requires -Version 5.1
<#
.SYNOPSIS
    Turn a downloaded Neo4j Community zip (+ a JRE) into the configured
    -Neo4jHome / -JreHome that electron/scripts/build-release.ps1 expects.

.DESCRIPTION
    build-release.ps1 zips the CONTENTS of a Neo4j home and a JRE home, but
    nothing produced those homes — they were hand-configured, which is neither
    reproducible nor reviewable. This script closes that gap: unpack, apply the
    app's required settings, and (optionally) set the password and load the
    shipped graph dump, then report what it produced.

    Everything is idempotent; re-running re-applies the settings in place.

    What it configures, and why:
      * loopback binds — the app is local-only; nothing listens on the LAN.
      * modest heap/pagecache — Neo4j coexists with Ollama holding models in
        VRAM/RAM on a laptop, so it must not assume the machine to itself. The
        graph store is ~140 MB, so a 512 MB page cache holds all of it.
      * https off — there is no certificate and no remote client.

    The data directory is left at its default (<neo4j-home>/data), which is what
    electron/lib/paths.js resolves to once the zip is unpacked to <userData>/neo4j.

.PARAMETER Zip
    The downloaded Neo4j Community zip, e.g. neo4j-community-2026.08.1-windows.zip.
    Its single top-level folder is flattened away so -Neo4jHome points directly at
    the directory holding bin/ and conf/. Alternative to -Neo4jHome.

.PARAMETER Neo4jHome
    An already-unpacked Neo4j home to (re)configure instead of -Zip.

.PARAMETER JreZip
    The downloaded JRE zip (Temurin/Zulu, JRE not JDK). Flattened the same way.

.PARAMETER JreHome
    An already-unpacked JRE home instead of -JreZip.

.PARAMETER StageDir
    Where the staged homes are written. Default C:\stage — giving
    <StageDir>\neo4j and <StageDir>\jre.

.PARAMETER Password
    If given, runs `neo4j-admin dbms set-initial-password`. MUST happen before
    the database is first started, or authentication is baked in wrong and the
    app cannot open its own store.

.PARAMETER Dump
    A neo4j.dump to load (its DIRECTORY is passed to --from-path). After loading,
    the store is migrated to this server's current format version and the
    resulting format is printed — which is the check that it stayed in the
    Community-loadable `aligned` family.

.PARAMETER HeapSize
    JVM heap. Default 1g.

.PARAMETER PageCacheSize
    Page cache. Default 512m.

.EXAMPLE
    pwsh -File scripts/stage-neo4j.ps1 `
      -Zip C:\Downloads\neo4j-community-2026.08.1-windows.zip `
      -JreZip C:\Downloads\OpenJDK21U-jre_x64_windows_hotspot.zip `
      -Password devpassword -Dump .\release\neo4j.dump

.EXAMPLE
    # Re-apply settings to an already-staged home
    pwsh -File scripts/stage-neo4j.ps1 -Neo4jHome C:\stage\neo4j -JreHome C:\stage\jre
#>
[CmdletBinding()]
param(
    [string]$Zip,
    [string]$Neo4jHome,
    [string]$JreZip,
    [string]$JreHome,
    [string]$StageDir = "C:\stage",
    [string]$Password,
    [string]$Dump,
    [string]$HeapSize = "1g",
    [string]$PageCacheSize = "512m"
)

$ErrorActionPreference = "Stop"

if (-not $Zip -and -not $Neo4jHome) { throw "Pass -Zip (a downloaded Neo4j Community zip) or -Neo4jHome." }
if (-not $JreZip -and -not $JreHome) { throw "Pass -JreZip (a downloaded JRE zip) or -JreHome." }

# ── helpers ─────────────────────────────────────────────────────────────────

# Neo4j and JRE zips both wrap everything in one top-level folder. The app's
# layout contract has no such level (<userData>/neo4j/bin/...), so unwrap it.
function Expand-Flattened([string]$Archive, [string]$Dest, [string]$What) {
    if (-not (Test-Path $Archive)) { throw "$What archive not found: $Archive" }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("stage-" + [guid]::NewGuid().ToString().Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        Write-Host "==> Unpacking $What ..." -ForegroundColor Cyan
        tar -xf $Archive -C $tmp
        if ($LASTEXITCODE -ne 0) { throw "Failed to unpack $Archive" }

        $entries = @(Get-ChildItem $tmp)
        $root = if ($entries.Count -eq 1 -and $entries[0].PSIsContainer) { $entries[0].FullName } else { $tmp }

        if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
        Move-Item $root $Dest
    } finally {
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
    return $Dest
}

# Replace the setting if present (commented or not), otherwise append it. Neo4j
# honours the LAST occurrence, but leaving stale duplicates makes the file a lie
# to whoever reads it next.
function Set-Neo4jSetting([string]$ConfPath, [string]$Key, [string]$Value) {
    $lines = @(Get-Content $ConfPath)
    $escaped = [regex]::Escape($Key)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*#?\s*$escaped\s*=") {
            if (-not $found) { $found = $true; "$Key=$Value" }   # keep one, drop later dupes
        } else {
            $line
        }
    }
    if (-not $found) {
        $out += ""
        $out += "# Set by scripts/stage-neo4j.ps1"
        $out += "$Key=$Value"
    }
    Set-Content -Path $ConfPath -Value $out -Encoding ascii
}

function Invoke-Admin([string]$AdminPath, [string]$JavaHome, [string[]]$Arguments) {
    $prev = $env:JAVA_HOME
    $env:JAVA_HOME = $JavaHome
    try {
        & $AdminPath @Arguments
        if ($LASTEXITCODE -ne 0) { throw "neo4j-admin $($Arguments -join ' ') failed (exit $LASTEXITCODE)." }
    } finally {
        $env:JAVA_HOME = $prev
    }
}

# ── 1. Stage the two homes ──────────────────────────────────────────────────

if ($Zip)    { $Neo4jHome = Expand-Flattened $Zip    (Join-Path $StageDir "neo4j") "Neo4j Community" }
if ($JreZip) { $JreHome   = Expand-Flattened $JreZip (Join-Path $StageDir "jre")   "JRE" }

$Neo4jHome = (Resolve-Path $Neo4jHome).Path
$JreHome   = (Resolve-Path $JreHome).Path

$conf  = Join-Path $Neo4jHome "conf\neo4j.conf"
$admin = Join-Path $Neo4jHome "bin\neo4j-admin.bat"
$java  = Join-Path $JreHome  "bin\java.exe"

if (-not (Test-Path $conf))  { throw "$Neo4jHome does not look like a Neo4j home (no conf\neo4j.conf)." }
if (-not (Test-Path $admin)) { throw "$Neo4jHome does not look like a Neo4j home (no bin\neo4j-admin.bat)." }
if (-not (Test-Path $java))  { throw "$JreHome does not look like a JRE home (no bin\java.exe)." }

# A JDK works but is ~120 MB of compiler the app never uses; flag it, don't fail.
if (Test-Path (Join-Path $JreHome "bin\javac.exe")) {
    Write-Warning "$JreHome is a JDK, not a JRE. It works, but ships a compiler you don't need."
}

Write-Host "Neo4j home: $Neo4jHome" -ForegroundColor Green
Write-Host "JRE home:   $JreHome"   -ForegroundColor Green

# ── 2. Apply the app's settings ─────────────────────────────────────────────

Write-Host "==> Configuring conf\neo4j.conf ..." -ForegroundColor Cyan
$settings = [ordered]@{
    "server.default_listen_address"   = "127.0.0.1"
    "server.bolt.listen_address"      = "127.0.0.1:7687"
    "server.http.listen_address"      = "127.0.0.1:7474"
    "server.https.enabled"            = "false"
    "server.memory.heap.initial_size" = $HeapSize
    "server.memory.heap.max_size"     = $HeapSize
    "server.memory.pagecache.size"    = $PageCacheSize
}
foreach ($k in $settings.Keys) {
    Set-Neo4jSetting $conf $k $settings[$k]
    Write-Host ("    {0,-34} {1}" -f $k, $settings[$k]) -ForegroundColor DarkGray
}

# ── 3. Password before first init (mandatory ordering) ──────────────────────

if ($Password) {
    Write-Host "==> Setting the initial password (must precede first start) ..." -ForegroundColor Cyan
    Invoke-Admin $admin $JreHome @("dbms", "set-initial-password", $Password)
}

# ── 4. Load + migrate + verify the dump ─────────────────────────────────────

if ($Dump) {
    if (-not (Test-Path $Dump)) { throw "Dump not found: $Dump" }
    $dumpDir = (Resolve-Path (Split-Path -Parent $Dump)).Path
    $dumpName = Split-Path -Leaf $Dump
    if ($dumpName -ne "neo4j.dump") {
        throw "neo4j-admin loads <database>.dump; rename '$dumpName' to neo4j.dump or point -Dump at one."
    }

    Write-Host "==> Loading $Dump ..." -ForegroundColor Cyan
    Invoke-Admin $admin $JreHome @("database", "load", "neo4j", "--from-path=$dumpDir", "--overwrite-destination=true")

    # Migrate to THIS server's current version of the same format. Without
    # --to-format it stays in the current family, so an `aligned` (record) store
    # stays Community-loadable; --to-format=block would make it Enterprise-only.
    Write-Host "==> Migrating the store to this server's format version ..." -ForegroundColor Cyan
    Invoke-Admin $admin $JreHome @("database", "migrate", "neo4j")

    Write-Host "==> Resulting store format:" -ForegroundColor Cyan
    Invoke-Admin $admin $JreHome @("database", "info", "--from-path=$(Join-Path $Neo4jHome 'data\databases')", "neo4j")

    Write-Host ""
    Write-Host "Confirm the format above is an 'aligned' (record) one. 'block' means" -ForegroundColor Yellow
    Write-Host "Enterprise-only and the desktop app's Community server cannot load it." -ForegroundColor Yellow
}

# ── 5. What to do next ──────────────────────────────────────────────────────

Write-Host ""
Write-Host "Staged. Next:" -ForegroundColor Green
Write-Host "  1. Start it by hand to check:  `$env:JAVA_HOME='$JreHome'; & '$Neo4jHome\bin\neo4j.bat' console"
Write-Host "  2. Build the release assets:"
Write-Host "       pwsh -File electron/scripts/build-release.ps1 -Neo4jHome '$Neo4jHome' -JreHome '$JreHome'"
Write-Host "  3. Rebuild the installer, then stage the USB (see docs/DECONTAINERIZE_PLAN.md)."
