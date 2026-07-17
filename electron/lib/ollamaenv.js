'use strict';

/**
 * Persist and apply the host-side Ollama environment variables the desktop
 * stack depends on.
 *
 * The Dockerized API reaches host-native Ollama at host.docker.internal:11434,
 * which only works if the daemon binds every interface (OLLAMA_HOST=0.0.0.0) —
 * by default Ollama listens on 127.0.0.1 and refuses the Docker bridge.
 * OLLAMA_KEEP_ALIVE / OLLAMA_MAX_LOADED_MODELS keep the chat and embedding
 * models warm and co-resident so queries don't pay reload lag.
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
const { spawn } = require('child_process');

const { run } = require('./exec');
// `./ollama` is lazy-required inside the restart helpers only: it pulls in
// `./paths` → electron, which we don't want to load (or download) for the pure
// helpers the test harness exercises.
const loadOllama = () => require('./ollama');

// The host env vars the desktop stack requires, with their target values. Keep
// in sync with the "required host environment variables" table in
// docs/HYBRID_SETUP.md.
const REQUIRED = Object.freeze({
  OLLAMA_HOST: '0.0.0.0',
  OLLAMA_KEEP_ALIVE: '-1',
  OLLAMA_MAX_LOADED_MODELS: '2',
});

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

function launchAgentPlist() {
  const cmds = Object.entries(REQUIRED)
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

function writeLaunchAgent() {
  const p = launchAgentPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, launchAgentPlist(), 'utf8');
  return p;
}

/**
 * Read the *persisted* value of a var (user-scope on Windows, launchd on macOS).
 * Best-effort: returns '' when unset or unreadable. `name` is always one of the
 * REQUIRED keys — a fixed constant, never user input.
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
 * Pure decision: given a map of the currently-persisted values, is any REQUIRED
 * var missing or wrong? Split out from `needsSetup` so it can be unit-tested
 * without spawning `setx`/`launchctl`.
 *
 * @param {Record<string,string>} current persisted name → value (missing = '').
 */
function computeNeedsSetup(current) {
  return Object.entries(REQUIRED).some(([name, value]) => (current[name] || '') !== value);
}

/** True if any REQUIRED var is not already persisted with its target value. */
async function needsSetup() {
  const current = {};
  for (const name of Object.keys(REQUIRED)) {
    current[name] = await currentValue(name);
  }
  return computeNeedsSetup(current);
}

async function persistWindows(onLine = () => {}) {
  for (const [name, value] of Object.entries(REQUIRED)) {
    onLine(`Setting ${name}…`);
    // setx persists to HKCU\Environment (no admin needed for user scope).
    const { code, stderr } = await run('setx', [name, value]);
    if (code !== 0) throw new Error(`setx ${name} failed: ${stderr.trim()}`);
  }
}

async function persistMac(onLine = () => {}) {
  // Apply to the current login session immediately so the relaunch below inherits
  // them, then install the login agent so a reboot/logout doesn't drop them.
  for (const [name, value] of Object.entries(REQUIRED)) {
    await run('launchctl', ['setenv', name, value]).catch(() => {});
  }
  onLine('Installing login agent so settings survive a reboot…');
  const plistPath = writeLaunchAgent();
  // unload first so a rewritten plist is reloaded cleanly (ignore "not loaded").
  await run('launchctl', ['unload', plistPath]).catch(() => {});
  const { code, stderr } = await run('launchctl', ['load', '-w', plistPath]);
  if (code !== 0) throw new Error(`launchctl load failed: ${stderr.trim()}`);
}

function spawnDetached(cmd, args, env) {
  const child = spawn(cmd, args, {
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
    env,
  });
  child.unref();
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
 */
async function restartOllama(onLine = () => {}) {
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
    spawnDetached(exe, [], { ...process.env, ...REQUIRED });
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
 * is missing does it write the values and restart Ollama.
 *
 * @param {(msg:string)=>void} onLine progress sink for wizard messages.
 * @returns {Promise<{supported:boolean, changed:boolean, restarted:boolean}>}
 *   `restarted` is meaningful only when `changed` is true; when it's false the
 *   caller should ask the user to restart Ollama themselves.
 */
async function ensure(onLine = () => {}) {
  if (!isSupportedPlatform()) return { supported: false, changed: false, restarted: false };
  if (!(await needsSetup())) return { supported: true, changed: false, restarted: false };

  onLine('Applying required Ollama settings…');
  if (process.platform === 'win32') await persistWindows(onLine);
  else await persistMac(onLine);

  const restarted = await restartOllama(onLine);
  return { supported: true, changed: true, restarted };
}

module.exports = {
  REQUIRED,
  LAUNCH_AGENT_LABEL,
  ensure,
  needsSetup,
  computeNeedsSetup,
  currentValue,
  restartOllama,
  launchAgentPath,
  launchAgentPlist,
  isSupportedPlatform,
};
