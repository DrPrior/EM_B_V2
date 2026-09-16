'use strict';

/**
 * Unit tests for lib/apibundle.js — installing the frozen API bundle and
 * re-installing it after an in-place app update.
 *
 * Runs hermetically under Node's test runner: real dirs in a temp folder, a fake
 * extractor, and injected assets/USB resolver — no Electron, no `tar`, no USB.
 * Pins that an updated manifest installs the new bundle (or fails loudly), and
 * that no failure leaves the previous install broken.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const apibundle = require('../lib/apibundle');

const EXE = 'emb-api.exe';
const OLD = { version: '0.4.0', apiBundle: { file: 'emb-api.zip', sha256: 'aaa' } };
const NEW = { version: '0.4.1', apiBundle: { file: 'emb-api.zip', sha256: 'bbb' } };

function tmpApiDir() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'emb-apibundle-')), 'api');
}

/** Fake `tar`: writes the exe (unless told not to) plus a file naming the build. */
function fakeExtract(build, { withExe = true } = {}) {
  const calls = [];
  const extractZip = async (zip, dest) => {
    calls.push({ zip, dest });
    fs.mkdirSync(path.join(dest, '_internal'), { recursive: true });
    if (withExe) fs.writeFileSync(path.join(dest, EXE), build);
    fs.writeFileSync(path.join(dest, '_internal', 'build.txt'), build);
  };
  return { extractZip, calls };
}

/** Put a complete install of `manifest` at apiDir, including a stale extra file. */
async function installed(apiDir, manifest) {
  await apibundle.installApiBundle('/usb/old.zip', manifest, {
    apiDir, exeName: EXE, extractZip: fakeExtract(manifest.version).extractZip,
  });
  fs.writeFileSync(path.join(apiDir, '_internal', 'stale.txt'), 'from the old build');
}

/** Build a deps object with spies; override per test. */
function makeDeps(apiDir, overrides = {}) {
  const events = [];
  const errors = [];
  const resolved = [];
  const { extractZip, calls } = fakeExtract(NEW.version);
  const deps = {
    apiDir,
    exeName: EXE,
    extractZip,
    assets: {
      assetPath: (dir, manifest, key) => `${dir}/${manifest[key].file}`,
      verify: async () => true,
    },
    resolveAssetsDir: async (m) => { resolved.push(m); return '/usb/assets'; },
    emit: (e) => events.push(e),
    onError: (m) => errors.push(m),
    ...overrides,
  };
  return { deps, events, errors, resolved, calls };
}

const build = (apiDir) => fs.readFileSync(path.join(apiDir, '_internal', 'build.txt'), 'utf8');

test('isCurrent: matches only when version and checksum both match', () => {
  assert.equal(apibundle.isCurrent({ version: '0.4.1', sha256: 'bbb' }, NEW), true);
  assert.equal(apibundle.isCurrent({ version: '0.4.0', sha256: 'bbb' }, NEW), false);
  assert.equal(apibundle.isCurrent({ version: '0.4.1', sha256: 'zzz' }, NEW), false);
  assert.equal(apibundle.isCurrent(null, NEW), false);
});

test('isCurrent: a blank dev checksum compares by version alone', () => {
  const dev = { version: '0.4.1', apiBundle: { file: 'emb-api.zip', sha256: '' } };
  assert.equal(apibundle.isCurrent({ version: '0.4.1', sha256: '' }, dev), true);
  assert.equal(apibundle.isCurrent({ version: '0.4.1' }, dev), true);
});

test('installApiBundle: records the manifest and leaves no staging dirs', async () => {
  const apiDir = tmpApiDir();
  await apibundle.installApiBundle('/usb/emb-api.zip', NEW, {
    apiDir, exeName: EXE, extractZip: fakeExtract('x').extractZip,
  });
  assert.equal(apibundle.isInstalled(NEW, { apiDir, exeName: EXE }), true);
  assert.equal(fs.existsSync(`${apiDir}.new`), false);
  assert.equal(fs.existsSync(`${apiDir}.old`), false);
});

test('ensureApiBundle: current install → done, no USB lookup, no extraction', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, NEW);
  const { deps, events, resolved, calls } = makeDeps(apiDir);
  assert.equal(await apibundle.ensureApiBundle(NEW, deps), true);
  assert.deepEqual(resolved, []);
  assert.deepEqual(calls, []);
  assert.equal(events.at(-1).status, 'done');
});

