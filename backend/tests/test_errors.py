"""Tests for the error hierarchy."""

import unittest
from http import HTTPStatus

from app.errors import (
    ApiError,
    BadRequestError,
    MethodNotAllowedError,
    NotFoundError,
    ValidationError,
)


class ErrorHierarchyTests(unittest.TestCase):
    def test_all_are_api_errors_and_exceptions(self):
        for cls in (
            NotFoundError,
            BadRequestError,
        ):
            self.assertTrue(issubclass(cls, ApiError))
            self.assertTrue(issubclass(cls, Exception))

    def test_not_found(self):
        err = NotFoundError()
        self.assertEqual(err.status, HTTPStatus.NOT_FOUND)
        self.assertEqual(err.code, "not_found")
        self.assertEqual(err.to_payload(), {"error": {"code": "not_found", "message": err.message}})
        self.assertNotIn("details", err.to_payload()["error"])

    def test_bad_request(self):
        err = BadRequestError()
        self.assertEqual(err.status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(err.code, "bad_request")

    def test_validation_carries_details(self):
        err = ValidationError({"title": "required, 1-200 chars"})
        self.assertEqual(err.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertEqual(err.code, "validation_error")
        self.assertEqual(
            err.to_payload(),
            {
                "error": {
                    "code": "validation_error",
                    "message": err.message,
                    "details": {"title": "required, 1-200 chars"},
                }
            },
        )

    def test_method_not_allowed_keeps_allowed(self):
        err = MethodNotAllowedError(["GET", "POST"])
        self.assertEqual(err.status, HTTPStatus.METHOD_NOT_ALLOWED)
        self.assertEqual(err.code, "method_not_allowed")
        self.assertEqual(err.allowed, ["GET", "POST"])

    def test_raisable_and_catchable_as_api_error(self):
        with self.assertRaises(ApiError):
            raise ValidationError({"x": "bad"})


if __name__ == "__main__":
    unittest.main()
