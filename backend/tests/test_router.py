"""Router tests: pure CRUD dispatch (no HTTP), with a temporary sqlite repo.

`dispatch(method, path, query, body, repo)`: on error **raises** `ApiError`, on
success returns `(status, payload)`.
"""

import os
import platform
import shutil
import sys
import tempfile
import unittest
from http import HTTPStatus

from app.errors import (
    MethodNotAllowedError,
    NotFoundError,
    ValidationError,
)
from app.repository import TaskRepository
from app.router import dispatch


class RouterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="router_test_")
        self.repo = TaskRepository(os.path.join(self.tmpdir, "tasks.db"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def go(self, method, path, *, query=None, body=None):
        return dispatch(method, path, query or {}, body, self.repo)


class HealthRouteTests(RouterTestCase):
    def test_health_payload(self):
        status, payload = self.go("GET", "/api/health")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(
            payload,
            {
                "status": "ok",
                "gil_enabled": sys._is_gil_enabled(),
                "python": platform.python_version(),
            },
        )


class NotFoundAndMethodTests(RouterTestCase):
    def test_unknown_route_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.go("GET", "/api/nope")

    def test_wrong_method_on_collection_raises_405(self):
        with self.assertRaises(MethodNotAllowedError) as ctx:
            self.go("DELETE", "/api/tasks")
        self.assertEqual(ctx.exception.allowed, ["GET", "POST", "OPTIONS"])

    def test_wrong_method_on_item_raises_405(self):
        with self.assertRaises(MethodNotAllowedError) as ctx:
            self.go("POST", "/api/tasks/abc")
        self.assertEqual(ctx.exception.allowed, ["GET", "PATCH", "DELETE", "OPTIONS"])

    def test_options_preflight_returns_204(self):
        status, payload = self.go("OPTIONS", "/api/tasks")
        self.assertEqual(status, HTTPStatus.NO_CONTENT)
        self.assertIsNone(payload)


class TaskCrudRouteTests(RouterTestCase):
    def _create(self, **body):
        body.setdefault("title", "T")
        status, payload = self.go("POST", "/api/tasks", body=body)
        self.assertEqual(status, HTTPStatus.CREATED)
        return payload

    def test_list_empty(self):
        status, payload = self.go("GET", "/api/tasks")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload, [])

    def test_create_returns_201_and_full_task(self):
        payload = self._create(title="hello", priority="high")
        self.assertEqual(payload["title"], "hello")
        self.assertEqual(payload["priority"], "high")
        self.assertEqual(payload["status"], "pending")
        self.assertIn("id", payload)

    def test_create_invalid_raises_422(self):
        with self.assertRaises(ValidationError):
            self.go("POST", "/api/tasks", body={"description": "no title"})

    def test_create_null_field_raises_422(self):
        with self.assertRaises(ValidationError):
            self.go("POST", "/api/tasks", body={"title": "ok", "description": None})

    def test_get_existing(self):
        created = self._create(title="x")
        status, payload = self.go("GET", f"/api/tasks/{created['id']}")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["id"], created["id"])

    def test_get_missing_raises_404(self):
        with self.assertRaises(NotFoundError):
            self.go("GET", "/api/tasks/does-not-exist")

    def test_list_filtered_by_status(self):
        self._create(title="p", status="pending")
        self._create(title="d", status="done")
        status, payload = self.go(
            "GET", "/api/tasks", query={"status": ["done"]}
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual([t["title"] for t in payload], ["d"])

    def test_list_invalid_status_raises_422(self):
        with self.assertRaises(ValidationError) as ctx:
            self.go("GET", "/api/tasks", query={"status": ["bogus"]})
        self.assertIn("status", ctx.exception.details)

    def test_patch_existing(self):
        created = self._create(title="orig")
        status, payload = self.go(
            "PATCH", f"/api/tasks/{created['id']}", body={"status": "done"}
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["status"], "done")

    def test_patch_missing_raises_404(self):
        with self.assertRaises(NotFoundError):
            self.go("PATCH", "/api/tasks/nope", body={"status": "done"})

    def test_delete_existing_returns_204(self):
        created = self._create()
        status, payload = self.go("DELETE", f"/api/tasks/{created['id']}")
        self.assertEqual(status, HTTPStatus.NO_CONTENT)
        self.assertIsNone(payload)

    def test_delete_missing_raises_404(self):
        with self.assertRaises(NotFoundError):
            self.go("DELETE", "/api/tasks/nope")


if __name__ == "__main__":
    unittest.main()
