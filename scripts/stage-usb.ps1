#requires -Version 5.1
<#
.SYNOPSIS
    Assemble the complete USB drive layout for the EM Knowledge Assistant
    desktop app: installer + assets/ + explainer/ + README.txt + the
    target-machine prep procedure.

.DESCRIPTION
    Run AFTER electron/scripts/build-release.ps1 (which builds the heavy assets
    and updates the manifest) and AFTER `npm run dist:win` in electron/ (which
    bakes that manifest into the installer).

    The script is the last mile — it does not build anything. It:

      1. Verifies the installer's *bundled* manifest matches the manifest in the
         repo (catches "assets rebuilt but installer not rebuilt").
      2. Reports the installer's Authenticode status. Unsigned only WARNS - the
         build ships unsigned until a certificate is available - but managed
         Windows machines will refuse an unsigned installer outright
         ("blocked by your system administrator"), so it must never be a
         surprise at the point of handing over a drive.
      3. Verifies every asset in release/ against that manifest's SHA-256, so a
         bad copy is caught here rather than on the user's machine.
      4. Copies the whole layout to -Destination with robocopy.
      5. Re-verifies the checksums at the destination when -Verify is given
         (worth it for a real USB stick — flash media fails quietly).

    Resulting layout:

        <Destination>\
          EM Knowledge Assistant-Setup-<version>.exe
          README.txt                       (from docs/USB_README.txt)
          TARGET_MACHINE_PREP.md           (from docs/TARGET_MACHINE_PREP.md)
          assets\                          (the whole release/ folder)
            emb-hybrid-api-<version>.tar.gz
            neo4j.dump
            project_data.tar.gz
          explainer\                       (from docs/explainer/)
            index.html ...

.PARAMETER Destination
    Where to assemble the layout. A USB drive root (e.g. E:\) or a local folder
    to drag across later. Defaults to <repo>\usb-staging.

.PARAMETER Verify
    Re-hash the three assets after copying. Slow (~1 GB) but the only way to
    know a USB stick wrote them intact. Recommended when writing to real media.

.PARAMETER SkipExplainer
    Leave out docs/explainer/ (maintainer documentation, not needed to run).

.EXAMPLE
    pwsh -File scripts/stage-usb.ps1
    Assemble into <repo>\usb-staging for review.

.EXAMPLE
    pwsh -File scripts/stage-usb.ps1 -Destination E:\ -Verify
    Write straight to the USB drive and verify it afterwards.
#>
[CmdletBinding()]
param(
    [string]$Destination,
    [switch]$Verify,
    [switch]$SkipExplainer
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

$releaseDir   = Join-Path $repoRoot "release"
$distDir      = Join-Path $repoRoot "electron/dist"
$manifestPath = Join-Path $repoRoot "electron/resources/assets.manifest.json"
$bundledPath  = Join-Path $distDir "win-unpacked/resources/assets.manifest.json"
$readmeSrc    = Join-Path $repoRoot "docs/USB_README.txt"
$prepSrc      = Join-Path $repoRoot "docs/TARGET_MACHINE_PREP.md"
$explainerSrc = Join-Path $repoRoot "docs/explainer"

if (-not $Destination) { $Destination = Join-Path $repoRoot "usb-staging" }

function Get-Sha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

# ── 1. Locate the pieces ────────────────────────────────────────────────────
if (-not (Test-Path $manifestPath)) { throw "Missing $manifestPath." }
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json

$installer = Get-ChildItem -Path $distDir -Filter "*Setup*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $installer) {
    throw "No installer in $distDir. Build it first: cd electron; npm run dist:win"
}

Write-Host "==> Installer: $($installer.Name)  ($([math]::Round($installer.Length/1MB,1)) MB, built $($installer.LastWriteTime))" -ForegroundColor Cyan

# ── 2. The installer must carry the current manifest ────────────────────────
# electron-builder copies resources/assets.manifest.json into the app at build
# time. If the assets were rebuilt after the installer, the baked-in checksums
# are stale and first-run setup fails with "Checksum mismatch" on the user's
# machine. Compare here instead.
if (Test-Path $bundledPath) {
    $repoHash    = Get-Sha256 $manifestPath
    $bundledHash = Get-Sha256 $bundledPath
    if ($repoHash -ne $bundledHash) {
        throw "The installer was built against a DIFFERENT assets manifest. " +
              "Rebuild it after building the assets: cd electron; npm run dist:win"
    }
    Write-Host "    Bundled manifest matches the repo manifest." -ForegroundColor DarkGray
} else {
    Write-Warning "Could not find $bundledPath - skipping the manifest-freshness check."
}

