'use strict';

/**
 * Best-effort GPU/NPU detection. Two consumers:
 *   1. Wizard messaging (the `accel` string below).
 *   2. lib/ollamaenv.js `ensure()`, which uses the `intel`/`nvidia`/`apple`
 *      flags to decide whether to persist the Intel iGPU-enable env vars
 *      (OLLAMA_VULKAN=1 / OLLAMA_IGPU_ENABLE=1). Ollama otherwise DROPS an
 *      integrated Intel GPU and falls back to CPU. NVIDIA (CUDA) and Apple
 *      (Metal) hosts are left on their native backend untouched.
 *
 * NPU (`npu`/`npuNames`) is detection-only. Machines with a Meteor Lake /
 * Lunar Lake / Arrow Lake Intel chip (or an Apple Silicon chip, which always
 * has a Neural Engine) expose an NPU alongside the GPU. Stock Ollama's
 * inference backends (CUDA/ROCm/Metal/Vulkan) have **no NPU code path** — NPU
 * acceleration for LLM inference exists only in separate stacks (OpenVINO,
 * ipex-llm's NPU mode, vendor SDKs), none of which this app integrates. So
 * unlike the Intel iGPU case, there is no env var to flip here: we report the
 * NPU's presence for visibility (wizard log, `accel` string) and otherwise
 * leave it unused, rather than claim acceleration that doesn't happen.
 */

const os = require('os');
const { run } = require('./exec');

/**
 * Pure classifier: turn raw device-name lists into the flags/summary string
 * the rest of the app consumes. Split out from `detect()` so it can be
 * unit-tested without spawning `powershell`/`system_profiler`.
 *
 * @param {string[]} names Display/video controller names.
 * @param {string[]} npuNames Detected NPU device names (empty = none found).
 * @param {NodeJS.Platform} platform `process.platform`.
 * @param {string} arch `os.arch()`.
 * @returns {{names:string[], nvidia:boolean, intel:boolean, intelArc:boolean,
 *   apple:boolean, npu:boolean, npuNames:string[], accel:string}}
 */
function classify(names, npuNames, platform, arch) {
  const joined = names.join(' ').toLowerCase();
  const nvidia = /nvidia|geforce|rtx|quadro|tesla/.test(joined);
  const intel = /intel/.test(joined);
  const intelArc = /\barc\b/.test(joined);
  const apple = platform === 'darwin' && arch === 'arm64';
  const npu = npuNames.length > 0;

  let accel = 'CPU (no supported GPU detected)';
  if (apple) accel = 'Apple Metal';
  else if (nvidia) accel = 'Nvidia CUDA';
  else if (intelArc) accel = 'Intel Arc (Vulkan, iGPU offload enabled)';
  else if (intel) accel = 'Intel integrated (Vulkan, iGPU offload enabled)';

  if (npu) {
    accel += ` + NPU present (${npuNames.join(', ')}) — not used, Ollama has no NPU backend`;
  }

  return { names, nvidia, intel, intelArc, apple, npu, npuNames, accel };
}

/**
 * @returns {Promise<{names:string[], nvidia:boolean, intel:boolean,
 *   intelArc:boolean, apple:boolean, npu:boolean, npuNames:string[],
 *   accel:string}>}
 */
async function detect() {
  let names = [];
  let npuNames = [];
  if (process.platform === 'win32') {
    const { code, stdout } = await run('powershell', [
      '-NoProfile', '-Command',
      "(Get-CimInstance Win32_VideoController).Name -join '||'",
    ]);
    if (code === 0) names = stdout.split('||').map((s) => s.trim()).filter(Boolean);

    // NPUs enumerate as ordinary PnP devices, not video controllers. Windows
    // 11 24H2+ groups them under a "Neural processing units" Device Manager
    // class; older builds only show the vendor driver name. Match both by
    // name so this works across Windows versions and vendors (Intel AI
    // Boost, Qualcomm Hexagon, AMD XDNA).
    const npuCmd = "(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | " +
      "Where-Object { $_.Name -match 'Neural Processing Unit|AI Boost|Hexagon NPU|XDNA' }).Name -join '||'";
    const npuRes = await run('powershell', ['-NoProfile', '-Command', npuCmd]);
    if (npuRes.code === 0) {
      npuNames = npuRes.stdout.split('||').map((s) => s.trim()).filter(Boolean);
    }
  } else if (process.platform === 'darwin') {
    const { code, stdout } = await run('system_profiler', ['SPDisplaysDataType']);
    if (code === 0) {
      names = stdout.split('\n')
        .filter((l) => /Chipset Model:/.test(l))
        .map((l) => l.split(':')[1].trim());
    }
    // Every Apple Silicon chip ships a Neural Engine; there's no separate
    // enumeration step needed the way there is on Windows.
    if (os.arch() === 'arm64') npuNames = ['Apple Neural Engine'];
  }

  return classify(names, npuNames, process.platform, os.arch());
}

module.exports = { detect, classify };
