'use strict';

/**
 * Guided first-run provisioning orchestrator (native, USB delivery).
 *
 * Runs the wizard steps in order, emitting progress events the renderer renders
 * as a checklist. Every step is idempotent and re-entrant: if the app is
 * relaunched mid-setup, each step re-checks whether its work is already done and
 * resumes.
 *
 * Decontainerized: there is no Docker and no prebuilt image. The heavy custom
 * assets are read from a local `assets/` folder on the USB (`assetsDir`):
 *   - apiBundle : the frozen PyInstaller one-dir API (emb-api.exe + _internal/)
 *   - neo4j     : Neo4j Community server (bin/, conf/, ... at the zip root)
 *   - jre       : the bundled JRE (used as JAVA_HOME for Neo4j)
 *   - snapshot  : the prebuilt graph dump (record/aligned format)
 *   - projectData : the source corpus (a top-level project_data/ dir)
 * Base models still come from the internet. Ollama is used in place if present.
 *
 * Build-pipeline contract (Workstream E must satisfy these when zipping assets):
 *   - apiBundle unzips to <userData>/api/emb-api.exe + _internal/ (contents at root)
 *   - neo4j unzips to <userData>/neo4j/bin/... (contents at root, not nested)
 *   - jre   unzips to <userData>/jre/bin/java
 *
 * Steps: gpu → ollama → models → neo4j → runtime → data → snapshot → start.
 */

const fs = require('fs');
const path = require('path');

const paths = require('./paths');
const gpu = require('./gpu');
const ollama = require('./ollama');
const ollamaenv = require('./ollamaenv');
const snapshot = require('./snapshot');
const assets = require('./assets');
const supervisor = require('../supervisor');
const logger = require('./logger');
const { ensureEnvFile } = require('./envfile');
const { runStream } = require('./exec');

const log = logger.getLogger('firstrun');

/** Kept for main.js compatibility; no longer thrown now that Docker is gone. */
class RebootRequiredError extends Error {}

function loadManifest() {
  return JSON.parse(fs.readFileSync(paths.assetsManifestPath(), 'utf8'));
}

/** Extract a .zip (Neo4j / JRE / API bundle). `tar` on Win10+/macOS reads zips. */
async function extractZip(archivePath, destDir, onLine = () => {}) {
  fs.mkdirSync(destDir, { recursive: true });
  const { code } = await runStream('tar', ['-xf', archivePath, '-C', destDir], {}, onLine);
  if (code !== 0) throw new Error(`Failed to extract ${archivePath}`);
}

/** Extract a .tar.gz (the source corpus). */
async function extractTarGz(archivePath, destDir, onLine = () => {}) {
  fs.mkdirSync(destDir, { recursive: true });
  const { code } = await runStream('tar', ['-xzf', archivePath, '-C', destDir], {}, onLine);
  if (code !== 0) throw new Error(`Failed to extract ${archivePath}`);
}

/**
 * @param {(e:{step:string,status:string,message?:string,progress?:number|null})=>void} emit
 * @param {string} assetsDir Folder on the USB holding the custom setup assets.
 */
