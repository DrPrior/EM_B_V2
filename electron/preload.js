'use strict';

/**
 * Context-isolated bridge between the wizard renderer and the main process.
 * Exposes only a narrow, typed surface — no Node APIs leak into the page.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  /** @returns {Promise<{firstRunComplete:boolean, platform:string}>} */
  getState: () => ipcRenderer.invoke('wizard:getState'),

  /** Kick off provisioning/startup. Resolves when done or on failure. */
  begin: () => ipcRenderer.invoke('wizard:begin'),

  /** Per-step progress: {step, status, message, progress}. */
  onProgress: (cb) => ipcRenderer.on('progress', (_e, p) => cb(p)),

  /** Fired when a manual step (e.g. Docker reboot) blocks provisioning. */
  onReboot: (cb) => ipcRenderer.on('reboot', (_e, p) => cb(p)),

  /** Fired on a fatal provisioning error. */
  onError: (cb) => ipcRenderer.on('error', (_e, p) => cb(p)),
});
