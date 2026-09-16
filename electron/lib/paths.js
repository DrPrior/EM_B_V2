'use strict';

/**
 * Filesystem locations for the desktop app.
 *
 * Bundled resources (Modelfiles, asset manifest) live under
 * process.resourcesPath when packaged, or the repo root during `npm start`.
 * Per-install state (generated env file, cached downloads, first-run marker)
 * lives under Electron's userData dir so it survives app updates.
 */

const path = require('path');
const { app } = require('electron');

function resourcesRoot() {
  // Packaged: extraResources are copied straight under resourcesPath.
  // Dev (`electron .`): fall back to the repo root two levels up from lib/.
  return app.isPackaged
    ? process.resourcesPath
    : path.join(__dirname, '..', '..');
}

function modelfilePath(name) {
  // name is "Modelfile" or "Modelfile.embeddings".
  return path.join(resourcesRoot(), name);
}

function assetsManifestPath() {
  return path.join(resourcesRoot(), 'assets.manifest.json');
}

function userDataDir() {
  return app.getPath('userData');
}

/** Cache dir for large downloaded assets (image tar, dump, project_data). */
function assetsDir() {
  return path.join(userDataDir(), 'assets');
}

/** Extracted project_data corpus, bind-mounted read-only into the API. */
function projectDataDir() {
  return path.join(userDataDir(), 'project_data');
}

/** Dir holding the Neo4j dump for the offline load (mounted as /snapshot). */
function snapshotDir() {
  return path.join(userDataDir(), 'snapshot');
}

/** Per-install compose env file (random Neo4j password, host paths). */
function envFilePath() {
  return path.join(userDataDir(), 'desktop.env');
}

/** Marker written once the guided first-run provisioning has fully succeeded. */
function firstRunMarkerPath() {
  return path.join(userDataDir(), 'first-run-complete.json');
}

/**
 * Rotating log files: electron.log (shell + child output) and api.log (handed to
 * the API as LOG_DIR). The folder a user sends when reporting a problem.
 */
function logsDir() {
  return path.join(userDataDir(), 'logs');
}

// --- Native runtime locations (decontainerized) ---------------------------
// The bundled Neo4j server, its JRE, and the frozen API bundle are unpacked
// under userData by the first-run provisioning (Workstream C/D). The build
// pipeline (Workstream E) must produce these layouts:
//   <userData>/neo4j/bin/neo4j(.bat) + neo4j-admin(.bat), data/, conf/
//   <userData>/jre/            (bundled JRE; used as JAVA_HOME)
//   <userData>/api/emb-api(.exe) + _internal/   (PyInstaller one-dir bundle)

const _WIN = process.platform === 'win32';

/** Root of the unpacked native Neo4j server. */
function neo4jHomeDir() {
  return path.join(userDataDir(), 'neo4j');
}

function neo4jBinDir() {
  return path.join(neo4jHomeDir(), 'bin');
}

/** `neo4j` launcher — run with `console` to start the server in-process. */
function neo4jConsolePath() {
  return path.join(neo4jBinDir(), _WIN ? 'neo4j.bat' : 'neo4j');
}

/** `neo4j-admin` launcher — used for the offline snapshot load. */
function neo4jAdminPath() {
  return path.join(neo4jBinDir(), _WIN ? 'neo4j-admin.bat' : 'neo4j-admin');
}

/** Bundled JRE home; exported to child processes as JAVA_HOME for Neo4j. */
function jreHomeDir() {
  return path.join(userDataDir(), 'jre');
}

/** Unpacked PyInstaller one-dir bundle of the API. */
function apiDir() {
  return path.join(userDataDir(), 'api');
}

/** The frozen API executable inside apiDir(). */
function apiExePath() {
  return path.join(apiDir(), _WIN ? 'emb-api.exe' : 'emb-api');
}

module.exports = {
  resourcesRoot,
  modelfilePath,
  assetsManifestPath,
  userDataDir,
  assetsDir,
  projectDataDir,
  snapshotDir,
  envFilePath,
  firstRunMarkerPath,
  logsDir,
  neo4jHomeDir,
  neo4jBinDir,
  neo4jConsolePath,
  neo4jAdminPath,
  jreHomeDir,
  apiDir,
  apiExePath,
};
