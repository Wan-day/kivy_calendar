"""Tests for the "not synced yet" state and the save/delete notices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fakes import (
    LOCAL,
    FakeCalendarStore,
    FakePermissions,
    calendar_row,
    millis,
)

from kivy_calendar.models import CalendarEvent
from phone_calendar.provider import AndroidCalendarProvider
from phone_calendar.service import PhoneCalendarService

NOW = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)
START = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)


def _service(store: FakeCalendarStore) -> PhoneCalendarService:
    return PhoneCalendarService(
        AndroidCalendarProvider(store, time_zone="UTC"),
        FakePermissions(),
        now=lambda: NOW,
    )


def _event_row(event_id: int, calendar_id: int, dirty: int | None) -> dict[str, object]:
    return {
        "_id": event_id,
        "calendar_id": calendar_id,
        "title": f"Event {event_id}",
        "dtstart": millis(START),
        "dtend": millis(START + timedelta(hours=1)),
        "eventTimezone": "UTC",
        "dirty": dirty,
    }


def _store() -> FakeCalendarStore:
    store = FakeCalendarStore(
        calendars=[
            calendar_row(1, "me@example.com", primary=1),
            calendar_row(2, "On my phone", account_type=LOCAL),
        ]
    )
    store.event_rows = {
        10: _event_row(10, 1, 1),
        11: _event_row(11, 1, 0),
        12: _event_row(12, 1, None),
        13: _event_row(13, 2, 1),
    }
    return store


def test_store_reports_dirty_events_of_syncing_calendars_only() -> None:
    """LOCAL calendars never sync, so their dirty rows do not count."""
    assert _store().dirty_event_ids() == {10}


def test_dirty_events_are_queued_in_the_list() -> None:
    """The cards of events waiting for sync are marked."""
    events = {event.id: event for event in _service(_store()).list_events()}

    assert events["10"].queued is True
    assert events["11"].queued is False
    assert events["12"].queued is False


def test_local_calendar_events_are_never_queued() -> None:
    """A dirty event in a LOCAL calendar stays unmarked."""
    events = {event.id: event for event in _service(_store()).list_events()}

    assert events["13"].queued is False


def test_occurrences_of_a_dirty_series_are_queued() -> None:
    """A repeating event is matched by its series id."""
    store = FakeCalendarStore(calendars=[calendar_row(1, "me@example.com")])
    row = _event_row(20, 1, 1)
    row["rrule"] = "FREQ=DAILY;COUNT=3"
    store.event_rows = {20: row}

    events = _service(store).list_events()

    assert events
    assert all(event.queued for event in events)


def test_listing_survives_a_failing_dirty_query() -> None:
    """Not knowing the sync state must not hide the events."""
    store = _store()

    def fail() -> set[int]:
        raise RuntimeError("boom")

    store.dirty_event_ids = fail  # type: ignore[method-assign]

    events = _service(store).list_events()

    assert len(events) == 4
    assert not any(event.queued for event in events)


def test_a_write_does_not_flag_the_saved_event_as_queued() -> None:
    """The notice, not the queue flag, tells the form about a phone write."""
    service = _service(_store())
    event = CalendarEvent(
        id="client-id-1",
        summary="New",
        start=START,
        end=START + timedelta(hours=1),
        start_timezone="UTC",
        end_timezone="UTC",
        calendar_id="1",
    )

    assert service.create_event(event).queued is False


def test_service_exposes_save_and_delete_notices() -> None:
    """The form reads these to tell the user Android syncs the change."""
    service = _service(_store())

    assert "Saved on the phone" in service.saved_notice
    assert "Deleted on the phone" in service.deleted_notice
    assert "syncs" in service.saved_notice
    assert "syncs" in service.deleted_notice
