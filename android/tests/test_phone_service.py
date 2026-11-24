"""Tests for PhoneCalendarService, the screens' service on Android."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeCalendarStore, FakePermissions, calendar_row, instance_row, millis

from kivy_calendar.models import CalendarEvent, ServiceError
from kivy_calendar.service import AccessGate, CalendarService
from phone_calendar.provider import AndroidCalendarProvider
from phone_calendar.service import PhoneCalendarService

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)


def _service(
    store: FakeCalendarStore,
    permissions: FakePermissions | None = None,
) -> PhoneCalendarService:
    return PhoneCalendarService(
        AndroidCalendarProvider(store, time_zone="Europe/Berlin"),
        permissions or FakePermissions(),
        now=lambda: NOW,
    )


def _store_with_events() -> FakeCalendarStore:
    start = datetime(2026, 11, 24, 10, 0, tzinfo=BERLIN)
    return FakeCalendarStore(
        calendars=[
            calendar_row(1, "me@example.com", primary=1),
            calendar_row(2, "Holidays", access=200),
        ],
        instances=[
            instance_row(
                1, 1, millis(start), millis(start + timedelta(hours=1)), "Review"
            ),
            instance_row(
                2,
                2,
                millis(start + timedelta(hours=3)),
                millis(start + timedelta(hours=4)),
                "Holiday",
            ),
        ],
    )


def test_is_a_calendar_service_with_an_access_gate() -> None:
    """The screens can use it, and the app can ask it for permission."""
    service = _service(FakeCalendarStore())

    as_service: CalendarService = service
    assert isinstance(as_service, AccessGate)


def test_lists_events_for_the_screens() -> None:
    """Phone events arrive as the screens' CalendarEvent values."""
    service = _service(_store_with_events())

    events = service.list_events()

    assert [event.summary for event in events] == ["Review", "Holiday"]
    assert all(isinstance(event, CalendarEvent) for event in events)
    assert events[0].start.tzinfo is not None


def test_reads_a_window_from_30_days_back_to_180_ahead() -> None:
    """The list covers the plan's window around now."""
    store = _store_with_events()

    _service(store).list_events()

    assert store.windows == [
        (millis(NOW - timedelta(days=30)), millis(NOW + timedelta(days=180)))
    ]


def test_offers_only_writable_calendars() -> None:
    """The dropdown lists calendars events can be saved to."""
    calendars = _service(_store_with_events()).list_calendars()

    assert [(c.id, c.summary, c.primary) for c in calendars] == [
        ("1", "me@example.com", True)
    ]


def test_finds_free_slots_around_phone_events() -> None:
    """Free-time suggestions skip the phone's busy events."""
    service = _service(_store_with_events())
    window_start = datetime(2026, 11, 24, 10, 0, tzinfo=BERLIN)

    slots = service.find_free_slots(
        60, window_start, window_start + timedelta(hours=6), "Europe/Berlin"
    )

    assert slots
    assert slots[0].start >= window_start + timedelta(hours=1)


def test_saving_is_not_available_yet() -> None:
    """Writes raise a clear ServiceError until 0.3.0."""
    service = _service(_store_with_events())
    event = service.list_events()[0]

    with pytest.raises(ServiceError) as error:
        service.create_event(event)

    assert error.value.code == "not_supported"
    assert "0.3.0" in error.value.message


def test_missing_permission_has_a_helpful_message() -> None:
    """A permission failure tells the user where to allow access."""
    service = _service(
        FakeCalendarStore(error=RuntimeError("java.lang.SecurityException"))
    )

    with pytest.raises(ServiceError) as error:
        service.list_events()

    assert error.value.code == "permission_denied"
    assert "app settings" in error.value.message


def test_access_gate_passes_through_to_android_permissions() -> None:
    """has_access, request_access and open_settings use the permission API."""
    permissions = FakePermissions(granted=False, answer=True)
    service = _service(FakeCalendarStore(), permissions)
    answers: list[bool] = []

    assert not service.has_access()
    service.request_access(answers.append)
    service.open_settings()

    assert answers == [True]
    assert service.has_access()
    assert permissions.settings_opened == 1


def test_sync_re_reads_the_calendar() -> None:
    """Sync returns the occurrence count."""
    assert _service(_store_with_events()).sync() == 2
