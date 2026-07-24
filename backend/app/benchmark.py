"""Python 3.14 concurrency demo: the same task run `workers` times in 3 modes.

Two tasks show the two faces of the GIL:

* `count_primes` (CPU-bound): the GIL serializes it, so `threads ≈ sequential` while
  `interpreters ≪ both` (each subinterpreter has its own GIL, PEP 684,
  https://peps.python.org/pep-0684/). Under `python3.14t` threads parallelize too.
* `io_roundtrip` (real blocking I/O): each worker makes a GET + POST to the `/api/slow`
  endpoint. urllib blocks and the endpoint sleeps, both releasing the GIL, so `threads`
  scale even under the GIL. This is the concurrent-HTTP-clients counterexample.

Both workers are module top-level (required to travel to subinterpreters). The `checksum`
(π(n) for cpu, W completed round-trips for io) is verified consistent across the 3 modes.
"""

import sys
import time
import urllib.request
from concurrent.futures import InterpreterPoolExecutor, ThreadPoolExecutor
from typing import Callable

from app.errors import ValidationError

DEFAULT_WORKERS = 4
DEFAULT_N = 200000
DEFAULT_DELAY = 50
DEFAULT_TASK = "cpu"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TASKS = ("cpu", "io")
WORKERS_RANGE = (1, 32)
N_RANGE = (10000, 5000000)
DELAY_RANGE = (1, 1000)


def count_primes(n: int) -> int:
    """Count the primes in `[2, n)` by trial division (CPU-bound)."""
    count = 0
    for k in range(2, n):
        is_prime = True
        divisor = 2
        while divisor * divisor <= k:
            if k % divisor == 0:
                is_prime = False
                break
            divisor += 1
        if is_prime:
            count += 1
    return count


def io_roundtrip(url: str) -> int:
    """One GET + one POST to `url` (real HTTP round-trips against `/api/slow`).

    urllib blocks during each request and the endpoint sleeps: both release the GIL, so
    threads overlap. Returns 1 when both calls return 200, else 0. Top-level (urllib is
    imported at module load) so it travels to subinterpreters.
    """
    for method in ("GET", "POST"):
        data = b"" if method == "POST" else None
        request = urllib.request.Request(url, method=method, data=data)
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                return 0
    return 1


def run_slow(ms: int) -> dict[str, object]:
    """Body of the `/api/slow` endpoint: block `ms` (a slow upstream), then acknowledge.

    The sleep is deliberate and releases the GIL, so this is a genuinely non-pure route.
    """
    time.sleep(ms / 1000.0)
    return {"ok": True, "ms": ms}


def _timed(work: Callable[[], list[int]]) -> tuple[list[int], float]:
    start = time.perf_counter()
    results = work()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms


def _with_pool(executor_cls, func, arg, workers: int) -> list[int]:
    with executor_cls(workers) as executor:
        return list(executor.map(func, [arg] * workers))


def _run_modes(func, arg, workers: int):
    """Run `func(arg)` `workers` times in each mode; return (results, ms) per mode."""
    seq, seq_ms = _timed(lambda: [func(arg) for _ in range(workers)])
    thr, thr_ms = _timed(lambda: _with_pool(ThreadPoolExecutor, func, arg, workers))
    itp, itp_ms = _timed(lambda: _with_pool(InterpreterPoolExecutor, func, arg, workers))
    return (seq, thr, itp), (seq_ms, thr_ms, itp_ms)


def run_benchmark(workers: int, *, task: str = DEFAULT_TASK, n: int = DEFAULT_N,
                  delay_ms: int = DEFAULT_DELAY,
                  base_url: str = DEFAULT_BASE_URL) -> dict[str, object]:
    if task == "io":
        url = f"{base_url}/api/slow?ms={delay_ms}"
        results, times = _run_modes(io_roundtrip, url, workers)
        # checksum = round-trips that completed OK (== W when healthy). A checksum < W
        # means a round-trip failed (e.g. timeout), not that the modes disagree.
        checksum = sum(results[0])
        ok = all(len(mode) == workers and sum(mode) == checksum for mode in results)
    else:
        results, times = _run_modes(count_primes, n, workers)
        checksum = results[0][0]  # shared per-call prime count
        ok = all(v == checksum for mode in results for v in mode)
    if not ok:
        raise RuntimeError("benchmark checksum mismatch across modes")

    seq_ms, thr_ms, int_ms = times
    response = {
        "gil_enabled": sys._is_gil_enabled(),
        "workers": workers,
        "task": task,
        "checksum": checksum,
        "results_ms": {
            "sequential": round(seq_ms, 1),
            "threads": round(thr_ms, 1),
            "interpreters": round(int_ms, 1),
        },
    }
    response["delay_ms" if task == "io" else "n"] = delay_ms if task == "io" else n
    return response


def _parse_int(name: str, raw: str | None, *, default: int, low: int, high: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ValidationError({name: f"must be an integer in [{low}, {high}]"})
    if not low <= value <= high:
        raise ValidationError({name: f"must be in [{low}, {high}]"})
    return value


def _query_first(query: dict, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def parse_slow_ms(query: dict) -> int:
    return _parse_int(
        "ms", _query_first(query, "ms"), default=DEFAULT_DELAY,
        low=DELAY_RANGE[0], high=DELAY_RANGE[1],
    )


def parse_params(query: dict) -> dict:
    """Validate the benchmark query and return kwargs for `run_benchmark`.

    `n` belongs to task=cpu and `delay_ms` to task=io; supplying the wrong one is a 422
    (strict, so a stale parameter can never be silently ignored).
    """
    def first(key: str) -> str | None:
        return _query_first(query, key)

    workers = _parse_int(
        "workers", first("workers"), default=DEFAULT_WORKERS,
        low=WORKERS_RANGE[0], high=WORKERS_RANGE[1],
    )
    task = first("task") or DEFAULT_TASK
    if task not in TASKS:
        raise ValidationError({"task": "must be 'cpu' or 'io'"})
    if task == "io":
        if first("n") is not None:
            raise ValidationError({"n": "n only applies to task=cpu"})
        delay_ms = _parse_int(
            "delay_ms", first("delay_ms"), default=DEFAULT_DELAY,
            low=DELAY_RANGE[0], high=DELAY_RANGE[1],
        )
        return {"workers": workers, "task": "io", "delay_ms": delay_ms}
    if first("delay_ms") is not None:
        raise ValidationError({"delay_ms": "delay_ms only applies to task=io"})
    n = _parse_int(
        "n", first("n"), default=DEFAULT_N, low=N_RANGE[0], high=N_RANGE[1]
    )
    return {"workers": workers, "task": "cpu", "n": n}
