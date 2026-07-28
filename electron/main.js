'use strict';

/**
 * Electron main process: single window that starts life as the setup wizard /
 * splash, then navigates to the local web UI (http://127.0.0.1:8000) once the
 * backend is healthy. On first launch it runs the guided provisioning
 * (Docker → Ollama → models → image → data → snapshot → start); on later
 * launches it takes the fast path of just bringing the stack up.
 */

const fs = require('fs');
const path = require('path');
const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');

const supervisor = require('./supervisor');
const paths = require('./lib/paths');
const assets = require('./lib/assets');
const { runFirstRun, RebootRequiredError, loadManifest } = require('./lib/firstrun');
const { ensureEnvFile } = require('./lib/envfile');

const APP_URL = 'http://127.0.0.1:8000';

let mainWindow = null;
let envPath = null;
let quitting = false;

function manifestVersion() {
  try {
    return JSON.parse(fs.readFileSync(paths.assetsManifestPath(), 'utf8')).image.version;
  } catch {
    return 'latest';
  }
}

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 780,
    minWidth: 720,
    minHeight: 560,
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, 'wizard', 'wizard.html'));

  // Keep navigation inside the app; open external links in the system browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(APP_URL)) { shell.openExternal(url); return { action: 'deny' }; }
    return { action: 'allow' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

async function navigateToApp() {
  await mainWindow.loadURL(APP_URL);
}

/**
 * Resolve the USB `assets/` folder holding the offline setup files. Tries
 * auto-detection first; if that fails, prompts the user with a native folder
 * picker (looping until they choose a valid folder or cancel). Returns the dir
 * or null if the user cancelled.
 */
async function resolveAssetsDir(manifest) {
  let dir = assets.findAssetsDir(manifest);
  while (!dir) {
    const res = await dialog.showOpenDialog(mainWindow, {
      title: 'Select the setup folder from the USB drive',
      message: 'Choose the “assets” folder that came with this app on the USB drive.',
      properties: ['openDirectory'],
      buttonLabel: 'Use this folder',
    });
    if (res.canceled || !res.filePaths.length) return null;
    const picked = res.filePaths[0];
    if (assets.isValidDir(picked, manifest)) { dir = picked; break; }
    await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      message: 'That folder doesn’t contain the setup files.',
      detail: `Expected to find "${manifest.image.file}" inside it. Pick the "assets" folder from the USB drive.`,
    });
  }
  if (dir) assets.saveDir(dir);
  return dir;
}

// Renderer asks what mode to show.
ipcMain.handle('wizard:getState', () => ({
  firstRunComplete: supervisor.isFirstRunComplete(),
  platform: process.platform,
}));

// Renderer triggers provisioning / startup. Progress streams over 'progress'.
ipcMain.handle('wizard:begin', async () => {
  try {
    const version = manifestVersion();
    envPath = ensureEnvFile({ appVersion: version }).path;

    if (supervisor.isFirstRunComplete()) {
      await supervisor.quickStart(envPath, (e) => send('progress', e));
    } else {
      const assetsDir = await resolveAssetsDir(loadManifest());
      if (!assetsDir) {
        send('error', { message: 'Setup files not found. Plug in the USB drive that came with the app and try again.' });
        return { ok: false, error: 'no-assets' };
      }
      await runFirstRun((e) => send('progress', e), assetsDir);
    }
    await navigateToApp();
    return { ok: true };
  } catch (err) {
    if (err instanceof RebootRequiredError) {
      send('reboot', { message: err.message });
      return { ok: false, reboot: true };
    }
    send('error', { message: err.message });
    return { ok: false, error: err.message };
  }
});

// Single-instance: focus the existing window instead of opening a second one.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });

  app.whenReady().then(createWindow);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}

// Tear the stack down cleanly on quit (data persists in the named volume).
app.on('before-quit', async (e) => {
  if (quitting || !envPath) return;
  e.preventDefault();
  quitting = true;
  await supervisor.stop(envPath);
  app.quit();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
