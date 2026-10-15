'use strict';

/**
 * Persist and apply the host-side Ollama environment variables the desktop
 * stack depends on.
 *
 * The native API reaches Ollama over loopback, so Ollama's default 127.0.0.1
 * bind is what we want and OLLAMA_HOST is not set. OLLAMA_KEEP_ALIVE /
 * OLLAMA_MAX_LOADED_MODELS keep the chat and embedding models warm and
 * co-resident so queries don't pay reload lag. Docker-era builds persisted
 * OLLAMA_HOST=0.0.0.0; `ensure` removes that value (see RETIRED).
 *
 * Ollama re-reads these every time the daemon starts, so they have to be set
 * *persistently* in the OS — a per-shell `$env:`/`export` is lost on the next
 * launch. The two platforms persist differently:
 *
 *   - Windows: `setx` writes them to the user environment (registry). Every
 *     future login/process (including Ollama auto-started from the tray) sees
 *     them.
 *   - macOS: `launchctl setenv` covers the *current* login session, but is lost
 *     on reboot/logout — the persistence gap the old manual docs called out. We
 *     close it by also installing a RunAtLoad **LaunchAgent** that re-applies
 *     the three vars at every login.
 *
 * After (re)writing the values we relaunch Ollama so the *running* daemon picks
 * them up mid-wizard, rather than only after the user's next login. All of it
 * is idempotent: if the persisted values already match, `ensure` is a no-op and
 * skips the disruptive restart.
 */

const os = require('os');
const fs = require('fs');
const path = require('path');

const { run, spawnDetached } = require('./exec');
// `./ollama` is lazy-required inside the restart helpers only: it pulls in
// `./paths` → electron, which we don't want to load (or download) for the pure
// helpers the test harness exercises.
const loadOllama = () => require('./ollama');

// The host env vars the desktop stack requires, with their target values. Keep
// in sync with the "required host environment variables" table in
// docs/HYBRID_SETUP.md.
//
// Two categories, both backend-agnostic (safe on CUDA/Metal/Vulkan alike):
//   - warmth:       KEEP_ALIVE + MAX_LOADED_MODELS keep both models co-resident.
//   - throughput:   FLASH_ATTENTION fuses attention over the KV cache (cutting
//                   prompt-eval and the long-context generation sag);
//                   KV_CACHE_TYPE=q8_0 halves KV memory (needs flash attention),
//                   easing the shared-VRAM budget; NUM_PARALLEL=1 pins a single
//                   context slot so a co-resident model isn't evicted for KV
//                   room (the source of the 17-25s mid-session reload spikes).
//                   NVIDIA/Metal gain the same speedups; a single-user app never
//                   needed >1 parallel slot. Flash attention on Vulkan is a
//                   no-op on builds that lack it, so it is safe to set blindly.
const REQUIRED = Object.freeze({
  OLLAMA_KEEP_ALIVE: '-1',
  OLLAMA_MAX_LOADED_MODELS: '2',
  OLLAMA_FLASH_ATTENTION: '1',
  OLLAMA_KV_CACHE_TYPE: 'q8_0',
  OLLAMA_NUM_PARALLEL: '1',
});

// Host vars an earlier (Docker-era) build persisted that must now be removed,
// keyed to the exact value that build wrote so a value the user set themselves
// is left alone. OLLAMA_HOST=0.0.0.0 let the API container reach Ollama over
// the Docker bridge; with a native API it only exposes the unauthenticated
// Ollama API to the network.
const RETIRED = Object.freeze({
  OLLAMA_HOST: '0.0.0.0',
});

// Extra host vars that unlock an *integrated* Intel GPU (Arc iGPU / Iris Xe) via
// Ollama's Vulkan backend. Ollama enumerates the iGPU at startup but then DROPS
// it by default — the server log says exactly "dropping integrated GPU; to
// enable, set OLLAMA_IGPU_ENABLE=1" — and silently falls back to CPU. These two
// flip that on (OLLAMA_VULKAN=1 in case the build doesn't default Vulkan on).
//
// They are applied ONLY on Intel-GPU hosts with no NVIDIA/Apple accelerator (see
// `resolveVars`), so a CUDA or Metal machine is never pushed onto the Vulkan
// path — those keep using their native backend exactly as before.
const INTEL_ACCEL = Object.freeze({
  OLLAMA_VULKAN: '1',
  OLLAMA_IGPU_ENABLE: '1',
});

/**
 * Resolve the full env-var set to persist for THIS machine: always the base
 * REQUIRED set, plus INTEL_ACCEL when the detected GPU is Intel and there is
 * no NVIDIA (CUDA) or Apple (Metal) accelerator to prefer instead. Pure so it
 * can be unit-tested without spawning anything.
 *
 * @param {{intel?:boolean, nvidia?:boolean, apple?:boolean}} [gpuInfo] shape
 *   returned by lib/gpu.js `detect()`.
 * @returns {Record<string,string>}
 */
