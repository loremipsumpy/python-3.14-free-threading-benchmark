"""HTTP plumbing: `ThreadingHTTPServer` + handler.

The only module that speaks raw HTTP. Parses the body, calls `router.dispatch`, and is
the **single point** that translates exceptions into JSON responses. Applies the
contract's CORS headers (`Vary: Origin` always; `Access-Control-Allow-Origin` only for
the allowed Origin; preflight headers on `OPTIONS`).
"""

import json
import logging
from http import HTTPMethod, HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from app.errors import ApiError, BadRequestError, MethodNotAllowedError
from app.repository import TaskRepository
from app.router import dispatch

_log = logging.getLogger("app.server")

_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_PREFLIGHT_METHODS = "GET, POST, PATCH, DELETE, OPTIONS"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._handle(HTTPMethod.GET)

    def do_POST(self) -> None:
        self._handle(HTTPMethod.POST)

    def do_PATCH(self) -> None:
        self._handle(HTTPMethod.PATCH)

    def do_DELETE(self) -> None:
        self._handle(HTTPMethod.DELETE)

    def do_OPTIONS(self) -> None:
        self._handle(HTTPMethod.OPTIONS)

    def do_PUT(self) -> None:
        # No route supports PUT ⇒ the router resolves it as 405 (not the default 501).
        self._handle(HTTPMethod.PUT)

    def _handle(self, method: HTTPMethod) -> None:
        is_preflight = method == HTTPMethod.OPTIONS
        try:
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            body = self._read_json_body()
            base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
            status, payload = dispatch(
                str(method), parts.path, query, body, self.server.repo, base_url
            )
            self._respond(status, payload, preflight=is_preflight)
        except ApiError as err:
            self._respond_error(err)
        except Exception:  # noqa: BLE001 - safety net: never leak a traceback to the client
            _log.exception("unhandled error handling %s %s", method, self.path)
            self._respond_error(ApiError())

    def _read_json_body(self) -> object | None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BadRequestError()

    def _respond(self, status: HTTPStatus, payload: object, *, preflight: bool) -> None:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if body:
            self.send_header("Content-Type", _JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        if status == HTTPStatus.CREATED and isinstance(payload, dict):
            self.send_header("Location", f"/api/tasks/{payload['id']}")
        self._send_cors_headers(preflight=preflight)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _respond_error(self, err: ApiError) -> None:
        body = json.dumps(err.to_payload()).encode("utf-8")
        self.send_response(err.status)
        self.send_header("Content-Type", _JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        if isinstance(err, MethodNotAllowedError):
            self.send_header("Allow", ", ".join(err.allowed))
        self._send_cors_headers(preflight=False)
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self, *, preflight: bool) -> None:
        # `Vary: Origin` ALWAYS (the response depends on the Origin).
        self.send_header("Vary", "Origin")
        origin = self.headers.get("Origin")
        if origin is not None and origin == self.server.cors_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        if preflight:
            self.send_header("Access-Control-Allow-Methods", _PREFLIGHT_METHODS)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")

    def log_message(self, format: str, *args: object) -> None:
        _log.info("%s - %s", self.address_string(), format % args)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # socketserver's default listen backlog is 5; the io benchmark opens up to 32
    # concurrent /api/slow connections (one per worker) plus margin, so a small backlog
    # overflows and TCP retransmits spike latency (~82ms to ~1000ms).
    request_queue_size = 128

    def __init__(self, server_address, handler_class, *, cors_origin: str, repo: TaskRepository) -> None:
        super().__init__(server_address, handler_class)
        self.cors_origin = cors_origin
        self.repo = repo


def make_server(host: str, port: int, *, cors_origin: str, repo: TaskRepository) -> _Server:
    return _Server((host, port), _Handler, cors_origin=cors_origin, repo=repo)
