"""E2E integration tests: real HTTP server + http.client against the contract."""

import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import unittest
from http import HTTPStatus
from http.client import HTTPConnection

from app.repository import TaskRepository
from app.server import make_server

CORS_ORIGIN = "http://localhost:5500"


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="api_test_")
        repo = TaskRepository(os.path.join(self.tmpdir, "tasks.db"))
        self.server = make_server("127.0.0.1", 0, cors_origin=CORS_ORIGIN, repo=repo)
        self.port = self.server.server_address[1]
        # low poll_interval ⇒ shutdown() near-instant in tearDown (doesn't hang the suite).
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port)
        try:
            hdrs = dict(headers or {})
            payload = None
            if body is not None:
                if isinstance(body, (bytes, str)):
                    payload = body  # raw (e.g. broken JSON)
                else:
                    payload = json.dumps(body)
                    hdrs.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            return resp, raw
        finally:
            conn.close()

    @staticmethod
    def json_body(raw):
        return json.loads(raw) if raw else None


class HealthEndpointTests(ApiTestCase):
    def test_health_ok(self):
        resp, raw = self.request("GET", "/api/health")
        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertEqual(resp.getheader("Content-Type"), "application/json; charset=utf-8")
        self.assertEqual(
            self.json_body(raw),
            {
                "status": "ok",
                "gil_enabled": sys._is_gil_enabled(),
                "python": platform.python_version(),
            },
        )

    def test_cors_header_present_for_allowed_origin(self):
        resp, _ = self.request("GET", "/api/health", headers={"Origin": CORS_ORIGIN})
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), CORS_ORIGIN)
        self.assertEqual(resp.getheader("Vary"), "Origin")

    def test_vary_always_present_without_origin(self):
        resp, _ = self.request("GET", "/api/health")
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        self.assertEqual(resp.getheader("Vary"), "Origin")

    def test_vary_present_but_no_acao_for_disallowed_origin(self):
        resp, _ = self.request(
            "GET", "/api/health", headers={"Origin": "http://evil.example"}
        )
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        self.assertEqual(resp.getheader("Vary"), "Origin")


