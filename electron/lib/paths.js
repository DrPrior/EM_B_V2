'use strict';

/**
 * Filesystem locations for the desktop app.
 *
 * Bundled resources (the compose file, Modelfiles, asset manifest) live under
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

function composePath() {
  return path.join(resourcesRoot(), 'docker-compose.desktop.yml');
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

module.exports = {
  resourcesRoot,
  composePath,
  modelfilePath,
  assetsManifestPath,
  userDataDir,
  assetsDir,
  projectDataDir,
  snapshotDir,
  envFilePath,
  firstRunMarkerPath,
};
