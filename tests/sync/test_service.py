"""Tests for write-through sync orchestration and retry replay."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from cache.repository import EventRepository
from core.errors import ErrorCode, Result
from core.sqlite import Database
from domain.event import Event
from google_calendar.fake import FakeCalendarProvider
from retry.queue import RetryJob, RetryQueue, RetryStatus
from sync.service import (
    CREATE_OPERATION,
    DELETE_OPERATION,
    UPDATE_OPERATION,
    SyncService,
)

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _event(
    event_id: str = "event-1",
    *,
    summary: str = "Team standup",
    hour: int = 9,
) -> Event:
    start = datetime(2026, 11, 6, hour, 0, tzinfo=BERLIN)
    return Event(
        id=event_id,
        summary=summary,
        start=start,
        end=start + timedelta(minutes=30),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
    )


def _event_result(result: Result[Event]) -> Event:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _jobs(result: Result[list[RetryJob]]) -> list[RetryJob]:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _job(result: Result[RetryJob]) -> RetryJob:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _cached(repository: EventRepository, event_id: str) -> Event | None:
    result = repository.get(event_id)
    if result.error is not None and result.error.code is ErrorCode.NOT_FOUND:
        return None
    assert result.is_ok, result.error
    return result.value


@pytest.fixture
def provider() -> FakeCalendarProvider:
    """Return an empty in-memory calendar provider."""
    return FakeCalendarProvider()


@pytest.fixture
def repository(tmp_path: Path) -> EventRepository:
    """Return a cache backed by a temporary SQLite file."""
    return EventRepository(Database(tmp_path / "calendar.db"))


@pytest.fixture
def retry_queue(tmp_path: Path) -> RetryQueue:
    """Return a retry queue with short, predictable backoff delays."""
    return RetryQueue(
        Database(tmp_path / "retry.db"),
        base_delay_seconds=10.0,
        max_delay_seconds=60.0,
    )


@pytest.fixture
def service(
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> SyncService:
    """Return a sync service wired to a fake provider and temporary storage."""
    return SyncService(provider, repository, retry_queue)


def test_create_writes_to_the_provider_before_caching(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
) -> None:
    """A confirmed create appears in both Google and the cache."""
    event = _event()

    created = _event_result(service.create_event(event))

    assert created == event
    assert provider.events == [event]
    assert _cached(repository, event.id) == event


def test_create_failure_is_queued_and_not_cached(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """An unconfirmed create is never shown as saved."""
    event = _event()
    provider.fail_next("create_event", message="calendar is offline")

    result = service.create_event(event)

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert provider.events == []
    assert _cached(repository, event.id) is None

    jobs = _jobs(retry_queue.list_due())
    assert len(jobs) == 1
    assert jobs[0].operation == CREATE_OPERATION
    assert jobs[0].payload == {"event": event.model_dump(mode="json")}


def test_permanent_create_failure_is_not_queued(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """An invalid create cannot succeed later, so it is not retried."""
    event = _event()
    provider.fail_next(
        "create_event",
        code=ErrorCode.INVALID_ARGUMENT,
        message="invalid event",
    )

    result = service.create_event(event)

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT
    assert _cached(repository, event.id) is None
    assert _jobs(retry_queue.list_due()) == []


def test_create_conflict_is_not_queued(
    service: SyncService,
    provider: FakeCalendarProvider,
    retry_queue: RetryQueue,
) -> None:
    """A 409 conflict is permanent and must not be replayed forever."""
    event = _event()
    provider.fail_next(
        "create_event",
        code=ErrorCode.ALREADY_EXISTS,
        message="event already exists",
    )

    result = service.create_event(event)

    assert result.error is not None
    assert result.error.code is ErrorCode.ALREADY_EXISTS
    assert _jobs(retry_queue.list_due()) == []



def test_update_writes_to_the_provider_before_refreshing_the_cache(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
) -> None:
    """A confirmed update replaces the stored event in both places."""
    event = _event()
    assert service.create_event(event).is_ok
    updated = _event(summary="Updated standup")

    result = service.update_event(updated)

    assert _event_result(result) == updated
    assert provider.events == [updated]
    assert _cached(repository, event.id) == updated


def test_update_failure_keeps_the_previous_state_and_queues_a_retry(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """A failed update leaves Google and the cache on the old value."""
    event = _event()
    assert service.create_event(event).is_ok
    provider.fail_next("update_event", message="rate limited")

    result = service.update_event(_event(summary="Updated standup"))

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert provider.events == [event]
    assert _cached(repository, event.id) == event

    jobs = _jobs(retry_queue.list_due())
    assert len(jobs) == 1
    assert jobs[0].operation == UPDATE_OPERATION
    assert Event.model_validate(jobs[0].payload["event"]).summary == "Updated standup"


def test_delete_removes_from_the_provider_before_the_cache(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
) -> None:
    """A confirmed delete removes the event from both places."""
    event = _event()
    assert service.create_event(event).is_ok

    assert service.delete_event(event.id).is_ok

    assert provider.events == []
    assert _cached(repository, event.id) is None


def test_delete_failure_keeps_the_event_and_queues_a_retry(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """A failed delete leaves the event visible until Google confirms it."""
    event = _event()
    assert service.create_event(event).is_ok
    provider.fail_next("delete_event", message="calendar is offline")

    result = service.delete_event(event.id)

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert provider.events == [event]
    assert _cached(repository, event.id) == event

    jobs = _jobs(retry_queue.list_due())
    assert len(jobs) == 1
    assert jobs[0].operation == DELETE_OPERATION
    assert jobs[0].payload == {"event_id": event.id}


def test_delete_of_a_missing_event_is_not_queued(
    service: SyncService,
    retry_queue: RetryQueue,
) -> None:
    """Deleting an event Google does not have is a permanent failure."""
    result = service.delete_event("missing")

    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert _jobs(retry_queue.list_due()) == []


def test_update_of_a_missing_event_is_not_queued(
    service: SyncService,
    retry_queue: RetryQueue,
) -> None:
    """Updating an unknown event cannot succeed by replaying it."""
    result = service.update_event(_event("missing"))

    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert _jobs(retry_queue.list_due()) == []



def test_sync_from_google_rebuilds_the_whole_cache(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
) -> None:
    """A full sync replaces stale cache rows with the upstream calendar."""
    first = _event("first", hour=9)
    second = _event("second", hour=10)
    stale = _event("stale", hour=8)
    assert provider.create_event(first).is_ok
    assert provider.create_event(second).is_ok
    assert repository.create(stale).is_ok

    result = service.sync_from_google()

    assert result.is_ok
    assert result.value == 2
    listed = repository.list()
    assert listed.is_ok
    assert listed.value is not None
    assert [event.id for event in listed.value] == ["first", "second"]


def test_sync_from_google_failure_leaves_the_cache_intact(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
) -> None:
    """A failed pull does not discard the current cache."""
    event = _event()
    assert service.create_event(event).is_ok
    provider.fail_next("list_events", message="offline")

    result = service.sync_from_google()

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert _cached(repository, event.id) == event


def test_process_due_retries_completes_a_failed_create(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """Replaying a create after the provider recovers completes the job."""
    event = _event()
    provider.fail_next("create_event", message="offline")
    assert service.create_event(event).is_error
    queued = _jobs(retry_queue.list_due())[0]

    processed = _jobs(service.process_due_retries())

    assert len(processed) == 1
    assert processed[0].id == queued.id
    assert processed[0].status is RetryStatus.COMPLETED
    assert provider.events == [event]
    assert _cached(repository, event.id) == event


def test_process_due_retries_backs_off_while_the_provider_stays_down(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """A retry failure reschedules the job instead of losing the write."""
    event = _event()
    provider.fail_next("create_event", times=2, message="offline")
    assert service.create_event(event).is_error
    queued = _jobs(retry_queue.list_due())[0]

    processed = _jobs(service.process_due_retries())

    assert len(processed) == 1
    failed_attempt = processed[0]
    assert failed_attempt.id == queued.id
    assert failed_attempt.status is RetryStatus.PENDING
    assert failed_attempt.attempts == 1
    assert failed_attempt.last_error is not None
    assert "upstream_error" in failed_attempt.last_error
    assert failed_attempt.available_at > queued.available_at
    assert provider.events == []
    assert _cached(repository, event.id) is None

    recovered = _jobs(service.process_due_retries(now=failed_attempt.available_at))

    assert len(recovered) == 1
    assert recovered[0].status is RetryStatus.COMPLETED
    assert recovered[0].attempts == 2
    assert provider.events == [event]
    assert _cached(repository, event.id) == event


def test_process_due_retries_replays_updates_and_deletes(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """Update and delete retries apply to the provider and the cache."""
    event = _event()
    assert service.create_event(event).is_ok

    provider.fail_next("update_event", message="offline")
    updated = _event(summary="Updated standup")
    assert service.update_event(updated).is_error
    _jobs(service.process_due_retries())

    assert provider.events == [updated]
    assert _cached(repository, updated.id) == updated

    provider.fail_next("delete_event", message="offline")
    assert service.delete_event(updated.id).is_error
    _jobs(service.process_due_retries())

    assert provider.events == []
    assert _cached(repository, updated.id) is None
    assert _jobs(retry_queue.list_due(now=datetime.now(UTC))) == []


def test_create_retry_treats_already_exists_as_success(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """A create that reached Google before a crash is not duplicated."""
    event = _event()
    provider.fail_next("create_event", message="connection dropped")
    assert service.create_event(event).is_error
    assert provider.create_event(event).is_ok

    processed = _jobs(service.process_due_retries())

    assert len(processed) == 1
    assert processed[0].status is RetryStatus.COMPLETED
    assert len(provider.events) == 1
    assert _cached(repository, event.id) == event
    assert _jobs(retry_queue.list_due()) == []


def test_delete_retry_treats_not_found_as_success(
    service: SyncService,
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """Deleting an event that already vanished still completes the job."""
    event = _event()
    assert service.create_event(event).is_ok
    provider.fail_next("delete_event", message="connection dropped")
    assert service.delete_event(event.id).is_error
    assert provider.delete_event(event.id).is_ok

    processed = _jobs(service.process_due_retries())

    assert processed[0].status is RetryStatus.COMPLETED
    assert provider.events == []
    assert _cached(repository, event.id) is None
    assert _jobs(retry_queue.list_due()) == []


def test_unknown_retry_operations_are_recorded_as_failures(
    service: SyncService,
    retry_queue: RetryQueue,
) -> None:
    """An unsupported queued operation does not crash the worker."""
    queued = _job(
        retry_queue.enqueue("archive_event", {"event_id": "event-1"}, now=NOW)
    )

    processed = _jobs(service.process_due_retries(now=NOW))

    assert len(processed) == 1
    assert processed[0].id == queued.id
    assert processed[0].status is RetryStatus.PENDING
    assert processed[0].last_error is not None
    assert "unknown retry operation" in processed[0].last_error


def test_invalid_retry_payload_is_recorded_as_a_failure(
    service: SyncService,
    retry_queue: RetryQueue,
) -> None:
    """A malformed payload is reported on the job instead of raising."""
    queued = _job(
        retry_queue.enqueue(CREATE_OPERATION, {"event": {"id": ""}}, now=NOW)
    )

    processed = _jobs(service.process_due_retries(now=NOW))

    assert processed[0].id == queued.id
    assert processed[0].status is RetryStatus.PENDING
    assert processed[0].last_error == f"invalid payload for {CREATE_OPERATION}"


def test_process_due_retries_respects_the_limit(
    service: SyncService,
    provider: FakeCalendarProvider,
    retry_queue: RetryQueue,
) -> None:
    """Only the requested number of due jobs are claimed in one cycle."""
    provider.fail_next("create_event", times=2, message="offline")
    assert service.create_event(_event("first")).is_error
    assert service.create_event(_event("second")).is_error
    assert len(_jobs(retry_queue.list_due())) == 2

    processed = _jobs(service.process_due_retries(limit=1))

    assert len(processed) == 1
    assert len(_jobs(retry_queue.list_due())) == 1
