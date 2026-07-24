// Minimal static server built 100% with Node 24 builtins (zero dependencies).
// Serves `public/` with its own MIME map, its own 404, and path-traversal protection.
// It implements no CORS or proxy: the UI talks straight to the backend on :8000.
//
// Usage: node server.mjs [--port 5500]
// Dev:   node --watch server.mjs
// Tests: node --test   (they use createServer/contentType on an ephemeral port)

import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const DEFAULT_PORT = 5500;
const PUBLIC_DIR = fileURLToPath(new URL('./public', import.meta.url));

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
};

export function contentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return MIME_TYPES[ext] ?? 'application/octet-stream';
}

function send(res, status, body, headers = {}) {
  res.writeHead(status, headers);
  res.end(body);
}

/**
 * Creates (without listening) an http.Server that serves static files from `root`.
 * @param {{ root?: string, logger?: (msg: string) => void }} [options]
 */
export function createServer({ root = PUBLIC_DIR, logger = console.log } = {}) {
  const rootDir = path.resolve(root);

  return http.createServer(async (req, res) => {
    const started = process.hrtime.bigint();
    let status = 500;

    try {
      // Decode BEFORE resolving: this way an encoded `..` (%2e%2e) is normalized
      // before the containment check below.
      let pathname;
      try {
        pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
      } catch {
        status = 400;
        send(res, status, 'Bad Request', { 'Content-Type': 'text/plain; charset=utf-8' });
        return;
      }

      if (pathname.endsWith('/')) pathname += 'index.html';

      // Reject any path that resolves outside of root (path traversal).
      const filePath = path.resolve(rootDir, '.' + pathname);
      if (filePath !== rootDir && !filePath.startsWith(rootDir + path.sep)) {
        status = 404;
        send(res, status, 'Not Found', { 'Content-Type': 'text/plain; charset=utf-8' });
        return;
      }

      let data;
      try {
        data = await readFile(filePath);
      } catch (err) {
        if (err.code === 'ENOENT' || err.code === 'EISDIR') {
          status = 404;
          send(res, status, 'Not Found', { 'Content-Type': 'text/plain; charset=utf-8' });
          return;
        }
        throw err;
      }

      status = 200;
      send(res, status, data, {
        'Content-Type': contentType(filePath),
        'Content-Length': data.length,
      });
    } catch (err) {
      status = 500;
      if (!res.headersSent) {
        send(res, status, 'Internal Server Error', {
          'Content-Type': 'text/plain; charset=utf-8',
        });
      }
      logger(`error serving ${req.method} ${req.url}: ${err.message}`);
    } finally {
      const ms = Number(process.hrtime.bigint() - started) / 1e6;
      logger(`${req.method} ${req.url} ${status} ${ms.toFixed(1)}ms`);
    }
  });
}

if (import.meta.main) {
  const { values } = parseArgs({
    options: { port: { type: 'string', short: 'p', default: String(DEFAULT_PORT) } },
  });
  const port = Number(values.port);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    console.error(`Invalid port: ${values.port}`);
    process.exit(1);
  }
  const server = createServer();
  server.listen(port, () => {
    console.log(`Static frontend at http://localhost:${port}  (root: ${PUBLIC_DIR})`);
  });
}
