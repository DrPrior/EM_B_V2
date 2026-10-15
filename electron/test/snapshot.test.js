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

// --- load + migrate ---------------------------------------------------------

/** Put a dump where importSnapshot expects one. */
function placeDump() {
  fs.mkdirSync(paths.snapshotDir(), { recursive: true });
  fs.writeFileSync(snapshot.dumpPath(), 'not a real archive');
}

/** A fake runStream recording each neo4j-admin invocation. */
function recorder(codes = {}) {
  const calls = [];
  const runStream = async (exe, args) => {
    calls.push({ exe, args, subcommand: args.slice(0, 2).join(' ') });
    const code = codes[args.slice(0, 2).join(' ')] ?? 0;
    if (code === 'throw') throw new Error('spawn ENOENT');
    return { code };
  };
  return { runStream, calls };
}

test('importSnapshot loads and then migrates, in that order', async () => {
  placeDump();
  const { runStream, calls } = recorder();

  await snapshot.importSnapshot(null, () => {}, { runStream });

  assert.deepEqual(calls.map((c) => c.subcommand), ['database load', 'database migrate']);
  assert.ok(calls[0].args.includes('--overwrite-destination=true'));
  assert.ok(calls[0].args.includes(`--from-path=${paths.snapshotDir()}`));
});

test('migrate is called without --to-format, so the store stays Community-loadable', async () => {
  placeDump();
  const { runStream, calls } = recorder();

  await snapshot.importSnapshot(null, () => {}, { runStream });

  const migrate = calls.find((c) => c.subcommand === 'database migrate');
  assert.deepEqual(migrate.args, ['database', 'migrate', 'neo4j']);
  // --to-format=block would produce an Enterprise-only store the bundled
  // Community server cannot open.
  assert.equal(migrate.args.some((a) => String(a).startsWith('--to-format')), false);
});

test('a failed load is fatal and leaves no marker', async () => {
  placeDump();
  const { runStream, calls } = recorder({ 'database load': 1 });

  await assert.rejects(
    () => snapshot.importSnapshot(null, () => {}, { runStream }),
    /neo4j-admin database load failed/,
  );
  assert.equal(calls.length, 1, 'must not migrate after a failed load');
  assert.equal(fs.existsSync(MARKER), false, 'a failed import must be retried next launch');
});

test('a failed migrate is reported but not fatal', async () => {
  placeDump();
  const lines = [];
  const { runStream } = recorder({ 'database migrate': 1 });

  await snapshot.importSnapshot(null, (l) => lines.push(l), { runStream });

  // The server start is the real verdict; failing here would turn a recoverable
  // state into a dead first run.
  assert.ok(lines.some((l) => /migration exited 1/.test(l)));
  assert.ok(lines.some((l) => /does not match the bundled Neo4j version/.test(l)));
  assert.ok(fs.existsSync(MARKER), 'the graph did load, so the import counts as done');
});

test('a migrate that cannot even spawn is caught, not thrown', async () => {
  placeDump();
  const lines = [];
  const { runStream } = recorder({ 'database migrate': 'throw' });

  await snapshot.importSnapshot(null, (l) => lines.push(l), { runStream });

  assert.ok(lines.some((l) => /migration could not run \(spawn ENOENT\)/.test(l)));
  assert.ok(fs.existsSync(MARKER));
});

test('the marker records the data dir so a relocated install re-imports', async () => {
  placeDump();
  const { runStream } = recorder();

  await snapshot.importSnapshot(null, () => {}, { runStream });

  const marker = JSON.parse(fs.readFileSync(MARKER, 'utf8'));
  assert.equal(marker.dataDir, paths.neo4jHomeDir());
  assert.equal(marker.database, 'neo4j');
  assert.match(marker.importedAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(snapshot.alreadyImported(), true);
});
