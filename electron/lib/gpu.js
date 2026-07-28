'use strict';

/**
 * Best-effort GPU detection, used only to tailor wizard messaging and hint at
 * acceleration. Actual acceleration is Ollama's job and is auto-detected at
 * runtime (CUDA for Nvidia, Vulkan for Intel Arc/iGPU, Metal on Apple Silicon,
 * CPU fallback otherwise) — nothing here changes how inference runs.
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
  else if (intelArc) accel = 'Intel Arc (Vulkan — experimental)';
  else if (intel) accel = 'Intel integrated (Vulkan — experimental, may fall back to CPU)';

  return { names, nvidia, intel, intelArc, apple, accel };
}

module.exports = { detect };
