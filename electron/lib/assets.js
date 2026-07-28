'use strict';

/**
 * Locates the offline setup assets shipped on the USB drive.
 *
 * The app is delivered by USB with no download server, so the three heavy custom
 * assets (API image tar, Neo4j snapshot, project_data archive) live in an
 * `assets/` folder next to the installer. Everything else (Docker/Ollama
 * installers, base models) still comes from the internet. These assets are only
 * needed during first-run setup — the USB can be removed afterward.
 *
 * Resolution order for the folder:
 *   1. $EMB_ASSETS_DIR
 *   2. a previously chosen+saved folder (userData/assets-dir.json)
 *   3. auto-scan: removable drives and dirs next to the app executable
 *   4. (caller falls back to a native folder picker)
 *
 * A folder is valid if it contains the manifest's image file — the signature.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { app } = require('electron');
const paths = require('./paths');
const { sha256 } = require('./download');

function savedDirPath() {
  return path.join(paths.userDataDir(), 'assets-dir.json');
}

function loadSavedDir() {
  try {
    return JSON.parse(fs.readFileSync(savedDirPath(), 'utf8')).dir || null;
  } catch { return null; }
}

function saveDir(dir) {
  fs.mkdirSync(paths.userDataDir(), { recursive: true });
  fs.writeFileSync(savedDirPath(), JSON.stringify({ dir }), 'utf8');
}

/** True if `dir` looks like a setup-assets folder for this manifest. */
function isValidDir(dir, manifest) {
  try {
    return !!dir && fs.existsSync(path.join(dir, manifest.image.file));
  } catch { return false; }
}

function candidateDirs() {
  const dirs = [];
  if (process.env.EMB_ASSETS_DIR) dirs.push(process.env.EMB_ASSETS_DIR);

  const saved = loadSavedDir();
  if (saved) dirs.push(saved);

  // Next to the installed/launched app (covers running Setup or app from USB).
  try {
    const exeDir = path.dirname(app.getPath('exe'));
    dirs.push(path.join(exeDir, 'assets'), path.join(exeDir, '..', 'assets'));
  } catch { /* ignore */ }

  if (process.platform === 'win32') {
    // Scan drive letters for <drive>:\assets and <drive>:\ .
    for (let c = 'A'.charCodeAt(0); c <= 'Z'.charCodeAt(0); c++) {
      const root = `${String.fromCharCode(c)}:\\`;
      dirs.push(path.join(root, 'assets'), root);
    }
  } else if (process.platform === 'darwin') {
    try {
      for (const vol of fs.readdirSync('/Volumes')) {
        dirs.push(path.join('/Volumes', vol, 'assets'), path.join('/Volumes', vol));
      }
    } catch { /* ignore */ }
  }
  // Dev convenience: the release/ output dir.
  dirs.push(path.join(os.homedir(), 'release'));
  return dirs;
}

/**
 * Return the first valid assets folder, or null if none found automatically.
 * @param {object} manifest
 */
function findAssetsDir(manifest) {
  for (const dir of candidateDirs()) {
    if (isValidDir(dir, manifest)) return dir;
  }
  return null;
}

/** Absolute path to a custom asset (key: 'image' | 'snapshot' | 'projectData'). */
function assetPath(dir, manifest, key) {
  return path.join(dir, manifest[key].file);
}

/**
 * Verify a local asset's SHA-256 if the manifest declares one. No-op when the
 * manifest checksum is blank (skips the multi-GB hash during development).
 */
async function verify(filePath, expected) {
  if (!expected) return true;
  const actual = await sha256(filePath);
  if (actual !== expected) {
    throw new Error(`Checksum mismatch for ${path.basename(filePath)} — the USB copy may be corrupt.`);
  }
  return true;
}

module.exports = { findAssetsDir, isValidDir, saveDir, assetPath, verify };