# ── 3. Report the installer's signature ─────────────────────────────────────
# Unsigned is a warning, not an error: the build ships unsigned until a
# certificate exists. But an unsigned installer is refused outright by
# AppLocker/WDAC/SmartScreen-for-Business on managed machines - and elevation
# does not bypass it - so this must be stated plainly, not discovered by whoever
# receives the drive.
$sig = Get-AuthenticodeSignature $installer.FullName
if ($sig.Status -eq "Valid") {
    $subject = $sig.SignerCertificate.Subject
    Write-Host "==> Signature: Valid" -ForegroundColor Green
    Write-Host "    Publisher: $subject" -ForegroundColor DarkGray
    if ($sig.TimeStamperCertificate) {
        Write-Host "    Timestamped - the signature outlives the certificate." -ForegroundColor DarkGray
    } else {
        Write-Warning "Signed but NOT timestamped: this signature stops validating when the certificate expires. Set win.signtoolOptions.rfc3161TimeStampServer and rebuild."
    }
} else {
    Write-Host "==> Signature: $($sig.Status)" -ForegroundColor Yellow
    Write-Warning ("The installer is not validly signed ($($sig.Status)). It will be blocked on " +
                   "IT-managed Windows machines with 'blocked by your system administrator', and " +
                   "running as Administrator does not help. Supply a certificate via CSC_LINK (or " +
                   "win.signtoolOptions.certificateSubjectName) and rebuild before wide distribution.")
}

# ── 4. Verify the source assets ─────────────────────────────────────────────
$assetKeys = @("image", "snapshot", "projectData")
Write-Host "==> Verifying source assets in release\ ..." -ForegroundColor Cyan
foreach ($key in $assetKeys) {
    $entry = $manifest.$key
    $file  = Join-Path $releaseDir $entry.file
    if (-not (Test-Path $file)) {
        throw "Missing asset: $file. Build it first: pwsh -File electron/scripts/build-release.ps1"
    }
    $actual = Get-Sha256 $file
    if ($actual -ne $entry.sha256) {
        throw "Checksum mismatch for $($entry.file) in release\ (manifest says $($entry.sha256), file is $actual). Rebuild the assets."
    }
    Write-Host ("    OK  {0,-32} {1,8:N1} MB" -f $entry.file, ((Get-Item $file).Length/1MB)) -ForegroundColor DarkGray
}

# ── 5. Copy the layout ──────────────────────────────────────────────────────
Write-Host "==> Staging to $Destination ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

Copy-Item $installer.FullName (Join-Path $Destination $installer.Name) -Force
Copy-Item $readmeSrc (Join-Path $Destination "README.txt") -Force

# The provisioning procedure travels with the drive: whoever preps the target
# machines (install Docker + Ollama, set OLLAMA_*, pull the base models) needs it
# before the end user ever runs the installer.
if (Test-Path $prepSrc) {
    Copy-Item $prepSrc (Join-Path $Destination "TARGET_MACHINE_PREP.md") -Force
} else {
    Write-Warning "docs/TARGET_MACHINE_PREP.md not found - the drive will ship without the machine-prep procedure."
}

# robocopy: resumable, shows throughput, and handles the multi-hundred-MB files
# far better than Copy-Item. Exit codes 0-7 are success (8+ is a real failure).
function Invoke-Robocopy([string]$Src, [string]$Dst, [string]$Label) {
    Write-Host "    $Label ..." -ForegroundColor DarkGray
    robocopy $Src $Dst /E /NJH /NJS /NDL /NP /R:2 /W:2 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed copying $Src (exit $LASTEXITCODE)." }
    $global:LASTEXITCODE = 0
}

Invoke-Robocopy $releaseDir (Join-Path $Destination "assets") "assets\"
if (-not $SkipExplainer) {
    if (Test-Path $explainerSrc) {
        Invoke-Robocopy $explainerSrc (Join-Path $Destination "explainer") "explainer\"
    } else {
        Write-Warning "docs/explainer not found - skipping."
    }
}

# ── 6. Verify what actually landed ──────────────────────────────────────────
if ($Verify) {
    Write-Host "==> Verifying the copied assets (re-hashing ~1 GB) ..." -ForegroundColor Cyan
    foreach ($key in $assetKeys) {
        $entry = $manifest.$key
        $dest  = Join-Path $Destination "assets/$($entry.file)"
        $actual = Get-Sha256 $dest
        if ($actual -ne $entry.sha256) {
            throw "Copy is corrupt: $($entry.file) at the destination does not match. Re-copy (the drive may be failing)."
        }
        Write-Host "    OK  $($entry.file)" -ForegroundColor DarkGray
    }
} else {
    Write-Host "    (Skipped destination verification. Re-run with -Verify when writing to a real USB drive.)" -ForegroundColor DarkGray
}

# ── 6. Summary ──────────────────────────────────────────────────────────────
$total = (Get-ChildItem $Destination -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host "Done. $Destination" -ForegroundColor Green
Get-ChildItem $Destination | Select-Object Name,
    @{n='SizeMB';e={ if ($_.PSIsContainer) {
        [math]::Round(((Get-ChildItem $_.FullName -Recurse -File | Measure-Object -Property Length -Sum).Sum)/1MB, 1)
    } else { [math]::Round($_.Length/1MB, 1) } }} | Format-Table
Write-Host ("Total: {0:N2} GB" -f ($total/1GB)) -ForegroundColor Green
