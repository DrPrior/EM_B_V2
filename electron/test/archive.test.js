'use strict';

/**
 * Unit tests for lib/archive.js — unpacking the USB setup assets.
 *
 * Runs against the real OS `tar` (bsdtar on Windows 10+ / macOS) and real temp
 * dirs, because the thing worth pinning is the *positional contract* between
 * three places that must agree or first run fails after a multi-GB copy:
 *
 *   electron/scripts/build-release.ps1  zips a directory's CONTENTS
 *   lib/archive.js                      extracts into <userData>/<name>
 *   lib/paths.js                        expects <userData>/api/emb-api.exe etc.
 *
 * So these tests assert that a contents-at-root zip lands at the destination
 * root (no extra nesting), and that a tar.gz built the way build-release.ps1
 * builds project_data.tar.gz keeps its top-level directory.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const { extractZip, extractTarGz } = require('../lib/archive');

function tmpDir(prefix = 'emb-archive-') {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

/** Build a source tree that mirrors a frozen API bundle. */
function apiBundleTree(root) {
  fs.mkdirSync(path.join(root, '_internal', 'src', 'static'), { recursive: true });
  fs.writeFileSync(path.join(root, 'emb-api.exe'), 'MZ-not-really');
  fs.writeFileSync(path.join(root, '_internal', 'base_library.zip'), 'zip');
  fs.writeFileSync(path.join(root, '_internal', 'src', 'static', 'index.html'), '<html>');
  return root;
}

/**
 * Zip a directory's CONTENTS so they land at the archive root — the same shape
 * build-release.ps1's Compress-Contents produces.
 */
function zipContents(srcDir, destZip) {
  execFileSync('tar', ['--format=zip', '-cf', destZip, '-C', srcDir, '.']);
  return destZip;
}

/** tar.gz a named directory, preserving it as the archive's top-level entry. */
function tarGzDir(parentDir, name, destArchive) {
  execFileSync('tar', ['-czf', destArchive, '-C', parentDir, name]);
  return destArchive;
}

test('extractZip puts a contents-at-root zip at the destination root', async () => {
  const work = tmpDir();
  const src = apiBundleTree(path.join(work, 'dist', 'emb-api'));
  const zip = zipContents(src, path.join(work, 'emb-api.zip'));

  const dest = path.join(work, 'userData', 'api');
  await extractZip(zip, dest);

  // The exact paths lib/paths.js resolves: no intermediate "emb-api/" level.
  assert.ok(fs.existsSync(path.join(dest, 'emb-api.exe')), 'emb-api.exe at dest root');
  assert.ok(fs.existsSync(path.join(dest, '_internal', 'base_library.zip')));
  assert.ok(
    fs.existsSync(path.join(dest, '_internal', 'src', 'static', 'index.html')),
    'nested resource paths survive extraction',
  );
  assert.equal(
    fs.existsSync(path.join(dest, 'emb-api')),
    false,
    'must not introduce an extra top-level directory',
  );
});

test('extractZip creates the destination directory when missing', async () => {
  const work = tmpDir();
  const src = apiBundleTree(path.join(work, 'src'));
  const zip = zipContents(src, path.join(work, 'a.zip'));

  const dest = path.join(work, 'does', 'not', 'exist', 'yet');
  assert.equal(fs.existsSync(dest), false);
  await extractZip(zip, dest);
  assert.ok(fs.existsSync(path.join(dest, 'emb-api.exe')));
});

test('extractTarGz keeps the archive top-level dir (project_data/)', async () => {
  const work = tmpDir();
  const corpus = path.join(work, 'staging', 'project_data', 'Cat A');
  fs.mkdirSync(corpus, { recursive: true });
  fs.writeFileSync(path.join(corpus, 'doc.txt'), 'hello');
  const archive = tarGzDir(path.join(work, 'staging'), 'project_data', path.join(work, 'pd.tar.gz'));

  // firstrun.js extracts this into userData itself, relying on the archive to
  // supply the project_data/ level that paths.projectDataDir() points at.
  const dest = path.join(work, 'userData');
  await extractTarGz(archive, dest);

  assert.ok(fs.existsSync(path.join(dest, 'project_data', 'Cat A', 'doc.txt')));
});

test('extractZip rejects when the archive is missing', async () => {
  const work = tmpDir();
  await assert.rejects(
    () => extractZip(path.join(work, 'nope.zip'), path.join(work, 'out')),
    /Failed to extract/,
  );
});

test('extractZip rejects on a corrupt archive', async () => {
  const work = tmpDir();
  const bad = path.join(work, 'bad.zip');
  fs.writeFileSync(bad, 'this is definitely not an archive');
  await assert.rejects(
    () => extractZip(bad, path.join(work, 'out')),
    /Failed to extract/,
  );
});

test('extractTarGz rejects on a corrupt archive', async () => {
  const work = tmpDir();
  const bad = path.join(work, 'bad.tar.gz');
  fs.writeFileSync(bad, 'not gzip either');
  await assert.rejects(
    () => extractTarGz(bad, path.join(work, 'out')),
    /Failed to extract/,
  );
});

test('a failed extraction does not leave the destination populated', async () => {
  const work = tmpDir();
  const bad = path.join(work, 'bad.zip');
  fs.writeFileSync(bad, 'garbage');
  const dest = path.join(work, 'out');

  await assert.rejects(() => extractZip(bad, dest));

  // The dir is created before tar runs, but nothing should have been written
  // into it — a half-populated dir is what apibundle.js's staged swap guards
  // against, and it must not come from here.
  assert.deepEqual(fs.readdirSync(dest), []);
});
