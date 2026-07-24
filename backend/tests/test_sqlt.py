"""Tests for the t-string helper (PEP 750, https://peps.python.org/pep-0750/) → parameterized (sql, params)."""

import sqlite3
import unittest

from app.sqlt import sql


class SqltTests(unittest.TestCase):
    def test_single_interpolation_becomes_placeholder(self):
        tid = "42"
        text, params = sql(t"SELECT * FROM tasks WHERE id = {tid}")

        self.assertEqual(text, "SELECT * FROM tasks WHERE id = ?")
        self.assertEqual(params, ["42"])

    def test_no_interpolation(self):
        text, params = sql(t"SELECT 1")

        self.assertEqual(text, "SELECT 1")
        self.assertEqual(params, [])

    def test_multiple_interpolations_preserve_order(self):
        a, b = "one", "two"
        text, params = sql(t"WHERE x = {a} AND y = {b}")

        self.assertEqual(text, "WHERE x = ? AND y = ?")
        self.assertEqual(params, ["one", "two"])

    def test_injection_stays_a_single_param(self):
        evil = "'; DROP TABLE tasks;--"
        text, params = sql(t"SELECT * FROM tasks WHERE id = {evil}")

        # The SQL text doesn't contain the payload: it travels as a parameter, not inline.
        self.assertEqual(text, "SELECT * FROM tasks WHERE id = ?")
        self.assertEqual(params, [evil])
        self.assertNotIn("DROP", text)

    def test_params_are_usable_by_sqlite3(self):
        # Smoke test: the (sql, params) actually works against sqlite3.
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE tasks(id TEXT)")
            conn.execute("INSERT INTO tasks(id) VALUES('42')")
            evil = "'; DROP TABLE tasks;--"
            text, params = sql(t"SELECT id FROM tasks WHERE id = {evil}")
            rows = conn.execute(text, params).fetchall()
            self.assertEqual(rows, [])  # no match; the table is still alive
            self.assertEqual(
                conn.execute("SELECT count(*) FROM tasks").fetchone()[0], 1
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
