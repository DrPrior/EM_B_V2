'use strict';

/**
 * Electron main process: single window that starts life as the setup wizard /
 * splash, then navigates to the local web UI (http://127.0.0.1:8000) once the
 * backend is healthy. On first launch it runs the guided provisioning
 * (GPU → Ollama → models → Neo4j → runtime → data → snapshot → start); on later
 * launches it takes the fast path of just bringing the stack up.
 */

const fs = require('fs');
const path = require('path');
const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');

const paths = require('./lib/paths');
const logger = require('./lib/logger');

// Configure logging before anything else loads, so module-load and first-run
// failures are recorded. Packaged: rotating files under userData/logs. Dev: the
// console, unless LOG_DIR is set to exercise file mode (same rule as the API).
let logDirError = null;
try {
  logger.configure({ dir: app.isPackaged ? paths.logsDir() : process.env.LOG_DIR || null });
} catch (err) {
  logger.configure({ dir: null });
  logDirError = err;
}
const log = logger.getLogger('main');

const supervisor = require('./supervisor');
const assets = require('./lib/assets');
const { ensureApiBundle } = require('./lib/apibundle');
const { extractZip } = require('./lib/archive');
const { runFirstRun, RebootRequiredError, loadManifest } = require('./lib/firstrun');
const { ensureEnvFile } = require('./lib/envfile');

const APP_URL = 'http://127.0.0.1:8000';

log.info(
  'App starting: version=%s electron=%s platform=%s packaged=%s logs=%s',
  app.getVersion(), process.versions.electron, process.platform, app.isPackaged,
  logger.logDir() || 'console',
);
if (logDirError) log.error('Could not use the logs directory; logging to console:', logDirError);

// uncaughtExceptionMonitor observes without changing Electron's default crash
// handling. Unhandled rejections don't crash the main process, so log them here.
process.on('uncaughtExceptionMonitor', (err, origin) => log.error('Uncaught exception (%s):', origin, err));
process.on('unhandledRejection', (reason) => log.error('Unhandled promise rejection:', reason));

let mainWindow = null;
let envPath = null;
let quitting = false;

function manifestVersion() {
  try {
    return JSON.parse(fs.readFileSync(paths.assetsManifestPath(), 'utf8')).version;
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

  mainWindow.webContents.on('render-process-gone', (_e, details) =>
    log.error('Renderer process gone: reason=%s exitCode=%s', details.reason, details.exitCode));
  mainWindow.webContents.on('did-fail-load', (_e, code, description, url) =>
    log.error('Page failed to load: %s (%s %s)', url, code, description));

  mainWindow.on('closed', () => { mainWindow = null; });
}

async function navigateToApp() {
  log.info('Backend ready; loading %s', APP_URL);
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
    if (res.canceled || !res.filePaths.length) {
      log.warn('User cancelled the setup-folder picker');
      return null;
    }
    const picked = res.filePaths[0];
    if (assets.isValidDir(picked, manifest)) { dir = picked; break; }
    log.warn('Picked folder does not contain setup files: %s', picked);
    await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      message: 'That folder doesn’t contain the setup files.',
      detail: `Expected to find "${manifest.apiBundle.file}" inside it. Pick the "assets" folder from the USB drive.`,
    });
  }
  if (dir) assets.saveDir(dir);
  return dir;
}

/**
 * Install the current manifest's API bundle before the fast-path start if an
 * in-place update changed it. Wires the real paths/assets/USB resolver into
 * lib/apibundle.js; see that module for the full rationale.
 */
function ensureApiBundleForVersion(manifest) {
  return ensureApiBundle(manifest, {
    apiDir: paths.apiDir(),
    exeName: path.basename(paths.apiExePath()),
    extractZip,
    assets,
    resolveAssetsDir,
    emit: (e) => send('progress', e),
    onError: (message) => send('error', { message }),
  });
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
      log.info('Starting (fast path), manifest version %s', version);
      // An in-place update ships a new manifest but keeps the first-run marker,
      // so install that version's API bundle before starting it.
      if (!(await ensureApiBundleForVersion(loadManifest()))) {
        log.error('API bundle for version %s is not installed; cannot start', version);
        return { ok: false, error: 'update-not-installed' };
      }
      await supervisor.quickStart(envPath, (e) => send('progress', e));
    } else {
      log.info('Starting guided first run, manifest version %s', version);
      const assetsDir = await resolveAssetsDir(loadManifest());
      if (!assetsDir) {
        log.error('Setup files not found; first run cannot continue');
        send('error', { message: 'Setup files not found. Plug in the USB drive that came with the app and try again.' });
        return { ok: false, error: 'no-assets' };
      }
      await runFirstRun((e) => send('progress', e), assetsDir);
    }
    await navigateToApp();
    return { ok: true };
  } catch (err) {
    if (err instanceof RebootRequiredError) {
      log.warn('Reboot required to continue setup: %s', err.message);
      send('reboot', { message: err.message });
      return { ok: false, reboot: true };
    }
    log.error('Startup failed:', err);
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

  app.on('child-process-gone', (_e, details) =>
    log.error('Electron child process gone: type=%s reason=%s exitCode=%s',
      details.type, details.reason, details.exitCode));

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}

// Tear the stack down cleanly on quit (data persists under userData).
app.on('before-quit', async (e) => {
  if (quitting || !envPath) return;
  e.preventDefault();
  quitting = true;
  log.info('Quitting; stopping backend');
  await supervisor.stop(envPath);
  app.quit();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
