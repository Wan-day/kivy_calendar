"""Reusable result types for returning failures across module boundaries.

Backend code should return a :class:`Result` for expected failures (missing
rows, storage errors, rate limits, ...) instead of raising exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable machine-readable error codes shared by backend modules."""

    INVALID_ARGUMENT = "invalid_argument"
    INVALID_EVENT = "invalid_event"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    INVALID_STATE = "invalid_state"
    STORAGE_ERROR = "storage_error"


@dataclass(frozen=True, slots=True)
class Error:
    """A failure returned from a backend operation."""

    code: ErrorCode
    message: str = ""


@dataclass(frozen=True, slots=True)
class Result[T]:
    """Either a successful value or an error, never both."""

    value: T | None = None
    error: Error | None = None

    @classmethod
    def ok(cls, value: T) -> Result[T]:
        """Return a successful result carrying ``value``."""
        return cls(value=value)

    @classmethod
    def fail(cls, code: ErrorCode, message: str = "") -> Result[T]:
        """Return a failed result carrying an error code and message."""
        return cls(error=Error(code=code, message=message))

    @property
    def is_ok(self) -> bool:
        """Whether the operation succeeded."""
        return self.error is None

    @property
    def is_error(self) -> bool:
        """Whether the operation failed."""
        return self.error is not None
