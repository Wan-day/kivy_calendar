"""Tests for the SQLite-backed retry queue."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from core.errors import ErrorCode, Result
from core.sqlite import Database
from retry.queue import RetryJob, RetryQueue, RetryStatus

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _job(result: Result[RetryJob]) -> RetryJob:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _jobs(result: Result[list[RetryJob]]) -> list[RetryJob]:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


@pytest.fixture
def queue(tmp_path: Path) -> RetryQueue:
    """Return a queue backed by a temporary SQLite file."""
    return RetryQueue(
        Database(tmp_path / "retry.db"),
        base_delay_seconds=10.0,
        max_delay_seconds=60.0,
    )


def test_enqueue_creates_a_pending_job(queue: RetryQueue) -> None:
    """New jobs start pending, immediately due, with no attempts."""
    job = _job(queue.enqueue("create_event", {"event_id": "client-id"}, now=NOW))

    assert job.status is RetryStatus.PENDING
    assert job.attempts == 0
    assert job.max_attempts == 5
    assert job.available_at == NOW
    assert job.created_at == NOW
    assert job.updated_at == NOW
    assert job.last_error is None
    assert job.payload == {"event_id": "client-id"}


def test_enqueue_generates_unique_ids_and_rejects_duplicates(
    queue: RetryQueue,
) -> None:
    """Job ids are unique and a caller-supplied duplicate is reported."""
    first = _job(queue.enqueue("create_event", now=NOW))
    second = _job(queue.enqueue("create_event", now=NOW))

    assert first.id != second.id

    duplicate = queue.enqueue("create_event", job_id=first.id, now=NOW)
    assert duplicate.error is not None
    assert duplicate.error.code is ErrorCode.ALREADY_EXISTS


def test_enqueue_rejects_a_non_json_payload(queue: RetryQueue) -> None:
    """Only JSON-serialisable payloads can be persisted."""
    result = queue.enqueue("create_event", {"not_json": object()}, now=NOW)

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT


def test_enqueue_rejects_a_naive_timestamp(queue: RetryQueue) -> None:
    """Queue timestamps must always carry timezone information."""
    result = queue.enqueue("create_event", now=datetime(2026, 11, 6, 12, 0))

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT


def test_list_due_only_returns_pending_jobs_that_are_due(
    queue: RetryQueue,
) -> None:
    """Future jobs stay hidden until their retry time arrives."""
    due = _job(queue.enqueue("due", now=NOW))
    future = _job(
        queue.enqueue(
            "future",
            available_at=NOW + timedelta(hours=1),
            now=NOW,
        )
    )

    assert [job.id for job in _jobs(queue.list_due(now=NOW))] == [due.id]
    assert [job.id for job in _jobs(queue.list_due(now=NOW + timedelta(hours=1)))] == [
        due.id,
        future.id,
    ]


def test_claim_due_marks_jobs_in_progress_once(queue: RetryQueue) -> None:
    """Claiming increments attempts and prevents a second claim."""
    queued = _job(queue.enqueue("create_event", now=NOW))

    claimed = _jobs(queue.claim_due(now=NOW))

    assert len(claimed) == 1
    assert claimed[0].id == queued.id
    assert claimed[0].status is RetryStatus.IN_PROGRESS
    assert claimed[0].attempts == 1
    assert claimed[0].claimed_at == NOW
    assert _jobs(queue.claim_due(now=NOW)) == []
    assert _jobs(queue.list_due(now=NOW)) == []


def test_complete_finishes_a_claimed_job_idempotently(
    queue: RetryQueue,
) -> None:
    """Completing a job records the finish time and can be repeated."""
    queued = _job(queue.enqueue("create_event", now=NOW))
    _jobs(queue.claim_due(now=NOW))

    completed = _job(queue.complete(queued.id, now=NOW + timedelta(seconds=5)))
    assert completed.status is RetryStatus.COMPLETED
    assert completed.completed_at == NOW + timedelta(seconds=5)
    assert completed.attempts == 1

    again = _job(queue.complete(queued.id, now=NOW + timedelta(minutes=5)))
    assert again.status is RetryStatus.COMPLETED
    assert again.completed_at == completed.completed_at


def test_complete_requires_a_claimed_job(queue: RetryQueue) -> None:
    """A job must be claimed before it can be completed."""
    queued = _job(queue.enqueue("create_event", now=NOW))

    result = queue.complete(queued.id, now=NOW)

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_STATE


def test_fail_reschedules_with_exponential_backoff(queue: RetryQueue) -> None:
    """A failed attempt becomes due again after an increasing delay."""
    queued = _job(queue.enqueue("create_event", now=NOW))
    _jobs(queue.claim_due(now=NOW))

    first_failure = _job(queue.fail(queued.id, "offline", now=NOW))
    assert first_failure.status is RetryStatus.PENDING
    assert first_failure.attempts == 1
    assert first_failure.last_error == "offline"
    assert first_failure.available_at == NOW + timedelta(seconds=10)
    assert _jobs(queue.list_due(now=NOW)) == []

    second_claim = _jobs(queue.claim_due(now=first_failure.available_at))
    assert len(second_claim) == 1
    assert second_claim[0].attempts == 2

    second_failure = _job(
        queue.fail(queued.id, "still offline", now=first_failure.available_at)
    )
    assert second_failure.available_at == first_failure.available_at + timedelta(
        seconds=20
    )


def test_fail_marks_a_job_dead_after_max_attempts(queue: RetryQueue) -> None:
    """Exhausting max_attempts leaves the job permanently failed."""
    queued = _job(queue.enqueue("create_event", max_attempts=2, now=NOW))

    _jobs(queue.claim_due(now=NOW))
    first_failure = _job(queue.fail(queued.id, "offline", now=NOW))
    _jobs(queue.claim_due(now=first_failure.available_at))
    final_failure = _job(
        queue.fail(queued.id, "offline again", now=first_failure.available_at)
    )

    assert final_failure.status is RetryStatus.FAILED
    assert final_failure.attempts == 2
    assert final_failure.last_error == "offline again"
    assert _jobs(queue.list_due(now=NOW + timedelta(days=1))) == []

    cannot_complete = queue.complete(queued.id, now=NOW + timedelta(days=1))
    assert cannot_complete.error is not None
    assert cannot_complete.error.code is ErrorCode.INVALID_STATE


def test_fail_caps_backoff_at_the_maximum(queue: RetryQueue) -> None:
    """The backoff delay never grows past max_delay_seconds."""
    queued = _job(queue.enqueue("create_event", max_attempts=6, now=NOW))
    due_at = NOW

    for expected_delay in (10, 20, 40, 60, 60):
        _jobs(queue.claim_due(now=due_at))
        failure = _job(queue.fail(queued.id, "offline", now=due_at))
        assert failure.available_at == due_at + timedelta(seconds=expected_delay)
        due_at = failure.available_at


def test_fail_permanently_marks_a_claimed_job_failed(
    queue: RetryQueue,
) -> None:
    """A non-retryable replay failure is terminal on the first attempt."""
    queued = _job(queue.enqueue("create_event", now=NOW))
    _jobs(queue.claim_due(now=NOW))

    failed = _job(
        queue.fail_permanently(queued.id, "auth_error: token revoked", now=NOW)
    )

    assert failed.status is RetryStatus.FAILED
    assert failed.attempts == 1
    assert failed.last_error == "auth_error: token revoked"
    assert failed.available_at == queued.available_at
    assert failed.completed_at is None
    assert _jobs(queue.list_due(now=NOW + timedelta(days=1))) == []

    cannot_complete = queue.complete(queued.id, now=NOW + timedelta(days=1))
    assert cannot_complete.error is not None
    assert cannot_complete.error.code is ErrorCode.INVALID_STATE


def test_fail_permanently_requires_a_claimed_job(queue: RetryQueue) -> None:
    """A pending job cannot be failed permanently behind a worker's back."""
    queued = _job(queue.enqueue("create_event", now=NOW))

    result = queue.fail_permanently(queued.id, "auth_error", now=NOW)

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_STATE


