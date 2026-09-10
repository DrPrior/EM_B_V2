<#
.SYNOPSIS
    Start the EM_B_Hybrid API natively (no Docker) for development.

.DESCRIPTION
    The decontainerized dev launcher (Workstream B of docs/DECONTAINERIZE_PLAN.md).
    It:
      1. Loads .env into the PROCESS environment. This matters because
         src/database/connection.py reads NEO4J_AUTH and DB_URI from os.environ
         directly (pydantic-settings' .env loading does NOT populate os.environ),
         so those must be real environment variables before uvicorn starts.
      2. Sanity-checks that host-native Ollama and native Neo4j are reachable,
         with actionable messages if not (the API's own lifespan also fail-fasts,
         but these give a clearer hint).
      3. Launches uvicorn with --reload from the repo root.

    Prerequisites (see docs/NATIVE_DEV.md):
      - Python deps installed in the ACTIVE environment
        (python -m pip install -r requirements-dev.txt)
      - Native Neo4j running and listening on bolt 127.0.0.1:7687
      - Host-native Ollama running (127.0.0.1:11434)
      - A .env file (copy from .env.example)

.PARAMETER Port
    Port for uvicorn (default 8000).

.PARAMETER NoReload
    Disable uvicorn --reload (e.g. for a stability test).
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = 'Stop'

# Repo root = parent of this script's scripts/ dir.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$envFile = Join-Path $RepoRoot '.env'
if (-not (Test-Path $envFile)) {
    Write-Error "No .env found at $envFile. Copy .env.example to .env and fill it in."
}

# --- 1. Load .env into the process environment ---
$loaded = @{}
foreach ($line in Get-Content $envFile) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    $eq = $trimmed.IndexOf('=')
    if ($eq -lt 1) { continue }
    $key = $trimmed.Substring(0, $eq).Trim()
    $val = $trimmed.Substring($eq + 1).Trim()
    # Strip one pair of surrounding quotes if present.
    if ($val.Length -ge 2 -and (($val[0] -eq '"' -and $val[-1] -eq '"') -or ($val[0] -eq "'" -and $val[-1] -eq "'"))) {
        $val = $val.Substring(1, $val.Length - 2)
    }
    Set-Item -Path "Env:$key" -Value $val
    $loaded[$key] = $val
}

foreach ($required in @('NEO4J_AUTH', 'DB_URI')) {
    if (-not $loaded.ContainsKey($required)) {
        Write-Error "$required is not set in .env — the API cannot reach Neo4j without it."
    }
}
Write-Host "Loaded $($loaded.Count) vars from .env" -ForegroundColor Green

# --- 2. Pre-flight checks (non-fatal; the API lifespan re-verifies) ---
$ollamaBase = if ($loaded.ContainsKey('OLLAMA_BASE_URL')) { $loaded['OLLAMA_BASE_URL'] } else { 'http://localhost:11434' }
try {
    Invoke-RestMethod -Uri "$ollamaBase/api/version" -TimeoutSec 5 | Out-Null
    Write-Host "Ollama reachable at $ollamaBase" -ForegroundColor Green
} catch {
    Write-Warning "Ollama not reachable at $ollamaBase. Start the Ollama app on the host. The API will fail-fast on startup until it is up."
}

# Neo4j bolt is a TCP service; a plain connect test avoids needing the driver here.
$boltHost = '127.0.0.1'; $boltPort = 7687
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect($boltHost, $boltPort)
    $tcp.Close()
    Write-Host "Neo4j bolt reachable at ${boltHost}:${boltPort}" -ForegroundColor Green
} catch {
    Write-Warning "Neo4j not reachable at ${boltHost}:${boltPort}. Start native Neo4j (see docs/NATIVE_DEV.md). The API will fail on startup until it is up."
}

# --- 3. Launch uvicorn from the active Python environment ---
$uvicornArgs = @('-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', "$Port")
if (-not $NoReload) { $uvicornArgs += '--reload' }

Write-Host "Starting API: python $($uvicornArgs -join ' ')" -ForegroundColor Cyan
& python @uvicornArgs
