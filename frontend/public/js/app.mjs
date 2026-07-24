// app.mjs - browser bootstrap: creates the api client, wires the monitor (log) and the
// tasks panel, feeds the connection readout from the event stream + health, and drives the
// benchmark card. It is the only piece that joins everything; the logic lives in the
// modules it orchestrates (api.js / log.js / ui.js / format.js).

import { createApi } from './api.js';
import { initLog } from './log.js';
import { initTasks } from './ui.js';
import { benchBars, formatMs } from './format.js';

const $ = (sel) => document.querySelector(sel);

const api = createApi();

// ── HTTP monitor ──────────────────────────────────────────────────────────────
initLog({
  events: api.events,
  listEl: $('#log-list'),
  emptyEl: $('#log-empty'),
  clearBtn: $('#log-clear'),
  template: $('#log-entry'),
});

// ── Connection readout (fed by the event stream + health) ────────────────────
const readout = $('#readout');
const connText = $('[data-conn-text]');
const gilVal = $('[data-gil]');
const pyVal = $('[data-py]');

function setConnection(state) {
  readout.dataset.state = state;
  connText.textContent =
    state === 'online' ? 'connected' : state === 'offline' ? 'offline' : 'not connected yet';
}

// Connection is derived from the request stream itself (no separate polling):
// a status 0 marks it offline; any OK response reasserts online.
api.events.addEventListener('http', (e) => {
  const { status, ok } = e.detail;
  if (status === 0) setConnection('offline');
  else if (ok) setConnection('online');
});

// ── Tasks panel ───────────────────────────────────────────────────────────────
const tasks = initTasks({
  api,
  form: $('#composer'),
  filterButtons: document.querySelectorAll('.seg'),
  listEl: $('#task-list'),
  emptyEl: $('#tasks-empty'),
  errorEl: $('#tasks-error'),
  template: $('#task-row'),
  composerError: $('#composer-error'),
});

// ── Benchmark card ──────────────────────────────────────────────────────────────
const benchForm = $('#bench-form');
const benchBtn = $('#bench-run');
const benchEmpty = $('#bench-empty');
const benchBarsEl = $('#bench-bars');
const benchMeta = $('#bench-meta');

function setBenchState(state, payload) {
  const running = state === 'running';
  benchBtn.disabled = running;
  if (state === 'done') {
    benchEmpty.hidden = true;
    benchBarsEl.hidden = false;
    benchMeta.hidden = false;
    return;
  }
  benchBarsEl.hidden = true;
  benchMeta.hidden = true;
  benchEmpty.hidden = false;
  benchEmpty.textContent = running
    ? 'Running benchmark… (may take a few seconds)'
    : payload?.status === 404
      ? 'The /api/benchmark endpoint is not available on the backend yet.'
      : `Could not run the benchmark: ${payload?.message ?? 'error'}`;
}

function renderBars(res) {
  const bars = benchBars(res.results_ms);
  const barEls = benchBarsEl.querySelectorAll('.bar');
  bars.forEach((bar, i) => {
    const el = barEls[i];
    if (!el) return;
    el.querySelector('.bar__fill').style.setProperty('--pct', `${bar.pct}%`);
    el.querySelector('.bar__value').textContent = formatMs(bar.ms);
  });
  benchMeta.textContent =
    `GIL ${res.gil_enabled ? 'on' : 'off'} · checksum ${res.checksum} · workers ${res.workers} · n ${res.n}`;
}

benchForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  setBenchState('running');
  try {
    const res = await api.runBenchmark({
      workers: Number(benchForm.elements.workers.value),
      n: Number(benchForm.elements.n.value),
    });
    renderBars(res);
    setBenchState('done');
  } catch (err) {
    setBenchState('error', err);
  }
});

// ── Startup ─────────────────────────────────────────────────────────────────────
(async () => {
  try {
    const health = await api.health();
    setConnection('online');
    gilVal.textContent = health.gil_enabled ? 'on' : 'off';
    pyVal.textContent = health.python;
  } catch {
    setConnection('offline'); // the detail already appears in the monitor
  }
})();

tasks.refresh();
