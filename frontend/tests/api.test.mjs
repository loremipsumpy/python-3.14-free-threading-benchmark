// Tests for api.js: the frontend's only network layer (node:test + node:assert/strict).
// Run from frontend/ with: node --test
//
// All the network is injected: createApi({ fetch, now, onLog }). We use a fake `fetch`
// that returns real `Response` objects (globals in Node 24), and a `now` with scripted
// values to verify the duration measurement deterministically.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  createApi,
  omitEmpty,
  buildQuery,
  benchmarkParams,
  ApiError,
  NetworkError,
} from '../public/js/api.js';

// ── Test helpers ─────────────────────────────────────────────────────────────

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });

/** Fake fetch that records every call and responds with `handler(url, options)`. */
function fakeFetch(handler) {
  const calls = [];
  async function fn(url, options = {}) {
    calls.push({ url, options });
    return handler(url, options, calls.length - 1);
  }
  fn.calls = calls;
  return fn;
}

/** now() that returns scripted values in sequence (the last one repeats). */
function seqNow(values) {
  let i = 0;
  return () => values[Math.min(i++, values.length - 1)];
}

/** Creates api + a notification collector (callback channel). */
function withLogs(opts) {
  const logs = [];
  const api = createApi({ onLog: (e) => logs.push(e), ...opts });
  return { api, logs };
}

const sampleTask = {
  id: '01983c9e-4a1b-7cde-9f00-abcdef012345',
  title: 'Buy coffee',
  description: '',
  status: 'pending',
  priority: 'medium',
  created_at: '2026-07-24T14:03:22.123456+00:00',
  updated_at: '2026-07-24T14:03:22.123456+00:00',
};

// ── Pure helpers ─────────────────────────────────────────────────────────────

test('omitEmpty drops undefined/null/"" and keeps 0 and false', () => {
  assert.deepEqual(
    omitEmpty({ a: '', b: null, c: undefined, d: 'x', e: 0, f: false }),
    { d: 'x', e: 0, f: false },
  );
  assert.deepEqual(omitEmpty(undefined), {});
  assert.deepEqual(omitEmpty(null), {});
});

test('buildQuery builds the query string and skips empties', () => {
  assert.equal(buildQuery({ status: 'pending' }), '?status=pending');
  assert.equal(buildQuery({ workers: 4, n: 200000 }), '?workers=4&n=200000');
  assert.equal(buildQuery({ status: '', x: null, y: undefined }), '');
  assert.equal(buildQuery({}), '');
});

test('benchmarkParams: cpu/default keeps n & drops delay_ms; io keeps delay_ms & drops n', () => {
  // compat: no task ⇒ cpu semantics (n applies, delay_ms does not)
  assert.deepEqual(benchmarkParams({ workers: 4, n: 200000 }), { workers: 4, n: 200000 });
  assert.deepEqual(
    benchmarkParams({ task: 'cpu', workers: 4, n: 200000, delay_ms: 50 }),
    { task: 'cpu', workers: 4, n: 200000 },
  );
  assert.deepEqual(
    benchmarkParams({ task: 'io', workers: 4, n: 200000, delay_ms: 50 }),
    { task: 'io', workers: 4, delay_ms: 50 },
  );
  assert.deepEqual(benchmarkParams(), {});
});

// ── Happy paths ───────────────────────────────────────────────────────────────

test('health(): GET /api/health and returns the body', async () => {
  const fetch = fakeFetch(() => json({ status: 'ok', gil_enabled: true, python: '3.14.4' }));
  const { api } = withLogs({ fetch });
  const out = await api.health();
  assert.deepEqual(out, { status: 'ok', gil_enabled: true, python: '3.14.4' });
  assert.equal(fetch.calls[0].url, 'http://localhost:8000/api/health');
  assert.equal(fetch.calls[0].options.method, 'GET');
});

test('listTasks(): without filter and with ?status=', async () => {
  const fetch = fakeFetch(() => json([sampleTask]));
  const { api } = withLogs({ fetch });
  const all = await api.listTasks();
  assert.deepEqual(all, [sampleTask]);
  assert.equal(fetch.calls[0].url, 'http://localhost:8000/api/tasks');

  await api.listTasks('pending');
  assert.equal(fetch.calls[1].url, 'http://localhost:8000/api/tasks?status=pending');
});

