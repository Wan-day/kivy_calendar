"""Tests for the in-memory calendar provider used by the sync service."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from core.errors import ErrorCode, Result
from domain.event import Event
from google.fake import FakeCalendarProvider
from google.provider import CalendarProvider, ProviderOperation

BERLIN = ZoneInfo("Europe/Berlin")


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


def _loaded_event(result: Result[Event | None]) -> Event:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


@pytest.fixture
def provider() -> FakeCalendarProvider:
    """Return an empty fake provider backed only by memory."""
    return FakeCalendarProvider()


def test_fake_provider_satisfies_the_interface(
    provider: FakeCalendarProvider,
) -> None:
    """The fake is usable anywhere the provider protocol is expected."""
    assert isinstance(provider, CalendarProvider)


def test_create_and_get_round_trip(provider: FakeCalendarProvider) -> None:
    """A created event is returned by id with client-generated ids preserved."""
    event = _event()

    created = _event_result(provider.create_event(event))
    loaded = provider.get_event(event.id)

    assert created == event
    assert loaded.is_ok
    assert loaded.value == event


def test_stored_events_cannot_be_mutated_through_results(
    provider: FakeCalendarProvider,
) -> None:
    """The fake hands out copies so callers cannot corrupt its state."""
    created = _event_result(provider.create_event(_event()))
    created.summary = "Mutated by caller"

    loaded = _loaded_event(provider.get_event("event-1"))
    assert loaded.summary == "Team standup"
    assert provider.events[0].summary == "Team standup"


def test_create_rejects_a_duplicate_client_generated_id(
    provider: FakeCalendarProvider,
) -> None:
    """Retrying cannot silently create two events with the same id."""
    assert provider.create_event(_event()).is_ok

    duplicate = provider.create_event(_event(summary="Duplicate"))

    assert duplicate.error is not None
    assert duplicate.error.code is ErrorCode.ALREADY_EXISTS
    assert len(provider.events) == 1


def test_update_replaces_an_existing_event(provider: FakeCalendarProvider) -> None:
    """Updates overwrite the stored copy."""
    assert provider.create_event(_event()).is_ok

    updated = _event_result(provider.update_event(_event(summary="Updated")))

    assert updated.summary == "Updated"
    assert _loaded_event(provider.get_event("event-1")).summary == "Updated"


def test_update_reports_a_missing_event(provider: FakeCalendarProvider) -> None:
    """Only events already in the fake can be updated."""
    result = provider.update_event(_event("missing"))

    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_get_returns_none_for_a_missing_event(
    provider: FakeCalendarProvider,
) -> None:
    """A missing event is a successful lookup with no value."""
    result = provider.get_event("missing")

    assert result.is_ok
    assert result.value is None


def test_delete_removes_an_event(provider: FakeCalendarProvider) -> None:
    """Deleting removes the event and a second delete reports not found."""
    assert provider.create_event(_event()).is_ok

    assert provider.delete_event("event-1").is_ok
    assert provider.get_event("event-1").value is None

    again = provider.delete_event("event-1")
    assert again.error is not None
    assert again.error.code is ErrorCode.NOT_FOUND


def test_list_returns_events_in_calendar_order() -> None:
    """Listing is deterministic and ordered by start time."""
    later = _event("later", hour=12)
    earlier = _event("earlier", hour=8)
    provider = FakeCalendarProvider([later, earlier])

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == ["earlier", "later"]


def test_injected_failure_leaves_state_unchanged(
    provider: FakeCalendarProvider,
) -> None:
    """A failed call behaves like an offline upstream and is consumed once."""
    provider.fail_next(
        ProviderOperation.CREATE,
        code=ErrorCode.UPSTREAM_ERROR,
        message="calendar is offline",
    )

    failed = provider.create_event(_event())

    assert failed.error is not None
    assert failed.error.code is ErrorCode.UPSTREAM_ERROR
    assert failed.error.message == "calendar is offline"
    assert provider.events == []
    assert provider.calls == [(ProviderOperation.CREATE, "event-1")]

    assert provider.create_event(_event()).is_ok
    assert len(provider.events) == 1


def test_failure_injection_can_cover_several_attempts(
    provider: FakeCalendarProvider,
) -> None:
    """A test can keep a provider failing across a retry cycle."""
    provider.fail_next("list_events", times=2, message="rate limited")

    first = provider.list_events()
    second = provider.list_events()
    third = provider.list_events()

    assert first.error is not None
    assert second.error is not None
    assert second.error.message == "rate limited"
    assert third.is_ok


def test_failure_injection_validates_its_input(
    provider: FakeCalendarProvider,
) -> None:
    """Misconfigured tests fail loudly instead of silently not injecting."""
    with pytest.raises(ValueError):
        provider.fail_next("not_an_operation")
    with pytest.raises(ValueError):
        provider.fail_next("create_event", times=0)
