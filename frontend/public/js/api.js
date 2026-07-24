// api.js: the ONLY network layer of the frontend.
//
// Consumes the tasks API (contract in docs/API_CONTRACT.md) and notifies every call
// (method, path, status, duration ms, request/response bodies) over two channels without
// touching the DOM: an `onLog` callback and an `EventTarget` (`api.events`, "http" event).
//
// Design:
//  - `createApi({ fetch, baseUrl, now, onLog })`: everything external is injectable → the
//    module is testable in node:test with a fake `fetch`, and in the browser it uses the
//    globals (`fetch`, `performance`, `EventTarget`, `CustomEvent`).
//  - Each method emits ONE notification and then returns the body or throws a typed error
//    (`ApiError`/`NetworkError`). No uncontrolled exception ever escapes: a network drop is
//    wrapped in `NetworkError`; an unexpected error body does not break parsing.
//  - Contract's `null` policy: empty optional fields are OMITTED from the body
//    (never sent as `null`).

const DEFAULT_BASE = 'http://localhost:8000';

const defaultNow = () =>
  typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();

// ── Typed errors ────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message ?? 'request failed');
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class NetworkError extends ApiError {
  constructor(message, cause) {
    super(0, 'network_error', message ?? 'network error', undefined);
    this.name = 'NetworkError';
    this.networkError = true;
    if (cause !== undefined) this.cause = cause;
  }
}

// ── Pure helpers (exported for unit tests) ──────────────────────────────────

/** Copies an object dropping keys whose value is undefined/null/"" (keeps 0 and false). */
export function omitEmpty(obj) {
  if (!obj || typeof obj !== 'object') return {};
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null || v === '') continue;
    out[k] = v;
  }
  return out;
}

/** Builds a query string (`?a=1&b=2`) skipping undefined/null/"" values. */
export function buildQuery(params) {
  const pairs = Object.entries(params ?? {})
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  return pairs.length ? `?${pairs.join('&')}` : '';
}

/**
 * Builds the benchmark query params, enforcing the contract's cpu/io exclusivity:
 * io uses `delay_ms` (sending `n` is a 422), cpu/default uses `n` (sending `delay_ms` is
 * a 422). No `task` ⇒ cpu semantics (backend default), keeping older callers working.
 */
export function benchmarkParams({ task, workers, n, delay_ms } = {}) {
  const params = {};
  if (task !== undefined) params.task = task;
  if (workers !== undefined) params.workers = workers;
  if (task === 'io') {
    if (delay_ms !== undefined) params.delay_ms = delay_ms;
  } else if (n !== undefined) {
    params.n = n;
  }
  return params;
}

const FALLBACK_CODE = {
  400: 'bad_request',
  404: 'not_found',
  405: 'method_not_allowed',
  422: 'validation_error',
  500: 'internal_error',
};

/** Translates (status, body) → ApiError, tolerating bodies that don't follow the contract. */
function normalizeError(status, body) {
  const err = body && typeof body === 'object' ? body.error : undefined;
  if (err && typeof err === 'object') {
    return new ApiError(status, err.code ?? FALLBACK_CODE[status] ?? 'http_error', err.message, err.details);
  }
  const message = typeof body === 'string' && body ? body : `request failed (${status})`;
  return new ApiError(status, FALLBACK_CODE[status] ?? 'http_error', message);
}

// ── Factory ───────────────────────────────────────────────────────────────────

export function createApi({
  fetch = globalThis.fetch,
  baseUrl = DEFAULT_BASE,
  now = defaultNow,
  onLog,
} = {}) {
  const events = new EventTarget();

  function emit(entry) {
    if (typeof onLog === 'function') {
      try { onLog(entry); } catch { /* misbehaving consumer: don't break the call */ }
    }
    events.dispatchEvent(new CustomEvent('http', { detail: entry }));
  }

  // A Response is consumed only once → read into a local. Never throws: an invalid JSON
  // or an empty body return null instead of breaking the call.
  async function readBody(res) {
    if (res.status === 204) return null;
    const ct = res.headers.get('content-type') ?? '';
    if (ct.includes('application/json')) {
      try { return await res.json(); } catch { return null; }
    }
    const text = await res.text();
    return text === '' ? null : text;
  }

  async function request(method, path, { body } = {}) {
    const url = baseUrl + path;
    const hasBody = body !== undefined;
    const requestBody = hasBody ? body : null;
    const t0 = now();

    let res;
    try {
      res = await fetch(url, {
        method,
        headers: hasBody ? { 'Content-Type': 'application/json; charset=utf-8' } : undefined,
        body: hasBody ? JSON.stringify(body) : undefined,
      });
    } catch (cause) {
      const ms = round(now() - t0);
      const err = new NetworkError(`could not reach ${url}`, cause);
      emit({ method, path, status: 0, ok: false, ms, request: requestBody, response: null,
        error: { code: err.code, message: err.message, networkError: true } });
      throw err;
    }

    const response = await readBody(res);
    const ms = round(now() - t0);

    if (!res.ok) {
      const err = normalizeError(res.status, response);
      emit({ method, path, status: res.status, ok: false, ms, request: requestBody, response,
        error: { code: err.code, message: err.message, details: err.details } });
      throw err;
    }

    emit({ method, path, status: res.status, ok: true, ms, request: requestBody, response, error: null });
    return response;
  }

  return {
    events,
    health: () => request('GET', '/api/health'),
    listTasks: (status) => request('GET', `/api/tasks${buildQuery({ status })}`),
    getTask: (id) => request('GET', `/api/tasks/${encodeURIComponent(id)}`),
    createTask: (input) => request('POST', '/api/tasks', { body: omitEmpty(input) }),
    patchTask: (id, changes) =>
      request('PATCH', `/api/tasks/${encodeURIComponent(id)}`, { body: omitEmpty(changes) }),
    deleteTask: (id) => request('DELETE', `/api/tasks/${encodeURIComponent(id)}`),
    runBenchmark: (params = {}) =>
      request('GET', `/api/benchmark${buildQuery(benchmarkParams(params))}`),
  };
}

/** Rounds to 3 decimals for stable durations. */
function round(ms) {
  return Math.round(ms * 1000) / 1000;
}
