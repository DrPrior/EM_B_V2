'use strict';

/**
 * Lifecycle supervisor for the native backend (Neo4j + API).
 *
 * Decontainerized: instead of `docker compose`, it spawns Neo4j and the frozen
 * API as child processes (lib/procs.js), waits for Neo4j's bolt port and then the
 * API's /health, and tears both down on quit. Ollama is host-native and ensured
 * running by the wizard before the stack starts.
 *
 * Logging: both children's stdout/stderr go to electron.log (scopes
 * `electron.supervisor.neo4j` / `.api`), and the API is handed the same logs dir
 * as LOG_DIR so it writes api.log beside it.
 */

const fs = require('fs');
const path = require('path');

const procs = require('./lib/procs');
const ollama = require('./lib/ollama');
const ollamaenv = require('./lib/ollamaenv');
const snapshot = require('./lib/snapshot');
const paths = require('./lib/paths');
const logger = require('./lib/logger');
const { parseEnv } = require('./lib/envfile');

const log = logger.getLogger('supervisor');

// Recent API output, for the health-timeout message when there is no api.log
// (console mode: the API's records arrive on its stdout instead).
const API_TAIL_LINES = 200;
let apiTail = [];

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
  } catch (err) {
    log.warn('Could not read env file %s: %s', envPath, err.message);
    return {};
  }
}

/**
 * Record a child's lifecycle. A spawn failure (e.g. the exe missing) arrives as
 * an 'error' event, which would otherwise be an unhandled crash of the main
 * process; an unexpected exit is the first sign the backend died.
 */
function watchChild(child, childLog) {
  if (!child) return;
  child.on('error', (err) => childLog.error('Process failed to start:', err));
  child.on('exit', (code, signal) => {
    if (code === 0) childLog.info('Process exited normally');
    else childLog.warn('Process exited (code=%s, signal=%s)', code, signal);
  });
}

/**
 * Start the stack: launch Neo4j, wait for bolt, launch the API, wait for health.
 * @param {(line:string)=>void} onLine
 */
async function start(envPath, onLine = () => {}) {
  const vars = loadEnv(envPath);
  const neo4jLog = log.child('neo4j');
  const apiLog = log.child('api');
  const logNeo4jLine = logger.lineLogger(neo4jLog);
  const logApiLine = logger.lineLogger(apiLog);

  log.info('Starting Neo4j (%s)', paths.neo4jConsolePath());
  const neo4j = procs.startNeo4j(vars, (line) => {
    logNeo4jLine(line);
    onLine(line);
  });
  watchChild(neo4j, neo4jLog);

  if (!(await procs.waitForBolt())) {
    log.error('Neo4j did not open bolt port %d in time', procs.BOLT_PORT);
    throw new Error('Neo4j did not open its bolt port in time.');
  }
  log.info('Neo4j accepting bolt connections on port %d', procs.BOLT_PORT);

  const logDir = logger.logDir();
  const apiVars = logDir ? { ...vars, LOG_DIR: logDir } : vars;
  apiTail = [];
  log.info('Starting API (%s), api.log in %s', paths.apiExePath(), logDir || 'console');
  const api = procs.startApi(apiVars, (line) => {
    apiTail.push(line);
    if (apiTail.length > API_TAIL_LINES) apiTail.shift();
    logApiLine(line);
    onLine(line);
  });
  watchChild(api, apiLog);

  const healthy = await waitForHealth();
  if (healthy) log.info('API healthy on port %d', procs.API_PORT);
  else log.error('API did not report healthy in time');
  return healthy;
}

/** Last ~64 KB of api.log, or '' if there is none. */
function readApiLogTail() {
  const dir = logger.logDir();
  if (!dir) return '';
  const file = path.join(dir, 'api.log');
  try {
    const { size } = fs.statSync(file);
    const length = Math.min(size, 64 * 1024);
    const buf = Buffer.alloc(length);
    const fd = fs.openSync(file, 'r');
    try {
      fs.readSync(fd, buf, 0, length, size - length);
    } finally {
      fs.closeSync(fd);
    }
    return buf.toString('utf8');
  } catch {
    return '';
  }
}

/**
 * Build the error thrown when the API never reports healthy.
 *
 * `/health` is gated behind the FastAPI lifespan, which fails fast on any
 * startup dependency (Neo4j unreachable or auth-mismatched, host Ollama not
 * running). The real cause is in the API's own log, so quote its error records
 * and root exception rather than leaving the user with an opaque timeout.
 */
async function healthTimeoutError() {
  const summary = logger.summarizeErrors(readApiLogTail() || apiTail.join('\n'));
  const detail = summary.length ? `\n\nThe API reported:\n${summary.join('\n')}` : '';
  const logDir = logger.logDir();
  const where = logDir ? `\n\nFull logs: ${logDir}` : '';
  return new Error(`The API did not become healthy in time.${detail}${where}`);
}

/** Stop the stack. Best-effort; never throws on quit. */
async function stop() {
  log.info('Stopping API and Neo4j');
  try {
    await procs.stopAll();
    log.info('Backend stopped');
  } catch (err) {
    log.warn('Error while stopping the backend:', err);
  }
}

/**
 * Subsequent-launch fast path: ensure host Ollama is running (usually auto-starts
 * at login), restore the graph if needed, then bring the native stack up. Emits
 * the same step events the wizard renders; throws with a needs-user event if a
 * dependency isn't ready.
 * @param {(e:{step:string,status:string,message?:string})=>void} emit
 */
async function quickStart(envPath, emitToRenderer = () => {}) {
  const logProgress = logger.progressLogger(log.child('quickstart'));
  const emit = (e) => {
    logProgress(e);
    emitToRenderer(e);
  };

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
    log.warn('Graph restore skipped:', err);
    emit({ step: 'start', status: 'active', message: `Skipping graph restore: ${err.message}` });
  }
  const healthy = await start(envPath, () => {});
  if (!healthy) throw await healthTimeoutError();
  emit({ step: 'start', status: 'done', message: 'Ready.' });
}

module.exports = { isFirstRunComplete, checkHealth, waitForHealth, healthTimeoutError, start, stop, quickStart };
