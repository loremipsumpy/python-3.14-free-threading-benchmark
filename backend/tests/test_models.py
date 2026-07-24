"""Domain tests: Task, payload validation, serialization."""

import unittest
import uuid
from datetime import datetime

from app.errors import ValidationError
from app.models import Priority, Task, TaskStatus

OLD = "2020-01-01T00:00:00+00:00"


def make_task(**over):
    base = dict(
        id=str(uuid.uuid7()),
        title="orig",
        description="d",
        status="pending",
        priority="medium",
        created_at=OLD,
        updated_at=OLD,
    )
    base.update(over)
    return Task.from_dict(base)


class TaskCreateTests(unittest.TestCase):
    def test_minimal_applies_defaults(self):
        t = Task.create({"title": "Buy coffee"})

        self.assertEqual(t.title, "Buy coffee")
        self.assertEqual(t.description, "")
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertEqual(t.priority, Priority.MEDIUM)
        self.assertEqual(t.created_at, t.updated_at)
        self.assertEqual(uuid.UUID(t.id).version, 7)
        datetime.fromisoformat(t.created_at)

    def test_full_payload(self):
        t = Task.create(
            {
                "title": "  with spaces  ",
                "description": "desc",
                "status": "in_progress",
                "priority": "high",
            }
        )
        self.assertEqual(t.title, "with spaces")
        self.assertEqual(t.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(t.priority, Priority.HIGH)

    def test_missing_title(self):
        with self.assertRaises(ValidationError) as ctx:
            Task.create({"description": "x"})
        self.assertIn("title", ctx.exception.details)

    def test_blank_title(self):
        with self.assertRaises(ValidationError):
            Task.create({"title": "   "})

    def test_title_too_long(self):
        with self.assertRaises(ValidationError):
            Task.create({"title": "x" * 201})

    def test_title_exactly_200_ok(self):
        t = Task.create({"title": "x" * 200})
        self.assertEqual(len(t.title), 200)

    def test_title_not_a_string(self):
        with self.assertRaises(ValidationError):
            Task.create({"title": 123})

    def test_unknown_field(self):
        with self.assertRaises(ValidationError) as ctx:
            Task.create({"title": "ok", "bogus": 1})
        self.assertEqual(ctx.exception.details.get("bogus"), "unknown field")

    def test_invalid_status(self):
        with self.assertRaises(ValidationError) as ctx:
            Task.create({"title": "ok", "status": "nope"})
        self.assertIn("status", ctx.exception.details)

    def test_invalid_priority(self):
        with self.assertRaises(ValidationError):
            Task.create({"title": "ok", "priority": "urgent"})

    def test_null_description_rejected(self):
        # explicit null ⇒ 422 (not normalized to "").
        with self.assertRaises(ValidationError) as ctx:
            Task.create({"title": "ok", "description": None})
        self.assertIn("description", ctx.exception.details)


class TaskPatchTests(unittest.TestCase):
    def test_patch_updates_field_and_timestamp(self):
        t = make_task()
        patched = t.patched({"status": "done"})

        self.assertEqual(patched.status, TaskStatus.DONE)
        self.assertEqual(patched.title, "orig")
        self.assertEqual(patched.created_at, OLD)
        self.assertGreater(
            datetime.fromisoformat(patched.updated_at),
            datetime.fromisoformat(OLD),
        )

    def test_patch_empty_body(self):
        with self.assertRaises(ValidationError):
            make_task().patched({})

    def test_patch_unknown_field(self):
        with self.assertRaises(ValidationError) as ctx:
            make_task().patched({"bogus": 1})
        self.assertEqual(ctx.exception.details.get("bogus"), "unknown field")

    def test_patch_invalid_value(self):
        with self.assertRaises(ValidationError):
            make_task().patched({"priority": "nope"})


class TaskSerializationTests(unittest.TestCase):
    def test_to_dict_shape_and_plain_types(self):
        t = Task.create({"title": "T", "status": "done"})
        d = t.to_dict()

        self.assertEqual(
            set(d),
            {"id", "title", "description", "status", "priority", "created_at", "updated_at"},
        )
        self.assertEqual(d["status"], "done")
        self.assertIsInstance(d["status"], str)
        self.assertNotIsInstance(d["status"], TaskStatus)  # plain value, not an enum

    def test_round_trip_from_dict(self):
        t = Task.create({"title": "T", "priority": "high"})
        self.assertEqual(Task.from_dict(t.to_dict()), t)


if __name__ == "__main__":
    unittest.main()
