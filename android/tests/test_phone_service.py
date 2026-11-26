"""Tests for PhoneCalendarService, the screens' service on Android."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeCalendarStore, FakePermissions, calendar_row, instance_row, millis

from kivy_calendar.models import CalendarEvent, EditScope, ServiceError
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


def test_reads_a_window_from_a_year_back_to_a_year_ahead() -> None:
    """The list covers a year either side of now."""
    store = _store_with_events()

    _service(store).list_events()

    assert store.windows == [
        (millis(NOW - timedelta(days=365)), millis(NOW + timedelta(days=365)))
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


def _new_event(**changes: object) -> CalendarEvent:
    start = datetime(2026, 11, 26, 9, 30, tzinfo=BERLIN)
    values: dict[str, object] = {
        "id": "app-id-7",
        "summary": "Dentist",
        "start": start,
        "end": start + timedelta(hours=1),
        "start_timezone": "Europe/Berlin",
        "end_timezone": "Europe/Berlin",
        "calendar_id": "1",
    }
    values.update(changes)
    return CalendarEvent(**values)  # type: ignore[arg-type]


def _writable_store() -> FakeCalendarStore:
    return FakeCalendarStore(
        calendars=[
            calendar_row(1, "me@example.com", primary=1),
            calendar_row(2, "Work"),
        ]
    )


def test_create_edit_and_delete_round_trip() -> None:
    """The screens can save, change and delete phone events."""
    store = _writable_store()
    service = _service(store)

    created = service.create_event(_new_event())
    listed = service.list_events()
    assert [event.summary for event in listed] == ["Dentist"]

    service.update_event(
        replace(listed[0], summary="Dentist, room 4"), source_calendar_id="1"
    )
    assert [event.summary for event in service.list_events()] == ["Dentist, room 4"]

    queued = service.delete_event(created.id, "1")
    assert queued is False
    assert service.list_events() == []


def test_changing_the_calendar_moves_the_event() -> None:
    """An edit that picks another calendar saves and then moves the event."""
    store = _writable_store()
    service = _service(store)
    service.create_event(_new_event())
    (event,) = service.list_events()

    service.update_event(
        replace(event, summary="Dentist (work)", calendar_id="2"),
        source_calendar_id="1",
    )

    (moved,) = service.list_events()
    assert moved.calendar_id == "2"
    assert moved.summary == "Dentist (work)"
    assert len(store.event_rows) == 1


DAILY = ["RRULE:FREQ=DAILY;COUNT=4"]


def _daily(
    store: FakeCalendarStore,
) -> tuple[PhoneCalendarService, list[CalendarEvent]]:
    """A synced daily series of four, listed for the screens."""
    service = _service(store)
    saved = service.create_event(_new_event(recurrence=DAILY))
    assert saved.recurring_event_id is not None
    store.event_rows[int(saved.recurring_event_id)]["_sync_id"] = "synced"
    return service, service.list_events()


def _titles(service: PhoneCalendarService) -> list[str]:
    return [event.summary for event in service.list_events()]


def test_offers_every_repeat_choice_to_the_form() -> None:
    """The form may ask for a scope and set repeat rules."""
    service = _service(_writable_store())

    assert service.repeat_scopes == (EditScope.THIS, EditScope.FOLLOWING, EditScope.ALL)
    assert service.edits_repeat_rules is True


@pytest.mark.parametrize(
    ("scope", "titles"),
    [
        (EditScope.THIS, ["Dentist", "Dentist", "Check-up", "Dentist"]),
        (EditScope.FOLLOWING, ["Dentist", "Dentist", "Check-up", "Check-up"]),
        (EditScope.ALL, ["Check-up"] * 4),
    ],
)
def test_saving_an_occurrence_follows_the_scope(
    scope: EditScope, titles: list[str]
) -> None:
    """The third of four occurrences is renamed with each scope."""
    store = _writable_store()
    service, events = _daily(store)

    service.update_event(replace(events[2], summary="Check-up"), "1", scope)

    assert _titles(service) == titles


@pytest.mark.parametrize(
    ("scope", "left"),
    [(EditScope.THIS, 3), (EditScope.FOLLOWING, 2), (EditScope.ALL, 0)],
)
def test_deleting_an_occurrence_follows_the_scope(scope: EditScope, left: int) -> None:
    """Deleting the third of four occurrences with each scope."""
    store = _writable_store()
    service, events = _daily(store)

    assert service.delete_event(events[2].id, "1", scope) is False

    assert len(service.list_events()) == left


def test_one_occurrence_cannot_move_to_another_calendar() -> None:
    """Android keeps exceptions in their series' calendar."""
    service, events = _daily(_writable_store())

    with pytest.raises(ServiceError) as error:
        service.update_event(replace(events[1], calendar_id="2"), "1", EditScope.THIS)

    assert "All events" in error.value.message
    assert {event.calendar_id for event in service.list_events()} == {"1"}


def test_moving_all_events_moves_the_series() -> None:
    """With "All events" the whole series ends up in the other calendar."""
    store = _writable_store()
    service, events = _daily(store)

    service.update_event(replace(events[1], calendar_id="2"), "1", EditScope.ALL)

    listed = service.list_events()
    assert len(listed) == 4
    assert {event.calendar_id for event in listed} == {"2"}


def test_a_new_rule_and_calendar_move_the_new_series() -> None:
    """A single event that starts repeating can change calendar in one save."""
    store = _writable_store()
    service = _service(store)
    service.create_event(_new_event())
    (event,) = service.list_events()

    service.update_event(replace(event, recurrence=DAILY, calendar_id="2"), "1")

    listed = service.list_events()
    assert len(listed) == 4
    assert {event.calendar_id for event in listed} == {"2"}


def test_bad_input_is_a_service_error() -> None:
    """An event whose end is before its start is reported, not raised raw."""
    service = _service(_writable_store())
    event = _new_event()

    with pytest.raises(ServiceError) as error:
        service.create_event(replace(event, end=event.start - timedelta(hours=1)))

    assert error.value.code == "invalid_event"
