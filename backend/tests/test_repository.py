"""Tests for the repository over a temporary sqlite3."""

import os
import shutil
import tempfile
import threading
import unittest

from app.errors import NotFoundError
from app.models import Priority, Task, TaskStatus
from app.repository import TaskRepository


class RepositoryTestCase(unittest.TestCase):
    def setUp(self):
        # Fresh temp directory per test (WAL creates -wal/-shm sidecars).
        self.tmpdir = tempfile.mkdtemp(prefix="tasks_test_")
        self.db_path = os.path.join(self.tmpdir, "tasks.db")
        self.repo = TaskRepository(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _new(self, **payload):
        payload.setdefault("title", "T")
        return self.repo.create(Task.create(payload))


class CrudTests(RepositoryTestCase):
    def test_create_then_get_roundtrip(self):
        t = self._new(title="hello", description="d", status="done", priority="high")
        got = self.repo.get(t.id)
        self.assertEqual(got, t)

    def test_get_missing_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.repo.get("nope")

    def test_list_orders_by_id_desc(self):
        a = self._new(title="a")
        b = self._new(title="b")
        c = self._new(title="c")
        ids = [t.id for t in self.repo.list_tasks()]
        # uuid7 is time-ordered ⇒ id DESC = most recent first
        self.assertEqual(ids, sorted([a.id, b.id, c.id], reverse=True))
        self.assertEqual(ids[0], c.id)

    def test_list_filters_by_status(self):
        self._new(title="p1", status="pending")
        self._new(title="d1", status="done")
        self._new(title="p2", status="pending")
        pending = self.repo.list_tasks(status=TaskStatus.PENDING)
        self.assertEqual({t.title for t in pending}, {"p1", "p2"})
        self.assertTrue(all(t.status is TaskStatus.PENDING for t in pending))

    def test_list_empty(self):
        self.assertEqual(self.repo.list_tasks(), [])

    def test_update_applies_patch_and_persists(self):
        t = self._new(title="orig", status="pending")
        updated = self.repo.update(t.id, {"status": "in_progress", "title": "new"})
        self.assertEqual(updated.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(updated.title, "new")
        self.assertEqual(self.repo.get(t.id).title, "new")
        self.assertNotEqual(updated.updated_at, t.updated_at)
        self.assertEqual(updated.created_at, t.created_at)

    def test_update_missing_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.repo.update("nope", {"status": "done"})

    def test_delete_removes_and_returns_none(self):
        t = self._new()
        self.assertIsNone(self.repo.delete(t.id))
        with self.assertRaises(NotFoundError):
            self.repo.get(t.id)

    def test_delete_missing_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.repo.delete("nope")


class ThreadingTests(RepositoryTestCase):
    def test_connection_per_thread(self):
        # Each thread opens its own connection (threading.local); they share the file.
        t = self._new(title="fromMain")
        result = {}

        def worker():
            result["got"] = self.repo.get(t.id).title

        th = threading.Thread(target=worker)
        th.start()
        th.join()
        self.assertEqual(result["got"], "fromMain")


if __name__ == "__main__":
    unittest.main()
