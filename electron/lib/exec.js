'use strict';

/**
 * Thin wrappers around child_process for running CLI tools (docker, installers)
 * with promise semantics and optional line-streamed output for progress UIs.
 */

const { spawn } = require('child_process');

/**
 * Run a command to completion, buffering output.
 * @returns {Promise<{code:number, stdout:string, stderr:string}>}
 * Rejects only on spawn failure (e.g. ENOENT); a non-zero exit resolves so the
 * caller can inspect `code` — check it explicitly.
 */
function run(cmd, args = [], opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { windowsHide: true, ...opts });
    let stdout = '';
    let stderr = '';
    if (child.stdout) child.stdout.on('data', (d) => (stdout += d.toString()));
    if (child.stderr) child.stderr.on('data', (d) => (stderr += d.toString()));
    child.on('error', reject);
    child.on('close', (code) => resolve({ code, stdout, stderr }));
  });
}

/**
 * Run a command, forwarding each output line to `onLine` as it arrives.
 * Useful for surfacing `docker load` / installer progress into the wizard.
 * @returns {Promise<{code:number}>}
 */
function runStream(cmd, args = [], opts = {}, onLine = () => {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { windowsHide: true, ...opts });
    let buf = '';
    const pump = (chunk) => {
      buf += chunk.toString();
      let idx;
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx).replace(/\r$/, '');
        buf = buf.slice(idx + 1);
        if (line) onLine(line);
      }
    };
    if (child.stdout) child.stdout.on('data', pump);
    if (child.stderr) child.stderr.on('data', pump);
    child.on('error', reject);
    child.on('close', (code) => {
      if (buf.trim()) onLine(buf.trim());
      resolve({ code });
    });
  });
}

/** True if `cmd --version` (or the given probe args) runs and exits cleanly. */
async function commandExists(cmd, probeArgs = ['--version']) {
  try {
    const { code } = await run(cmd, probeArgs);
    return code === 0;
  } catch {
    return false;
  }
}

module.exports = { run, runStream, commandExists };
