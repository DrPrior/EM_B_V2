'use strict';

/**
 * Best-effort GPU detection. Two consumers:
 *   1. Wizard messaging (the `accel` string below).
 *   2. lib/ollamaenv.js `ensure()`, which uses the `intel`/`nvidia`/`apple`
 *      flags to decide whether to persist the Intel iGPU-enable env vars
 *      (OLLAMA_VULKAN=1 / OLLAMA_IGPU_ENABLE=1). Ollama otherwise DROPS an
 *      integrated Intel GPU and falls back to CPU. NVIDIA (CUDA) and Apple
 *      (Metal) hosts are left on their native backend untouched.
 */

const os = require('os');
const { run } = require('./exec');

/**
 * @returns {Promise<{names:string[], nvidia:boolean, intel:boolean,
 *   intelArc:boolean, apple:boolean, accel:string}>}
 */
async function detect() {
  let names = [];
  if (process.platform === 'win32') {
    const { code, stdout } = await run('powershell', [
      '-NoProfile', '-Command',
      "(Get-CimInstance Win32_VideoController).Name -join '||'",
    ]);
    if (code === 0) names = stdout.split('||').map((s) => s.trim()).filter(Boolean);
  } else if (process.platform === 'darwin') {
    const { code, stdout } = await run('system_profiler', ['SPDisplaysDataType']);
    if (code === 0) {
      names = stdout.split('\n')
        .filter((l) => /Chipset Model:/.test(l))
        .map((l) => l.split(':')[1].trim());
    }
  }

  const joined = names.join(' ').toLowerCase();
  const nvidia = /nvidia|geforce|rtx|quadro|tesla/.test(joined);
  const intel = /intel/.test(joined);
  const intelArc = /\barc\b/.test(joined);
  const apple = process.platform === 'darwin' && os.arch() === 'arm64';

  let accel = 'CPU (no supported GPU detected)';
  if (apple) accel = 'Apple Metal';
  else if (nvidia) accel = 'Nvidia CUDA';
  else if (intelArc) accel = 'Intel Arc (Vulkan, iGPU offload enabled)';
  else if (intel) accel = 'Intel integrated (Vulkan, iGPU offload enabled)';

  return { names, nvidia, intel, intelArc, apple, accel };
}

module.exports = { detect };
