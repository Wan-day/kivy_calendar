"""FastAPI-facing error helpers for the backend API."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from core.errors import Error, ErrorCode, Result

_ERROR_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_ARGUMENT: 400,
    ErrorCode.INVALID_EVENT: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.ALREADY_EXISTS: 409,
    ErrorCode.INVALID_STATE: 409,
    ErrorCode.STORAGE_ERROR: 500,
    ErrorCode.UPSTREAM_ERROR: 503,
    ErrorCode.AUTH_ERROR: 401,
}


class ApiError(Exception):
    """An expected backend error translated into an HTTP response."""

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        """Create the HTTP-facing error."""
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_status(error: Error) -> int:
    """Map a backend error code to an HTTP status code."""
    return _ERROR_STATUS[error.code]


def ensure_ok[T](result: Result[T], status_code: int | None = None) -> None:
    """Raise :class:`ApiError` from a failed backend ``Result``."""
    if not result.is_error:
        return
    error = result.error
    if error is None:  # pragma: no cover - defensive
        raise RuntimeError("result failed without an error")
    resolved = status_code if status_code is not None else error_status(error)
    raise ApiError(resolved, error.code, error.message)


def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Return a structured JSON error response for :class:`ApiError`."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code.value, "message": exc.message}},
    )