def test_failed_transition_for_unknown_job_is_not_found(
    queue: RetryQueue,
) -> None:
    """Missing jobs are returned as errors, not exceptions."""
    complete = queue.complete("missing", now=NOW)
    fail = queue.fail("missing", "offline", now=NOW)
    fail_permanently = queue.fail_permanently("missing", "auth_error", now=NOW)
    get = queue.get("missing")

    for result in (complete, fail, fail_permanently, get):
        assert result.error is not None
        assert result.error.code is ErrorCode.NOT_FOUND


def test_invalid_limit_is_rejected(queue: RetryQueue) -> None:
    """Callers cannot ask the queue for zero jobs."""
    result = queue.claim_due(now=NOW, limit=0)

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT


def test_jobs_survive_a_queue_restart(tmp_path: Path) -> None:
    """Queued work is durable across process restarts."""
    database = Database(tmp_path / "retry.db")
    original = RetryQueue(database)
    queued = _job(original.enqueue("create_event", {"event_id": "e1"}, now=NOW))

    restarted = RetryQueue(Database(database.path))
    loaded = _job(restarted.get(queued.id))

    assert loaded.operation == "create_event"
    assert loaded.payload == {"event_id": "e1"}
    assert loaded.status is RetryStatus.PENDING
    assert loaded.available_at == NOW