test('getTask(id): GET /api/tasks/{id}', async () => {
  const fetch = fakeFetch(() => json(sampleTask));
  const { api } = withLogs({ fetch });
  const out = await api.getTask(sampleTask.id);
  assert.deepEqual(out, sampleTask);
  assert.equal(fetch.calls[0].url, `http://localhost:8000/api/tasks/${sampleTask.id}`);
});

test('createTask(): POST, omits empty optionals, JSON header, never sends null', async () => {
  const fetch = fakeFetch(() => json(sampleTask, 201));
  const { api } = withLogs({ fetch });
  await api.createTask({ title: 'Buy coffee', description: '', priority: 'high', status: undefined });

  const { options } = fetch.calls[0];
  assert.equal(options.method, 'POST');
  assert.match(options.headers['Content-Type'], /application\/json/);
  const body = JSON.parse(options.body);
  assert.deepEqual(body, { title: 'Buy coffee', priority: 'high' }); // description "" and status undefined omitted
  assert.ok(!options.body.includes('null'), 'the body must not contain null');
});

test('createTask(): an explicit null is omitted (contract null policy)', async () => {
  const fetch = fakeFetch(() => json(sampleTask, 201));
  const { api } = withLogs({ fetch });
  await api.createTask({ title: 'x', description: null });
  assert.deepEqual(JSON.parse(fetch.calls[0].options.body), { title: 'x' });
});

test('patchTask(): PATCH /api/tasks/{id} with a clean body', async () => {
  const fetch = fakeFetch(() => json({ ...sampleTask, status: 'done' }));
  const { api } = withLogs({ fetch });
  await api.patchTask(sampleTask.id, { status: 'done', description: '' });
  assert.equal(fetch.calls[0].options.method, 'PATCH');
  assert.equal(fetch.calls[0].url, `http://localhost:8000/api/tasks/${sampleTask.id}`);
  assert.deepEqual(JSON.parse(fetch.calls[0].options.body), { status: 'done' });
});

test('deleteTask(): DELETE, 204 returns null and notifies ok', async () => {
  const fetch = fakeFetch(() => new Response(null, { status: 204 }));
  const { api, logs } = withLogs({ fetch });
  const out = await api.deleteTask(sampleTask.id);
  assert.equal(out, null);
  assert.equal(fetch.calls[0].options.method, 'DELETE');
  assert.equal(logs.length, 1);
  assert.equal(logs[0].status, 204);
  assert.equal(logs[0].ok, true);
  assert.equal(logs[0].response, null);
});

test('runBenchmark(): with params builds a query; without params sends no query', async () => {
  const fetch = fakeFetch(() =>
    json({ gil_enabled: true, workers: 4, n: 200000, checksum: 17984, results_ms: {} }));
  const { api } = withLogs({ fetch });
  await api.runBenchmark({ workers: 4, n: 200000 });
  assert.equal(fetch.calls[0].url, 'http://localhost:8000/api/benchmark?workers=4&n=200000');
  await api.runBenchmark();
  assert.equal(fetch.calls[1].url, 'http://localhost:8000/api/benchmark');
});

test('runBenchmark(): io sends task+delay_ms (no n); cpu sends task+n (no delay_ms)', async () => {
  const fetch = fakeFetch(() => json({ task: 'io', gil_enabled: true, workers: 4, delay_ms: 50, checksum: 0, results_ms: {} }));
  const { api } = withLogs({ fetch });
  await api.runBenchmark({ task: 'io', workers: 4, delay_ms: 50, n: 200000 });
  assert.equal(fetch.calls[0].url, 'http://localhost:8000/api/benchmark?task=io&workers=4&delay_ms=50');
  await api.runBenchmark({ task: 'cpu', workers: 8, n: 100000, delay_ms: 50 });
  assert.equal(fetch.calls[1].url, 'http://localhost:8000/api/benchmark?task=cpu&workers=8&n=100000');
});

// ── Duration measurement ──────────────────────────────────────────────────────

