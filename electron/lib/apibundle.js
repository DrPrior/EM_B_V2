'use strict';

/**
 * Install the frozen API bundle and keep it matched to the bundled manifest.
 *
 * First run unpacks `apiBundle` under userData. An in-place app update ships a
 * new manifest (new `version` / `apiBundle.sha256`) but keeps the first-run
 * marker, so launches take the fast path and would keep running the old API exe
 * behind the new shell. `ensureApiBundle` compares what is installed with the
 * manifest and, on a mismatch, re-unpacks the bundle from the USB assets,
 * prompting for the drive if it isn't mounted.
 *
 * What is installed is recorded in a marker file *inside* the bundle dir, so the
 * record and the files it describes are swapped in together. The swap is staged
 * so an interrupted install never leaves a half-extracted dir that looks
 * current: extract into `api.new/`, write the marker there, move `api/` aside to
 * `api.old/`, move `api.new/` into place. A failed final rename moves `api.old/`
 * back; a crash anywhere before it leaves no current marker at `api/`, so the
 * next launch simply reinstalls.
 *
 * Directories and I/O are injected, so this is testable without Electron;
 * main.js and firstrun.js wire in the real paths, extractor, and USB resolver.
 */

const fs = require('fs');
const path = require('path');

const MARKER = '.installed-bundle.json';

/** The identity of the bundle a manifest describes. */
function bundleId(manifest) {
  return { version: manifest.version, sha256: manifest.apiBundle.sha256 || '' };
}

/** The marker of the installed bundle, or null if none/unreadable. */
function readInstalled(apiDir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(apiDir, MARKER), 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Pure: does the installed marker describe the manifest's bundle? Both version
 * and checksum must match, so a rebuilt bundle under the same version counts as
 * an update too (dev manifests leave sha256 blank; then version alone decides).
 */
function isCurrent(installed, manifest) {
  const want = bundleId(manifest);
  return !!installed && installed.version === want.version
    && (installed.sha256 || '') === want.sha256;
}

/** True if the manifest's bundle is fully installed at `apiDir`. */
function isInstalled(manifest, { apiDir, exeName }) {
  return isCurrent(readInstalled(apiDir), manifest) && fs.existsSync(path.join(apiDir, exeName));
}

/**
 * Unpack `zipPath` as the installed bundle, replacing any previous one. Throws
 * (leaving the previous install untouched) if extraction fails or the archive
 * doesn't have `exeName` at its root.
 */
async function installApiBundle(zipPath, manifest, { apiDir, exeName, extractZip, onLine = () => {} }) {
  const staging = `${apiDir}.new`;
  const old = `${apiDir}.old`;
  fs.rmSync(staging, { recursive: true, force: true });
  fs.rmSync(old, { recursive: true, force: true });
  try {
    await extractZip(zipPath, staging, onLine);
    if (!fs.existsSync(path.join(staging, exeName))) {
      throw new Error(`${path.basename(zipPath)} does not contain ${exeName} at its root.`);
    }
    fs.writeFileSync(path.join(staging, MARKER),
      JSON.stringify({ ...bundleId(manifest), installedAt: new Date().toISOString() }), 'utf8');
    if (fs.existsSync(apiDir)) fs.renameSync(apiDir, old);
    try {
      fs.renameSync(staging, apiDir);
    } catch (err) {
      // Put the previous install back rather than leave no API at all.
      if (!fs.existsSync(apiDir) && fs.existsSync(old)) fs.renameSync(old, apiDir);
      throw err;
    }
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
  try {
    fs.rmSync(old, { recursive: true, force: true });
  } catch {
    /* leftover api.old/ is harmless; the next install clears it */
  }
}

/**
 * Fast-path guard: make sure the manifest's API bundle is installed before the
 * stack starts, installing it from the USB assets if it isn't.
 *
 * @param {{version:string, apiBundle:{file:string, sha256:string}}} manifest
 * @param {object} deps
 * @param {string} deps.apiDir Where the bundle is installed.
 * @param {string} deps.exeName API executable file name at the bundle root.
 * @param {(zip:string, dest:string, onLine?:Function)=>Promise<void>} deps.extractZip
 * @param {{assetPath:(dir:string, manifest:object, key:string)=>string, verify:(file:string, sha:string)=>Promise<boolean>}} deps.assets
 * @param {(manifest:object)=>Promise<string|null>} deps.resolveAssetsDir Returns the
 *   USB assets dir, or null if the user declined / it isn't available.
 * @param {(e:{step:string, status:string, message?:string})=>void} deps.emit Progress sink.
 * @param {(message:string)=>void} deps.onError User-facing error sink.
 * @returns {Promise<boolean>} false when the bundle is out of date and couldn't be
 *   installed (a user-facing message has already been sent via `onError`).
 */
async function ensureApiBundle(manifest, deps) {
  const { apiDir, exeName, extractZip, assets, resolveAssetsDir, emit, onError } = deps;
  if (isInstalled(manifest, deps)) {
    emit({ step: 'runtime', status: 'done', message: 'Application up to date.' });
    return true;
  }

  const installed = readInstalled(apiDir);
  const label = installed ? `${installed.version} → ${manifest.version}` : manifest.version;
  emit({ step: 'runtime', status: 'active', message: `Installing the application update (${label})…` });
  const fail = (message) => {
    emit({ step: 'runtime', status: 'error', message: 'Update not installed.' });
    onError(message);
    return false;
  };

  const assetsDir = await resolveAssetsDir(manifest);
  if (!assetsDir) {
    return fail(`This update (version ${manifest.version}) needs the USB drive to finish ` +
      'installing. Plug it in and reopen the app.');
  }
  const zip = assets.assetPath(assetsDir, manifest, 'apiBundle');
  try {
    await assets.verify(zip, manifest.apiBundle.sha256);
  } catch {
    return fail(`The setup files in ${assetsDir} are not version ${manifest.version} (or are ` +
      'damaged). Use the USB drive that came with this update.');
  }
  await installApiBundle(zip, manifest, {
    apiDir,
    exeName,
    extractZip,
    onLine: (l) => emit({ step: 'runtime', status: 'active', message: l }),
  });
  emit({ step: 'runtime', status: 'done', message: `Application updated to ${manifest.version}.` });
  return true;
}

module.exports = { MARKER, readInstalled, isCurrent, isInstalled, installApiBundle, ensureApiBundle };
