"""API error hierarchy.

Each `ApiError` knows its contract `status` (`HTTPStatus`) and `code`, and serializes
to the normative JSON shape `{"error": {"code", "message", ["details"]}}`. Raised from
`models`/`repository`/`router`; `server.py` translates them to HTTP responses at a
single point.
"""

from http import HTTPStatus


class ApiError(Exception):
    """Base: a domain error carrying a contract status + code."""

    status: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    default_message: str = "internal error"

    def __init__(self, message: str | None = None, *, details: object | None = None) -> None:
        self.message = message if message is not None else self.default_message
        self.details = details
        super().__init__(self.message)

    def to_payload(self) -> dict[str, object]:
        error: dict[str, object] = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


class NotFoundError(ApiError):
    status = HTTPStatus.NOT_FOUND
    code = "not_found"
    default_message = "resource not found"


class ValidationError(ApiError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_error"
    default_message = "invalid task data"

    def __init__(self, details: object, message: str | None = None) -> None:
        super().__init__(message, details=details)


class BadRequestError(ApiError):
    status = HTTPStatus.BAD_REQUEST
    code = "bad_request"
    default_message = "malformed JSON body"


class MethodNotAllowedError(ApiError):
    status = HTTPStatus.METHOD_NOT_ALLOWED
    code = "method_not_allowed"
    default_message = "method not allowed"

    def __init__(self, allowed, message: str | None = None) -> None:
        super().__init__(message)
        self.allowed = list(allowed)
