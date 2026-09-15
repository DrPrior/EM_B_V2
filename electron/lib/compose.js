'use strict';

/**
 * Shared `docker compose` invocation for the desktop stack. Every call pins the
 * bundled desktop compose file, the per-install env file (credentials + host
 * paths for interpolation), and a fixed project name. The Neo4j data volume is
 * explicitly named in the compose file, so it attaches regardless of project.
 */

const { run, runStream } = require('./exec');
const paths = require('./paths');

const PROJECT = 'em_b_hybrid';

// Name of the Neo4j data volume declared in docker-compose.desktop.yml. Kept
// here so the snapshot importer can tie its "already imported" marker to the
// volume and re-import if the volume name ever changes (e.g. after the fix that
// moved the desktop stack off the shared dev volume). MUST match the `name:`
// under `volumes.neo4j_data` in docker-compose.desktop.yml.
const NEO4J_VOLUME = 'emb_desktop_neo4j_data';

function baseArgs(envPath) {
  return ['compose', '--env-file', envPath, '-f', paths.composePath(), '-p', PROJECT];
}

function up(envPath, onLine = () => {}) {
  return runStream('docker', [...baseArgs(envPath), 'up', '-d'], {}, onLine);
}

function down(envPath, onLine = () => {}) {
  return runStream('docker', [...baseArgs(envPath), 'down'], {}, onLine);
}

function stop(envPath, service, onLine = () => {}) {
  return runStream('docker', [...baseArgs(envPath), 'stop', service], {}, onLine);
}

/** Run a throwaway one-off container: `compose run --rm --no-deps <extra...>`. */
function runOneOff(envPath, extraArgs, onLine = () => {}) {
  return runStream('docker', [...baseArgs(envPath), 'run', '--rm', '--no-deps', ...extraArgs], {}, onLine);
}

/** Best-effort probe of container state for a service. */
async function psState(envPath, service) {
  const { code, stdout } = await run('docker', [...baseArgs(envPath), 'ps', '-a', '--format', '{{.Names}} {{.State}}', service]);
  return code === 0 ? stdout.trim() : '';
}

/**
 * Last `tail` log lines from a service (best-effort, for diagnostics). The API's
 * real startup failure (Neo4j unreachable/auth, host Ollama unreachable) is
 * fail-fast inside the container and only appears here — never in `up -d`
 * output — so callers surface this when a health check times out. Returns '' if
 * the log can't be read.
 */
async function logs(envPath, service, tail = 40) {
  const { code, stdout, stderr } = await run(
    'docker', [...baseArgs(envPath), 'logs', '--tail', String(tail), service]);
  return code === 0 ? (stdout || stderr).trim() : '';
}

module.exports = { PROJECT, NEO4J_VOLUME, baseArgs, up, down, stop, runOneOff, psState, logs };
