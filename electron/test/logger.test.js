'use strict';

/**
 * Unit tests for lib/logger.js — the desktop shell's rotating log sink.
 *
 * Runs hermetically under Node's test runner: real files in a temp dir, no
 * Electron. Pins the behaviours a support log depends on: the line format shared
 * with api.log, rotation, the console fallback, and never throwing.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const logger = require('../lib/logger');

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'emb-logger-'));
}

function readLog(dir, file = 'electron.log') {
  return fs.readFileSync(path.join(dir, file), 'utf8');
}

test.afterEach(() => {
  logger.configure({ dir: null });
});

test('file mode writes lines in the same format as api.log', () => {
  const dir = tmpDir();
  assert.equal(logger.configure({ dir }), dir);
  assert.equal(logger.logDir(), dir);

  logger.getLogger('supervisor').error('API exited with code %d', 3);

  const line = readLog(dir).trim();
  assert.match(line, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ERROR    electron\.supervisor  API exited with code 3$/);
});

test('levels below the threshold are dropped', () => {
  const dir = tmpDir();
  logger.configure({ dir, level: 'warn' });
  const log = logger.getLogger('main');

  log.info('quiet');
  log.warn('loud');

  const content = readLog(dir);
  assert.doesNotMatch(content, /quiet/);
  assert.match(content, /WARNING  electron\.main  loud/);
});

test('errors are logged with their stack trace', () => {
  const dir = tmpDir();
  logger.configure({ dir });

  logger.getLogger('main').error('wizard failed:', new Error('bolt closed'));

  const content = readLog(dir);
  assert.match(content, /wizard failed: Error: bolt closed/);
  assert.match(content, /logger\.test\.js/); // a stack frame, not just the message
});

test('child loggers extend the scope name', () => {
  const dir = tmpDir();
  logger.configure({ dir });

  logger.getLogger('supervisor').child('api').info('Uvicorn running');

  assert.match(readLog(dir), /INFO     electron\.supervisor\.api  Uvicorn running/);
});

test('rotates when the size cap would be exceeded and keeps maxFiles backups', () => {
  const dir = tmpDir();
  logger.configure({ dir, maxBytes: 120, maxFiles: 2 });
  const log = logger.getLogger('rot');

  for (let i = 0; i < 12; i++) log.info(`record number ${i} padding padding`);

  const files = fs.readdirSync(dir).sort();
  assert.deepEqual(files, ['electron.log', 'electron.log.1', 'electron.log.2']);
  for (const f of files) assert.ok(fs.statSync(path.join(dir, f)).size <= 120);
  assert.match(readLog(dir), /record number 11/);
});

test('console mode writes errors to stderr and info to stdout', (t) => {
  logger.configure({ dir: null });
  const out = [];
  const err = [];
  t.mock.method(console, 'log', (l) => out.push(l));
  t.mock.method(console, 'error', (l) => err.push(l));

  const log = logger.getLogger('main');
  log.info('hello');
  log.error('boom');

  assert.equal(logger.logDir(), null);
  assert.equal(out.length, 1);
  assert.match(out[0], /INFO     electron\.main  hello/);
  assert.equal(err.length, 1);
  assert.match(err[0], /ERROR    electron\.main  boom/);
});

test('an unwritable log dir falls back to the console instead of throwing', (t) => {
  const dir = tmpDir();
  const blocker = path.join(dir, 'not-a-dir');
  fs.writeFileSync(blocker, 'x'); // a file where the logs dir should be
  logger.configure({ dir: blocker });
  const err = [];
  t.mock.method(console, 'error', (l) => err.push(l));

  assert.doesNotThrow(() => logger.getLogger('main').error('still recorded'));
  assert.match(err[0], /still recorded/);
});

test('progressLogger records transitions, skips download ticks and duplicates', () => {
  const dir = tmpDir();
  logger.configure({ dir });
  const logProgress = logger.progressLogger(logger.getLogger('firstrun'));

  logProgress({ step: 'models', status: 'active', message: 'Checking language models…' });
  logProgress({ step: 'models', status: 'active', message: 'Downloading gemma', progress: 0.1 });
  logProgress({ step: 'models', status: 'active', message: 'Downloading gemma', progress: 0.2 });
  logProgress({ step: 'models', status: 'done', message: 'Models ready.' });
  logProgress({ step: 'models', status: 'done', message: 'Models ready.' });
  logProgress({ step: 'ollama', status: 'needs-user', message: 'Please start Ollama' });

  const lines = readLog(dir).trim().split('\n');
  assert.equal(lines.length, 3);
  assert.match(lines[0], /INFO .*step=models status=active Checking language models…/);
  assert.match(lines[1], /INFO .*step=models status=done Models ready\./);
  assert.match(lines[2], /WARNING .*step=ollama status=needs-user Please start Ollama/);
});

test('lineLogger ignores blank child output', () => {
  const dir = tmpDir();
  logger.configure({ dir });
  const onLine = logger.lineLogger(logger.getLogger('neo4j'));

  onLine('   ');
  onLine('Started.');

  assert.equal(readLog(dir).trim().split('\n').length, 1);
});

test('summarizeErrors extracts error records and the root exception from api.log', () => {
  const apiLog = [
    '2026-09-16 09:17:35 INFO     em_b.main  API starting; logging to C:/logs/api.log',
    '2026-09-16 09:17:37 ERROR    em_b.main  Unexpected error during Neo4j connection',
    'Traceback (most recent call last):',
    '  File "src/main.py", line 55, in lifespan',
    "neo4j.exceptions.ServiceUnavailable: Failed to establish connection to ('127.0.0.1', 7687)",
    '2026-09-16 09:17:37 ERROR    uvicorn.error  Application startup failed. Exiting.',
  ].join('\r\n');

  assert.deepEqual(logger.summarizeErrors(apiLog), [
    '2026-09-16 09:17:37 ERROR    em_b.main  Unexpected error during Neo4j connection',
    '2026-09-16 09:17:37 ERROR    uvicorn.error  Application startup failed. Exiting.',
    "neo4j.exceptions.ServiceUnavailable: Failed to establish connection to ('127.0.0.1', 7687)",
  ]);
  assert.deepEqual(logger.summarizeErrors(''), []);
});
