'use strict';

/**
 * Unit tests for lib/procs.js — the readiness probes the supervisor sequences
 * the native stack with.
 *
 * These matter because Docker used to supply ordering for free
 * (`depends_on: service_healthy`). Natively, "Neo4j is ready" and "the API is
 * ready" are these two functions, and a probe that reports ready too early
 * starts the API against a database that is not accepting bolt yet.
 *
 * Probes run against throwaway local servers, not the real stack — hence the
 * `target` override on checkHealth/waitForBolt. Nothing here spawns Neo4j or
 * the frozen API (see docs/DECONTAINERIZE_PLAN.md: a managed-machine ASR rule
 * blocks the exe outright, so that path is only testable end-to-end).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('http');
const net = require('net');

const { stubElectron } = require('./electron-stub');

stubElectron(); // lib/procs.js -> lib/paths.js -> require('electron')

const procs = require('../lib/procs');

/** Start an HTTP server that answers /health with the given status/body. */
function healthServer(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () =>
      resolve({
        target: { host: '127.0.0.1', port: server.address().port },
        close: () => new Promise((r) => server.close(r)),
      }),
    );
  });
}

/** A port nothing is listening on (bound, then released). */
function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

test('checkHealth is true only for 200 + {"status":"healthy"}', async () => {
  const srv = await healthServer((req, res) => {
    assert.equal(req.url, '/health');
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ status: 'healthy' }));
  });
  try {
    assert.equal(await procs.checkHealth(2000, srv.target), true);
  } finally {
    await srv.close();
  }
});

test('checkHealth is false when the API answers but is not healthy', async () => {
  const srv = await healthServer((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ status: 'degraded' }));
  });
  try {
    assert.equal(await procs.checkHealth(2000, srv.target), false);
  } finally {
    await srv.close();
  }
});

test('checkHealth is false on a 5xx', async () => {
  const srv = await healthServer((req, res) => {
    res.writeHead(503);
    res.end(JSON.stringify({ status: 'healthy' })); // right body, wrong status code
  });
  try {
    assert.equal(await procs.checkHealth(2000, srv.target), false);
  } finally {
    await srv.close();
  }
});

test('checkHealth is false on a non-JSON body rather than throwing', async () => {
  const srv = await healthServer((req, res) => {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<html>a proxy or captive portal got in the way</html>');
  });
  try {
    assert.equal(await procs.checkHealth(2000, srv.target), false);
  } finally {
    await srv.close();
  }
});

test('checkHealth is false when nothing is listening', async () => {
  const port = await freePort();
  assert.equal(await procs.checkHealth(1000, { host: '127.0.0.1', port }), false);
});

test('waitForHealth gives up and returns false rather than hanging', async () => {
  const port = await freePort();
  const started = Date.now();
  assert.equal(
    await procs.waitForHealth(3, 10, { host: '127.0.0.1', port }),
    false,
  );
  // Bounded by retries — proves it is not waiting on the 90x2s production budget.
  assert.ok(Date.now() - started < 5000);
});

test('waitForHealth succeeds once the API comes up mid-wait', async () => {
  const port = await freePort();
  const target = { host: '127.0.0.1', port };

  let server;
  const startLate = setTimeout(() => {
    server = http.createServer((req, res) => {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ status: 'healthy' }));
    });
    server.listen(port, '127.0.0.1');
  }, 120);

  try {
    assert.equal(await procs.waitForHealth(40, 50, target), true);
  } finally {
    clearTimeout(startLate);
    if (server) await new Promise((r) => server.close(r));
  }
});

test('waitForBolt is true as soon as the port accepts a connection', async () => {
  const server = net.createServer((sock) => sock.end());
  const port = await new Promise((r) =>
    server.listen(0, '127.0.0.1', () => r(server.address().port)),
  );
  try {
    assert.equal(await procs.waitForBolt(3, 10, { host: '127.0.0.1', port }), true);
  } finally {
    await new Promise((r) => server.close(r));
  }
});

test('waitForBolt is false while nothing is listening on bolt', async () => {
  const port = await freePort();
  assert.equal(await procs.waitForBolt(2, 10, { host: '127.0.0.1', port }), false);
});

test('stopAll is safe when nothing was ever started', async () => {
  await procs.stopAll();
  await procs.stopAll(); // idempotent: quit paths can call it more than once
});

test('the loopback ports the supervisor sequences on are the documented ones', () => {
  assert.equal(procs.BOLT_PORT, 7687);
  assert.equal(procs.API_PORT, 8000);
});
