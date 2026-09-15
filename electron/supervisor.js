'use strict';

/**
 * Lifecycle supervisor for the native backend (Neo4j + API).
 *
 * Decontainerized: instead of `docker compose`, it spawns Neo4j and the frozen
 * API as child processes (lib/procs.js), waits for Neo4j's bolt port and then the
 * API's /health, and tears both down on quit. Ollama is host-native and ensured
 * running by the wizard before the stack starts.
 */

const fs = require('fs');

const procs = require('./lib/procs');
const ollama = require('./lib/ollama');
const ollamaenv = require('./lib/ollamaenv');
const snapshot = require('./lib/snapshot');
const paths = require('./lib/paths');
const { parseEnv } = require('./lib/envfile');

/** True once the guided first-run provisioning has fully completed. */
function isFirstRunComplete() {
  return fs.existsSync(paths.firstRunMarkerPath());
}

function checkHealth(timeoutMs = 2000) {
  return procs.checkHealth(timeoutMs);
}

function waitForHealth(retries = 90, delayMs = 2000) {
  return procs.waitForHealth(retries, delayMs);
}

/** Read the per-install env file into a plain object for the child processes. */
function loadEnv(envPath) {
  try {
    return parseEnv(fs.readFileSync(envPath, 'utf8'));
  } catch {
    return {};
  }
}

/**
 * Start the stack: launch Neo4j, wait for bolt, launch the API, wait for health.
 * @param {(line:string)=>void} onLine
 */
 * Build the error thrown when the API never reports healthy.
 *
 * `/health` is gated behind the FastAPI lifespan, which fails fast on any
 * startup dependency — Neo4j unreachable or auth-mismatched, or host Ollama
 * unreachable from the container (host.docker.internal:11434 blocked by the
 * firewall, or OLLAMA_HOST=0.0.0.0 not applied to the running daemon). That real
 * cause is in the API container log, not in `compose up -d` output, so append
 * its tail here rather than leaving the user with an opaque timeout.
 */
async function healthTimeoutError(envPath) {
  let detail = '';
  try {
    const out = await compose.logs(envPath, 'api', 40);
    const tail = out.split('\n').map((l) => l.trim()).filter(Boolean).slice(-12).join('\n');
    if (tail) detail = `\n\nThe API container reported:\n${tail}`;
  } catch { /* diagnostics are best-effort */ }
  return new Error(`The API did not become healthy in time.${detail}`);
}

/** Stop the stack. Best-effort; never throws on quit. */
async function stop() {
  try {
    await procs.stopAll();
  } catch {
    /* ignore on shutdown */
  }
}

/**
 * Subsequent-launch fast path: ensure host Ollama is running (usually auto-starts
 * at login), restore the graph if needed, then bring the native stack up. Emits
 * the same step events the wizard renders; throws with a needs-user event if a
 * dependency isn't ready.
 * @param {(e:{step:string,status:string,message?:string})=>void} emit
 */
async function quickStart(envPath, emit = () => {}) {
  emit({ step: 'ollama', status: 'active', message: 'Waiting for Ollama…' });
  if (!(await ollama.isRunning()) && !(await ollama.waitForRunning(30, 2000))) {
    emit({ step: 'ollama', status: 'needs-user', message: 'Please start Ollama, then retry.' });
    throw new Error('Ollama not running');
  }
  // Self-heal the host env vars if something cleared them. No-op on the warm path.
  const envRes = await ollamaenv.ensure((msg) =>
    emit({ step: 'ollama', status: 'active', message: msg }),
  );
  if (envRes.changed && !envRes.restarted) {
    emit({
      step: 'ollama',
      status: 'needs-user',
      message: 'Quit and reopen Ollama to apply required settings, then retry.',
    });
    throw new Error('Ollama must be restarted to apply required settings');
  }
  emit({ step: 'ollama', status: 'done', message: 'Ollama is running.' });

  emit({ step: 'start', status: 'active', message: 'Starting the assistant…' });
  // Neo4j is not started yet, so the offline snapshot load is safe. Idempotent —
  // a no-op once the marker matches the current data dir.
  try {
    await snapshot.importSnapshot(envPath, (l) =>
      emit({ step: 'start', status: 'active', message: l }),
    );
  } catch (err) {
    emit({ step: 'start', status: 'active', message: `Skipping graph restore: ${err.message}` });
  }
  const healthy = await start(envPath, () => {});
  if (!healthy) throw await healthTimeoutError(envPath);
  emit({ step: 'start', status: 'done', message: 'Ready.' });
}

module.exports = { isFirstRunComplete, checkHealth, waitForHealth, healthTimeoutError, start, stop, quickStart };
