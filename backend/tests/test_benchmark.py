"""Tests for the 3.14 concurrency benchmark.

Uses a small `n` (10000) to keep the suite fast. CPU timings are **not** asserted (at
small `n` subinterpreter startup dominates and it would be flaky); only checksum
correctness and validation. The io task's threads-scale-under-GIL claim IS asserted:
sleep timing is deterministic and GIL release during blocking is core-independent, so
`threads < sequential / 2` is robust.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from concurrent.futures import InterpreterPoolExecutor, ThreadPoolExecutor
from http import HTTPStatus
from http.client import HTTPConnection

from app.benchmark import count_primes, parse_params, run_benchmark
from app.errors import ValidationError
from app.repository import TaskRepository
from app.server import make_server

SMALL_N = 10000
PI_10000 = 1229  # π(10000), correctness anchor


class CountPrimesTests(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(count_primes(2), 0)
        self.assertEqual(count_primes(3), 1)
        self.assertEqual(count_primes(SMALL_N), PI_10000)


class ThreeModesAgreeTests(unittest.TestCase):
    def test_all_three_modes_identical_checksum(self):
        truth = count_primes(SMALL_N)
        with ThreadPoolExecutor(2) as ex:
            thr = list(ex.map(count_primes, [SMALL_N] * 2))
        with InterpreterPoolExecutor(2) as ex:
            interp = list(ex.map(count_primes, [SMALL_N] * 2))
        self.assertTrue(all(r == truth for r in thr))
        self.assertTrue(all(r == truth for r in interp))


class RunBenchmarkTests(unittest.TestCase):
    def test_shape_and_checksum(self):
        result = run_benchmark(workers=2, n=SMALL_N)

        self.assertEqual(result["gil_enabled"], sys._is_gil_enabled())
        self.assertEqual(result["workers"], 2)
        self.assertEqual(result["n"], SMALL_N)
        self.assertEqual(result["checksum"], PI_10000)
        self.assertEqual(
            set(result["results_ms"]), {"sequential", "threads", "interpreters"}
        )
        for value in result["results_ms"].values():
            self.assertIsInstance(value, float)
            self.assertGreaterEqual(value, 0.0)


class ParseParamsTests(unittest.TestCase):
    def test_cpu_defaults(self):
        self.assertEqual(parse_params({}), {"workers": 4, "task": "cpu", "n": 200000})

    def test_cpu_explicit(self):
        self.assertEqual(
            parse_params({"workers": ["6"], "n": ["10000"]}),
            {"workers": 6, "task": "cpu", "n": 10000},
        )

    def test_workers_boundary_32_ok(self):
        self.assertEqual(parse_params({"workers": ["32"]})["workers"], 32)

    def test_workers_out_of_range_high(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params({"workers": ["33"]})
        self.assertIn("[1, 32]", ctx.exception.details["workers"])

    def test_workers_out_of_range_low(self):
        with self.assertRaises(ValidationError):
            parse_params({"workers": ["0"]})

    def test_n_out_of_range(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params({"n": ["5000"]})
        self.assertIn("n", ctx.exception.details)

    def test_non_numeric_workers(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params({"workers": ["abc"]})
        self.assertIn("workers", ctx.exception.details)

    def test_io_defaults(self):
        self.assertEqual(
            parse_params({"task": ["io"]}),
            {"workers": 4, "task": "io", "delay_ms": 50},
        )

    def test_io_with_delay(self):
        self.assertEqual(
            parse_params({"task": ["io"], "workers": ["8"], "delay_ms": ["100"]}),
            {"workers": 8, "task": "io", "delay_ms": 100},
        )

    def test_io_rejects_n(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params({"task": ["io"], "n": ["200000"]})
        self.assertEqual(ctx.exception.details["n"], "n only applies to task=cpu")

    def test_cpu_rejects_delay(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params({"task": ["cpu"], "delay_ms": ["50"]})
        self.assertIn("delay_ms", ctx.exception.details)

    def test_invalid_task(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params({"task": ["gpu"]})
        self.assertIn("task", ctx.exception.details)

    def test_delay_out_of_range(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params({"task": ["io"], "delay_ms": ["1001"]})
        self.assertIn("delay_ms", ctx.exception.details)


class RunBenchmarkTaskTests(unittest.TestCase):
    # io behavior is E2E-only: it makes real HTTP round-trips to /api/slow, so it needs a
    # live server (see the endpoint tests). Only the cpu response shape is unit-checkable.
    def test_cpu_response_adds_task_keeps_n(self):
        result = run_benchmark(2, task="cpu", n=SMALL_N)
        self.assertEqual(result["task"], "cpu")
        self.assertIn("n", result)
        self.assertNotIn("delay_ms", result)


class BenchmarkEndpointE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bench_test_")
        repo = TaskRepository(os.path.join(self.tmpdir, "tasks.db"))
        self.server = make_server(
            "127.0.0.1", 0, cors_origin="http://localhost:5500", repo=repo
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def get(self, path):
        conn = HTTPConnection("127.0.0.1", self.port)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            raw = resp.read()
            return resp, json.loads(raw) if raw else None
        finally:
            conn.close()

    def test_benchmark_endpoint_ok(self):
        resp, payload = self.get(f"/api/benchmark?workers=2&n={SMALL_N}")
        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertEqual(payload["checksum"], PI_10000)
        self.assertEqual(payload["workers"], 2)
        self.assertEqual(payload["n"], SMALL_N)
        self.assertEqual(payload["gil_enabled"], sys._is_gil_enabled())
        self.assertEqual(
            set(payload["results_ms"]), {"sequential", "threads", "interpreters"}
        )

    def test_benchmark_invalid_workers_422(self):
        resp, payload = self.get("/api/benchmark?workers=99")
        self.assertEqual(resp.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertEqual(payload["error"]["code"], "validation_error")
        self.assertIn("workers", payload["error"]["details"])

    def test_io_endpoint_scales(self):
        # Real HTTP: each worker does GET+POST to this server's own /api/slow. Threads
        # overlap because urllib and the sleep both release the GIL.
        resp, payload = self.get("/api/benchmark?task=io&workers=4&delay_ms=20")
        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertEqual(payload["task"], "io")
        self.assertEqual(payload["delay_ms"], 20)
        self.assertEqual(payload["checksum"], 4)  # 4 workers completed both round-trips
        self.assertNotIn("n", payload)
        self.assertLess(
            payload["results_ms"]["threads"], payload["results_ms"]["sequential"] / 3
        )

    def test_slow_endpoint_get_and_post(self):
        for method, path in (("GET", "/api/slow?ms=5"), ("POST", "/api/slow?ms=5")):
            conn = HTTPConnection("127.0.0.1", self.port)
            try:
                conn.request(method, path)
                resp = conn.getresponse()
                payload = json.loads(resp.read())
            finally:
                conn.close()
            self.assertEqual(resp.status, HTTPStatus.OK)
            self.assertEqual(payload, {"ok": True, "ms": 5})

    def test_io_rejects_n_422(self):
        resp, payload = self.get("/api/benchmark?task=io&n=200000")
        self.assertEqual(resp.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertEqual(payload["error"]["details"]["n"], "n only applies to task=cpu")


if __name__ == "__main__":
    unittest.main()