class TaskLifecycleE2ETests(ApiTestCase):
    """Full CRUD lifecycle: POST → GET → PATCH → DELETE → 404."""

    def test_full_crud_lifecycle(self):
        resp, raw = self.request(
            "POST", "/api/tasks", body={"title": "Buy coffee", "priority": "high"}
        )
        self.assertEqual(resp.status, HTTPStatus.CREATED)
        task = self.json_body(raw)
        tid = task["id"]
        self.assertEqual(resp.getheader("Location"), f"/api/tasks/{tid}")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["priority"], "high")

        resp, raw = self.request("GET", "/api/tasks")
        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertIn(tid, [t["id"] for t in self.json_body(raw)])

        resp, raw = self.request("GET", f"/api/tasks/{tid}")
        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertEqual(self.json_body(raw)["id"], tid)

        resp, raw = self.request("PATCH", f"/api/tasks/{tid}", body={"status": "done"})
        self.assertEqual(resp.status, HTTPStatus.OK)
        patched = self.json_body(raw)
        self.assertEqual(patched["status"], "done")
        self.assertNotEqual(patched["updated_at"], task["updated_at"])
        self.assertEqual(patched["created_at"], task["created_at"])

        resp, raw = self.request("DELETE", f"/api/tasks/{tid}")
        self.assertEqual(resp.status, HTTPStatus.NO_CONTENT)
        self.assertEqual(raw, b"")

        resp, raw = self.request("GET", f"/api/tasks/{tid}")
        self.assertEqual(resp.status, HTTPStatus.NOT_FOUND)
        self.assertEqual(self.json_body(raw)["error"]["code"], "not_found")

    def test_list_filter_by_status(self):
        self.request("POST", "/api/tasks", body={"title": "p", "status": "pending"})
        self.request("POST", "/api/tasks", body={"title": "d", "status": "done"})
        resp, raw = self.request("GET", "/api/tasks?status=done")
        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertEqual([t["title"] for t in self.json_body(raw)], ["d"])

    def test_invalid_status_filter_422(self):
        resp, raw = self.request("GET", "/api/tasks?status=bogus")
        self.assertEqual(resp.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertEqual(self.json_body(raw)["error"]["code"], "validation_error")


class ErrorContractTests(ApiTestCase):
    def test_malformed_json_400(self):
        resp, raw = self.request(
            "POST", "/api/tasks", body="{not valid json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(self.json_body(raw)["error"]["code"], "bad_request")

    def test_null_field_422(self):
        resp, raw = self.request(
            "POST", "/api/tasks", body={"title": "ok", "description": None}
        )
        self.assertEqual(resp.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        payload = self.json_body(raw)
        self.assertEqual(payload["error"]["code"], "validation_error")
        self.assertIn("description", payload["error"]["details"])

    def test_missing_title_422(self):
        resp, raw = self.request("POST", "/api/tasks", body={"description": "x"})
        self.assertEqual(resp.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("title", self.json_body(raw)["error"]["details"])

    def test_unknown_route_404(self):
        resp, raw = self.request("GET", "/api/nope")
        self.assertEqual(resp.status, HTTPStatus.NOT_FOUND)
        self.assertEqual(self.json_body(raw)["error"]["code"], "not_found")

    def test_method_not_allowed_405_with_allow_header(self):
        # DELETE on the collection is not allowed.
        resp, raw = self.request("DELETE", "/api/tasks")
        self.assertEqual(resp.status, HTTPStatus.METHOD_NOT_ALLOWED)
        self.assertEqual(resp.getheader("Allow"), "GET, POST, OPTIONS")
        self.assertEqual(self.json_body(raw)["error"]["code"], "method_not_allowed")

    def test_method_not_allowed_on_item(self):
        resp, _ = self.request("POST", "/api/tasks/abc")
        self.assertEqual(resp.status, HTTPStatus.METHOD_NOT_ALLOWED)
        self.assertEqual(resp.getheader("Allow"), "GET, PATCH, DELETE, OPTIONS")

    def test_put_gives_405_not_501(self):
        resp, _ = self.request("PUT", "/api/tasks/abc")
        self.assertEqual(resp.status, HTTPStatus.METHOD_NOT_ALLOWED)


class PreflightCorsTests(ApiTestCase):
    def test_preflight_options_headers_exact(self):
        resp, raw = self.request(
            "OPTIONS", "/api/tasks", headers={"Origin": CORS_ORIGIN}
        )
        self.assertEqual(resp.status, HTTPStatus.NO_CONTENT)
        self.assertEqual(raw, b"")
        self.assertEqual(resp.getheader("Vary"), "Origin")
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), CORS_ORIGIN)
        self.assertEqual(
            resp.getheader("Access-Control-Allow-Methods"),
            "GET, POST, PATCH, DELETE, OPTIONS",
        )
        self.assertEqual(resp.getheader("Access-Control-Allow-Headers"), "Content-Type")
        self.assertEqual(resp.getheader("Access-Control-Max-Age"), "86400")

    def test_preflight_without_origin_still_has_methods_but_no_acao(self):
        resp, _ = self.request("OPTIONS", "/api/tasks")
        self.assertEqual(resp.status, HTTPStatus.NO_CONTENT)
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        self.assertEqual(resp.getheader("Vary"), "Origin")
        self.assertEqual(
            resp.getheader("Access-Control-Allow-Methods"),
            "GET, POST, PATCH, DELETE, OPTIONS",
        )


class ServerConfigTests(ApiTestCase):
    def test_request_queue_size_raised_for_concurrent_io(self):
        # Default socketserver backlog is 5; the io benchmark opens up to 32 concurrent
        # /api/slow connections. Behavioral proof is the live io run; here we guard the
        # value (a timing-based concurrency assertion would be flaky in CI).
        self.assertEqual(self.server.request_queue_size, 128)


if __name__ == "__main__":
    unittest.main()
