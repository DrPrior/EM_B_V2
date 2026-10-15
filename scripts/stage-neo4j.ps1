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
      * usage reporting and Browser telemetry off — Neo4j defaults both on, and
        the app promises that nothing leaves the machine.

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

    There is deliberately no -Password switch. `dbms set-initial-password` ignores
    --additional-config and writes data\dbms\auth.ini into the Neo4j home itself,
    which build-release.ps1 would then zip — shipping a known credential to every
    user. The password belongs on the END USER's machine, where lib/firstrun.js
    generates a random one and sets it before the first start. To smoke-test
    locally, copy the staged home first; the script prints how.

.PARAMETER Dump
    A neo4j.dump to load (its DIRECTORY is passed to --from-path). After loading,
    the store is migrated to this server's current format version and the
    resulting format is printed — which is the check that it stayed in the
    Community-loadable `aligned` family.

.PARAMETER ReExport
    After migrating, dump the store back out so the SHIPPED artifact is already
    at the bundled server's format version.

    This is required, not cosmetic, whenever the bundled Neo4j is a different
    release from the one the dump was taken on: electron/lib/snapshot.js runs
    `database load` and then starts the server, so a dump that still needs
    migrating would fail on the user's machine after a multi-GB unpack.

    The previous dump is preserved as neo4j.dump.pre-migration (never
    overwritten on a re-run), and the re-exported dump is then verified by
    loading it into a throwaway data directory and reading its store format —
    so what gets checked is the artifact that ships, not the store it came from.

.PARAMETER HeapSize
    JVM heap. Default 1g.

.PARAMETER PageCacheSize
    Page cache. Default 512m.

.EXAMPLE
    pwsh -File scripts/stage-neo4j.ps1 `
      -Zip C:\Downloads\neo4j-community-2026.08.1-windows.zip `
      -JreZip C:\Downloads\OpenJDK21U-jre_x64_windows_hotspot.zip `
      -Dump .\release\neo4j.dump -ReExport

    Stage both homes, load the graph, migrate it to the bundled server's format,
    and write the migrated dump back to release\ ready for build-release.ps1.

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
    [string]$Dump,
    [switch]$ReExport,
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

    # Both vendors offer installers next to the archives, and the installer is
    # the more prominent download. tar would fail on one with a useless message.
    $ext = [IO.Path]::GetExtension($Archive).ToLowerInvariant()
    if ($ext -in @('.msi', '.exe')) {
        throw ("$What is an installer ($ext), not an archive: $Archive`n" +
               "       This ships as an unpacked folder, so download the .zip build instead. " +
               "For the JRE: https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse")
    }
    if ($ext -notin @('.zip', '.gz', '.tgz', '.tar')) {
        Write-Warning "$What has an unexpected extension '$ext'; expected .zip."
    }
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

<#
    Read a DUMP's store format, by loading it into a throwaway data directory.

    There is no way to ask a dump directly: `database load --info` reports the
    ARCHIVE format ("Neo4j ZSTD Dump") and never the store format, and
    `database info --from-path` wants an unpacked store. So unpack a copy
    somewhere disposable and inspect that.
