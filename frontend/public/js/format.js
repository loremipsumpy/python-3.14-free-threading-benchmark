// format.js: pure presentation logic (NO DOM). Shared by log.js, ui.js and app.mjs;
// tested with node:test (tests/format.test.mjs). Being DOM-free, it is importable and
// verifiable in Node without a browser.

/** Duration in ms → "12.4 ms" (1 decimal); non-number → "-". */
export function formatMs(ms) {
  return typeof ms === 'number' && Number.isFinite(ms) ? `${ms.toFixed(1)} ms` : '-';
}

/** HTTP code → color family: 2xx/3xx ok, 4xx warn, rest (5xx and 0=network down) err. */
export function statusFamily(status) {
  if (status >= 200 && status < 400) return 'ok';
  if (status >= 400 && status < 500) return 'warn';
  return 'err';
}

/** Value → text for the log's <pre>: null/undefined placeholder, string as-is, rest JSON. */
export function prettyBody(value) {
  if (value === null || value === undefined) return '(no body)';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Meta line for a benchmark result: "CPU-bound · GIL on · checksum … · workers … · n …"
 *  (io variant shows "delay …ms" instead of n). */
export function benchMetaLine(res) {
  const task = res.task === 'io' ? 'IO-bound' : 'CPU-bound';
  const detail = res.task === 'io' ? `delay ${res.delay_ms}ms` : `n ${res.n}`;
  return `${task} · GIL ${res.gil_enabled ? 'on' : 'off'} · checksum ${res.checksum} · workers ${res.workers} · ${detail}`;
}

const BENCH_KEYS = ['sequential', 'threads', 'interpreters'];

/** results_ms → ordered bars [{key,label,ms,pct}], pct proportional to the max (no NaN). */
export function benchBars(resultsMs) {
  const source = resultsMs ?? {};
  const values = BENCH_KEYS.map((key) => {
    const ms = source[key];
    return Number.isFinite(ms) ? ms : 0;
  });
  const max = Math.max(0, ...values);
  return BENCH_KEYS.map((key, i) => ({
    key,
    label: key,
    ms: values[i],
    pct: max > 0 ? Math.round((values[i] / max) * 100) : 0,
  }));
}
