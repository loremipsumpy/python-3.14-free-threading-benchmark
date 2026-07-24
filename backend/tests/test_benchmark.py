"""Tests for the 3.14 concurrency benchmark.

Uses a small `n` (10000) to keep the suite fast. Timings are **not** asserted (at
small `n` subinterpreter startup dominates ⇒ it would be flaky); only checksum
correctness and parameter validation.
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
    def test_defaults(self):
        self.assertEqual(parse_params(None, None), (4, 200000))

    def test_valid_values(self):
        self.assertEqual(parse_params("6", "10000"), (6, 10000))

    def test_workers_boundary_32_ok(self):
        self.assertEqual(parse_params("32", None), (32, 200000))

    def test_workers_out_of_range_high(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params("33", None)
        self.assertIn("workers", ctx.exception.details)
        self.assertIn("[1, 32]", ctx.exception.details["workers"])

    def test_workers_out_of_range_low(self):
        with self.assertRaises(ValidationError):
            parse_params("0", None)

    def test_n_too_small(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params(None, "5000")
        self.assertIn("n", ctx.exception.details)

    def test_n_too_large(self):
        with self.assertRaises(ValidationError):
            parse_params(None, "6000000")

    def test_non_numeric(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_params("abc", None)
        self.assertIn("workers", ctx.exception.details)


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


if __name__ == "__main__":
    unittest.main()
