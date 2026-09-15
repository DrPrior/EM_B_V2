'use strict';

/**
 * Native process manager for the decontainerized backend.
 *
 * Replaces the Docker/compose supervision (lib/compose.js): starts Neo4j and the
 * frozen API as child processes, probes their readiness (a bolt TCP connect for
 * Neo4j, GET /health for the API), and kills the process trees on stop. Ollama is
 * host-native and handled separately (lib/ollama.js).
 *
 * Everything binds loopback: Neo4j bolt on 127.0.0.1:7687, the API on
 * 127.0.0.1:8000. The frozen API reads API_HOST/API_PORT from its environment
 * (run_api.py); Neo4j reads its own conf. Java for Neo4j comes from the bundled
 * JRE via JAVA_HOME.
 */

const http = require('http');
const net = require('net');
const { spawn } = require('child_process');
const paths = require('./paths');

const BOLT_HOST = '127.0.0.1';
const BOLT_PORT = 7687;
const API_HOST = '127.0.0.1';
const API_PORT = 8000;

let neo4jChild = null;
let apiChild = null;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/** Base child env: inherit ours, point Java at the bundled JRE, then override. */
function childEnv(vars = {}) {
  return { ...process.env, JAVA_HOME: paths.jreHomeDir(), ...vars };
}

function wireOutput(child, onLine) {
  const pump = (d) =>
    d
      .toString()
      .split(/\r?\n/)
      .forEach((l) => l && onLine(l));
  if (child.stdout) child.stdout.on('data', pump);
  if (child.stderr) child.stderr.on('data', pump);
}

/** Start `neo4j console` (server runs in the foreground child). */
function startNeo4j(vars = {}, onLine = () => {}) {
  neo4jChild = spawn(paths.neo4jConsolePath(), ['console'], {
    env: childEnv(vars),
    windowsHide: true,
  });
  wireOutput(neo4jChild, onLine);
  return neo4jChild;
}

/** Start the frozen API exe (binds 127.0.0.1:8000). */
function startApi(vars = {}, onLine = () => {}) {
  apiChild = spawn(paths.apiExePath(), [], {
    env: childEnv({ API_HOST, API_PORT: String(API_PORT), ...vars }),
    cwd: paths.apiDir(),
    windowsHide: true,
  });
  wireOutput(apiChild, onLine);
  return apiChild;
}

/** Resolve true if a TCP connection to host:port succeeds within timeoutMs. */
function tcpOpen(host, port, timeoutMs = 2000) {
  return new Promise((resolve) => {
    const sock = new net.Socket();
    const done = (ok) => {
      sock.destroy();
      resolve(ok);
    };
    sock.setTimeout(timeoutMs);
    sock.once('connect', () => done(true));
    sock.once('timeout', () => done(false));
    sock.once('error', () => done(false));
    sock.connect(port, host);
  });
}

/** Wait until Neo4j accepts bolt connections (readiness, not just process-alive). */
async function waitForBolt(retries = 60, delayMs = 1000) {
  for (let i = 0; i < retries; i++) {
    if (await tcpOpen(BOLT_HOST, BOLT_PORT)) return true;
    await sleep(delayMs);
  }
  return false;
}

/** Resolve true if the API answers /health with {status:"healthy"}. */
function checkHealth(timeoutMs = 2000) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: API_HOST, port: API_PORT, path: '/health', timeout: timeoutMs },
      (res) => {
        let body = '';
        res.on('data', (d) => (body += d));
        res.on('end', () => {
          try {
            resolve(res.statusCode === 200 && JSON.parse(body).status === 'healthy');
          } catch {
            resolve(false);
          }
        });
      },
    );
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve(false));
  });
}

async function waitForHealth(retries = 90, delayMs = 2000) {
  for (let i = 0; i < retries; i++) {
    if (await checkHealth()) return true;
    await sleep(delayMs);
  }
  return false;
}

/** Kill a child and its whole tree (best-effort; resolves regardless). */
function killTree(child) {
  return new Promise((resolve) => {
    if (!child || child.exitCode !== null || child.killed) return resolve();
    if (process.platform === 'win32') {
      const k = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
        windowsHide: true,
      });
      k.on('close', () => resolve());
      k.on('error', () => {
        try {
          child.kill('SIGKILL');
        } catch {
          /* ignore */
        }
        resolve();
      });
    } else {
      try {
        child.kill('SIGTERM');
      } catch {
        /* ignore */
      }
      resolve();
    }
  });
}

/** Stop the API first, then Neo4j (reverse of start order). Never throws. */
async function stopAll() {
  await killTree(apiChild).catch(() => {});
  await killTree(neo4jChild).catch(() => {});
  apiChild = null;
  neo4jChild = null;
}

module.exports = {
  startNeo4j,
  startApi,
  waitForBolt,
  checkHealth,
  waitForHealth,
  stopAll,
  BOLT_PORT,
  API_PORT,
};
