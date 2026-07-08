'use strict';

/**
 * Guided first-run provisioning orchestrator.
 *
 * Runs the wizard steps in order, emitting progress events the renderer renders
 * as a checklist. Every step is idempotent and re-entrant: if Docker Desktop
 * required a reboot, the user relaunches the app and provisioning resumes where
 * it left off (each step re-checks whether its work is already done).
 *
 * Steps: gpu → docker → ollama → models → image → data → snapshot → start.
 */

const fs = require('fs');
const path = require('path');

const paths = require('./paths');
const gpu = require('./gpu');
const docker = require('./docker');
const ollama = require('./ollama');
const snapshot = require('./snapshot');
const compose = require('./compose');
const supervisor = require('../supervisor');
const { ensureEnvFile } = require('./envfile');
const { ensureAsset } = require('./download');
const { runStream } = require('./exec');

class RebootRequiredError extends Error {}

function loadManifest() {
  const raw = fs.readFileSync(paths.assetsManifestPath(), 'utf8');
  return JSON.parse(raw);
}

function imageTag(manifest) {
  return `emb-hybrid-api:${manifest.image.version}`;
}

async function extractTarGz(archivePath, destDir, onLine = () => {}) {
  fs.mkdirSync(destDir, { recursive: true });
  // `tar` ships with Windows 10+ (bsdtar) and macOS.
  const { code } = await runStream('tar', ['-xzf', archivePath, '-C', destDir], {}, onLine);
  if (code !== 0) throw new Error(`Failed to extract ${archivePath}`);
}

/**
 * @param {(e:{step:string,status:string,message?:string,progress?:number|null})=>void} emit
 */
async function runFirstRun(emit) {
  const manifest = loadManifest();
  const step = (s, status, message, progress = null) => emit({ step: s, status, message, progress });

  // 1. GPU (informational).
  step('gpu', 'active', 'Detecting graphics hardware…');
  const g = await gpu.detect();
  step('gpu', 'done', `Acceleration: ${g.accel}`);

  // 2. Docker Desktop.
  step('docker', 'active', 'Checking for Docker…');
  if (!(await docker.isInstalled())) {
    step('docker', 'active', 'Installing Docker Desktop…');
    await docker.installDockerDesktop(manifest, (p) =>
      step('docker', 'active', p.message || p.line || 'Installing Docker Desktop…',
        p.fraction ?? null));
  }
  if (!(await docker.isDaemonRunning())) {
    step('docker', 'active', 'Waiting for Docker to start…');
    const up = await docker.waitForDaemon(60, 2000);
    if (!up) {
      step('docker', 'needs-user',
        'Docker Desktop needs to finish installing (this may require a restart). ' +
        'Complete it, ensure Docker is running, then reopen this app.');
      throw new RebootRequiredError('Docker daemon not running');
    }
  }
  step('docker', 'done', 'Docker is running.');

  // 3. Ollama (host-native, for GPU inference).
  step('ollama', 'active', 'Checking for Ollama…');
  if (!(await ollama.isRunning())) {
    step('ollama', 'active', 'Installing Ollama…');
    await ollama.installOllama(manifest, (p) =>
      step('ollama', 'active', p.message || p.line || 'Installing Ollama…', p.fraction ?? null));
  }
  step('ollama', 'done', 'Ollama is running.');

  // 4. Models (~10 GB on first run).
  step('models', 'active', 'Downloading language models (~10 GB, first run only)…');
  await ollama.ensureModels((p) => {
    const label = p.stage === 'pull' ? `Downloading ${p.model}` :
      p.stage === 'create' ? `Building ${p.model}` :
      p.stage === 'skip' ? `${p.model} already present` : `${p.model} ready`;
    step('models', 'active', `${label}${p.status ? ' — ' + p.status : ''}`, p.fraction ?? null);
  });
  step('models', 'done', 'Models ready.');

  // Env file (needed by every compose call below).
  const { path: envPath } = ensureEnvFile({ appVersion: manifest.image.version });

  // 5. API image.
  const tag = imageTag(manifest);
  step('image', 'active', 'Preparing the application image…');
  if (!(await docker.imageExists(tag))) {
    const tar = path.join(paths.assetsDir(), path.basename(new URL(manifest.image.url).pathname));
    step('image', 'active', 'Downloading the application image…');
    await ensureAsset({ url: manifest.image.url, dest: tar, sha256: manifest.image.sha256 },
      (p) => step('image', 'active', 'Downloading the application image…', p.fraction ?? null));
    step('image', 'active', 'Loading the application image into Docker…');
    await docker.loadImage(tar, (l) => step('image', 'active', l));
  }
  step('image', 'done', 'Application image ready.');

  // 6. Source corpus (mounted read-only so citation links resolve).
  const dataMarker = path.join(paths.userDataDir(), 'data-ready.json');
  step('data', 'active', 'Preparing source documents…');
  if (!fs.existsSync(dataMarker)) {
    const archive = path.join(paths.assetsDir(), path.basename(new URL(manifest.projectData.url).pathname));
    await ensureAsset({ url: manifest.projectData.url, dest: archive, sha256: manifest.projectData.sha256 },
      (p) => step('data', 'active', 'Downloading source documents…', p.fraction ?? null));
    step('data', 'active', 'Extracting source documents…');
    // The archive holds a top-level `project_data/` dir (tar -C <repo> project_data),
    // so extract into userData — yielding <userData>/project_data, which is what
    // PROJECT_DATA_DIR points at and what gets mounted to /app/project_data.
    await extractTarGz(archive, paths.userDataDir());
    fs.writeFileSync(dataMarker, JSON.stringify({ readyAt: new Date().toISOString() }), 'utf8');
  }
  step('data', 'done', 'Source documents ready.');

  // 7. Graph snapshot.
  step('snapshot', 'active', 'Preparing the knowledge graph…');
  if (!snapshot.alreadyImported()) {
    await ensureAsset({ url: manifest.snapshot.url, dest: snapshot.dumpPath(), sha256: manifest.snapshot.sha256 },
      (p) => step('snapshot', 'active', 'Downloading the knowledge graph…', p.fraction ?? null));
    await snapshot.importSnapshot(envPath, (l) => step('snapshot', 'active', l));
  }
  step('snapshot', 'done', 'Knowledge graph ready.');

  // 8. Start the stack.
  step('start', 'active', 'Starting the assistant…');
  await compose.up(envPath, (l) => step('start', 'active', l));
  const healthy = await supervisor.waitForHealth(120, 2000);
  if (!healthy) throw new Error('The API did not become healthy in time.');
  step('start', 'done', 'Ready.');

  // Mark first run complete.
  fs.writeFileSync(paths.firstRunMarkerPath(),
    JSON.stringify({ completedAt: new Date().toISOString(), version: manifest.image.version }), 'utf8');

  return { envPath };
}

module.exports = { runFirstRun, RebootRequiredError };