function resolveVars(gpuInfo = {}) {
  const intelOnly = !!gpuInfo.intel && !gpuInfo.nvidia && !gpuInfo.apple;
  return intelOnly ? { ...REQUIRED, ...INTEL_ACCEL } : { ...REQUIRED };
}

// macOS login agent that re-applies REQUIRED at every login (persistence).
const LAUNCH_AGENT_LABEL = 'com.emassistant.ollama-env';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** True on the two platforms the desktop app targets (installers exist). */
function isSupportedPlatform() {
  return process.platform === 'win32' || process.platform === 'darwin';
}

/** Absolute path of the macOS LaunchAgent plist this module manages. */
function launchAgentPath() {
  return path.join(os.homedir(), 'Library', 'LaunchAgents', `${LAUNCH_AGENT_LABEL}.plist`);
}

function launchAgentPlist(required = REQUIRED) {
  const cmds = Object.entries(required)
    .map(([k, v]) => `launchctl setenv ${k} ${v}`)
    .join('; ');
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LAUNCH_AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>sh</string>
    <string>-c</string>
    <string>${cmds}</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
`;
}

function writeLaunchAgent(required = REQUIRED) {
  const p = launchAgentPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, launchAgentPlist(required), 'utf8');
  return p;
}

/**
 * Read the *persisted* value of a var (user-scope on Windows, launchd on macOS).
 * Best-effort: returns '' when unset or unreadable. `name` is always a REQUIRED,
 * INTEL_ACCEL or RETIRED key — a fixed constant, never user input.
 */
async function currentValue(name) {
  try {
    if (process.platform === 'win32') {
      const { code, stdout } = await run('powershell', [
        '-NoProfile', '-Command',
        `[Environment]::GetEnvironmentVariable('${name}','User')`,
      ]);
      return code === 0 ? stdout.trim() : '';
    }
    if (process.platform === 'darwin') {
      // `launchctl getenv` prints the value (or nothing) to stdout.
      const { code, stdout } = await run('launchctl', ['getenv', name]);
      return code === 0 ? stdout.trim() : '';
    }
  } catch {
    /* treat an unreadable var as unset */
  }
  return '';
}

/**
 * Pure: which RETIRED vars are still persisted with the value an earlier build
 * wrote (and so should be removed)?
 *
 * @param {Record<string,string>} current persisted name → value (missing = '').
 * @returns {string[]}
 */
function computeRetired(current, retired = RETIRED) {
  return Object.entries(retired)
    .filter(([name, value]) => (current[name] || '') === value)
    .map(([name]) => name);
}

/**
 * Pure decision: given a map of the currently-persisted values, is any REQUIRED
 * var missing or wrong, or any RETIRED value still present? Split out from
 * `needsSetup` so it can be unit-tested without spawning `setx`/`launchctl`.
 *
 * @param {Record<string,string>} current persisted name → value (missing = '').
 */
function computeNeedsSetup(current, required = REQUIRED, retired = RETIRED) {
  return Object.entries(required).some(([name, value]) => (current[name] || '') !== value)
    || computeRetired(current, retired).length > 0;
}

/** Read the persisted value of every REQUIRED-set and RETIRED var. */
async function readCurrent(required = REQUIRED) {
  const current = {};
  for (const name of [...Object.keys(required), ...Object.keys(RETIRED)]) {
    current[name] = await currentValue(name);
  }
  return current;
}

/** True if any var in `required` is not persisted with its target value, or a RETIRED value remains. */
async function needsSetup(required = REQUIRED) {
  return computeNeedsSetup(await readCurrent(required), required);
}

async function persistWindows(required = REQUIRED, onLine = () => {}) {
  for (const [name, value] of Object.entries(required)) {
    onLine(`Setting ${name}…`);
    // setx persists to HKCU\Environment (no admin needed for user scope).
    const { code, stderr } = await run('setx', [name, value]);
    if (code !== 0) throw new Error(`setx ${name} failed: ${stderr.trim()}`);
  }
}

async function persistMac(required = REQUIRED, onLine = () => {}) {
  // Apply to the current login session immediately so the relaunch below inherits
  // them, then install the login agent so a reboot/logout doesn't drop them.
  for (const [name, value] of Object.entries(required)) {
    await run('launchctl', ['setenv', name, value]).catch(() => {});
  }
  onLine('Installing login agent so settings survive a reboot…');
  const plistPath = writeLaunchAgent(required);
  // unload first so a rewritten plist is reloaded cleanly (ignore "not loaded").
  await run('launchctl', ['unload', plistPath]).catch(() => {});
  const { code, stderr } = await run('launchctl', ['load', '-w', plistPath]);
  if (code !== 0) throw new Error(`launchctl load failed: ${stderr.trim()}`);
}

/**
 * Remove retired vars from the persisted OS environment. `setx` cannot delete,
 * so Windows clears the user-scope value via .NET. On macOS the rewritten login
 * agent no longer sets them, so only the current session needs `unsetenv`.
 * `names` are RETIRED keys — fixed constants, never user input.
 */
async function unsetRetired(names, onLine = () => {}) {
  for (const name of names) {
    onLine(`Removing ${name}…`);
    if (process.platform === 'win32') {
      const { code, stderr } = await run('powershell', [
        '-NoProfile', '-Command',
        `[Environment]::SetEnvironmentVariable('${name}',$null,'User')`,
      ]);
      if (code !== 0) throw new Error(`Removing ${name} failed: ${stderr.trim()}`);
    } else if (process.platform === 'darwin') {
      await run('launchctl', ['unsetenv', name]).catch(() => {});
    }
  }
}

/** Poll until the Ollama daemon is no longer answering, or the retries run out. */
async function waitForStopped(retries = 12, delayMs = 500) {
  const ollama = loadOllama();
  for (let i = 0; i < retries; i++) {
    if (!(await ollama.isRunning())) return true;
    await sleep(delayMs);
  }
  return false;
}

/**
 * Quit the running Ollama app and relaunch it so it re-reads the env vars we
 * just persisted. Returns true once the daemon is reachable again, false if we
 * couldn't relaunch it (the caller then asks the user to restart Ollama).
 * `retired` names are stripped from the relaunched daemon's env: Electron may
 * itself have inherited them from the environment it was launched with.
 */
async function restartOllama(required = REQUIRED, onLine = () => {}, retired = []) {
  onLine('Restarting Ollama to apply the new settings…');
  if (process.platform === 'darwin') {
    await run('osascript', ['-e', 'tell application "Ollama" to quit']).catch(() => {});
    await waitForStopped();
    // GUI relaunch inherits the launchctl session env set in persistMac().
    await run('open', ['-a', 'Ollama']).catch(() => {});
  } else if (process.platform === 'win32') {
    await run('taskkill', ['/F', '/IM', 'ollama app.exe']).catch(() => {});
    await run('taskkill', ['/F', '/IM', 'ollama.exe']).catch(() => {});
    await waitForStopped();
    // Standard per-user install location for the Windows Ollama app. Spawn it
    // with an explicit merged env so it gets the values now, without waiting for
    // the registry change to propagate to freshly launched processes.
    const exe = path.join(
      process.env.LOCALAPPDATA || '', 'Programs', 'Ollama', 'ollama app.exe',
    );
    if (!fs.existsSync(exe)) return false;
    const env = { ...process.env, ...required };
    for (const name of retired) delete env[name];
    spawnDetached(exe, [], env);
  } else {
    return false;
  }
  return loadOllama().waitForRunning(30, 1000);
}

/**
 * Ensure the required host Ollama env vars are persisted and live.
 *
 * Idempotent and cheap on the warm path: if every value is already persisted it
 * returns immediately without touching the running daemon. Only when something
 * is missing, or a RETIRED value is still persisted, does it write/remove the
 * values and restart Ollama.
 *
 * On an Intel-only GPU host it additionally persists the iGPU-enable vars
 * (INTEL_ACCEL) so Ollama offloads to the integrated Arc/Iris GPU instead of
 * dropping it and falling back to CPU. NVIDIA/Apple hosts get only the base
 * set, unchanged.
 *
 * @param {(msg:string)=>void} onLine progress sink for wizard messages.
 * @param {{intel?:boolean, nvidia?:boolean, apple?:boolean}} [gpuInfo] detected
 *   GPU shape (from lib/gpu.js). Passed by the wizard, which has already probed
 *   it; omitted, this probes it itself.
 * @returns {Promise<{supported:boolean, changed:boolean, restarted:boolean}>}
 *   `restarted` is meaningful only when `changed` is true; when it's false the
 *   caller should ask the user to restart Ollama themselves.
 */
async function ensure(onLine = () => {}, gpuInfo) {
  if (!isSupportedPlatform()) return { supported: false, changed: false, restarted: false };

  const info = gpuInfo || (await require('./gpu').detect());
  const required = resolveVars(info);
  const current = await readCurrent(required);
  if (!computeNeedsSetup(current, required)) return { supported: true, changed: false, restarted: false };
  const retired = computeRetired(current);

  onLine('Applying required Ollama settings…');
  if (process.platform === 'win32') await persistWindows(required, onLine);
  else await persistMac(required, onLine);
  await unsetRetired(retired, onLine);

  const restarted = await restartOllama(required, onLine, retired);
  return { supported: true, changed: true, restarted };
}

module.exports = {
  REQUIRED,
  INTEL_ACCEL,
  RETIRED,
  LAUNCH_AGENT_LABEL,
  resolveVars,
  ensure,
  needsSetup,
  computeNeedsSetup,
  computeRetired,
  currentValue,
  restartOllama,
  launchAgentPath,
  launchAgentPlist,
  isSupportedPlatform,
};
