"""SQLite-backed retry queue scaffolding.

Jobs survive process restarts and are claimed before work is attempted.  This
phase only provides the queue mechanics; actually performing Google Calendar
calls is out of scope.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.errors import ErrorCode, Result
from core.sqlite import Database, run_in_transaction

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY_SECONDS = 30.0
DEFAULT_MAX_DELAY_SECONDS = 3600.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS retry_jobs (
    id TEXT PRIMARY KEY NOT NULL,
    operation TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'in_progress', 'completed', 'failed')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    available_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_retry_jobs_due
    ON retry_jobs (status, available_at);
"""

_COLUMNS = (
    "id",
    "operation",
    "payload",
    "status",
    "attempts",
    "max_attempts",
    "available_at",
    "last_error",
    "created_at",
    "updated_at",
    "claimed_at",
    "completed_at",
)
_COLUMN_LIST = ", ".join(_COLUMNS)
_PLACEHOLDERS = ", ".join("?" for _ in _COLUMNS)
_INSERT = f"INSERT INTO retry_jobs ({_COLUMN_LIST}) VALUES ({_PLACEHOLDERS})"
_DUE_SELECT = (
    f"SELECT {_COLUMN_LIST} FROM retry_jobs "
    "WHERE status = ? AND available_at <= ? "
    "ORDER BY available_at, created_at, id LIMIT ?"
)