async function runFirstRun(emit, assetsDir) {
  const manifest = loadManifest();
  log.info('First run starting (assets=%s, version=%s)', assetsDir, manifest.version);
  // Every wizard event passes through here, so this one hook records the whole
  // provisioning run (transitions only, not per-tick download progress).
  const logProgress = logger.progressLogger(log);
  const step = (s, status, message, progress = null) => {
    const e = { step: s, status, message, progress };
    logProgress(e);
    emit(e);
  };

  // 1. GPU (informational).
  step('gpu', 'active', 'Detecting graphics hardware…');
  const g = await gpu.detect();
  step('gpu', 'done', `Acceleration: ${g.accel}`);

  // 2. Ollama (host-native, for GPU inference).
  step('ollama', 'active', 'Checking for Ollama…');
  if (!(await ollama.isRunning())) {
    if (await ollama.isInstalled()) {
      step('ollama', 'active', 'Starting Ollama…');
      if (!(await ollama.start((p) => step('ollama', 'active', p.message)))) {
        step('ollama', 'needs-user',
          'Ollama is installed but could not be started automatically. Open Ollama, then click Retry.');
        throw new Error('Ollama is installed but could not be started');
      }
    } else {
      step('ollama', 'active', 'Installing Ollama…');
      await ollama.installOllama(manifest, (p) =>
        step('ollama', 'active', p.message || p.line || 'Installing Ollama…', p.fraction ?? null));
    }
  }
  // Persist + apply the host env vars Ollama needs. Native: NO OLLAMA_HOST=0.0.0.0
  // (the API reaches Ollama over loopback); ollamaenv keeps the warmth/perf vars.
  step('ollama', 'active', 'Configuring Ollama for the app…');
  const envRes = await ollamaenv.ensure((msg) => step('ollama', 'active', msg), g);
  if (envRes.changed && !envRes.restarted) {
    step('ollama', 'needs-user',
      'Ollama needs to restart to apply required settings. Quit Ollama and reopen it, then click Retry.');
    throw new Error('Ollama must be restarted to apply required settings');
  }
  step('ollama', 'done', 'Ollama is running.');

  // 3. Models — pull bases only if missing, then build the custom variants.
  step('models', 'active', 'Checking language models…');
  await ollama.ensureModels((p) => {
    const label = p.stage === 'pull' ? `Downloading ${p.model} (large — first run only)` :
      p.stage === 'create' ? `Building ${p.model}` :
      p.stage === 'skip' ? `${p.model} already present` : `${p.model} ready`;
    step('models', 'active', `${label}${p.status ? ' — ' + p.status : ''}`, p.fraction ?? null);
  });
  step('models', 'done', 'Models ready.');

  // Env file (stable Neo4j password + native vars). Needed by the steps below.
  const { path: envPath, vars } = ensureEnvFile();

  // 4. Neo4j engine — unpack the bundled server + JRE, set the initial password
  //    BEFORE the first start (the password is baked into the data dir on init).
  step('neo4j', 'active', 'Preparing the database engine…');
  if (!fs.existsSync(paths.neo4jConsolePath())) {
    const nz = assets.assetPath(assetsDir, manifest, 'neo4j');
    await assets.verify(nz, manifest.neo4j.sha256);
    step('neo4j', 'active', 'Unpacking Neo4j…');
    await extractZip(nz, paths.neo4jHomeDir(), (l) => step('neo4j', 'active', l));
  }
  if (!fs.existsSync(path.join(paths.jreHomeDir(), 'bin'))) {
    const jz = assets.assetPath(assetsDir, manifest, 'jre');
    await assets.verify(jz, manifest.jre.sha256);
    step('neo4j', 'active', 'Unpacking the Java runtime…');
    await extractZip(jz, paths.jreHomeDir(), (l) => step('neo4j', 'active', l));
  }
  const pwMarker = path.join(paths.userDataDir(), 'neo4j-password-set.json');
  if (!fs.existsSync(pwMarker)) {
    step('neo4j', 'active', 'Setting database credentials…');
    const password = vars.NEO4J_AUTH.split('/')[1];
    const env = { ...process.env, JAVA_HOME: paths.jreHomeDir() };
    const { code } = await runStream(paths.neo4jAdminPath(),
      ['dbms', 'set-initial-password', password], { env }, (l) => step('neo4j', 'active', l));
    if (code !== 0) throw new Error('Failed to set the Neo4j initial password.');
    fs.writeFileSync(pwMarker, JSON.stringify({ setAt: new Date().toISOString() }), 'utf8');
  }
  step('neo4j', 'done', 'Database engine ready.');

  // 5. Runtime — unpack the frozen API bundle.
  step('runtime', 'active', 'Preparing the application…');
  if (!fs.existsSync(paths.apiExePath())) {
    const az = assets.assetPath(assetsDir, manifest, 'apiBundle');
    await assets.verify(az, manifest.apiBundle.sha256);
    step('runtime', 'active', 'Unpacking the application…');
    await extractZip(az, paths.apiDir(), (l) => step('runtime', 'active', l));
  }
  step('runtime', 'done', 'Application ready.');

  // 6. Source corpus — extract the project_data archive under userData (its
  //    top-level project_data/ dir lands at paths.projectDataDir()).
  const dataMarker = path.join(paths.userDataDir(), 'data-ready.json');
  step('data', 'active', 'Preparing source documents…');
  if (!fs.existsSync(dataMarker)) {
    const archive = assets.assetPath(assetsDir, manifest, 'projectData');
    await assets.verify(archive, manifest.projectData.sha256);
    step('data', 'active', 'Extracting source documents…');
    await extractTarGz(archive, paths.userDataDir(), (l) => step('data', 'active', l));
    fs.writeFileSync(dataMarker, JSON.stringify({ readyAt: new Date().toISOString() }), 'utf8');
  }
  step('data', 'done', 'Source documents ready.');

  // 7. Graph snapshot — copy the dump into place and load it OFFLINE (Neo4j is
  //    not started yet), so the slow ingest/enrich pipeline is skipped.
  step('snapshot', 'active', 'Preparing the knowledge graph…');
  if (!snapshot.alreadyImported()) {
    const srcDump = assets.assetPath(assetsDir, manifest, 'snapshot');
    await assets.verify(srcDump, manifest.snapshot.sha256);
    fs.mkdirSync(paths.snapshotDir(), { recursive: true });
    if (srcDump !== snapshot.dumpPath()) fs.copyFileSync(srcDump, snapshot.dumpPath());
    await snapshot.importSnapshot(envPath, (l) => step('snapshot', 'active', l));
  }
  step('snapshot', 'done', 'Knowledge graph ready.');

  // 8. Start the native stack (Neo4j → API) and wait for health.
  step('start', 'active', 'Starting the assistant…');
  const healthy = await supervisor.start(envPath, (l) => step('start', 'active', l));
  if (!healthy) throw await supervisor.healthTimeoutError();
  step('start', 'done', 'Ready.');

  // Mark first run complete.
  log.info('First run complete');
  fs.writeFileSync(paths.firstRunMarkerPath(),
    JSON.stringify({ completedAt: new Date().toISOString() }), 'utf8');

  return { envPath };
}

module.exports = { runFirstRun, RebootRequiredError, loadManifest };
