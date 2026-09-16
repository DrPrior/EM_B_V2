'use strict';

/**
 * Logging for the desktop shell.
 *
 * One process-wide sink, chosen once by configure():
 *   - File mode (packaged app, or LOG_DIR set in dev): size-capped rotating
 *     `electron.log` in the logs dir. Nothing goes to the console.
 *   - Console mode (dev `npm start`): console.log / console.error.
 *
 * The same logs dir is handed to the API child as LOG_DIR, so a user reporting a
 * problem sends one folder holding electron.log (shell + Neo4j/API child output)
 * and api.log (the API's own records).
 *
 * Line format matches the Python side (src/core/logging_config.py):
 *   2026-09-16 09:17:35 ERROR    electron.supervisor  message
 *
 * Deliberately free of any `require('electron')` so it runs under `node --test`.
 * Logging must never take the app down: every write swallows its own failures.
 */

const fs = require('fs');
const path = require('path');
const util = require('util');

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
// Python's levelname spelling, so both log files grep the same way.
const LABELS = { debug: 'DEBUG', info: 'INFO', warn: 'WARNING', error: 'ERROR' };

const DEFAULTS = { file: 'electron.log', maxBytes: 10 * 1000 * 1000, maxFiles: 5, level: 'info' };

let sink = null; // { dir, filePath, maxBytes, maxFiles } in file mode; null for console
let threshold = LEVELS.info;

/**
 * Choose the destination. Call once at startup; later calls replace the sink.
 * @param {{dir?:string|null, file?:string, maxBytes?:number, maxFiles?:number, level?:string}} opts
 * @returns {string|null} the logs dir in file mode, or null for console mode
 */
function configure(opts = {}) {
  const { dir = null, file, maxBytes, maxFiles, level } = { ...DEFAULTS, ...opts };
  threshold = LEVELS[String(level).toLowerCase()] ?? LEVELS.info;
  sink = dir ? { dir, filePath: path.join(dir, file), maxBytes, maxFiles } : null;
  return logDir();
}

/** The configured logs dir, or null in console mode. */
function logDir() {
  return sink ? sink.dir : null;
}

function pad(n) {
  return String(n).padStart(2, '0');
}

/** Local time as `YYYY-MM-DD HH:MM:SS` (Python's asctime with the same datefmt). */
function timestamp(d = new Date()) {
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

/** Build one log line. Args follow util.format, so Errors render with their stack. */
function formatLine(level, scope, args, date = new Date()) {
  return `${timestamp(date)} ${LABELS[level].padEnd(8)} ${scope}  ${util.format(...args)}`;
}

/** Shift electron.log → .1 → .2 …, dropping the oldest beyond maxFiles. */
function rotate(filePath, maxFiles) {
  const oldest = `${filePath}.${maxFiles}`;
  if (fs.existsSync(oldest)) fs.rmSync(oldest, { force: true });
  for (let i = maxFiles - 1; i >= 1; i--) {
    const from = `${filePath}.${i}`;
    if (fs.existsSync(from)) fs.renameSync(from, `${filePath}.${i + 1}`);
  }
  if (fs.existsSync(filePath)) fs.renameSync(filePath, `${filePath}.1`);
}

function writeFile(line) {
  const { dir, filePath, maxBytes, maxFiles } = sink;
  const data = `${line}\n`;
  fs.mkdirSync(dir, { recursive: true });
  let size = 0;
  try {
    size = fs.statSync(filePath).size;
  } catch {
    /* no file yet */
  }
  if (size > 0 && size + Buffer.byteLength(data) > maxBytes) rotate(filePath, maxFiles);
  fs.appendFileSync(filePath, data, 'utf8');
}

function write(level, line) {
  if (sink) {
    try {
      writeFile(line);
      return;
    } catch {
      /* disk trouble: fall through to the console rather than lose the record */
    }
  }
  if (LEVELS[level] >= LEVELS.warn) console.error(line);
  else console.log(line);
}

/**
 * A logger for one area of the shell, e.g. getLogger('supervisor').
 * Scopes are prefixed `electron.` to sit beside the API's `em_b.*` names.
 */
function getLogger(scope) {
  const name = scope.startsWith('electron') ? scope : `electron.${scope}`;
  const emit = (level) => (...args) => {
    if (LEVELS[level] < threshold) return;
    write(level, formatLine(level, name, args));
  };
  return {
    name,
    debug: emit('debug'),
    info: emit('info'),
    warn: emit('warn'),
    error: emit('error'),
    child: (sub) => getLogger(`${name}.${sub}`),
  };
}

/**
 * Adapt a logger to the wizard's progress events ({step, status, message, progress}).
 *
 * Model pulls emit many events per second with a numeric `progress`; those are
 * skipped so the log records transitions, not a download meter. Consecutive
 * duplicates are dropped. needs-user → WARNING, error → ERROR.
 */
function progressLogger(log) {
  let last = null;
  return (e) => {
    if (!e || !e.step) return;
    if (e.status === 'active' && typeof e.progress === 'number') return;
    const key = `${e.step}|${e.status}|${e.message || ''}`;
    if (key === last) return;
    last = key;
    const line = `step=${e.step} status=${e.status}${e.message ? ` ${e.message}` : ''}`;
    if (e.status === 'error') log.error(line);
    else if (e.status === 'needs-user') log.warn(line);
    else log.info(line);
  };
}

/** Adapt a logger to a child process's line-by-line output (procs.js onLine). */
function lineLogger(log) {
  return (line) => {
    if (line && line.trim()) log.info(line);
  };
}

const RECORD_HEADER = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (WARNING|ERROR|CRITICAL)\s/;
const EXCEPTION_LINE = /^[A-Za-z_][\w.]*(Error|Exception|Unavailable|Exit)\b[\w.]*: /;

/**
 * Pull the useful part out of api.log text for a user-facing error: the most
 * recent WARNING/ERROR record lines plus the last exception message (the real
 * cause, which sits at the bottom of a traceback rather than in the header).
 * @returns {string[]}
 */
function summarizeErrors(text, maxRecords = 4) {
  const lines = String(text || '').split(/\r?\n/);
  const records = lines.filter((l) => RECORD_HEADER.test(l)).slice(-maxRecords);
  const cause = lines.filter((l) => EXCEPTION_LINE.test(l)).slice(-1);
  return [...records, ...cause];
}

module.exports = {
  configure,
  logDir,
  getLogger,
  progressLogger,
  lineLogger,
  summarizeErrors,
  // exported for tests
  formatLine,
  timestamp,
};
