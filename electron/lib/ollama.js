'use strict';

/**
 * Host-native Ollama provisioning for the wizard.
 *
 * Mirrors src/services/ollama_bootstrap.py but drives /api/pull and /api/create
 * with stream:true so the wizard can show real download/build progress. Doing it
 * here means the API container's startup bootstrap hits its instant warm path
 * (a single /api/tags read). Ollama runs natively on the host for GPU access, so
 * we talk to it at localhost:11434.
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { run, runStream, spawnDetached, commandExists } = require('./exec');
const { downloadFile } = require('./download');
const { parseModelfile } = require('./modelfile');
const paths = require('./paths');

const HOST = '127.0.0.1';
const PORT = 11434;

// Must match src/core/config.py.
const VARIANTS = [
  { variant: 'chat-model', base: 'gemma4:12b-it-qat', modelfile: 'Modelfile' },
  { variant: 'embedding-model', base: 'qwen3-embedding:4b', modelfile: 'Modelfile.embeddings' },
];

// Fallback installer URLs (overridable via assets.manifest.json → ollama).
const DEFAULT_INSTALLERS = {
  win32: 'https://ollama.com/download/OllamaSetup.exe',
  darwin: 'https://ollama.com/download/Ollama.dmg',
};

function apiGet(pathname, timeoutMs = 4000) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: HOST, port: PORT, path: pathname, timeout: timeoutMs }, (res) => {
      let body = '';
      res.on('data', (d) => (body += d));
      res.on('end', () => {
        try { resolve({ status: res.statusCode, json: body ? JSON.parse(body) : null }); }
        catch (e) { reject(e); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

/** POST JSON and invoke onObject for each newline-delimited JSON chunk streamed back. */
function apiPostStream(pathname, payload, onObject) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(payload);
    const req = http.request(
      { host: HOST, port: PORT, path: pathname, method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
      (res) => {
        let buf = '';
        res.on('data', (chunk) => {
          buf += chunk.toString();
          let idx;
          while ((idx = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 1);
            if (!line) continue;
            try { onObject(JSON.parse(line)); } catch { /* ignore partial */ }
          }
        });
        res.on('end', () => {
          if (buf.trim()) { try { onObject(JSON.parse(buf.trim())); } catch { /* ignore */ } }
          if (res.statusCode >= 400) reject(new Error(`${pathname} → HTTP ${res.statusCode}`));
          else resolve();
        });
      },
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

async function isRunning() {
  try {
    const { status } = await apiGet('/api/version', 2000);
    return status === 200;
  } catch { return false; }
}

async function waitForRunning(retries = 30, delayMs = 2000) {
  for (let i = 0; i < retries; i++) {
    if (await isRunning()) return true;
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return false;
}

/**
 * Standard install locations for the Ollama launcher. Windows installs per-user
 * by default but supports a per-machine install, and deployments that push it
 * centrally usually take the latter — check both.
 */
function appPathCandidates() {
  if (process.platform === 'win32') {
    const bases = [
      process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Programs'),
      process.env.ProgramFiles,
      process.env['ProgramFiles(x86)'],
    ];
    return bases.filter(Boolean).map((b) => path.join(b, 'Ollama', 'ollama app.exe'));
  }
  if (process.platform === 'darwin') return ['/Applications/Ollama.app'];
  return [];
}

/** Path to the installed Ollama launcher, or null if it isn't in a known place. */
function installedAppPath() {
  return appPathCandidates().find((p) => fs.existsSync(p)) || null;
}

/**
 * True if Ollama is installed, whether or not the daemon is currently up.
 *
 * Distinct from `isRunning`: a machine where Ollama was pre-installed but never
 * launched (fresh image, tray app not started yet) is installed-but-not-running,
 * and must not be reinstalled over. Falls back to probing the CLI on PATH so a
 * non-default install directory still counts.
 */
async function isInstalled() {
  if (installedAppPath() != null) return true;
  return commandExists('ollama', ['--version']);
}

/**
 * Start an already-installed Ollama and wait for the daemon to answer.
 * Returns false if it isn't installed or didn't come up, in which case the
 * caller asks the user to start it rather than reinstalling.
 */
async function start(onProgress = () => {}) {
  onProgress({ phase: 'start', message: 'Starting Ollama…' });
  const exe = installedAppPath();
  if (exe != null) {
    if (process.platform === 'darwin') {
      await run('open', ['-a', exe]).catch(() => {});
    } else {
      spawnDetached(exe);
    }
  } else if (await commandExists('ollama', ['--version'])) {
    // Installed outside the standard locations but on PATH — serve directly.
    spawnDetached('ollama', ['serve']);
  } else {
    return false;
  }
  return waitForRunning(30, 1000);
}

async function listTags() {
  const { json } = await apiGet('/api/tags', 8000);
  return new Set((json?.models || []).map((m) => m.name || ''));
}

function isPresent(name, tags) {
  return tags.has(name) || tags.has(`${name}:latest`);
}

function pullBase(model, onProgress = () => {}) {
  return apiPostStream('/api/pull', { model, stream: true }, (obj) => {
    const fraction = obj.total ? (obj.completed || 0) / obj.total : null;
    onProgress({ status: obj.status || '', fraction });
  });
}

function createVariant(variant, base, modelfileName, onProgress = () => {}) {
  const mfPath = paths.modelfilePath(modelfileName);
  const { system, parameters } = parseModelfile(fs.readFileSync(mfPath, 'utf8'));
  const payload = { model: variant, from: base, stream: true };
  if (system != null) payload.system = system;
  if (Object.keys(parameters).length) payload.parameters = parameters;
  return apiPostStream('/api/create', payload, (obj) => onProgress({ status: obj.status || '' }));
}

/**
 * Ensure every base model + custom variant exists. Idempotent.
 * @param {(e:{stage:string, model:string, status?:string, fraction?:number|null})=>void} onProgress
 */
async function ensureModels(onProgress = () => {}) {
  const tags = await listTags();
  for (const { variant, base, modelfile } of VARIANTS) {
    if (isPresent(variant, tags)) {
      onProgress({ stage: 'skip', model: variant, fraction: 1 });
      continue;
    }
    if (!isPresent(base, tags)) {
      await pullBase(base, (p) => onProgress({ stage: 'pull', model: base, ...p }));
    }
    await createVariant(variant, base, modelfile, (p) => onProgress({ stage: 'create', model: variant, ...p }));
    onProgress({ stage: 'done', model: variant, fraction: 1 });
  }
}

function installerUrl(manifest) {
  return (manifest?.ollama && manifest.ollama[process.platform]) || DEFAULT_INSTALLERS[process.platform];
}

/**
 * Download and launch the Ollama installer for this platform, then wait for the
 * daemon to come up. On Windows OllamaSetup.exe runs interactively; on macOS the
 * user drags the app from the mounted dmg. Returns true once reachable.
 */
async function installOllama(manifest, onProgress = () => {}) {
  const url = installerUrl(manifest);
  if (!url) throw new Error(`No Ollama installer URL for platform ${process.platform}`);
  const dest = path.join(paths.assetsDir(), path.basename(url));
  onProgress({ phase: 'download', message: 'Downloading Ollama…' });
  await downloadFile(url, dest, (p) => onProgress({ phase: 'download', ...p }));

  onProgress({ phase: 'install', message: 'Launching the Ollama installer…' });
  if (process.platform === 'win32') {
    // /SILENT keeps it unattended where the NSIS-style installer supports it.
    await runStream(dest, ['/SILENT'], {}, (l) => onProgress({ phase: 'install', line: l }));
  } else if (process.platform === 'darwin') {
    await runStream('open', ['-W', dest], {}, () => {});
    onProgress({ phase: 'install', message: 'Drag Ollama to Applications, then launch it.' });
  }

  onProgress({ phase: 'wait', message: 'Waiting for Ollama to start…' });
  const up = await waitForRunning(60, 2000);
  if (!up) throw new Error('Ollama did not become reachable after install.');
  return true;
}

module.exports = {
  VARIANTS,
  isRunning,
  isInstalled,
  installedAppPath,
  start,
  waitForRunning,
  ensureModels,
  installOllama,
  isPresent,
  listTags,
};
