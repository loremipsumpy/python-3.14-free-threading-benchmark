// Tests for the static server (node:test + node:assert/strict).
// Run from frontend/ with: node --test
//
// Design: a single http.Server shared on an ephemeral port, started in before() and
// ALWAYS closed in after() (otherwise the event loop stays alive and the runner hangs).
// Uses global `fetch` and top-level await (Node 24, zero dependencies).

import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import { createServer, contentType } from '../server.mjs';

const PUBLIC_DIR = fileURLToPath(new URL('../public', import.meta.url));

let server;
let base;

before(async () => {
  server = createServer({ root: PUBLIC_DIR, logger: () => {} });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  base = `http://127.0.0.1:${port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
});

test('GET / serves index.html with Content-Type text/html', async () => {
  const res = await fetch(`${base}/`);
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-type') ?? '', /^text\/html/);
  const body = await res.text();
  assert.ok(body.length > 0, 'index.html should not be empty');
});

test('GET /styles.css responds with Content-Type text/css', async () => {
  const res = await fetch(`${base}/styles.css`);
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-type') ?? '', /^text\/css/);
});

test('a nonexistent route responds 404', async () => {
  const res = await fetch(`${base}/does-not-exist.html`);
  assert.equal(res.status, 404);
});

test('an encoded path traversal is blocked with 404 and leaks no external content', async () => {
  // An encoded `..` (%2e%2e%2f) survives fetch's URL parsing; without decoding before
  // resolving it would escape public/. It must return 404 and never /etc/passwd.
  const res = await fetch(`${base}/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd`);
  assert.equal(res.status, 404);
  const body = await res.text();
  assert.ok(!body.includes('root:'), '/etc/passwd content must not leak');
});

test('contentType() maps known extensions and falls back to octet-stream', () => {
  assert.match(contentType('index.html'), /^text\/html/);
  assert.match(contentType('styles.css'), /^text\/css/);
  assert.match(contentType('app.js'), /^text\/javascript/);
  assert.match(contentType('mod.mjs'), /^text\/javascript/);
  assert.match(contentType('data.json'), /^application\/json/);
  assert.equal(contentType('icon.svg'), 'image/svg+xml');
  assert.equal(contentType('favicon.ico'), 'image/x-icon');
  assert.equal(contentType('pic.png'), 'image/png');
  assert.equal(contentType('file.unknown'), 'application/octet-stream');
});
