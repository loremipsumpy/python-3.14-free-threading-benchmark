"""Benchmark sweep and SVG chart, 100% stdlib (mirrors the repo's zero-dependency rule).

Two modes (argparse subcommands):

* ``collect``: sweeps workers 1..32 against a running benchmark API and writes a JSON
  run file. Structured around an injectable fetch callable; retries each point once,
  and aborts before writing anything if a point still fails (never a partial file).
* ``render``: turns two run files (GIL build + free-threaded build) into a hand-built
  SVG line chart with five series. No plotting dependency: the SVG is emitted as text.

Usage:
    python3 scripts/sweep.py collect --base-url http://localhost:8000 --out gil.json
    python3 scripts/sweep.py render --gil gil.json --ft ft.json --out benchmark.svg
"""

import argparse
import json
import math
import sys
import urllib.request
from xml.sax.saxutils import escape

WORKERS_MIN = 1
WORKERS_MAX = 32
DEFAULT_N = 200000
DEFAULT_DELAY = 50
DEFAULT_BASE_URL = "http://localhost:8000"
# A single w=32/n=200000 benchmark runs the sequential mode ~32x, so a call can take
# tens of seconds; the read timeout has to be generous or the sweep aborts spuriously.
FETCH_TIMEOUT = 600

# ---------------------------------------------------------------------------
# collect (network I/O; not unit-tested, see module docstring)
# ---------------------------------------------------------------------------


def _http_get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _fetch_with_retry(fetch, url: str, timeout: float, label: str) -> dict:
    try:
        return fetch(url, timeout)
    except Exception as first:  # noqa: BLE001 - one retry, then a clear abort
        print(f"  {label}: attempt failed ({first}); retrying once", file=sys.stderr)
        try:
            return fetch(url, timeout)
        except Exception as second:  # noqa: BLE001
            raise RuntimeError(f"{label} failed after retry ({url}): {second}") from second


def collect(base_url: str, *, task: str = "cpu", n: int = DEFAULT_N,
            delay_ms: int = DEFAULT_DELAY, fetch=_http_get_json, progress=sys.stderr) -> dict:
    """Sweep workers 1..32; return the full run in memory (caller persists it).

    `python`/`gil_enabled` come from ``/api/health`` (the benchmark response has no
    `python` field). Accumulates every point before returning, so a mid-sweep failure
    aborts without leaving a half-written file.
    """
    health = _fetch_with_retry(fetch, f"{base_url}/api/health", 30, "health")
    points = []
    for workers in range(WORKERS_MIN, WORKERS_MAX + 1):
        if task == "io":
            url = f"{base_url}/api/benchmark?task=io&workers={workers}&delay_ms={delay_ms}"
        else:
            url = f"{base_url}/api/benchmark?workers={workers}&n={n}"
        data = _fetch_with_retry(fetch, url, FETCH_TIMEOUT, f"workers={workers}")
        ms = data["results_ms"]
        points.append(
            {
                "workers": workers,
                "sequential": ms["sequential"],
                "threads": ms["threads"],
                "interpreters": ms["interpreters"],
            }
        )
        print(
            f"  workers {workers:2d}/{WORKERS_MAX}: "
            f"sequential={ms['sequential']:.1f}ms threads={ms['threads']:.1f}ms "
            f"interpreters={ms['interpreters']:.1f}ms",
            file=progress,
        )
    run = {
        "gil_enabled": health["gil_enabled"],
        "task": task,
        "python": health["python"],
        "points": points,
    }
    run["delay_ms" if task == "io" else "n"] = delay_ms if task == "io" else n
    return run


# ---------------------------------------------------------------------------
# render (pure; unit-tested)
# ---------------------------------------------------------------------------

WIDTH = 920
HEIGHT = 540
MARGIN_LEFT = 70
MARGIN_RIGHT = 210
MARGIN_TOP = 64
MARGIN_BOTTOM = 64
PLOT_W = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
PLOT_H = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
PLOT_BOTTOM = MARGIN_TOP + PLOT_H

