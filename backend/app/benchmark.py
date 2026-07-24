"""Python 3.14 concurrency demo: the same CPU-bound function in 3 modes.

`count_primes` is **module top-level** (required to travel to subinterpreters) and
deterministic, so all three modes produce the same result — the `checksum` is
`count_primes(n) = π(n)`, verified identical at runtime (correctness guarantee).

On the standard build (GIL enabled): `threads ≈ sequential` (the GIL serializes the
CPU-bound work) while `interpreters ≪ both` — each subinterpreter has its own GIL
(PEP 684, https://peps.python.org/pep-0684/), so they run truly in parallel.
Under `python3.14t` (free-threading) threads
would also parallelize, without touching this code.
"""

import sys
import time
from concurrent.futures import InterpreterPoolExecutor, ThreadPoolExecutor
from typing import Callable

from app.errors import ValidationError

DEFAULT_WORKERS = 4
DEFAULT_N = 200000
WORKERS_RANGE = (1, 8)
N_RANGE = (10000, 5000000)


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


def _timed(work: Callable[[], list[int]]) -> tuple[list[int], float]:
    start = time.perf_counter()
    results = work()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms


def _sequential(n: int, workers: int) -> list[int]:
    return [count_primes(n) for _ in range(workers)]


def _with_pool(executor_cls, n: int, workers: int) -> list[int]:
    with executor_cls(workers) as executor:
        return list(executor.map(count_primes, [n] * workers))


def run_benchmark(workers: int, n: int) -> dict[str, object]:
    seq_results, seq_ms = _timed(lambda: _sequential(n, workers))
    thr_results, thr_ms = _timed(lambda: _with_pool(ThreadPoolExecutor, n, workers))
    int_results, int_ms = _timed(lambda: _with_pool(InterpreterPoolExecutor, n, workers))

    # Correctness guarantee: all 3 modes must agree on every result.
    all_results = seq_results + thr_results + int_results
    checksum = all_results[0]
    if any(value != checksum for value in all_results):
        raise RuntimeError("benchmark checksum mismatch across modes")

    return {
        "gil_enabled": sys._is_gil_enabled(),
        "workers": workers,
        "n": n,
        "checksum": checksum,
        "results_ms": {
            "sequential": round(seq_ms, 1),
            "threads": round(thr_ms, 1),
            "interpreters": round(int_ms, 1),
        },
    }


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


def parse_params(workers_raw: str | None, n_raw: str | None) -> tuple[int, int]:
    workers = _parse_int(
        "workers", workers_raw, default=DEFAULT_WORKERS, low=WORKERS_RANGE[0], high=WORKERS_RANGE[1]
    )
    n = _parse_int("n", n_raw, default=DEFAULT_N, low=N_RANGE[0], high=N_RANGE[1])
    return workers, n
