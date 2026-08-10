'use strict';

/**
 * Import the prebuilt Neo4j graph snapshot into the local volume.
 *
 * Node port of scripts/import-graph.ps1: Neo4j Community must be offline to load,
 * so we stop the service and run `neo4j-admin database load` in a throwaway
 * container that mounts the dump dir and shares the named data volume. Idempotent
 * via a marker file — the ~hours-long ingest/enrich pipeline is skipped entirely.
 */

const fs = require('fs');
const path = require('path');
const compose = require('./compose');
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
 * True only if the snapshot has been loaded into the volume the desktop stack
 * currently uses. The marker records the target volume, so a volume change
 * (e.g. the fix that moved the desktop stack off the shared dev volume, which
 * leaves the new volume empty) re-imports instead of starting with an empty
 * graph. Markers written before this field existed have no `volume` and are
 * treated as stale, forcing a one-time re-import into the correct volume.
 */
function alreadyImported() {
  const marker = readMarker();
  return marker !== null && marker.volume === compose.NEO4J_VOLUME;
}

function dumpPath() {
  return path.join(paths.snapshotDir(), `${DATABASE}.dump`);
}

/**
 * Load snapshot/<db>.dump into the em_b_v2_neo4j_data volume (overwriting any
 * existing local graph). Requires the dump to have been downloaded already.
 * @param {(line:string)=>void} onLine
 */
async function importSnapshot(envPath, onLine = () => {}) {
  if (alreadyImported()) {
    onLine('Graph already imported — skipping.');
    return;
  }
  const dump = dumpPath();
  if (!fs.existsSync(dump)) {
    throw new Error(`Snapshot dump not found at ${dump}. Download it first.`);
  }

  onLine('Stopping Neo4j (offline load required)…');
  await compose.stop(envPath, 'neo4j', onLine);

  // Docker Desktop wants forward-slashed absolute host paths for -v.
  const hostSnapshot = paths.snapshotDir().replace(/\\/g, '/');
  onLine('Loading graph into the local volume (existing data is overwritten)…');
  const { code } = await compose.runOneOff(
    envPath,
    ['-v', `${hostSnapshot}:/snapshot`, 'neo4j',
      'neo4j-admin', 'database', 'load', DATABASE,
      '--from-path=/snapshot', '--overwrite-destination=true'],
    onLine,
  );
  if (code !== 0) throw new Error('neo4j-admin database load failed.');

  fs.writeFileSync(
    markerPath(),
    JSON.stringify({
      importedAt: new Date().toISOString(),
      database: DATABASE,
      volume: compose.NEO4J_VOLUME,
    }),
    'utf8',
  );
  onLine(`Graph restored into ${compose.NEO4J_VOLUME}.`);
}

module.exports = { importSnapshot, alreadyImported, dumpPath, DATABASE };