# Mid-tone colors chosen to read on both light and dark GitHub backgrounds (no pure
# black/white). Axis/grid ink is a neutral gray for the same reason.
INK = "#888888"
SERIES_STYLE = {
    "seq": "#8c8c8c",
    "threads_gil": "#e15759",
    "interp_gil": "#4e79a7",
    "threads_ft": "#f28e2b",
    "interp_ft": "#59a14f",
}
X_TICKS = (1, 4, 8, 12, 16, 20, 24, 28, 32)
Y_STEPS = (1, 2, 4, 5, 10, 20, 25, 50, 100, 200, 500)


def x_for_workers(workers: int) -> float:
    return MARGIN_LEFT + (workers - WORKERS_MIN) / (WORKERS_MAX - WORKERS_MIN) * PLOT_W


def y_for_seconds(seconds: float, y_max: float) -> float:
    return PLOT_BOTTOM - (seconds / y_max) * PLOT_H


def axis_max(max_value: float) -> float:
    """Smallest multiple of 2 that clears the data by 5% headroom (min 2), so the
    plotted lines fill the panel instead of leaving the top half empty.
    """
    steps = max(1, math.ceil(max(max_value, 0.0) * 1.05 / 2.0))
    return steps * 2.0


def y_ticks(y_max: float) -> list[float]:
    """Whole-number gridline values from 0 to y_max. Picks the smallest step from
    `Y_STEPS` that yields at most 6 intervals, so labels stay integers (e.g. y_max=12
    gives 0..12 step 2) instead of the fractional ticks a fixed tick count produces.
    """
    step = next((s for s in Y_STEPS if y_max / s <= 6), Y_STEPS[-1])
    ticks = []
    value = 0.0
    while value < y_max - 1e-9:
        ticks.append(value)
        value += step
    ticks.append(float(y_max))
    return ticks


def _series(gil_run: dict, ft_run: dict, mode: str):
    """Series as (label, color, [(workers, value), ...]) for the chart mode.

    time: value is seconds (ms / 1000); the sequential line comes from the GIL run only
    (an FT sequential would be a redundant sixth line). speedup: value is own-build
    sequential / mode, so the sequential series falls out as a flat 1x reference.
    """
    style = SERIES_STYLE
    if mode == "speedup":
        def measure(run, key):
            return [(p["workers"], p["sequential"] / p[key]) for p in run["points"]]
    else:
        def measure(run, key):
            return [(p["workers"], p[key] / 1000.0) for p in run["points"]]
    return [
        ("sequential (reference)", style["seq"], measure(gil_run, "sequential")),
        ("threads (GIL)", style["threads_gil"], measure(gil_run, "threads")),
        ("interpreters (GIL)", style["interp_gil"], measure(gil_run, "interpreters")),
        ("threads (free-threaded)", style["threads_ft"], measure(ft_run, "threads")),
        ("interpreters (free-threaded)", style["interp_ft"], measure(ft_run, "interpreters")),
    ]


def _polyline_points(points: list, y_max: float) -> str:
    return " ".join(
        f"{x_for_workers(w):.1f},{y_for_seconds(v, y_max):.1f}" for w, v in points
    )


def _task_label(run: dict) -> str:
    if run.get("task") == "io":
        return f"I/O-bound task (HTTP, delay={run['delay_ms']}ms)"
    return f"CPU-bound task (n={run['n']})"


