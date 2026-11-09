"""Tests for the pure event filter and sort helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from kivy_calendar.api import CalendarEvent
from kivy_calendar.filtering import (
    DEFAULT_SORT,
    DEFAULT_SORT_LABEL,
    SORT_BY_LABEL,
    SORT_LABELS,
    filter_events,
    parse_date_input,
    sort_events,
)

BERLIN = ZoneInfo("Europe/Berlin")


def _event(event_id: str, *, summary: str, start: datetime) -> CalendarEvent:
    """Return a timed event around ``start``."""
    return CalendarEvent(
        id=event_id,
        summary=summary,
        start=start,
        end=start + timedelta(hours=1),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
    )


def _event_at(event_id: str, *, summary: str, day: int, hour: int) -> CalendarEvent:
    """Return an event on November ``day`` at ``hour`` in Berlin."""
    start = datetime(2026, 11, day, hour, 0, tzinfo=BERLIN)
    return _event(event_id, summary=summary, start=start)


def test_filter_events_matches_the_name_case_insensitively() -> None:
    """The name filter is a substring match without regard to case."""
    events = [
        _event_at("e1", summary="Team Standup", day=9, hour=9),
        _event_at("e2", summary="Dentist", day=10, hour=9),
    ]

    assert [event.id for event in filter_events(events, name="standup")] == ["e1"]
    assert [event.id for event in filter_events(events, name="  TEAM  ")] == ["e1"]
    assert len(filter_events(events, name="dentist")) == 1


def test_filter_events_without_a_name_returns_every_event() -> None:
    """A blank name filter keeps the list unfiltered."""
    events = [
        _event_at("e1", summary="Team Standup", day=9, hour=9),
        _event_at("e2", summary="Dentist", day=10, hour=9),
    ]

    assert [event.id for event in filter_events(events)] == ["e1", "e2"]


def test_filter_events_bounds_by_local_date() -> None:
    """The date bounds use the event's local calendar date, not the UTC one."""
    start = datetime(2026, 11, 9, 0, 30, tzinfo=BERLIN)
    events = [_event("e1", summary="Night flight", start=start)]

    assert len(filter_events(events, date_from=date(2026, 11, 9))) == 1
    assert len(filter_events(events, date_from=date(2026, 11, 10))) == 0
    in_range = filter_events(
        events,
        date_from=date(2026, 11, 9),
        date_to=date(2026, 11, 9),
    )
    assert len(in_range) == 1
    out_of_range = filter_events(
        events,
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 9),
    )
    assert len(out_of_range) == 0


def test_sort_events_orders_by_start_then_id() -> None:
    """The default sort is by start time and then event id."""
    events = [
        _event_at("e2", summary="Second", day=10, hour=9),
        _event_at("e1", summary="First", day=9, hour=9),
    ]

    assert [event.id for event in sort_events(events)] == ["e1", "e2"]


def test_sort_events_orders_by_start_descending() -> None:
    """The newest sort order lists the latest events first."""
    events = [
        _event_at("e1", summary="First", day=9, hour=9),
        _event_at("e2", summary="Second", day=10, hour=9),
    ]

    ordered = sort_events(events, order="start_desc")
    assert [event.id for event in ordered] == ["e2", "e1"]


def test_sort_events_orders_by_name() -> None:
    """The name sort is case-insensitive."""
    events = [
        _event_at("e2", summary="zebra", day=10, hour=9),
        _event_at("e1", summary="Alpha", day=9, hour=9),
    ]

    assert [event.id for event in sort_events(events, order="name")] == ["e1", "e2"]


def test_parse_date_input_reads_blank_and_valid_values() -> None:
    """The date input parser accepts blanks and ``YYYY-MM-DD`` dates."""
    assert parse_date_input("") is None
    assert parse_date_input("   ") is None
    assert parse_date_input("2026-11-09") == date(2026, 11, 9)
    assert parse_date_input("not-a-date") is None


def test_sort_labels_map_to_sort_orders() -> None:
    """The spinner labels map onto the pure sort orders."""
    assert DEFAULT_SORT == "start"
    assert DEFAULT_SORT_LABEL == "Start: oldest first"
    assert SORT_LABELS[-1] == "Name: A-Z"
    assert SORT_BY_LABEL["Name: A-Z"] == "name"
