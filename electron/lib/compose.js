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

module.exports = { PROJECT, baseArgs, up, down, stop, runOneOff, psState };