class RetryStatus(StrEnum):
    """Lifecycle states of a queued retry job."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RetryJob(BaseModel):
    """A durable unit of work that may be retried after a failure."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: RetryStatus = RetryStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=1)
    available_at: datetime
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("id", "operation")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("retry job id and operation must not be blank")
        return value

    @field_validator(
        "available_at",
        "created_at",
        "updated_at",
        "claimed_at",
        "completed_at",
    )
    @classmethod
    def _timestamps_must_have_timezone(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include time zone information")
        return value


class RetryQueue:
    """Store and process retryable jobs in SQLite."""

    def __init__(
        self,
        database: Database | None = None,
        *,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    ) -> None:
        if base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be positive")
        if max_delay_seconds < base_delay_seconds:
            raise ValueError(
                "max_delay_seconds must be greater than or equal to "
                "base_delay_seconds"
            )
        self._database = database if database is not None else Database()
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds

    @property
    def database(self) -> Database:
        """The database this queue writes to."""
        return self._database

    def enqueue(
        self,
        operation: str,
        payload: dict[str, Any] | None = None,
        *,
        job_id: str | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        available_at: datetime | None = None,
        now: datetime | None = None,
    ) -> Result[RetryJob]:
        """Add a job, due immediately unless ``available_at`` is given."""
        try:
            current_time = _as_utc(now if now is not None else datetime.now(UTC))
            due_at = (
                _as_utc(available_at) if available_at is not None else current_time
            )
            job = RetryJob(
                id=job_id or uuid.uuid4().hex,
                operation=operation,
                payload=_json_payload(payload),
                max_attempts=max_attempts,
                available_at=due_at,
                created_at=current_time,
                updated_at=current_time,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            return Result.fail(ErrorCode.INVALID_ARGUMENT, str(exc))

        def operation_fn(connection: sqlite3.Connection) -> Result[RetryJob]:
            try:
                connection.execute(_INSERT, _job_values(job))
            except sqlite3.IntegrityError:
                return Result.fail(
                    ErrorCode.ALREADY_EXISTS,
                    f"retry job {job.id!r} already exists",
                )
            return Result.ok(job)

        return run_in_transaction(self._database, _SCHEMA, operation_fn)

    def get(self, job_id: str) -> Result[RetryJob]:
        """Return one job by id."""

        def operation(connection: sqlite3.Connection) -> Result[RetryJob]:
            row = _find_job(connection, job_id)
            if row is None:
                return _not_found(job_id)
            return Result.ok(_row_to_job(row))

        return run_in_transaction(self._database, _SCHEMA, operation)

    def list_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 10,
    ) -> Result[list[RetryJob]]:
        """List pending jobs whose retry time has arrived, without claiming."""
        try:
            current_time = _as_utc(now if now is not None else datetime.now(UTC))
        except ValueError as exc:
            return Result.fail(ErrorCode.INVALID_ARGUMENT, str(exc))
        if limit < 1:
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT,
                "limit must be at least 1",
            )

        def operation(connection: sqlite3.Connection) -> Result[list[RetryJob]]:
            rows = connection.execute(
                _DUE_SELECT,
                (
                    RetryStatus.PENDING.value,
                    _format_timestamp(current_time),
                    limit,
                ),
            ).fetchall()
            return Result.ok([_row_to_job(row) for row in rows])

        return run_in_transaction(self._database, _SCHEMA, operation)

    def claim_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 10,
    ) -> Result[list[RetryJob]]:
        """Atomically claim due jobs and increment their attempt counters."""
        try:
            current_time = _as_utc(now if now is not None else datetime.now(UTC))
        except ValueError as exc:
            return Result.fail(ErrorCode.INVALID_ARGUMENT, str(exc))
        if limit < 1:
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT,
                "limit must be at least 1",
            )

        current_timestamp = _format_timestamp(current_time)

        def operation(connection: sqlite3.Connection) -> Result[list[RetryJob]]:
            rows = connection.execute(
                _DUE_SELECT,
                (RetryStatus.PENDING.value, current_timestamp, limit),
            ).fetchall()
            claimed: list[RetryJob] = []
            for row in rows:
                cursor = connection.execute(
                    "UPDATE retry_jobs "
                    "SET status = ?, attempts = attempts + 1, "
                    "claimed_at = ?, updated_at = ? "
                    "WHERE id = ? AND status = ?",
                    (
                        RetryStatus.IN_PROGRESS.value,
                        current_timestamp,
                        current_timestamp,
                        row["id"],
                        RetryStatus.PENDING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                claimed_row = _find_job(connection, row["id"])
                if claimed_row is not None:
                    claimed.append(_row_to_job(claimed_row))
            return Result.ok(claimed)

        return run_in_transaction(self._database, _SCHEMA, operation)

    def reclaim_stale(
        self,
        older_than: timedelta,
        *,
        now: datetime | None = None,
    ) -> Result[list[RetryJob]]:
        """Return stale claimed jobs to the pending state.

        A worker can crash after :meth:`claim_due` but before it completes or
        fails the job, leaving the job ``in_progress`` forever.  Jobs claimed at
        or before ``now - older_than`` are reclaimed so another worker can pick
        them up.  Attempt counts are preserved, and reclaimed jobs become due
        immediately.
        """
        if older_than <= timedelta(0):
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT,
                "older_than must be positive",
            )
        try:
            current_time = _as_utc(now if now is not None else datetime.now(UTC))
        except ValueError as exc:
            return Result.fail(ErrorCode.INVALID_ARGUMENT, str(exc))

        current_timestamp = _format_timestamp(current_time)
        cutoff = _format_timestamp(current_time - older_than)

        def operation(connection: sqlite3.Connection) -> Result[list[RetryJob]]:
            rows = connection.execute(
                f"SELECT {_COLUMN_LIST} FROM retry_jobs "
                "WHERE status = ? AND claimed_at IS NOT NULL AND claimed_at <= ? "
                "ORDER BY claimed_at, created_at, id",
                (RetryStatus.IN_PROGRESS.value, cutoff),
            ).fetchall()
            reclaimed: list[RetryJob] = []
            for row in rows:
                cursor = connection.execute(
                    "UPDATE retry_jobs "
                    "SET status = ?, available_at = ?, claimed_at = NULL, "
                    "updated_at = ? "
                    "WHERE id = ? AND status = ?",
                    (
                        RetryStatus.PENDING.value,
                        current_timestamp,
                        current_timestamp,
                        row["id"],
                        RetryStatus.IN_PROGRESS.value,
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                reclaimed_row = _find_job(connection, row["id"])
                if reclaimed_row is not None:
                    reclaimed.append(_row_to_job(reclaimed_row))
            return Result.ok(reclaimed)

        return run_in_transaction(self._database, _SCHEMA, operation)

    def complete(
        self,
        job_id: str,
        *,
        now: datetime | None = None,
    ) -> Result[RetryJob]:
        """Mark a claimed job as completed.

        Completing an already completed job is idempotent so a worker can safely
        retry a completion after a crash.
        """
        try:
            current_time = _as_utc(now if now is not None else datetime.now(UTC))
        except ValueError as exc:
            return Result.fail(ErrorCode.INVALID_ARGUMENT, str(exc))
        current_timestamp = _format_timestamp(current_time)

        def operation(connection: sqlite3.Connection) -> Result[RetryJob]:
            row = _find_job(connection, job_id)
            if row is None:
                return _not_found(job_id)
            job = _row_to_job(row)
            if job.status is RetryStatus.COMPLETED:
                return Result.ok(job)
            if job.status is not RetryStatus.IN_PROGRESS:
                return _invalid_state(job, "complete")
            connection.execute(
                "UPDATE retry_jobs "
                "SET status = ?, completed_at = ?, updated_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    RetryStatus.COMPLETED.value,
                    current_timestamp,
                    current_timestamp,
                    job_id,
                    RetryStatus.IN_PROGRESS.value,
                ),
            )
            updated_row = _find_job(connection, job_id)
            if updated_row is None:
                return _not_found(job_id)
            return Result.ok(_row_to_job(updated_row))

        return run_in_transaction(self._database, _SCHEMA, operation)

    def fail(
        self,
        job_id: str,
        error: str,
        *,
        now: datetime | None = None,
    ) -> Result[RetryJob]:
        """Record a failure and either reschedule the job or mark it failed."""
        try:
            current_time = _as_utc(now if now is not None else datetime.now(UTC))
        except ValueError as exc:
            return Result.fail(ErrorCode.INVALID_ARGUMENT, str(exc))
        current_timestamp = _format_timestamp(current_time)

        def operation(connection: sqlite3.Connection) -> Result[RetryJob]:
            row = _find_job(connection, job_id)
            if row is None:
                return _not_found(job_id)
            job = _row_to_job(row)
            if job.status is not RetryStatus.IN_PROGRESS:
                return _invalid_state(job, "fail")

            if job.attempts >= job.max_attempts:
                new_status = RetryStatus.FAILED
                due_at = job.available_at
            else:
                new_status = RetryStatus.PENDING
                due_at = current_time + self._backoff_delay(job.attempts)

            connection.execute(
                "UPDATE retry_jobs "
                "SET status = ?, available_at = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    new_status.value,
                    _format_timestamp(due_at),
                    error,
                    current_timestamp,
                    job_id,
                    RetryStatus.IN_PROGRESS.value,
                ),
            )
            updated_row = _find_job(connection, job_id)
            if updated_row is None:
                return _not_found(job_id)
            return Result.ok(_row_to_job(updated_row))

        return run_in_transaction(self._database, _SCHEMA, operation)

    def fail_permanently(
        self,
        job_id: str,
        error: str,
        *,
        now: datetime | None = None,
    ) -> Result[RetryJob]:
        """Mark a claimed job as failed without scheduling another attempt.

        This is for non-retryable failures discovered while replaying a job
        (for example an authentication error): the job is terminal
        immediately, regardless of its remaining attempt budget.
        """
        try:
            current_time = _as_utc(now if now is not None else datetime.now(UTC))
        except ValueError as exc:
            return Result.fail(ErrorCode.INVALID_ARGUMENT, str(exc))
        current_timestamp = _format_timestamp(current_time)

        def operation(connection: sqlite3.Connection) -> Result[RetryJob]:
            row = _find_job(connection, job_id)
            if row is None:
                return _not_found(job_id)
            job = _row_to_job(row)
            if job.status is not RetryStatus.IN_PROGRESS:
                return _invalid_state(job, "fail permanently")

            connection.execute(
                "UPDATE retry_jobs "
                "SET status = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    RetryStatus.FAILED.value,
                    error,
                    current_timestamp,
                    job_id,
                    RetryStatus.IN_PROGRESS.value,
                ),
            )
            updated_row = _find_job(connection, job_id)
            if updated_row is None:
                return _not_found(job_id)
            return Result.ok(_row_to_job(updated_row))

        return run_in_transaction(self._database, _SCHEMA, operation)

    def _backoff_delay(self, attempts: int) -> timedelta:
        exponent = max(attempts - 1, 0)
        delay = self._base_delay_seconds * (2**exponent)
        return timedelta(seconds=min(delay, self._max_delay_seconds))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include time zone information")
    return value.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _json_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(payload) if payload is not None else {}
    json.dumps(value)
    return value


