// Tests for format.js: pure presentation logic (no DOM), used by log.js/ui.js/app.mjs.
// Run from frontend/ with: node --test

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatMs, statusFamily, prettyBody, benchBars, benchMetaLine } from '../public/js/format.js';

test('formatMs: 1 decimal + suffix, and "-" for non-numbers', () => {
  assert.equal(formatMs(12.4), '12.4 ms');
  assert.equal(formatMs(12.36), '12.4 ms');
  assert.equal(formatMs(0), '0.0 ms');
  assert.equal(formatMs(null), '-');
  assert.equal(formatMs(undefined), '-');
  assert.equal(formatMs(NaN), '-');
});

test('statusFamily: maps to ok/warn/err by HTTP family (0 = network down)', () => {
  for (const s of [200, 201, 204, 304]) assert.equal(statusFamily(s), 'ok', `status ${s}`);
  for (const s of [400, 404, 422]) assert.equal(statusFamily(s), 'warn', `status ${s}`);
  for (const s of [500, 502]) assert.equal(statusFamily(s), 'err', `status ${s}`);
  assert.equal(statusFamily(0), 'err'); // network down
});

test('prettyBody: null/undefined → placeholder; string as-is; object/array → indented JSON', () => {
  assert.equal(prettyBody(null), '(no body)');
  assert.equal(prettyBody(undefined), '(no body)');
  assert.equal(prettyBody('plain text'), 'plain text');
  assert.equal(prettyBody({ a: 1 }), '{\n  "a": 1\n}');
  assert.equal(prettyBody([1, 2]), '[\n  1,\n  2\n]');
});

test('benchBars: fixed order, pct proportional to the max, no NaN', () => {
  const bars = benchBars({ sequential: 1200, threads: 1180, interpreters: 300 });
  assert.deepEqual(bars.map((b) => b.key), ['sequential', 'threads', 'interpreters']);
  assert.deepEqual(bars.map((b) => b.pct), [100, 98, 25]);
  assert.deepEqual(bars.map((b) => b.ms), [1200, 1180, 300]);
});

test('benchMetaLine: cpu shows n; io shows delay; reflects the GIL state', () => {
  assert.equal(
    benchMetaLine({ task: 'cpu', gil_enabled: true, checksum: 17984, workers: 4, n: 200000 }),
    'CPU-bound · GIL on · checksum 17984 · workers 4 · n 200000',
  );
  assert.equal(
    benchMetaLine({ task: 'io', gil_enabled: false, checksum: 0, workers: 4, delay_ms: 50 }),
    'IO-bound · GIL off · checksum 0 · workers 4 · delay 50ms',
  );
});

test('benchBars: all zero or a missing key → pct 0 (no NaN)', () => {
  const zero = benchBars({ sequential: 0, threads: 0, interpreters: 0 });
  assert.deepEqual(zero.map((b) => b.pct), [0, 0, 0]);

  const missing = benchBars({ sequential: 1000, threads: 500 }); // no interpreters
  assert.deepEqual(missing.map((b) => b.key), ['sequential', 'threads', 'interpreters']);
  assert.equal(missing[2].ms, 0);
  assert.equal(missing[2].pct, 0);
  assert.ok(missing.every((b) => Number.isFinite(b.pct)), 'no pct should be NaN');
});
