'use strict';

/**
 * Unit tests for lib/imageupdate.js — the in-place-update image guard.
 *
 * Dependencies are injected, so these run hermetically under Node's test runner
 * with no Docker, no USB, and no Electron. They pin the behaviour that fixed the
 * start-step failure: an updated app must load the new image (or fail loudly)
 * rather than letting `compose up` reference a missing tag.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { ensureImageForVersion } = require('../lib/imageupdate');

const MANIFEST = { image: { version: '0.1.2', sha256: 'abc123', file: 'emb-hybrid-api-0.1.2.tar.gz' } };

/** Build a deps object with sensible spies; override per test. */
function makeDeps(overrides = {}) {
  const events = [];
  const errors = [];
  const loaded = [];
  const deps = {
    docker: {
      imageExists: async () => false,
      loadImage: async (tar) => { loaded.push(tar); },
    },
    assets: {
      assetPath: (dir, manifest, key) => `${dir}/${manifest[key].file}`,
      verify: async () => true,
    },
    resolveAssetsDir: async () => '/usb/assets',
    emit: (e) => events.push(e),
    onError: (m) => errors.push(m),
    ...overrides,
  };
  return { deps, events, errors, loaded };
}

test('no-op when the image for the current version is already present', async () => {
  const { deps, events, errors, loaded } = makeDeps({
    docker: { imageExists: async (tag) => tag === 'emb-hybrid-api:0.1.2', loadImage: async () => { throw new Error('should not load'); } },
  });

  const ok = await ensureImageForVersion(MANIFEST, deps);

  assert.equal(ok, true);
  assert.deepEqual(loaded, []);
  assert.deepEqual(events, []);
  assert.deepEqual(errors, []);
});

test('loads the versioned image from the USB assets when missing', async () => {
  const verified = [];
  const { deps, events, errors, loaded } = makeDeps({
    assets: {
      assetPath: (dir, manifest, key) => `${dir}/${manifest[key].file}`,
      verify: async (file, sha) => { verified.push([file, sha]); return true; },
    },
  });

  const ok = await ensureImageForVersion(MANIFEST, deps);

  assert.equal(ok, true);
  // Verified the exact tar resolved from the USB assets dir against its checksum.
  assert.deepEqual(verified, [['/usb/assets/emb-hybrid-api-0.1.2.tar.gz', 'abc123']]);
  assert.deepEqual(loaded, ['/usb/assets/emb-hybrid-api-0.1.2.tar.gz']);
  // Emitted a terminal 'done' for the image step; never surfaced an error.
  assert.equal(events.at(-1).status, 'done');
  assert.deepEqual(errors, []);
});

test('fails with a USB-needed message when the image is missing and no assets are available', async () => {
  const { deps, errors, loaded } = makeDeps({
    resolveAssetsDir: async () => null, // user declined / drive not mounted
  });

  const ok = await ensureImageForVersion(MANIFEST, deps);

  assert.equal(ok, false);
  assert.deepEqual(loaded, []); // never attempted a load
  assert.equal(errors.length, 1);
  assert.match(errors[0], /USB drive/);
  assert.match(errors[0], /0\.1\.2/);
});

test('propagates a checksum-verification failure instead of loading a bad image', async () => {
  const { deps, loaded } = makeDeps({
    assets: {
      assetPath: (dir, manifest, key) => `${dir}/${manifest[key].file}`,
      verify: async () => { throw new Error('Checksum mismatch'); },
    },
  });

  await assert.rejects(() => ensureImageForVersion(MANIFEST, deps), /Checksum mismatch/);
  assert.deepEqual(loaded, []); // bad tar never loaded
});
