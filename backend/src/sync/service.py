"""Write-through orchestration between the provider, cache, and retry queue.

Google Calendar is the source of truth.  Every write reaches the provider first,
and the SQLite cache is updated only after the provider confirms it.  When the
provider is unavailable the write is queued for retry and returned as an error,
so the client never displays an event that Google has not accepted.  The cache
is disposable and can be rebuilt from the provider with a full sync.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cache.repository import EventRepository
from core.errors import Error, ErrorCode, Result
from domain.event import Event
from google.provider import CalendarProvider
from retry.queue import RetryJob, RetryQueue

CREATE_OPERATION = "create_event"
UPDATE_OPERATION = "update_event"
DELETE_OPERATION = "delete_event"

DEFAULT_RETRY_BATCH_SIZE = 10

_EVENT_PAYLOAD_KEY = "event"
_EVENT_ID_PAYLOAD_KEY = "event_id"


class SyncService:
    """Coordinate provider writes, cache updates, and deferred retries."""

    def __init__(
        self,
        provider: CalendarProvider,
        repository: EventRepository,
        retry_queue: RetryQueue,
        *,
        retry_batch_size: int = DEFAULT_RETRY_BATCH_SIZE,
    ) -> None:
        if retry_batch_size < 1:
            raise ValueError("retry_batch_size must be at least 1")
        self._provider = provider
        self._repository = repository
        self._retry_queue = retry_queue
        self._retry_batch_size = retry_batch_size

    def create_event(self, event: Event) -> Result[Event]:
        """Create ``event`` in Google first, then cache the confirmed event.

        A provider failure queues the event payload for retry and returns the
        provider error; the event is not cached until Google confirms it.
        """
        result = self._provider.create_event(event)
        if result.error is not None:
            return self._queue_failed_write(
                CREATE_OPERATION,
                {_EVENT_PAYLOAD_KEY: event.model_dump(mode="json")},
                result.error,
            )

        confirmed = result.value
        if confirmed is None:
            return Result.fail(
                ErrorCode.UPSTREAM_ERROR,
                "calendar provider reported success without an event",
            )
        self._cache_event(confirmed)
        return result

    def update_event(self, event: Event) -> Result[Event]:
        """Update ``event`` in Google first, then refresh the cached copy."""
        result = self._provider.update_event(event)
        if result.error is not None:
            return self._queue_failed_write(
                UPDATE_OPERATION,
                {_EVENT_PAYLOAD_KEY: event.model_dump(mode="json")},
                result.error,
            )

        confirmed = result.value
        if confirmed is None:
            return Result.fail(
                ErrorCode.UPSTREAM_ERROR,
                "calendar provider reported success without an event",
            )
        self._cache_event(confirmed)
        return result

    def delete_event(self, event_id: str) -> Result[None]:
        """Delete ``event_id`` in Google first, then drop the cached copy."""
        result = self._provider.delete_event(event_id)
        if result.error is not None:
            return self._queue_failed_write(
                DELETE_OPERATION,
                {_EVENT_ID_PAYLOAD_KEY: event_id},
                result.error,
            )

        self._repository.delete(event_id)
        return result

    def sync_from_google(self) -> Result[int]:
        """Rebuild the disposable cache from the provider.

        A failed pull leaves the existing cache untouched.  A successful pull
        replaces every cached event in one transaction and returns the number of
        cached events.
        """
        listed = self._provider.list_events()
        if listed.error is not None:
            return Result.fail(listed.error.code, listed.error.message)

        events = listed.value
        if events is None:
            return Result.fail(
                ErrorCode.UPSTREAM_ERROR,
                "calendar provider reported success without an event list",
            )
        return self._repository.replace_all(events)

    def process_due_retries(
        self,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> Result[list[RetryJob]]:
        """Replay due write retries against the provider.

        Successful replays are completed.  Provider failures are recorded on the
        job and rescheduled with the queue's exponential backoff.  ``now`` is
        forwarded to every queue transition so a caller can use one clock for
        the whole cycle.
        """
        claimed = self._retry_queue.claim_due(
            now=now,
            limit=limit if limit is not None else self._retry_batch_size,
        )
        if claimed.error is not None:
            return Result.fail(claimed.error.code, claimed.error.message)

        processed: list[RetryJob] = []
        for job in claimed.value or []:
            outcome = self._process_job(job, now=now)
            if outcome.error is not None:
                return Result.fail(outcome.error.code, outcome.error.message)
            if outcome.value is not None:
                processed.append(outcome.value)
        return Result.ok(processed)

    def _process_job(
        self,
        job: RetryJob,
        *,
        now: datetime | None,
    ) -> Result[RetryJob]:
        """Replay one claimed job and record its final queue state."""
        if job.operation in (CREATE_OPERATION, UPDATE_OPERATION):
            return self._replay_write(job, now=now)
        if job.operation == DELETE_OPERATION:
            return self._replay_delete(job, now=now)
        return self._retry_queue.fail(
            job.id,
            f"unknown retry operation {job.operation!r}",
            now=now,
        )

    def _replay_write(
        self,
        job: RetryJob,
        *,
        now: datetime | None,
    ) -> Result[RetryJob]:
        event = _event_from_payload(job.payload)
        if event is None:
            return self._retry_queue.fail(
                job.id,
                f"invalid payload for {job.operation}",
                now=now,
            )

        if job.operation == CREATE_OPERATION:
            result = self._provider.create_event(event)
        else:
            result = self._provider.update_event(event)

        if result.error is not None:
            if (
                job.operation == CREATE_OPERATION
                and result.error.code is ErrorCode.ALREADY_EXISTS
            ):
                # The event id is client-generated, so an earlier attempt may
                # have reached Google before the worker recorded success.
                self._cache_event(event)
                return self._retry_queue.complete(job.id, now=now)
            return self._retry_queue.fail(
                job.id,
                _describe_error(result.error),
                now=now,
            )

        self._cache_event(result.value if result.value is not None else event)
        return self._retry_queue.complete(job.id, now=now)

    def _replay_delete(
        self,
        job: RetryJob,
        *,
        now: datetime | None,
    ) -> Result[RetryJob]:
        event_id = _event_id_from_payload(job.payload)
        if event_id is None:
            return self._retry_queue.fail(
                job.id,
                f"invalid payload for {job.operation}",
                now=now,
            )

        result = self._provider.delete_event(event_id)
        if result.error is not None:
            if result.error.code is ErrorCode.NOT_FOUND:
                # The event is already gone, which is the outcome we wanted.
                self._repository.delete(event_id)
                return self._retry_queue.complete(job.id, now=now)
            return self._retry_queue.fail(
                job.id,
                _describe_error(result.error),
                now=now,
            )

        self._repository.delete(event_id)
        return self._retry_queue.complete(job.id, now=now)

    def _cache_event(self, event: Event) -> None:
        """Best-effort cache refresh after the provider has confirmed a write.

        Cache failures are intentionally ignored: the event already exists in
        Google, and the disposable cache can be rebuilt by a later sync.
        """
        updated = self._repository.update(event)
        if updated.error is not None and updated.error.code is ErrorCode.NOT_FOUND:
            self._repository.create(event)

    def _queue_failed_write[T](
        self,
        operation: str,
        payload: dict[str, Any],
        failure: Error,
    ) -> Result[T]:
        """Queue a failed provider write and return the original failure."""
        queued = self._retry_queue.enqueue(operation, payload)
        if queued.error is not None:
            return Result.fail(
                ErrorCode.STORAGE_ERROR,
                f"{_describe_error(failure)}; retry could not be queued: "
                f"{queued.error.message}",
            )
        return Result.fail(failure.code, failure.message)


def _event_from_payload(payload: dict[str, Any]) -> Event | None:
    """Rebuild an event from a retry payload, or ``None`` when it is invalid."""
    raw_event = payload.get(_EVENT_PAYLOAD_KEY)
    if not isinstance(raw_event, dict):
        return None
    try:
        return Event.model_validate(raw_event)
    except ValueError:
        return None


def _event_id_from_payload(payload: dict[str, Any]) -> str | None:
    """Return a non-blank event id from a delete payload."""
    event_id = payload.get(_EVENT_ID_PAYLOAD_KEY)
    if isinstance(event_id, str) and event_id.strip():
        return event_id
    return None


def _describe_error(error: Error) -> str:
    """Format a provider error for a retry job's ``last_error`` field."""
    if error.message:
        return f"{error.code.value}: {error.message}"
    return error.code.value
