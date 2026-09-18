'use strict';

/**
 * Import the prebuilt Neo4j graph snapshot into the local native store.
 *
 * Decontainerized port: runs the bundled native `neo4j-admin database load`
 * (Neo4j must be offline, so the caller loads BEFORE starting the server)
 * instead of a throwaway compose container. Idempotent via a marker file — the
 * hours-long ingest/enrich pipeline is skipped entirely.
 *
 * The shipped dump must be in a Community-loadable record format (aligned /
 * standard), not Enterprise `block` — see docs/DECONTAINERIZE_PLAN.md.
 */

const fs = require('fs');
const path = require('path');

const { runStream } = require('./exec');
const paths = require('./paths');

const DATABASE = 'neo4j';

function markerPath() {
  return path.join(paths.userDataDir(), 'graph-imported.json');
}

function readMarker() {
  try {
    return JSON.parse(fs.readFileSync(markerPath(), 'utf8'));
  } catch {
    return null;
  }
}

/**
 * True only if the snapshot was loaded into the Neo4j data dir currently in use.
 * The marker records the target home dir, so a relocated install re-imports
 * rather than starting with an empty graph. Markers without `dataDir` (e.g. from
 * the old Docker volume era) are treated as stale, forcing a one-time re-import.
 */
function alreadyImported() {
  const marker = readMarker();
  return marker !== null && marker.dataDir === paths.neo4jHomeDir();
}

function dumpPath() {
  return path.join(paths.snapshotDir(), `${DATABASE}.dump`);
}

/**
 * Load snapshot/neo4j.dump into the local Neo4j store (overwriting any existing
 * local graph), then bring the store up to the bundled server's format version.
 * Neo4j must be stopped — the caller runs this before start().
 *
 * @param {string|null} _envPath Unused; kept for call-site compatibility.
 * @param {(line:string)=>void} onLine
 * @param {{runStream?: Function}} [deps] Injection seam for tests.
 */
async function importSnapshot(_envPath, onLine = () => {}, { runStream: run = runStream } = {}) {
  if (alreadyImported()) {
    onLine('Graph already imported — skipping.');
    return;
  }
  const dump = dumpPath();
  if (!fs.existsSync(dump)) {
    throw new Error(`Snapshot dump not found at ${dump}. Provision it first.`);
  }

  onLine('Loading graph into the local Neo4j store (existing data is overwritten)…');
  const env = { ...process.env, JAVA_HOME: paths.jreHomeDir() };
  const { code } = await run(
    paths.neo4jAdminPath(),
    [
      'database',
      'load',
      DATABASE,
      `--from-path=${paths.snapshotDir()}`,
      '--overwrite-destination=true',
    ],
    { env },
    onLine,
  );
  if (code !== 0) throw new Error('neo4j-admin database load failed.');

  // Belt and braces. The shipped dump is supposed to be exported at the bundled
  // server's format version already (scripts/stage-neo4j.ps1 -ReExport), and if
  // it is, this costs about a second: `migrate` reports "the current store
  // version and the migration target version are the same, so there is nothing
  // to do" and exits 0. If someone ships a dump from a different Neo4j line,
  // this is what stops the server refusing to open the store right after a
  // multi-GB unpack.
  //
  // No --to-format: that keeps the store in its current family, so a record
  // (aligned) store stays Community-loadable. --to-format=block would produce
  // an Enterprise-only store the bundled server could not open.
  //
  // Deliberately NOT fatal. Migration is the backstop, not the mechanism — and
  // the real verdict comes moments later when the server either starts or does
  // not. Failing here would turn a recoverable state into a dead first run.
  onLine('Checking the store matches the bundled Neo4j version…');
  try {
    const migrated = await run(
      paths.neo4jAdminPath(),
      ['database', 'migrate', DATABASE],
      { env },
      onLine,
    );
    if (migrated.code !== 0) {
      onLine(
        `Store migration exited ${migrated.code}; continuing. If Neo4j now fails to ` +
          'start, the shipped dump does not match the bundled Neo4j version.',
      );
    }
  } catch (err) {
    onLine(`Store migration could not run (${err.message}); continuing.`);
  }

  fs.writeFileSync(
    markerPath(),
    JSON.stringify({
      importedAt: new Date().toISOString(),
      database: DATABASE,
      dataDir: paths.neo4jHomeDir(),
    }),
    'utf8',
  );
  onLine('Graph restored into the local Neo4j store.');
}

module.exports = { importSnapshot, alreadyImported, dumpPath, DATABASE };
