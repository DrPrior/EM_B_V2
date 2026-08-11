'use strict';

/**
 * Unit tests for lib/gpu.js — the pure `classify()` logic only.
 *
 * Run with `npm test` (Node's built-in test runner, no extra deps). We do NOT
 * exercise `detect()` here: it spawns `powershell`/`system_profiler`, so it
 * belongs to on-machine verification, not a hermetic unit test.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const gpu = require('../lib/gpu');

test('classify: NVIDIA host, no NPU', () => {
  const r = gpu.classify(['NVIDIA GeForce RTX 4070'], [], 'win32', 'x64');
  assert.equal(r.nvidia, true);
  assert.equal(r.npu, false);
  assert.equal(r.accel, 'Nvidia CUDA');
});

test('classify: Intel Arc iGPU host, no NPU', () => {
  const r = gpu.classify(['Intel(R) Arc(TM) 140V Graphics'], [], 'win32', 'x64');
  assert.equal(r.intel, true);
  assert.equal(r.intelArc, true);
  assert.equal(r.npu, false);
  assert.equal(r.accel, 'Intel Arc (Vulkan, iGPU offload enabled)');
});

test('classify: Intel Arc iGPU host with an NPU appends a visibility-only note', () => {
  const r = gpu.classify(
    ['Intel(R) Arc(TM) 140V Graphics'],
    ['Intel(R) AI Boost'],
    'win32', 'x64',
  );
  assert.equal(r.npu, true);
  assert.deepEqual(r.npuNames, ['Intel(R) AI Boost']);
  assert.equal(
    r.accel,
    'Intel Arc (Vulkan, iGPU offload enabled) + NPU present (Intel(R) AI Boost) — not used, Ollama has no NPU backend',
  );
});

test('classify: plain Intel integrated GPU (no Arc) still detected as Intel', () => {
  const r = gpu.classify(['Intel(R) Iris(R) Xe Graphics'], [], 'win32', 'x64');
  assert.equal(r.intel, true);
  assert.equal(r.intelArc, false);
  assert.equal(r.accel, 'Intel integrated (Vulkan, iGPU offload enabled)');
});

test('classify: Apple Silicon always reports its Neural Engine as an NPU', () => {
  const r = gpu.classify(['Apple M3 Pro'], ['Apple Neural Engine'], 'darwin', 'arm64');
  assert.equal(r.apple, true);
  assert.equal(r.npu, true);
  assert.match(r.accel, /^Apple Metal \+ NPU present \(Apple Neural Engine\)/);
});

test('classify: Intel Mac (x64) is not treated as Apple Silicon', () => {
  const r = gpu.classify(['AMD Radeon Pro 5500M'], [], 'darwin', 'x64');
  assert.equal(r.apple, false);
});

test('classify: no GPU, no NPU falls back to CPU with no note appended', () => {
  const r = gpu.classify([], [], 'win32', 'x64');
  assert.equal(r.accel, 'CPU (no supported GPU detected)');
});

test('classify: NVIDIA host with an NPU still prefers CUDA and only notes the NPU', () => {
  const r = gpu.classify(['NVIDIA GeForce RTX 4070'], ['Intel(R) AI Boost'], 'win32', 'x64');
  assert.equal(r.nvidia, true);
  assert.equal(r.npu, true);
  assert.match(r.accel, /^Nvidia CUDA \+ NPU present/);
});

test('classify propagates the raw names list unchanged', () => {
  const r = gpu.classify(['A', 'B'], [], 'win32', 'x64');
  assert.deepEqual(r.names, ['A', 'B']);
});