test('ensureApiBundle: updated manifest replaces the old bundle wholesale', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, OLD);
  const { deps, events, errors, calls } = makeDeps(apiDir);

  assert.equal(await apibundle.ensureApiBundle(NEW, deps), true);
  assert.deepEqual(errors, []);
  assert.equal(calls[0].zip, '/usb/assets/emb-api.zip');
  assert.equal(build(apiDir), NEW.version);
  assert.equal(fs.existsSync(path.join(apiDir, '_internal', 'stale.txt')), false);
  assert.equal(apibundle.readInstalled(apiDir).version, NEW.version);
  assert.match(events[0].message, /0\.4\.0 → 0\.4\.1/);
  assert.deepEqual(events.at(-1), { step: 'runtime', status: 'done', message: 'Application updated to 0.4.1.' });
});

test('ensureApiBundle: a rebuilt bundle under the same version is reinstalled', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, { ...NEW, apiBundle: { ...NEW.apiBundle, sha256: 'old-build' } });
  const { deps, calls } = makeDeps(apiDir);
  assert.equal(await apibundle.ensureApiBundle(NEW, deps), true);
  assert.equal(calls.length, 1);
});

test('ensureApiBundle: install without a marker (pre-tracking) is reinstalled', async () => {
  const apiDir = tmpApiDir();
  fs.mkdirSync(apiDir, { recursive: true });
  fs.writeFileSync(path.join(apiDir, EXE), 'untracked');
  const { deps, calls } = makeDeps(apiDir);
  assert.equal(await apibundle.ensureApiBundle(NEW, deps), true);
  assert.equal(calls.length, 1);
  assert.equal(apibundle.isInstalled(NEW, { apiDir, exeName: EXE }), true);
});

test('ensureApiBundle: USB unavailable → false, clear error, old install intact', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, OLD);
  const { deps, events, errors, calls } = makeDeps(apiDir, { resolveAssetsDir: async () => null });

  assert.equal(await apibundle.ensureApiBundle(NEW, deps), false);
  assert.equal(calls.length, 0);
  assert.match(errors[0], /version 0\.4\.1\) needs the USB drive/);
  assert.equal(events.at(-1).status, 'error');
  assert.equal(build(apiDir), OLD.version);
});

test('ensureApiBundle: wrong-version USB (checksum mismatch) → false, old install intact', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, OLD);
  const { deps, errors, calls } = makeDeps(apiDir, {
    assets: {
      assetPath: (dir, manifest, key) => `${dir}/${manifest[key].file}`,
      verify: async () => { throw new Error('Checksum mismatch'); },
    },
  });

  assert.equal(await apibundle.ensureApiBundle(NEW, deps), false);
  assert.equal(calls.length, 0);
  assert.match(errors[0], /not version 0\.4\.1/);
  assert.equal(apibundle.readInstalled(apiDir).version, OLD.version);
});

test('ensureApiBundle: archive without the exe throws and keeps the old install', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, OLD);
  const { deps } = makeDeps(apiDir, { extractZip: fakeExtract('nested', { withExe: false }).extractZip });

  await assert.rejects(apibundle.ensureApiBundle(NEW, deps), /does not contain emb-api\.exe/);
  assert.equal(build(apiDir), OLD.version);
  assert.equal(fs.existsSync(`${apiDir}.new`), false);
});

test('ensureApiBundle: extraction failure throws and keeps the old install', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, OLD);
  const { deps } = makeDeps(apiDir, {
    extractZip: async (zip, dest) => {
      fs.mkdirSync(dest, { recursive: true });
      fs.writeFileSync(path.join(dest, 'partial'), '');
      throw new Error(`Failed to extract ${zip}`);
    },
  });

  await assert.rejects(apibundle.ensureApiBundle(NEW, deps), /Failed to extract/);
  assert.equal(apibundle.readInstalled(apiDir).version, OLD.version);
  assert.equal(fs.existsSync(`${apiDir}.new`), false);
});

test('ensureApiBundle: recovers from a crash that left only api.old/', async () => {
  const apiDir = tmpApiDir();
  await installed(apiDir, OLD);
  fs.renameSync(apiDir, `${apiDir}.old`); // interrupted between the two renames
  const { deps } = makeDeps(apiDir);

  assert.equal(await apibundle.ensureApiBundle(NEW, deps), true);
  assert.equal(build(apiDir), NEW.version);
  assert.equal(fs.existsSync(`${apiDir}.old`), false);
});