def test_reclaim_stale_returns_crashed_jobs_to_pending(
    queue: RetryQueue,
) -> None:
    """A job claimed by a crashed worker becomes due again."""
    queued = _job(queue.enqueue("create_event", now=NOW))
    _jobs(queue.claim_due(now=NOW))
    reclaimed_at = NOW + timedelta(minutes=10)

    result = queue.reclaim_stale(timedelta(minutes=5), now=reclaimed_at)

    assert result.is_ok
    assert result.value is not None
    assert len(result.value) == 1
    reclaimed = result.value[0]
    assert reclaimed.id == queued.id
    assert reclaimed.status is RetryStatus.PENDING
    assert reclaimed.attempts == 1
    assert reclaimed.claimed_at is None
    assert reclaimed.available_at == reclaimed_at
    assert reclaimed.updated_at == reclaimed_at


def test_reclaim_stale_leaves_recent_claims_alone(
    queue: RetryQueue,
) -> None:
    """A job claimed recently may still be running, so it is not reclaimed."""
    _job(queue.enqueue("create_event", now=NOW))
    _jobs(queue.claim_due(now=NOW))

    result = queue.reclaim_stale(timedelta(minutes=5), now=NOW + timedelta(minutes=1))

    assert result.is_ok
    assert result.value == []


def test_reclaimed_jobs_can_be_claimed_again(queue: RetryQueue) -> None:
    """Reclaiming makes the job claimable without resetting attempt history."""
    queued = _job(queue.enqueue("create_event", now=NOW))
    _jobs(queue.claim_due(now=NOW))
    reclaimed_at = NOW + timedelta(minutes=10)
    _jobs(queue.reclaim_stale(timedelta(minutes=5), now=reclaimed_at))

    claimed = _jobs(queue.claim_due(now=reclaimed_at))

    assert len(claimed) == 1
    assert claimed[0].id == queued.id
    assert claimed[0].status is RetryStatus.IN_PROGRESS
    assert claimed[0].attempts == 2
    assert claimed[0].claimed_at == reclaimed_at


def test_reclaim_stale_ignores_jobs_that_are_not_in_progress(
    queue: RetryQueue,
) -> None:
    """Only jobs abandoned after claiming are reclaimed."""
    pending = _job(queue.enqueue("pending", now=NOW))
    completed = _job(queue.enqueue("completed", now=NOW))
    _jobs(queue.claim_due(now=NOW, limit=2))
    _job(queue.complete(completed.id, now=NOW))

    result = queue.reclaim_stale(timedelta(seconds=1), now=NOW + timedelta(hours=1))

    assert result.is_ok
    assert result.value is not None
    assert [job.id for job in result.value] == [pending.id]
    assert _job(queue.get(completed.id)).status is RetryStatus.COMPLETED


def test_reclaim_stale_rejects_invalid_arguments(queue: RetryQueue) -> None:
    """Bad reclaim windows and naive timestamps produce error results."""
    zero = queue.reclaim_stale(timedelta(0), now=NOW)
    naive = queue.reclaim_stale(timedelta(minutes=1), now=datetime(2026, 11, 6, 12, 0))

    for result in (zero, naive):
        assert result.error is not None
        assert result.error.code is ErrorCode.INVALID_ARGUMENT
