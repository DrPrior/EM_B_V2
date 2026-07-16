#requires -Version 5.1
<#
.SYNOPSIS
    Verify that host-native Ollama is actually offloading a model onto the GPU
    (e.g. an Intel Arc via Vulkan) instead of silently falling back to CPU.

.DESCRIPTION
    This app has no GPU code of its own: all GPU use happens inside the
    host-native Ollama daemon, which serves the custom `chat-model` /
    `embedding-model` variants over http://localhost:11434 (see
    docs/HYBRID_SETUP.md). "Testing on an Intel Arc GPU" therefore reduces to a
    single question: did Ollama load the model into GPU VRAM, or is it running on
    the CPU?

    There is nothing to emulate — Ollama needs a real Vulkan-capable GPU. Run
    this ON the machine with the Arc GPU. The script:

      1. Confirms the Ollama daemon is reachable.
      2. Scans the server log for the backend Ollama picked (Vulkan / Intel /
         CUDA / "no compatible GPUs"), so you can see what it detected at boot.
      3. Warms the model with a tiny generation and reports eval throughput.
      4. Reads /api/ps (size vs size_vram) and prints an exact GPU/CPU verdict.

    A '100% GPU' verdict on the Arc machine is the goal. '100% CPU' means Vulkan
    was not detected — check the log lines in step 2, confirm the Ollama version
    supports your Arc, and consider Intel's ipex-llm portable Ollama build. A
    partial split usually means the model does not fit in Arc VRAM (this stack
    keeps two models resident via OLLAMA_MAX_LOADED_MODELS=2).

.PARAMETER Model
    The model to verify. Defaults to "chat-model" (the app's chat variant). Must
    be a generation-capable model — do NOT pass "embedding-model" here, it has no
    /api/generate endpoint.

.PARAMETER OllamaHost
    Base URL of the Ollama daemon. Defaults to http://localhost:11434.

.PARAMETER Prompt
    The warm-up prompt sent to the model. Defaults to a trivial one.

.PARAMETER LogPath
    Path to the Ollama server log. Defaults to %LOCALAPPDATA%\Ollama\server.log
    (the standard Windows location).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\verify-arc-gpu.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\verify-arc-gpu.ps1 -Model chat-model
#>
[CmdletBinding()]
param(
    [string]$Model = "chat-model",
    [string]$OllamaHost = "http://localhost:11434",
    [string]$Prompt = "Reply with the single word: ok.",
    [string]$LogPath = "$env:LOCALAPPDATA\Ollama\server.log"
)

$ErrorActionPreference = "Stop"

# Run from the repo root regardless of where the script is invoked from.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# --- 1. Daemon reachable? --------------------------------------------------
Write-Host "==> Checking Ollama daemon at $OllamaHost ..." -ForegroundColor Cyan
try {
    $version = Invoke-RestMethod -Uri "$OllamaHost/api/version" -TimeoutSec 5
    Write-Host "    Ollama $($version.version) is up." -ForegroundColor Green
}
catch {
    throw "Ollama is not reachable at $OllamaHost. Start the daemon (or the tray app) and retry. ($_)"
}

# --- 2. What backend did it detect at boot? --------------------------------
Write-Host "==> Scanning server log for the GPU backend it selected ..." -ForegroundColor Cyan
if (Test-Path $LogPath) {
    # Lines that reveal which library/GPU Ollama loaded, or that it found none.
    $pattern = 'vulkan|intel|arc|level_zero|cuda|rocm|hip|metal|inference compute|looking for compatible|no compatible GPUs|library=|gpu'
    $hits = Get-Content $LogPath -Tail 400 | Select-String -Pattern $pattern
    if ($hits) {
        $hits | Select-Object -Last 12 | ForEach-Object { Write-Host "    $($_.Line.Trim())" -ForegroundColor DarkGray }
    }
    else {
        Write-Host "    No GPU/backend lines found in the last 400 log lines." -ForegroundColor Yellow
    }
}
else {
    Write-Host "    Log not found at $LogPath — skipping (pass -LogPath to point at it)." -ForegroundColor Yellow
}

# --- 3. Warm the model and measure throughput ------------------------------
Write-Host "==> Loading '$Model' and running a warm-up generation ..." -ForegroundColor Cyan
$body = @{
    model   = $Model
    prompt  = $Prompt
    stream  = $false
    options = @{ num_predict = 16 }
} | ConvertTo-Json

try {
    $gen = Invoke-RestMethod -Uri "$OllamaHost/api/generate" -Method Post -Body $body `
        -ContentType "application/json" -TimeoutSec 300
}
catch {
    throw "Generation against '$Model' failed. Is the model pulled/built on this host? Run 'ollama list'. ($_)"
}

if ($gen.eval_count -and $gen.eval_duration -gt 0) {
    $tokPerSec = [math]::Round($gen.eval_count / ($gen.eval_duration / 1e9), 1)
    Write-Host "    Generated $($gen.eval_count) tokens at $tokPerSec tok/s." -ForegroundColor Green
}

# --- 4. GPU vs CPU verdict from /api/ps ------------------------------------
Write-Host "==> Reading /api/ps to determine where '$Model' is running ..." -ForegroundColor Cyan
$ps = Invoke-RestMethod -Uri "$OllamaHost/api/ps" -TimeoutSec 10
$entry = $ps.models | Where-Object { $_.name -eq $Model -or $_.model -eq $Model } | Select-Object -First 1

if (-not $entry) {
    throw "'$Model' is not currently loaded (it may have been unloaded). Re-run, or set OLLAMA_KEEP_ALIVE=-1."
}

$total = [double]$entry.size
$vram  = [double]$entry.size_vram
$gpuPct = if ($total -gt 0) { [math]::Round($vram / $total * 100) } else { 0 }

Write-Host ""
Write-Host "    Model : $($entry.name)" -ForegroundColor Green
Write-Host ("    VRAM  : {0:N0} MB of {1:N0} MB total" -f ($vram / 1MB), ($total / 1MB)) -ForegroundColor Green

if ($gpuPct -ge 99) {
    Write-Host "    VERDICT: 100% GPU — fully offloaded to the GPU. Arc acceleration confirmed." -ForegroundColor Green
}
elseif ($gpuPct -le 1) {
    Write-Host "    VERDICT: 100% CPU — NOT accelerated. Vulkan/Arc was not used." -ForegroundColor Red
    Write-Host "             Check the backend log lines above, confirm your Ollama version" -ForegroundColor Red
    Write-Host "             supports this Arc GPU, or try Intel's ipex-llm Ollama build." -ForegroundColor Red
}
else {
    Write-Host "    VERDICT: $gpuPct% GPU / $(100 - $gpuPct)% CPU — partial offload." -ForegroundColor Yellow
    Write-Host "             The model likely does not fit in Arc VRAM alongside the other" -ForegroundColor Yellow
    Write-Host "             resident model. Use a smaller quant or lower OLLAMA_MAX_LOADED_MODELS." -ForegroundColor Yellow
}

exit 0
