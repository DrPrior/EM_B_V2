'use strict';

/**
 * Unit tests for lib/snapshot.js — the import-once marker around
 * `neo4j-admin database load`.
 *
 * The marker decides whether a launch skips the graph import. Get it wrong in
 * one direction and the app comes up with an empty database; wrong in the other
 * and every launch re-loads a multi-hundred-MB dump. The case that motivated
 * recording `dataDir` is a relocated install: the marker exists, but it
 * describes a Neo4j home the app is no longer using, so the import must run
 * again.
 *
 * Only the decision logic and the pre-flight failures are covered here — the
 * paths that actually shell out to neo4j-admin need a real bundled Neo4j (see
 * docs/DECONTAINERIZE_PLAN.md, Workstream C).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { stubElectron } = require('./electron-stub');

const { userData } = stubElectron();

const paths = require('../lib/paths');
const snapshot = require('../lib/snapshot');

const MARKER = path.join(userData, 'graph-imported.json');

function writeMarker(obj) {
  fs.mkdirSync(userData, { recursive: true });
  fs.writeFileSync(MARKER, typeof obj === 'string' ? obj : JSON.stringify(obj), 'utf8');
}

test.beforeEach(() => {
  fs.rmSync(MARKER, { force: true });
});

test('alreadyImported is false with no marker', () => {
  assert.equal(snapshot.alreadyImported(), false);
});

test('alreadyImported is true when the marker names the current Neo4j home', () => {
  writeMarker({ importedAt: new Date().toISOString(), dataDir: paths.neo4jHomeDir() });
  assert.equal(snapshot.alreadyImported(), true);
});

test('alreadyImported is false when the marker names a different Neo4j home', () => {
  // A relocated install: skipping here would start with an empty graph.
  writeMarker({ dataDir: path.join(os.tmpdir(), 'some-old-install', 'neo4j') });
  assert.equal(snapshot.alreadyImported(), false);
});

test('a legacy marker without dataDir is treated as stale', () => {
  // Markers written in the Docker-volume era carried no dataDir; they must
  // force exactly one re-import onto the native store.
  writeMarker({ importedAt: '2026-01-01T00:00:00.000Z', database: 'neo4j' });
  assert.equal(snapshot.alreadyImported(), false);
});

test('a corrupt marker is treated as stale rather than throwing', () => {
  writeMarker('{ this is not json');
  assert.equal(snapshot.alreadyImported(), false);
});

test('dumpPath is neo4j.dump inside the snapshot dir', () => {
  assert.equal(snapshot.dumpPath(), path.join(paths.snapshotDir(), 'neo4j.dump'));
  assert.equal(snapshot.DATABASE, 'neo4j');
});

test('importSnapshot fails with an actionable message when the dump is absent', async () => {
  fs.rmSync(snapshot.dumpPath(), { force: true });
  await assert.rejects(
    () => snapshot.importSnapshot(null, () => {}),
    /Snapshot dump not found at .*neo4j\.dump\. Provision it first\./,
  );
});

test('importSnapshot skips without touching neo4j-admin when already imported', async () => {
  writeMarker({ dataDir: paths.neo4jHomeDir() });
  const lines = [];

  // No dump on disk and no bundled Neo4j: if this did not return early it would
  // throw or try to spawn a non-existent neo4j-admin.
  fs.rmSync(snapshot.dumpPath(), { force: true });
  await snapshot.importSnapshot(null, (l) => lines.push(l));

  assert.deepEqual(lines, ['Graph already imported — skipping.']);
});
