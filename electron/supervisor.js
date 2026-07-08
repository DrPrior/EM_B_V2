'use strict';

/**
 * Lifecycle supervisor for the Dockerized backend (Neo4j + API).
 *
 * Brings the stack up, polls the API's /health endpoint, and tears it down on
 * quit. Ollama is host-native and outside this supervisor — the wizard ensures
 * it's running before the stack starts.
 */

const fs = require('fs');
const http = require('http');
const compose = require('./lib/compose');
const docker = require('./lib/docker');
const ollama = require('./lib/ollama');
const paths = require('./lib/paths');

const HEALTH_URL = { host: '127.0.0.1', port: 8000, path: '/health' };

/** True once the guided first-run provisioning has fully completed. */
function isFirstRunComplete() {
  return fs.existsSync(paths.firstRunMarkerPath());
}

function checkHealth(timeoutMs = 2000) {
  return new Promise((resolve) => {
    const req = http.get({ ...HEALTH_URL, timeout: timeoutMs }, (res) => {
      let body = '';
      res.on('data', (d) => (body += d));
      res.on('end', () => {
        try { resolve(res.statusCode === 200 && JSON.parse(body).status === 'healthy'); }
        catch { resolve(false); }
      });
    });
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve(false));
  });
}

async function waitForHealth(retries = 60, delayMs = 2000) {
  for (let i = 0; i < retries; i++) {
    if (await checkHealth()) return true;
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return false;
}

/** Start the stack (idempotent — compose up -d) and wait until healthy. */
async function start(envPath, onLine = () => {}) {
  await compose.up(envPath, onLine);
  return waitForHealth();
}

/** Stop the stack. Best-effort; never throws on quit. */
async function stop(envPath, onLine = () => {}) {
  try { await compose.down(envPath, onLine); } catch { /* ignore on shutdown */ }
}

/**
 * Subsequent-launch fast path: wait for the already-installed Docker + Ollama to
 * be running (they usually auto-start at login), then bring the stack up. Emits
 * the same step events the wizard renders; throws with a needs-user event if a
 * dependency isn't running.
 * @param {(e:{step:string,status:string,message?:string})=>void} emit
 */
async function quickStart(envPath, emit = () => {}) {
  emit({ step: 'docker', status: 'active', message: 'Waiting for Docker…' });
  if (!(await docker.isDaemonRunning()) && !(await docker.waitForDaemon(30, 2000))) {
    emit({ step: 'docker', status: 'needs-user', message: 'Please start Docker Desktop, then retry.' });
    throw new Error('Docker daemon not running');
  }
  emit({ step: 'docker', status: 'done', message: 'Docker is running.' });

  emit({ step: 'ollama', status: 'active', message: 'Waiting for Ollama…' });
  if (!(await ollama.isRunning()) && !(await ollama.waitForRunning(30, 2000))) {
    emit({ step: 'ollama', status: 'needs-user', message: 'Please start Ollama, then retry.' });
    throw new Error('Ollama not running');
  }
  emit({ step: 'ollama', status: 'done', message: 'Ollama is running.' });

  emit({ step: 'start', status: 'active', message: 'Starting the assistant…' });
  const healthy = await start(envPath, () => {});
  if (!healthy) throw new Error('The API did not become healthy in time.');
  emit({ step: 'start', status: 'done', message: 'Ready.' });
}

module.exports = { isFirstRunComplete, checkHealth, waitForHealth, start, stop, quickStart };