def render_svg(gil_run: dict, ft_run: dict, mode: str = "time") -> str:
    series = _series(gil_run, ft_run, mode)
    y_max = axis_max(max(value for _, _, points in series for _, value in points))
    label = _task_label(gil_run)
    if mode == "speedup":
        title = f"Speedup vs sequential, W copies of the same {label}, higher is better"
        y_label = "speedup (x)"
    else:
        title = f"Time to run W copies of the same {label}"
        y_label = "seconds"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="sans-serif">',
        f'<text x="{WIDTH / 2:.0f}" y="32" text-anchor="middle" font-size="18" '
        f'fill="{INK}">{escape(title)}</text>',
    ]

    # Horizontal grid + y-axis labels (seconds), on whole-number gridlines.
    for value in y_ticks(y_max):
        y = y_for_seconds(value, y_max)
        parts.append(
            f'<line x1="{MARGIN_LEFT}" y1="{y:.1f}" x2="{MARGIN_LEFT + PLOT_W}" '
            f'y2="{y:.1f}" stroke="{INK}" stroke-opacity="0.25"/>'
        )
        parts.append(
            f'<text x="{MARGIN_LEFT - 10}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="12" fill="{INK}">{value:g}</text>'
        )

    # X-axis ticks (workers).
    for w in X_TICKS:
        x = x_for_workers(w)
        parts.append(
            f'<text x="{x:.1f}" y="{PLOT_BOTTOM + 20:.0f}" text-anchor="middle" '
            f'font-size="12" fill="{INK}">{w}</text>'
        )

    # Axis titles.
    parts.append(
        f'<text x="{MARGIN_LEFT + PLOT_W / 2:.0f}" y="{HEIGHT - 18}" '
        f'text-anchor="middle" font-size="13" fill="{INK}">workers (w)</text>'
    )
    parts.append(
        f'<text x="20" y="{MARGIN_TOP + PLOT_H / 2:.0f}" text-anchor="middle" '
        f'font-size="13" fill="{INK}" transform="rotate(-90 20 {MARGIN_TOP + PLOT_H / 2:.0f})">'
        f"{escape(y_label)}</text>"
    )

    # Data series.
    for _label, color, points in series:
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
            f'points="{_polyline_points(points, y_max)}"/>'
        )

    # Legend (swatches as <rect>, labels as <text>).
    legend_x = MARGIN_LEFT + PLOT_W + 20
    legend_y = MARGIN_TOP + 10
    for i, (label, color, _points) in enumerate(series):
        row_y = legend_y + i * 24
        parts.append(
            f'<rect x="{legend_x}" y="{row_y - 10}" width="18" height="4" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{legend_x + 26}" y="{row_y - 4}" font-size="12" '
            f'fill="{INK}">{escape(label)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="sweep", description="Collect benchmark points and render an SVG chart."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser(
        "collect", help="sweep workers 1..32 against a running benchmark API"
    )
    collect_parser.add_argument("--task", choices=("cpu", "io"), default="cpu")
    collect_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    collect_parser.add_argument("--n", type=int, default=DEFAULT_N, help="task=cpu only")
    collect_parser.add_argument(
        "--delay-ms", type=int, default=DEFAULT_DELAY, help="task=io only"
    )
    collect_parser.add_argument("--out", help="output JSON path (default: stdout)")

    render_parser = sub.add_parser(
        "render", help="render two collected JSON files into an SVG line chart"
    )
    render_parser.add_argument("--gil", required=True, help="run JSON from the GIL build")
    render_parser.add_argument(
        "--ft", required=True, help="run JSON from the free-threaded build"
    )
    render_parser.add_argument(
        "--mode", choices=("time", "speedup"), default="time",
        help="time: seconds per run; speedup: sequential/mode, higher is better",
    )
    render_parser.add_argument("--out", default="benchmark.svg")

    args = parser.parse_args(argv)

    if args.command == "collect":
        run = collect(args.base_url, task=args.task, n=args.n, delay_ms=args.delay_ms)
        text = json.dumps(run, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text)
            print(f"wrote {args.out} ({len(run['points'])} points)", file=sys.stderr)
        else:
            print(text)
    elif args.command == "render":
        with open(args.gil, encoding="utf-8") as handle:
            gil_run = json.load(handle)
        with open(args.ft, encoding="utf-8") as handle:
            ft_run = json.load(handle)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(render_svg(gil_run, ft_run, args.mode))
        print(f"wrote {args.out} ({args.mode})", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
