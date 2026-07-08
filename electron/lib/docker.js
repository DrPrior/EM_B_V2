'use strict';

/**
 * Docker detection + management for the wizard.
 *
 * Fully silent Docker Desktop installation is not possible (Windows needs admin,
 * WSL2, and usually a reboot), so `installDockerDesktop` downloads the official
 * installer and launches it, then the wizard guides the user through the manual
 * steps and re-checks. Everything else (loading the prebuilt image, running
 * compose) is automated.
 */

const path = require('path');
const { run, runStream, commandExists } = require('./exec');
const { downloadFile } = require('./download');
const paths = require('./paths');

const DEFAULT_INSTALLERS = {
  win32: 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe',
  darwin: 'https://desktop.docker.com/mac/main/arm64/Docker.dmg',
};

/** True if the `docker` CLI is on PATH. */
async function isInstalled() {
  return commandExists('docker', ['--version']);
}

/** True if the Docker daemon is up (compose usable). */
async function isDaemonRunning() {
  const { code } = await run('docker', ['info', '--format', '{{.ServerVersion}}']);
  return code === 0;
}

/** Wait for the daemon (Docker Desktop can take a while to start). */
async function waitForDaemon(retries = 60, delayMs = 2000) {
  for (let i = 0; i < retries; i++) {
    if (await isDaemonRunning()) return true;
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return false;
}

/** True if an image with the given tag is present locally. */
async function imageExists(tag) {
  const { code, stdout } = await run('docker', ['images', '-q', tag]);
  return code === 0 && stdout.trim().length > 0;
}

/** `docker load` a saved image tar, streaming progress lines. */
async function loadImage(tarPath, onLine = () => {}) {
  const { code } = await runStream('docker', ['load', '-i', tarPath], {}, onLine);
  if (code !== 0) throw new Error(`docker load failed for ${tarPath}`);
}

function installerUrl(manifest) {
  return (manifest?.docker && manifest.docker[process.platform]) || DEFAULT_INSTALLERS[process.platform];
}

/**
 * Download and launch Docker Desktop's installer. Cannot verify completion here
 * (needs admin + often a reboot); the wizard polls isInstalled/waitForDaemon
 * afterward and instructs the user as needed.
 */
async function installDockerDesktop(manifest, onProgress = () => {}) {
  const url = installerUrl(manifest);
  if (!url) throw new Error(`No Docker installer URL for platform ${process.platform}`);
  const dest = path.join(paths.assetsDir(), path.basename(decodeURIComponent(url)));
  onProgress({ phase: 'download', message: 'Downloading Docker Desktop…' });
  await downloadFile(url, dest, (p) => onProgress({ phase: 'download', ...p }));

  onProgress({ phase: 'install', message: 'Launching the Docker Desktop installer…' });
  if (process.platform === 'win32') {
    // Interactive: requires admin elevation and (first time) a reboot for WSL2.
    await runStream(dest, ['install'], {}, (l) => onProgress({ phase: 'install', line: l }));
  } else if (process.platform === 'darwin') {
    await runStream('open', ['-W', dest], {}, () => {});
    onProgress({ phase: 'install', message: 'Drag Docker to Applications, launch it, then continue.' });
  }
  return dest;
}

module.exports = {
  isInstalled,
  isDaemonRunning,
  waitForDaemon,
  imageExists,
  loadImage,
  installDockerDesktop,
};