def _job_values(job: RetryJob) -> tuple[object, ...]:
    return (
        job.id,
        job.operation,
        json.dumps(job.payload, sort_keys=True),
        job.status.value,
        job.attempts,
        job.max_attempts,
        _format_timestamp(job.available_at),
        job.last_error,
        _format_timestamp(job.created_at),
        _format_timestamp(job.updated_at),
        _format_timestamp(job.claimed_at) if job.claimed_at is not None else None,
        _format_timestamp(job.completed_at) if job.completed_at is not None else None,
    )


def _row_to_job(row: sqlite3.Row) -> RetryJob:
    return RetryJob(
        id=row["id"],
        operation=row["operation"],
        payload=json.loads(row["payload"]),
        status=RetryStatus(row["status"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        available_at=datetime.fromisoformat(row["available_at"]),
        last_error=row["last_error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        claimed_at=(
            datetime.fromisoformat(row["claimed_at"])
            if row["claimed_at"] is not None
            else None
        ),
        completed_at=(
            datetime.fromisoformat(row["completed_at"])
            if row["completed_at"] is not None
            else None
        ),
    )


def _find_job(
    connection: sqlite3.Connection,
    job_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        f"SELECT {_COLUMN_LIST} FROM retry_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()


def _not_found(job_id: str) -> Result[RetryJob]:
    return Result.fail(ErrorCode.NOT_FOUND, f"retry job {job_id!r} was not found")


def _invalid_state(job: RetryJob, action: str) -> Result[RetryJob]:
    return Result.fail(
        ErrorCode.INVALID_STATE,
        f"cannot {action} retry job {job.id!r} in state {job.status.value!r}",
    )
