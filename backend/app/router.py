"""CRUD dispatch: `(method, path, query, body, repo, base_url)` → `(status, payload)`.

Knows nothing about raw HTTP or SQL. Routes with structural `match/case` over
`(method, segments)`. On success returns `(HTTPStatus, payload)`; on error **raises**
an `ApiError` (`server.py` is the single point that translates it to an HTTP response).
`base_url` is the server's own address, needed by the io benchmark to call `/api/slow`.
"""

import platform
import sys
from http import HTTPStatus

from app.benchmark import (
    DEFAULT_BASE_URL,
    parse_params,
    parse_slow_ms,
    run_benchmark,
    run_slow,
)
from app.errors import MethodNotAllowedError, NotFoundError, ValidationError
from app.models import Task, TaskStatus
from app.repository import TaskRepository

type Segments = tuple[str, ...]
type Query = dict[str, list[str]]
type Body = object | None
type Dispatched = tuple[HTTPStatus, object]


def _health() -> dict[str, object]:
    return {
        "status": "ok",
        "gil_enabled": sys._is_gil_enabled(),
        "python": platform.python_version(),
    }


def _allowed_methods(segments: Segments) -> list[str] | None:
    match segments:
        case ("api", "health"):
            return ["GET", "OPTIONS"]
        case ("api", "tasks"):
            return ["GET", "POST", "OPTIONS"]
        case ("api", "tasks", _):
            return ["GET", "PATCH", "DELETE", "OPTIONS"]
        case ("api", "benchmark"):
            return ["GET", "OPTIONS"]
        case ("api", "slow"):
            return ["GET", "POST", "OPTIONS"]
        case _:
            return None


def _status_filter(query: Query) -> TaskStatus | None:
    values = query.get("status")
    if not values:
        return None
    try:
        return TaskStatus(values[0])
    except (ValueError, TypeError):
        raise ValidationError({"status": "must be one of: pending, in_progress, done"})


def dispatch(method: str, path: str, query: Query, body: Body, repo: TaskRepository,
             base_url: str = DEFAULT_BASE_URL) -> Dispatched:
    segments = tuple(part for part in path.split("/") if part)

    match (method, segments):
        case ("GET", ("api", "health")):
            return HTTPStatus.OK, _health()

        case ("OPTIONS", ("api", *_)):
            return HTTPStatus.NO_CONTENT, None

        case ("GET", ("api", "tasks")):
            tasks = repo.list_tasks(_status_filter(query))
            return HTTPStatus.OK, [t.to_dict() for t in tasks]

        case ("POST", ("api", "tasks")):
            task = repo.create(Task.create(body))
            return HTTPStatus.CREATED, task.to_dict()

        case ("GET", ("api", "tasks", task_id)):
            return HTTPStatus.OK, repo.get(task_id).to_dict()

        case ("PATCH", ("api", "tasks", task_id)):
            return HTTPStatus.OK, repo.update(task_id, body).to_dict()

        case ("DELETE", ("api", "tasks", task_id)):
            repo.delete(task_id)
            return HTTPStatus.NO_CONTENT, None

        case ("GET", ("api", "benchmark")):
            return HTTPStatus.OK, run_benchmark(**parse_params(query), base_url=base_url)

        case ("GET" | "POST", ("api", "slow")):
            return HTTPStatus.OK, run_slow(parse_slow_ms(query))

        case _:
            allowed = _allowed_methods(segments)
            if allowed is None:
                raise NotFoundError()
            raise MethodNotAllowedError(allowed)