#>
function Get-DumpStoreFormat([string]$AdminPath, [string]$JavaHome, [string]$DumpDir) {
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("verify-" + [guid]::NewGuid().ToString().Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        $cfg = Join-Path $tmp "verify.conf"
        $posix = $tmp.Replace('\', '/')
        Set-Content -Path $cfg -Encoding ascii -Value @(
            "server.directories.data=$posix/data",
            "server.directories.transaction.logs.root=$posix/tx"
        )
        Invoke-Admin $AdminPath $JavaHome @(
            "database", "load", "neo4j", "--from-path=$DumpDir", "--additional-config=$cfg"
        ) | Out-Null
        $info = & {
            $prev = $env:JAVA_HOME; $env:JAVA_HOME = $JavaHome
            try { & $AdminPath database info --from-path="$tmp\data\databases" neo4j 2>&1 } finally { $env:JAVA_HOME = $prev }
        }
        $line = $info | Where-Object { $_ -match 'Store format version' } | Select-Object -First 1
        if ($line) { return ($line -split ':', 2)[1].Trim() }
        return "(could not read store format)"
    } finally {
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

<#
    Make sure the Neo4j home about to be zipped carries no database state.

    build-release.ps1 zips this home's CONTENTS, so anything under data\ ships to
    every user. Two things can get there, and both are bad:

      data\dbms\auth.ini        a credential. `dbms set-initial-password` IGNORES
                                --additional-config and always writes into
                                <NEO4J_HOME>\data, so one stray invocation bakes
                                a known password into the bundle.
      data\databases\neo4j\     the whole graph (~140 MB) — on top of the
                                neo4j.dump we already ship, which snapshot.js
                                loads over it with --overwrite-destination=true.
                                Pure waste.

    Empty leftover directories are harmless and get recreated, so clear the lot
    and report anything that actually held data.
#>
function Assert-ShipClean([string]$HomeDir) {
    $data = Join-Path $HomeDir "data"
    if (-not (Test-Path $data)) {
        New-Item -ItemType Directory -Force -Path $data | Out-Null
        return
    }

    $auth = Join-Path $data "dbms\auth.ini"
    $store = Join-Path $data "databases\neo4j"
    $hadAuth = Test-Path $auth
    $hadStore = (Test-Path $store) -and @(Get-ChildItem $store -Force -ErrorAction SilentlyContinue).Count -gt 0

    Get-ChildItem $data -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    if ($hadAuth -or $hadStore) {
        Write-Host "==> Cleared database state from the staged home (it must not ship):" -ForegroundColor Yellow
        if ($hadAuth)  { Write-Host "      removed data\dbms\auth.ini (a credential)" -ForegroundColor Yellow }
        if ($hadStore) { Write-Host "      removed data\databases\neo4j (the graph ships as neo4j.dump)" -ForegroundColor Yellow }
    } else {
        Write-Host "==> Staged home is ship-clean (data\ is empty)." -ForegroundColor Green
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

# Neo4j 2026.x is built and tested on Java 17/21 — Neo4j Desktop bundles only
# those, and the dev server runs 21. A JVM outside that range may refuse to run
# the server, and finding that out on a user's machine is the expensive way.
$javaMajor = 0
$verText = (& $java -version 2>&1 | Out-String)
if ($verText -match 'version "(\d+)') { $javaMajor = [int]$Matches[1] }
if ($javaMajor -eq 0) {
    Write-Warning "Could not read a Java version from $java."
} elseif ($javaMajor -lt 17) {
    throw "$JreHome is Java $javaMajor. Neo4j 2026.x needs 17 or 21 — use Temurin/Zulu JRE 21."
} elseif ($javaMajor -gt 21) {
    Write-Warning ("$JreHome is Java $javaMajor. Neo4j 2026.x ships and tests on 17/21 (this machine's " +
                   "Neo4j runs 21). If the server or neo4j-admin misbehaves, drop to JRE 21 first.")
} else {
    Write-Host "Java: $javaMajor (supported)" -ForegroundColor Green
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
    # Neo4j defaults both of these ON. The first periodically sends anonymous
    # usage statistics to Neo4j; the second lets the bundled Neo4j Browser send
    # its own telemetry. The app promises users that nothing leaves the machine,
    # so both are off.
    "dbms.usage_report.enabled"       = "false"
    "client.allow_telemetry"          = "false"
}
foreach ($k in $settings.Keys) {
    Set-Neo4jSetting $conf $k $settings[$k]
    Write-Host ("    {0,-34} {1}" -f $k, $settings[$k]) -ForegroundColor DarkGray
}

# ── 3. Migrate + re-export the dump, in a SCRATCH data directory ────────────
#
# Everything below redirects server.directories.* into a temp dir. The Neo4j
# home staged above must reach build-release.ps1 with an EMPTY data/ — see
# Assert-ShipClean for what would otherwise end up in neo4j-community.zip.

if ($Dump) {
    if (-not (Test-Path $Dump)) { throw "Dump not found: $Dump" }
    $dumpDir = (Resolve-Path (Split-Path -Parent $Dump)).Path
    $dumpName = Split-Path -Leaf $Dump
    if ($dumpName -ne "neo4j.dump") {
        throw "neo4j-admin loads <database>.dump; rename '$dumpName' to neo4j.dump or point -Dump at one."
    }

    $scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("stage-db-" + [guid]::NewGuid().ToString().Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    try {
        $scratchCfg = Join-Path $scratch "scratch.conf"
        $posix = $scratch.Replace('\', '/')
        Set-Content -Path $scratchCfg -Encoding ascii -Value @(
            "server.directories.data=$posix/data",
            "server.directories.transaction.logs.root=$posix/tx"
        )

        Write-Host "==> Loading $Dump into a scratch store ..." -ForegroundColor Cyan
        Invoke-Admin $admin $JreHome @(
            "database", "load", "neo4j", "--from-path=$dumpDir",
            "--overwrite-destination=true", "--additional-config=$scratchCfg"
        )

        # Migrate to THIS server's current version of the same format. Without
        # --to-format it stays in the current family, so an `aligned` (record)
        # store stays Community-loadable; --to-format=block would make it
        # Enterprise-only. It is a ~1s no-op when nothing needs doing.
        Write-Host "==> Migrating the store to this server's format version ..." -ForegroundColor Cyan
        Invoke-Admin $admin $JreHome @("database", "migrate", "neo4j", "--additional-config=$scratchCfg")

        Write-Host "==> Resulting store format:" -ForegroundColor Cyan
        Invoke-Admin $admin $JreHome @("database", "info", "--from-path=$scratch\data\databases", "neo4j")

        # ── 3b. Re-export, so the artifact that SHIPS is already migrated ───
        if ($ReExport) {
            # snapshot.js loads the dump and starts the server; its migrate call
            # is a non-fatal backstop, not something to rely on. So the shipped
            # dump must already match the bundled server.
            $backup = Join-Path $dumpDir "neo4j.dump.pre-migration"
            if (-not (Test-Path $backup)) {
                Write-Host "==> Preserving the pre-migration dump -> $backup" -ForegroundColor Cyan
                Copy-Item (Join-Path $dumpDir "neo4j.dump") $backup
            } else {
                Write-Host "==> Keeping the existing $([IO.Path]::GetFileName($backup)) (not overwriting it)." -ForegroundColor DarkGray
            }

            Write-Host "==> Re-exporting the migrated store -> $dumpDir\neo4j.dump" -ForegroundColor Cyan
            Invoke-Admin $admin $JreHome @(
                "database", "dump", "neo4j", "--to-path=$dumpDir",
                "--overwrite-destination=true", "--additional-config=$scratchCfg"
            )

            Write-Host "==> Verifying the RE-EXPORTED dump (the file that ships) ..." -ForegroundColor Cyan
            $format = Get-DumpStoreFormat $admin $JreHome $dumpDir
            Write-Host "    Store format version: $format" -ForegroundColor Green
            if ($format -match 'block') {
                throw "The re-exported dump is '$format' — Enterprise-only. The bundled Community server cannot load it."
            }
            if ($format -notmatch 'aligned|standard') {
                Write-Warning "Unrecognized store format '$format'. Confirm Community can load it before shipping."
            }
        }
    } finally {
        if (Test-Path $scratch) { Remove-Item $scratch -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

# ── 4. The staged home must ship empty ──────────────────────────────────────

Assert-ShipClean $Neo4jHome

# ── 5. What to do next ──────────────────────────────────────────────────────

Write-Host ""
Write-Host "Staged. Next:" -ForegroundColor Green
Write-Host "  1. Build the release assets:"
Write-Host "       pwsh -File electron/scripts/build-release.ps1 -Neo4jHome '$Neo4jHome' -JreHome '$JreHome'"
Write-Host "  2. Rebuild the installer, then stage the USB (see docs/DECONTAINERIZE_PLAN.md)."
Write-Host ""
Write-Host "To smoke-test the server by hand, do it on a COPY — starting it writes a" -ForegroundColor DarkGray
Write-Host "store and an auth.ini into data\, which must not reach the shipped zip:" -ForegroundColor DarkGray
Write-Host "    Copy-Item '$Neo4jHome' C:\stage\neo4j-smoketest -Recurse" -ForegroundColor DarkGray
Write-Host "    `$env:JAVA_HOME='$JreHome'" -ForegroundColor DarkGray
Write-Host "    C:\stage\neo4j-smoketest\bin\neo4j-admin.bat dbms set-initial-password <pw>" -ForegroundColor DarkGray
Write-Host "    C:\stage\neo4j-smoketest\bin\neo4j-admin.bat database load neo4j --from-path='$($dumpDir ?? "<dump dir>")'" -ForegroundColor DarkGray
Write-Host "    C:\stage\neo4j-smoketest\bin\neo4j.bat console" -ForegroundColor DarkGray
