"""Tests for the calendar service interface and the in-memory service."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from kivy_calendar.api import BackendClient, BackendError
from kivy_calendar.memory_service import (
    PERSONAL_CALENDAR,
    WORK_CALENDAR,
    InMemoryCalendarService,
    sample_events,
)
from kivy_calendar.models import CalendarEvent, ServiceError
from kivy_calendar.service import CalendarService, choose_service

BERLIN = ZoneInfo("Europe/Berlin")


def _event(
    event_id: str = "evt-1",
    start: datetime | None = None,
    minutes: int = 60,
    calendar_id: str = "",
) -> CalendarEvent:
    begin = start or datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN)
    return CalendarEvent(
        id=event_id,
        summary="Standup",
        start=begin,
        end=begin + timedelta(minutes=minutes),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        calendar_id=calendar_id,
    )


def test_both_services_satisfy_the_interface() -> None:
    """The screens can take either service as a CalendarService."""
    services: list[CalendarService] = [
        InMemoryCalendarService(),
        BackendClient(base_url="http://localhost:8000", token="t"),
    ]
    assert len(services) == 2


def test_backend_errors_are_service_errors() -> None:
    """Screens catch ServiceError, which includes backend failures."""
    error = BackendError(503, "upstream_error", "Google is down")

    assert isinstance(error, ServiceError)
    assert (error.status_code, error.code, error.message) == (
        503,
        "upstream_error",
        "Google is down",
    )


def test_memory_service_creates_lists_updates_and_deletes() -> None:
    """Events round-trip; new events land in the primary calendar."""
    service = InMemoryCalendarService()

    created = service.create_event(_event())
    assert created.calendar_id == PERSONAL_CALENDAR.id
    assert service.list_events() == [created]

    moved = service.update_event(
        replace(created, summary="Daily sync", calendar_id=WORK_CALENDAR.id),
        source_calendar_id=PERSONAL_CALENDAR.id,
    )
    assert service.list_events() == [moved]
    assert moved.summary == "Daily sync"

    assert service.delete_event(moved.id) is False
    assert service.list_events() == []


def test_memory_service_create_is_idempotent_but_rejects_clashes() -> None:
    """Saving the same new event twice keeps one copy."""
    service = InMemoryCalendarService()
    event = _event()

    service.create_event(event)
    service.create_event(event)
    assert len(service.list_events()) == 1

    with pytest.raises(ServiceError) as error:
        service.create_event(replace(event, summary="Other"))
    assert error.value.code == "already_exists"


def test_memory_service_reports_missing_events() -> None:
    """Updating or deleting an unknown event is a not_found error."""
    service = InMemoryCalendarService()

    with pytest.raises(ServiceError) as update_error:
        service.update_event(_event())
    with pytest.raises(ServiceError) as delete_error:
        service.delete_event("missing")

    assert update_error.value.code == "not_found"
    assert delete_error.value.code == "not_found"


def test_memory_service_lists_events_earliest_first() -> None:
    """The list is sorted by start time."""
    late = _event("late", datetime(2026, 11, 9, 15, 0, tzinfo=BERLIN))
    early = _event("early", datetime(2026, 11, 9, 8, 0, tzinfo=BERLIN))
    service = InMemoryCalendarService([late, early])

    assert [event.id for event in service.list_events()] == ["early", "late"]
    assert service.sync() == 2


def test_free_slots_skip_busy_times_on_quarter_hours() -> None:
    """Slots start on 15-minute boundaries and avoid existing events."""
    busy = _event(start=datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN), minutes=90)
    service = InMemoryCalendarService([busy])
    window_start = datetime(2026, 11, 9, 8, 50, tzinfo=BERLIN)

    slots = service.find_free_slots(
        30, window_start, window_start + timedelta(hours=3), "Europe/Berlin"
    )

    starts = [slot.start.strftime("%H:%M") for slot in slots]
    assert starts[0] == "10:30"
    assert all(slot.end - slot.start == timedelta(minutes=30) for slot in slots)
    assert all(slot.start.minute % 15 == 0 for slot in slots)
    assert len(slots) <= 5


def test_free_slots_reject_naive_windows_and_unknown_zones() -> None:
    """Bad input is a ServiceError, never a crash."""
    service = InMemoryCalendarService()
    aware = datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN)

    with pytest.raises(ServiceError):
        service.find_free_slots(30, aware.replace(tzinfo=None), aware, "UTC")
    with pytest.raises(ServiceError):
        service.find_free_slots(30, aware, aware + timedelta(hours=1), "Mars/Base")


def test_sample_events_are_around_now() -> None:
    """Sample data covers today and the next two days, with one all-day event."""
    now = datetime(2026, 11, 24, 8, 0, tzinfo=BERLIN)

    events = sample_events(now)

    days = {event.start.date() for event in events}
    assert min(days) == now.date()
    assert max(days) == now.date() + timedelta(days=2)
    assert sum(event.all_day for event in events) == 1
    assert len({event.id for event in events}) == len(events)


def test_choose_service_uses_memory_on_request_on_any_platform() -> None:
    """KIVY_CALENDAR_SERVICE=memory runs on sample events, also on Android."""
    android, android_error = choose_service(
        {"KIVY_CALENDAR_SERVICE": "memory"}, platform="android"
    )
    requested, requested_error = choose_service(
        {"KIVY_CALENDAR_SERVICE": "memory"}, platform="linux"
    )

    assert isinstance(android, InMemoryCalendarService)
    assert isinstance(requested, InMemoryCalendarService)
    assert android_error is None and requested_error is None
    assert android.list_events()


def test_choose_service_uses_the_backend_on_desktop() -> None:
    """With a token, desktop talks to the backend from the given environment."""
    service, error = choose_service(
        {
            "BACKEND_API_TOKEN": "secret",
            "KIVY_CALENDAR_API_BASE_URL": "http://10.0.0.2:8000",
        },
        platform="linux",
    )

    assert error is None
    assert isinstance(service, BackendClient)
    assert service.base_url == "http://10.0.0.2:8000"


def test_choose_service_explains_a_missing_token() -> None:
    """Without a token the app still starts and says how to fix it."""
    service, error = choose_service({}, platform="linux")

    assert service is None
    assert error is not None
    assert "BACKEND_API_TOKEN" in error
    assert "KIVY_CALENDAR_SERVICE=memory" in error


def test_choose_service_reports_a_missing_phone_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the Android package the app starts and says why."""
    import sys

    monkeypatch.setitem(sys.modules, "phone_calendar", None)

    service, error = choose_service({}, platform="android")

    assert service is None
    assert error is not None and "phone calendar" in error


def test_memory_service_is_not_an_access_gate() -> None:
    """Only services that need permission show the permission screen."""
    from kivy_calendar.service import AccessGate

    assert not isinstance(InMemoryCalendarService(), AccessGate)
