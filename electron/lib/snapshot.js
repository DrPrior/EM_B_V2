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
 * local graph). Neo4j must be stopped — the caller runs this before start().
 * @param {(line:string)=>void} onLine
 */
async function importSnapshot(_envPath, onLine = () => {}) {
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
  const { code } = await runStream(
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
