"""Tests for startup: command-line argument parsing."""

import unittest

from app.__main__ import parse_args


class ParseArgsTests(unittest.TestCase):
    def test_defaults(self):
        args = parse_args([])

        self.assertEqual(args.host, "localhost")
        self.assertEqual(args.port, 8000)
        self.assertEqual(args.db, "tasks.db")
        self.assertEqual(args.cors_origin, "http://localhost:5500")

    def test_overrides(self):
        args = parse_args(
            [
                "--host", "0.0.0.0",
                "--port", "9001",
                "--db", "/tmp/t.db",
                "--cors-origin", "http://x:1",
            ]
        )

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9001)
        self.assertEqual(args.db, "/tmp/t.db")
        self.assertEqual(args.cors_origin, "http://x:1")


if __name__ == "__main__":
    unittest.main()