test('measures the duration with an injected now()', async () => {
  const fetch = fakeFetch(() => json([]));
  const { api, logs } = withLogs({ fetch, now: seqNow([1000, 1012.4]) });
  await api.listTasks();
  assert.equal(logs.length, 1);
  assert.equal(logs[0].ms, 12.4);
});

// ── Notification shape (callback + EventTarget) ─────────────────────────────

test('notification: correct shape and emitted via callback and via EventTarget', async () => {
  const fetch = fakeFetch(() => json([sampleTask]));
  const { api, logs } = withLogs({ fetch, now: seqNow([0, 5]) });
  const seen = [];
  api.events.addEventListener('http', (e) => seen.push(e.detail));

  await api.listTasks('done');

  assert.equal(logs.length, 1);
  assert.equal(seen.length, 1);
  const entry = logs[0];
  assert.deepEqual(Object.keys(entry).sort(),
    ['error', 'method', 'ms', 'ok', 'path', 'request', 'response', 'status'].sort());
  assert.equal(entry.method, 'GET');
  assert.equal(entry.path, '/api/tasks?status=done');
  assert.equal(entry.status, 200);
  assert.equal(entry.ok, true);
  assert.equal(entry.ms, 5);
  assert.equal(entry.request, null);
  assert.deepEqual(entry.response, [sampleTask]);
  assert.equal(entry.error, null);
  assert.deepEqual(seen[0], entry);
});

// ── Contract errors ───────────────────────────────────────────────────────────

test('contract 422 error: throws ApiError with code/details and emits ONE notification', async () => {
  const errBody = {
    error: {
      code: 'validation_error',
      message: 'invalid task data',
      details: { title: 'required, 1-200 chars' },
    },
  };
  const fetch = fakeFetch(() => json(errBody, 422));
  const { api, logs } = withLogs({ fetch });

  await assert.rejects(
    api.createTask({ title: '' }),
    (err) => {
      assert.ok(err instanceof ApiError, 'must be an ApiError');
      assert.equal(err.status, 422);
      assert.equal(err.code, 'validation_error');
      assert.equal(err.details.title, 'required, 1-200 chars');
      return true;
    },
  );
  assert.equal(logs.length, 1, 'exactly one notification on the error path');
  assert.equal(logs[0].status, 422);
  assert.equal(logs[0].ok, false);
  assert.equal(logs[0].error.code, 'validation_error');
  assert.deepEqual(logs[0].error.details, { title: 'required, 1-200 chars' });
  assert.deepEqual(logs[0].response, errBody);
});

test('404 error: ApiError not_found', async () => {
  const fetch = fakeFetch(() => json({ error: { code: 'not_found', message: 'does not exist' } }, 404));
  const { api } = withLogs({ fetch });
  await assert.rejects(api.getTask('nope'), (err) => {
    assert.equal(err.status, 404);
    assert.equal(err.code, 'not_found');
    return true;
  });
});

test('500 with a non-JSON body: controlled ApiError, no uncontrolled exception', async () => {
  const fetch = fakeFetch(() =>
    new Response('Internal Server Error', { status: 500, headers: { 'content-type': 'text/plain' } }));
  const { api, logs } = withLogs({ fetch });
  await assert.rejects(api.health(), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 500);
    assert.equal(err.code, 'internal_error');
    return true;
  });
  assert.equal(logs.length, 1);
  assert.equal(logs[0].status, 500);
});

// ── Backend down ──────────────────────────────────────────────────────────────

test('backend down: controlled NetworkError (not a raw TypeError) + ONE notification status 0', async () => {
  const fetch = async () => { throw new TypeError('failed to fetch'); };
  const { api, logs } = withLogs({ fetch });

  await assert.rejects(api.health(), (err) => {
    assert.ok(err instanceof NetworkError, 'must be a controlled NetworkError');
    assert.ok(err instanceof ApiError, 'NetworkError extends ApiError');
    assert.equal(err.status, 0);
    assert.equal(err.code, 'network_error');
    return true;
  });
  assert.equal(logs.length, 1);
  assert.equal(logs[0].status, 0);
  assert.equal(logs[0].ok, false);
  assert.equal(logs[0].error.networkError, true);
});
