"""`Task` persistence over sqlite3, thread-safe.

One connection **per thread** (`threading.local`) because sqlite3 objects don't cross
threads and `ThreadingHTTPServer` uses one thread per request. All SQL is built with
`sqlt` (t-strings) ⇒ *values* always travel parameterized; *identifiers* (columns) are
static template text. `autocommit=True` (3.12): writes are single-statement, atomic per
statement, so the `PRAGMA journal_mode=WAL` doesn't run inside an implicit transaction.
"""

import sqlite3
import threading

from app.errors import NotFoundError
from app.models import Task, TaskStatus
from app.sqlt import sql

type Row = sqlite3.Row

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL,
    priority    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""


def _row_to_task(row: Row) -> Task:
    return Task.from_dict(dict(row))


class TaskRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, autocommit=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(_SCHEMA)
            self._local.conn = conn
        return conn

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        conn = self._conn()
        if status is None:
            query, params = sql(t"SELECT * FROM tasks ORDER BY id DESC")
        else:
            value = status.value
            query, params = sql(
                t"SELECT * FROM tasks WHERE status = {value} ORDER BY id DESC"
            )
        return [_row_to_task(row) for row in conn.execute(query, params).fetchall()]

    def get(self, task_id: str) -> Task:
        conn = self._conn()
        query, params = sql(t"SELECT * FROM tasks WHERE id = {task_id}")
        row = conn.execute(query, params).fetchone()
        if row is None:
            raise NotFoundError()
        return _row_to_task(row)

    def create(self, task: Task) -> Task:
        conn = self._conn()
        # Columns = static text (identifiers); values = interpolated (parameters).
        query, params = sql(
            t"INSERT INTO tasks "
            t"(id, title, description, status, priority, created_at, updated_at) "
            t"VALUES ({task.id}, {task.title}, {task.description}, {task.status.value}, "
            t"{task.priority.value}, {task.created_at}, {task.updated_at})"
        )
        conn.execute(query, params)
        return task

    def update(self, task_id: str, payload: object) -> Task:
        # Precedence: 404 (exists?) before 422 (payload valid?).
        current = self.get(task_id)
        updated = current.patched(payload)
        conn = self._conn()
        query, params = sql(
            t"UPDATE tasks SET title = {updated.title}, "
            t"description = {updated.description}, status = {updated.status.value}, "
            t"priority = {updated.priority.value}, updated_at = {updated.updated_at} "
            t"WHERE id = {task_id}"
        )
        conn.execute(query, params)
        return updated

    def delete(self, task_id: str) -> None:
        conn = self._conn()
        query, params = sql(t"DELETE FROM tasks WHERE id = {task_id}")
        cursor = conn.execute(query, params)
        if cursor.rowcount == 0:
            raise NotFoundError()
