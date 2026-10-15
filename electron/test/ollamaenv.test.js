'use strict';

/**
 * Unit tests for lib/ollamaenv.js — the pure, side-effect-free logic only.
 *
 * Run with `npm test` (Node's built-in test runner, no extra deps). We do NOT
 * exercise `ensure`/`persist*`/`restartOllama` here: those spawn `setx` /
 * `launchctl` / `taskkill` and restart Ollama, so they belong to the on-machine
 * verification checklist in electron/README.md, not to a hermetic unit test.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const os = require('node:os');
const path = require('node:path');

const ollamaenv = require('../lib/ollamaenv');

test('REQUIRED carries the warmth and throughput vars', () => {
  assert.deepEqual(ollamaenv.REQUIRED, {
    OLLAMA_KEEP_ALIVE: '-1',
    OLLAMA_MAX_LOADED_MODELS: '2',
    OLLAMA_FLASH_ATTENTION: '1',
    OLLAMA_KV_CACHE_TYPE: 'q8_0',
    OLLAMA_NUM_PARALLEL: '1',
  });
});

test('REQUIRED is frozen (target values are constants, not mutated at runtime)', () => {
  assert.ok(Object.isFrozen(ollamaenv.REQUIRED));
});

test('REQUIRED does not bind Ollama to every interface (native API uses loopback)', () => {
  assert.equal('OLLAMA_HOST' in ollamaenv.REQUIRED, false);
  assert.equal('OLLAMA_HOST' in ollamaenv.INTEL_ACCEL, false);
});

test('RETIRED targets the Docker-era OLLAMA_HOST=0.0.0.0 and is frozen', () => {
  assert.deepEqual(ollamaenv.RETIRED, { OLLAMA_HOST: '0.0.0.0' });
  assert.ok(Object.isFrozen(ollamaenv.RETIRED));
});

test('computeRetired: flags a value an earlier build persisted', () => {
  assert.deepEqual(ollamaenv.computeRetired({ OLLAMA_HOST: '0.0.0.0' }), ['OLLAMA_HOST']);
});

test('computeRetired: leaves unset or user-chosen values alone', () => {
  assert.deepEqual(ollamaenv.computeRetired({}), []);
  assert.deepEqual(ollamaenv.computeRetired({ OLLAMA_HOST: '' }), []);
  assert.deepEqual(ollamaenv.computeRetired({ OLLAMA_HOST: '127.0.0.1:11500' }), []);
});

test('INTEL_ACCEL carries the iGPU-enable vars and is frozen', () => {
  assert.deepEqual(ollamaenv.INTEL_ACCEL, {
    OLLAMA_VULKAN: '1',
    OLLAMA_IGPU_ENABLE: '1',
  });
  assert.ok(Object.isFrozen(ollamaenv.INTEL_ACCEL));
});

test('resolveVars: Intel-only host adds the iGPU-enable vars', () => {
  const vars = ollamaenv.resolveVars({ intel: true, nvidia: false, apple: false });
  assert.deepEqual(vars, { ...ollamaenv.REQUIRED, ...ollamaenv.INTEL_ACCEL });
});

test('resolveVars: NVIDIA present → base three only (CUDA left untouched)', () => {
  const vars = ollamaenv.resolveVars({ intel: true, nvidia: true, apple: false });
  assert.deepEqual(vars, { ...ollamaenv.REQUIRED });
});

test('resolveVars: Apple Silicon → base three only (Metal left untouched)', () => {
  const vars = ollamaenv.resolveVars({ intel: false, nvidia: false, apple: true });
  assert.deepEqual(vars, { ...ollamaenv.REQUIRED });
});

test('resolveVars: no GPU info → base three only', () => {
  assert.deepEqual(ollamaenv.resolveVars(), { ...ollamaenv.REQUIRED });
  assert.deepEqual(ollamaenv.resolveVars({}), { ...ollamaenv.REQUIRED });
});

test('resolveVars does not mutate REQUIRED', () => {
  ollamaenv.resolveVars({ intel: true });
  assert.deepEqual(ollamaenv.REQUIRED, {
    OLLAMA_KEEP_ALIVE: '-1',
    OLLAMA_MAX_LOADED_MODELS: '2',
    OLLAMA_FLASH_ATTENTION: '1',
    OLLAMA_KV_CACHE_TYPE: 'q8_0',
    OLLAMA_NUM_PARALLEL: '1',
  });
});

test('computeNeedsSetup: false only when every var already matches', () => {
  const exact = { ...ollamaenv.REQUIRED };
  assert.equal(ollamaenv.computeNeedsSetup(exact), false);
});

test('computeNeedsSetup: extra unrelated vars do not force setup', () => {
  const withExtra = { ...ollamaenv.REQUIRED, OLLAMA_ORIGINS: '*' };
  assert.equal(ollamaenv.computeNeedsSetup(withExtra), false);
});

test('computeNeedsSetup: true when a var is missing', () => {
  const missing = { ...ollamaenv.REQUIRED };
  delete missing.OLLAMA_KEEP_ALIVE;
  assert.equal(ollamaenv.computeNeedsSetup(missing), true);
});

test('computeNeedsSetup: true when a var holds the wrong value', () => {
  const wrong = { ...ollamaenv.REQUIRED, OLLAMA_NUM_PARALLEL: '4' };
  assert.equal(ollamaenv.computeNeedsSetup(wrong), true);
});

test('computeNeedsSetup: true when a retired value is still persisted', () => {
  const stale = { ...ollamaenv.REQUIRED, OLLAMA_HOST: '0.0.0.0' };
  assert.equal(ollamaenv.computeNeedsSetup(stale), true);
});

test('computeNeedsSetup: a user-chosen OLLAMA_HOST does not force setup', () => {
  const custom = { ...ollamaenv.REQUIRED, OLLAMA_HOST: '127.0.0.1:11500' };
  assert.equal(ollamaenv.computeNeedsSetup(custom), false);
});

test('computeNeedsSetup: empty string counts as unset', () => {
  const blank = { ...ollamaenv.REQUIRED, OLLAMA_KEEP_ALIVE: '' };
  assert.equal(ollamaenv.computeNeedsSetup(blank), true);
});

test('computeNeedsSetup: an empty map needs setup', () => {
  assert.equal(ollamaenv.computeNeedsSetup({}), true);
});

test('launchAgentPath lives under ~/Library/LaunchAgents with the label', () => {
  const p = ollamaenv.launchAgentPath();
  assert.equal(
    p,
    path.join(os.homedir(), 'Library', 'LaunchAgents', `${ollamaenv.LAUNCH_AGENT_LABEL}.plist`),
  );
});

test('launchAgentPlist declares RunAtLoad and every REQUIRED setenv', () => {
  const plist = ollamaenv.launchAgentPlist();
  assert.match(plist, /<key>RunAtLoad<\/key><true\/>/);
  assert.match(plist, new RegExp(`<string>${ollamaenv.LAUNCH_AGENT_LABEL}</string>`));
  for (const [name, value] of Object.entries(ollamaenv.REQUIRED)) {
    // The plist runs `launchctl setenv <NAME> <VALUE>` for each var.
    assert.match(plist, new RegExp(`launchctl setenv ${name} ${value.replace('.', '\\.')}`));
  }
  assert.doesNotMatch(plist, /OLLAMA_HOST/);
});

test('launchAgentPlist is a well-formed plist document', () => {
  const plist = ollamaenv.launchAgentPlist();
  assert.match(plist, /^<\?xml version="1\.0" encoding="UTF-8"\?>/);
  assert.match(plist, /<!DOCTYPE plist PUBLIC/);
  assert.match(plist, /<plist version="1\.0">[\s\S]*<\/plist>/);
});

test('isSupportedPlatform matches the current platform expectation', () => {
  const expected = process.platform === 'win32' || process.platform === 'darwin';
  assert.equal(ollamaenv.isSupportedPlatform(), expected);
});
