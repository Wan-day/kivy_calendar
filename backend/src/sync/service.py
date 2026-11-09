"""Write-through orchestration between the provider, cache, and retry queue.

Google Calendar is the source of truth.  Every write reaches the provider first,
and the SQLite cache is updated only after the provider confirms it.  When the
provider is unavailable the write is queued for retry and returned as an error,
so the client never displays an event that Google has not accepted.  The cache
is disposable and can be rebuilt from the provider with a full sync.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from cache.repository import EventRepository
from core.errors import Error, ErrorCode, Result, is_retryable
from domain.event import Event
from google_calendar.provider import CalendarProvider, ProviderOperation
from retry.queue import RetryJob, RetryQueue

CREATE_OPERATION = ProviderOperation.CREATE.value
UPDATE_OPERATION = ProviderOperation.UPDATE.value
DELETE_OPERATION = ProviderOperation.DELETE.value

DEFAULT_RETRY_BATCH_SIZE = 10
DEFAULT_RETRY_LEASE = timedelta(minutes=5)

_EVENT_PAYLOAD_KEY = "event"
_EVENT_ID_PAYLOAD_KEY = "event_id"
_CALENDAR_ID_PAYLOAD_KEY = "calendar_id"


class SyncService:
    """Coordinate provider writes, cache updates, and deferred retries."""

    def __init__(
        self,
        provider: CalendarProvider,
        repository: EventRepository,
        retry_queue: RetryQueue,
        *,
        retry_batch_size: int = DEFAULT_RETRY_BATCH_SIZE,
        retry_lease: timedelta = DEFAULT_RETRY_LEASE,
    ) -> None:
        if retry_batch_size < 1:
            raise ValueError("retry_batch_size must be at least 1")
        if retry_lease <= timedelta(0):
            raise ValueError("retry_lease must be positive")
        self._provider = provider
        self._repository = repository
        self._retry_queue = retry_queue
        self._retry_batch_size = retry_batch_size
        self._retry_lease = retry_lease

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
        """Update ``event`` in Google first, then refresh the cached copy.

        A blank ``calendar_id`` is filled from the cached event so an edit
        targets the calendar the event came from.  If the cache lookup fails the
        provider falls back to its configured default calendar.
        """
        resolved = event
        if not event.calendar_id:
            resolved = event.model_copy(
                update={"calendar_id": self._cached_calendar_id(event.id)}
            )
        result = self._provider.update_event(resolved)
        if result.error is not None:
            return self._queue_failed_write(
                UPDATE_OPERATION,
                {_EVENT_PAYLOAD_KEY: resolved.model_dump(mode="json")},
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
        """Delete ``event_id`` in Google first, then drop the cached copy.

        The calendar is taken from the cached event so a delete targets the
        calendar the event came from.  A missing cache entry falls back to the
        provider's configured default calendar.
        """
        calendar_id = self._cached_calendar_id(event_id)
        result = self._provider.delete_event(calendar_id, event_id)
        if result.error is not None:
            return self._queue_failed_write(
                DELETE_OPERATION,
                {
                    _EVENT_ID_PAYLOAD_KEY: event_id,
                    _CALENDAR_ID_PAYLOAD_KEY: calendar_id,
                },
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

        Jobs abandoned by a crashed worker are reclaimed first, then due jobs
        are claimed.  Successful replays are completed and provider failures are
        recorded on the job and rescheduled with the queue's exponential
        backoff.  Every claimed job is attempted even if one queue transition
        fails; those failures are aggregated and returned.  ``now`` is forwarded
        to every queue transition so a caller can use one clock for the whole
        cycle.
        """
        reclaimed = self._retry_queue.reclaim_stale(self._retry_lease, now=now)
        if reclaimed.error is not None:
            return Result.fail(reclaimed.error.code, reclaimed.error.message)

        claimed = self._retry_queue.claim_due(
            now=now,
            limit=limit if limit is not None else self._retry_batch_size,
        )
        if claimed.error is not None:
            return Result.fail(claimed.error.code, claimed.error.message)

        processed: list[RetryJob] = []
        transition_errors: list[Error] = []
        for job in claimed.value or []:
            outcome = self._process_job(job, now=now)
            if outcome.error is not None:
                transition_errors.append(
                    Error(
                        outcome.error.code,
                        f"retry job {job.id!r}: {outcome.error.message}",
                    )
                )
                continue
            if outcome.value is not None:
                processed.append(outcome.value)

        if transition_errors:
            return Result.fail(
                _aggregate_error_code(transition_errors),
                "; ".join(error.message for error in transition_errors),
            )
        return Result.ok(processed)

    def _process_job(
        self,
        job: RetryJob,
        *,
        now: datetime | None,
    ) -> Result[RetryJob]:
        """Replay one claimed job and record its final queue state."""
        operation = _as_operation(job.operation)
        if (
            operation is ProviderOperation.CREATE
            or operation is ProviderOperation.UPDATE
        ):
            return self._replay_write(job, operation=operation, now=now)
        if operation is ProviderOperation.DELETE:
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
        operation: ProviderOperation,
        now: datetime | None,
    ) -> Result[RetryJob]:
        event = _event_from_payload(job.payload)
        if event is None:
            return self._retry_queue.fail(
                job.id,
                f"invalid payload for {job.operation}",
                now=now,
            )

        if operation is ProviderOperation.CREATE:
            result = self._provider.create_event(event)
        else:
            result = self._provider.update_event(event)

        if result.error is not None:
            if (
                operation is ProviderOperation.CREATE
                and result.error.code is ErrorCode.ALREADY_EXISTS
            ):
                return self._replay_existing_create(job, event, now=now)
            return self._record_provider_failure(job, result.error, now=now)

        self._cache_event(result.value if result.value is not None else event)
        return self._retry_queue.complete(job.id, now=now)

    def _replay_existing_create(
        self,
        job: RetryJob,
        event: Event,
        *,
        now: datetime | None,
    ) -> Result[RetryJob]:
        """Recover a create whose id already reached Google.

        The event id is client-generated, so an earlier attempt may have arrived
        before the worker recorded success.  Google's copy is authoritative:
        fetch and cache it rather than the local queued payload.  If the fetch
        fails or finds nothing the failure is recorded on the job so the queue
        can back off and eventually stop at ``max_attempts`` instead of leaving
        the job ``in_progress`` forever.
        """
        existing = self._provider.get_event(event.calendar_id, event.id)
        if existing.error is not None:
            return self._retry_queue.fail(
                job.id,
                _describe_error(existing.error),
                now=now,
            )

        confirmed = existing.value
        if confirmed is None:
            return self._retry_queue.fail(
                job.id,
                f"event {event.id!r} was reported as existing but could not "
                "be fetched from Google",
                now=now,
            )

        self._cache_event(confirmed)
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

        calendar_id = _calendar_id_from_payload(job.payload)
        result = self._provider.delete_event(calendar_id, event_id)
        if result.error is not None:
            if result.error.code is ErrorCode.NOT_FOUND:
                # The event is already gone, which is the outcome we wanted.
                self._repository.delete(event_id)
                return self._retry_queue.complete(job.id, now=now)
            return self._record_provider_failure(job, result.error, now=now)

        self._repository.delete(event_id)
        return self._retry_queue.complete(job.id, now=now)

    def _record_provider_failure(
        self,
        job: RetryJob,
        error: Error,
        *,
        now: datetime | None,
    ) -> Result[RetryJob]:
        """Record a replayed write failure with the right retry semantics.

        Transient upstream failures back off and may be tried again; permanent
        failures (invalid arguments, authentication errors, ...) fail the job
        immediately because replaying them cannot succeed.
        """
        if is_retryable(error):
            return self._retry_queue.fail(
                job.id,
                _describe_error(error),
                now=now,
            )
        return self._retry_queue.fail_permanently(
            job.id,
            _describe_error(error),
            now=now,
        )

    def _cached_calendar_id(self, event_id: str) -> str:
        """Return the calendar a cached event came from, or blank when unknown."""
        cached = self._repository.get(event_id)
        if cached.error is not None or cached.value is None:
            return ""
        return cached.value.calendar_id

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
        """Queue a failed provider write and return the original failure.

        Only transient upstream failures are queued.  Permanent failures such
        as an invalid request, a missing event, or a conflict are returned
        immediately because replaying them cannot succeed.
        """
        if not is_retryable(failure):
            return Result.fail(failure.code, failure.message)
        queued = self._retry_queue.enqueue(operation, payload)
        if queued.error is not None:
            return Result.fail(
                ErrorCode.STORAGE_ERROR,
                f"{_describe_error(failure)}; retry could not be queued: "
                f"{queued.error.message}",
            )
        return Result.fail(failure.code, failure.message)


def _as_operation(value: str) -> ProviderOperation | None:
    """Parse a queued operation name, or ``None`` when it is unsupported."""
    try:
        return ProviderOperation(value)
    except ValueError:
        return None


def _aggregate_error_code(errors: list[Error]) -> ErrorCode:
    """Prefer a storage failure when several retry transitions failed."""
    for error in errors:
        if error.code is ErrorCode.STORAGE_ERROR:
            return ErrorCode.STORAGE_ERROR
    return errors[0].code


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


def _calendar_id_from_payload(payload: dict[str, Any]) -> str:
    """Return a delete payload's calendar id, defaulting old jobs to blank."""
    calendar_id = payload.get(_CALENDAR_ID_PAYLOAD_KEY)
    return calendar_id if isinstance(calendar_id, str) else ""


def _describe_error(error: Error) -> str:
    """Format a provider error for a retry job's ``last_error`` field."""
    if error.message:
        return f"{error.code.value}: {error.message}"
    return error.code.value
