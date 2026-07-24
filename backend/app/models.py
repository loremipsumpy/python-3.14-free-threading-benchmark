"""Pure domain: `Task`, its enums (`TaskStatus`/`Priority`), and payload validation
and serialization. No HTTP or SQL dependencies.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from app.errors import ValidationError

TITLE_ERROR = "required, 1-200 chars"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _validate(payload: object, *, require_title: bool) -> dict[str, object]:
    """Validate a POST/PATCH payload and return only the provided fields, already
    normalized. Accumulates **all** errors in `details` (one per field) instead of
    failing on the first. `require_title` distinguishes create from PATCH.
    """
    if not isinstance(payload, dict):
        raise ValidationError({"body": "expected a JSON object"})

    details: dict[str, str] = {}
    cleaned: dict[str, object] = {}

    for key, value in payload.items():
        match key:
            case "title":
                if isinstance(value, str) and 1 <= len(value.strip()) <= 200:
                    cleaned["title"] = value.strip()
                else:
                    details["title"] = TITLE_ERROR
            case "description":
                if isinstance(value, str):
                    cleaned["description"] = value
                else:
                    details["description"] = "must be a string"
            case "status":
                try:
                    cleaned["status"] = TaskStatus(value)
                except (ValueError, TypeError):
                    details["status"] = "must be one of: pending, in_progress, done"
            case "priority":
                try:
                    cleaned["priority"] = Priority(value)
                except (ValueError, TypeError):
                    details["priority"] = "must be one of: low, medium, high"
            case _:
                details[key] = "unknown field"

    if require_title and "title" not in payload:
        details["title"] = TITLE_ERROR

    if details:
        raise ValidationError(details)
    return cleaned


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True, kw_only=True)
class Task:
    id: str
    title: str
    description: str
    status: TaskStatus
    priority: Priority
    created_at: str
    updated_at: str

    @classmethod
    def create(cls, payload: object) -> Self:
        cleaned = _validate(payload, require_title=True)
        now = _now()
        return cls(
            id=str(uuid.uuid7()),
            title=cleaned["title"],
            description=cleaned.get("description", ""),
            status=cleaned.get("status", TaskStatus.PENDING),
            priority=cleaned.get("priority", Priority.MEDIUM),
            created_at=now,
            updated_at=now,
        )

    def patched(self, payload: object) -> Self:
        if isinstance(payload, dict) and not payload:
            raise ValidationError({"body": "must be a non-empty object"})
        cleaned = _validate(payload, require_title=False)
        return replace(self, **cleaned, updated_at=_now())

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Self:
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=TaskStatus(data["status"]),
            priority=Priority(data["priority"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )
