"""Tests for reading the phone's calendar through AndroidCalendarProvider."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import (
    FakeCalendarStore,
    calendar_row,
    instance_row,
    millis,
    utc_midnight,
)

from core.errors import ErrorCode
from phone_calendar.provider import AndroidCalendarProvider

BERLIN = ZoneInfo("Europe/Berlin")
WINDOW_START = datetime(2026, 11, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 12, 1, tzinfo=UTC)


def _provider(store: FakeCalendarStore) -> AndroidCalendarProvider:
    return AndroidCalendarProvider(store, time_zone="Europe/Berlin")


def _events(store: FakeCalendarStore) -> list:  # type: ignore[type-arg]
    result = _provider(store).list_events(WINDOW_START, WINDOW_END)
    assert result.error is None, result.error
    assert result.value is not None
    return result.value


def test_lists_writable_visible_calendars_primary_first() -> None:
    """Read-only and hidden calendars are not offered for new events."""
    store = FakeCalendarStore(
        calendars=[
            calendar_row(3, "Work"),
            calendar_row(1, "me@example.com", primary=1),
            calendar_row(2, "Holidays in Germany", access=200),
            calendar_row(4, "Hidden", visible=0),
        ]
    )

    result = _provider(store).list_calendars()

    assert result.value is not None
    assert [(c.id, c.summary, c.primary) for c in result.value] == [
        ("1", "me@example.com", True),
        ("3", "Work", False),
    ]


def test_maps_a_timed_event_into_its_own_zone() -> None:
    """Begin/end milliseconds become aware times in the event's zone."""
    start = datetime(2026, 11, 9, 9, 30, tzinfo=BERLIN)
    store = FakeCalendarStore(
        calendars=[calendar_row(1, "Personal")],
        instances=[
            instance_row(
                7,
                1,
                millis(start),
                millis(start + timedelta(minutes=30)),
                "Standup",
                description="Daily",
            )
        ],
    )

    (event,) = _events(store)

    assert event.id == "7"
    assert event.calendar_id == "1"
    assert event.summary == "Standup"
    assert event.description == "Daily"
    assert event.start == start
    assert event.start.tzinfo is not None
    assert event.start_timezone == "Europe/Berlin"
    assert event.end - event.start == timedelta(minutes=30)
    assert event.recurring_event_id is None


def test_maps_an_all_day_event_from_utc_midnights() -> None:
    """All-day rows use UTC midnights and an exclusive end date."""
    store = FakeCalendarStore(
        calendars=[calendar_row(1, "Personal")],
        instances=[
            instance_row(
                8,
                1,
                utc_midnight(date(2026, 11, 25)),
                utc_midnight(date(2026, 11, 26)),
                "Birthday",
                allDay=1,
                eventTimezone="UTC",
            )
        ],
    )

    (event,) = _events(store)

    assert event.all_day
    assert event.start.date() == date(2026, 11, 25)
    assert event.end.date() == date(2026, 11, 26)
    assert event.start_timezone == "UTC"


def test_recurring_occurrences_get_their_own_ids() -> None:
    """Each occurrence of a series is its own event with the series id."""
    first = datetime(2026, 11, 2, 8, 0, tzinfo=BERLIN)
    rows = [
        instance_row(
            9,
            1,
            millis(first + timedelta(days=7 * week)),
            millis(first + timedelta(days=7 * week, hours=1)),
            "Gym",
            rrule="FREQ=WEEKLY",
        )
        for week in range(3)
    ]
    store = FakeCalendarStore(calendars=[calendar_row(1, "Personal")], instances=rows)

    events = _events(store)

    assert len({event.id for event in events}) == 3
    assert all(event.recurring_event_id == "9" for event in events)
    assert events[0].recurrence == ["RRULE:FREQ=WEEKLY"]
    assert events[0].id == f"9_{millis(first)}"


def test_an_exception_of_a_series_points_at_the_series() -> None:
    """A changed occurrence (original_id set) belongs to its series."""
    start = datetime(2026, 11, 10, 8, 0, tzinfo=BERLIN)
    store = FakeCalendarStore(
        calendars=[calendar_row(1, "Personal")],
        instances=[
            instance_row(
                12,
                1,
                millis(start),
                millis(start + timedelta(hours=1)),
                original_id=9,
            )
        ],
    )

    (event,) = _events(store)

    assert event.recurring_event_id == "9"
    assert event.id == f"12_{millis(start)}"


def test_skips_cancelled_occurrences_and_hidden_calendars() -> None:
    """Cancelled occurrences and events in hidden calendars are not listed."""
    start = datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN)
    begin, end = millis(start), millis(start + timedelta(hours=1))
    store = FakeCalendarStore(
        calendars=[calendar_row(1, "Shown"), calendar_row(2, "Hidden", visible=0)],
        instances=[
            instance_row(1, 1, begin, end, "Kept"),
            instance_row(2, 1, begin, end, "Cancelled", eventStatus=2),
            instance_row(3, 2, begin, end, "In hidden calendar"),
        ],
    )

    assert [event.summary for event in _events(store)] == ["Kept"]


def test_marks_free_and_read_only_events() -> None:
    """Free events and events in read-only calendars carry those hints."""
    start = datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN)
    begin, end = millis(start), millis(start + timedelta(hours=1))
    store = FakeCalendarStore(
        calendars=[calendar_row(1, "Mine"), calendar_row(2, "Holidays", access=200)],
        instances=[
            instance_row(1, 1, begin, end, "Free time", availability=1),
            instance_row(2, 2, begin, end, "Holiday"),
        ],
    )

    events = {event.summary: event for event in _events(store)}

    assert events["Free time"].transparent
    assert not events["Free time"].calendar_read_only
    assert events["Holiday"].calendar_read_only


def test_repairs_zero_length_events_and_unknown_zones() -> None:
    """Android allows end == begin and odd zones; the event stays listable."""
    start = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
    store = FakeCalendarStore(
        calendars=[calendar_row(1, "Mine")],
        instances=[
            instance_row(
                1, 1, millis(start), millis(start), "Reminder", eventTimezone="Mars"
            )
        ],
    )

    (event,) = _events(store)

    assert event.start_timezone == "Europe/Berlin"
    assert event.end > event.start


def test_queries_the_requested_window_in_milliseconds() -> None:
    """The store is asked for exactly the window, in epoch milliseconds."""
    store = FakeCalendarStore(calendars=[calendar_row(1, "Mine")])

    _events(store)

    assert store.windows == [(millis(WINDOW_START), millis(WINDOW_END))]


def test_a_missing_permission_is_reported_not_raised() -> None:
    """A SecurityException from Android becomes a PERMISSION_DENIED result."""
    store = FakeCalendarStore(
        error=RuntimeError("JVM exception occurred: java.lang.SecurityException")
    )

    calendars = _provider(store).list_calendars()
    events = _provider(store).list_events(WINDOW_START, WINDOW_END)

    assert calendars.error is not None
    assert calendars.error.code == ErrorCode.PERMISSION_DENIED
    assert events.error is not None
    assert events.error.code == ErrorCode.PERMISSION_DENIED


def test_writes_are_not_available_yet() -> None:
    """Saving arrives in 0.3.0; until then writes return INVALID_STATE."""
    provider = _provider(FakeCalendarStore())

    result = provider.delete_event("1", "7")

    assert result.error is not None
    assert result.error.code == ErrorCode.INVALID_STATE


def test_get_event_finds_a_listed_occurrence() -> None:
    """get_event looks the id up among the listed occurrences."""
    start = datetime.now(UTC).replace(microsecond=0)
    store = FakeCalendarStore(
        calendars=[calendar_row(1, "Mine")],
        instances=[
            instance_row(5, 1, millis(start), millis(start + timedelta(hours=1)))
        ],
    )
    provider = _provider(store)

    found = provider.get_event("1", "5")
    missing = provider.get_event("1", "6")

    assert found.value is not None and found.value.id == "5"
    assert missing.error is None and missing.value is None
