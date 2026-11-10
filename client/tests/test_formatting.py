"""Tests for the Kivy-free formatting helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from kivy_calendar.api import CalendarEvent
from kivy_calendar.formatting import (
    default_event_times,
    format_event_when,
    to_input_value,
)

BERLIN = ZoneInfo("Europe/Berlin")


def _event(start: datetime, end: datetime, *, all_day: bool = False) -> CalendarEvent:
    return CalendarEvent(
        id="event-1",
        summary="Team standup",
        start=start,
        end=end,
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        all_day=all_day,
    )


def test_default_event_times_rounds_up_to_the_next_full_hour() -> None:
    """The prefilled window starts at the next full hour."""
    now = datetime(2026, 11, 9, 14, 20, tzinfo=BERLIN)

    start, end = default_event_times(now)

    assert start == datetime(2026, 11, 9, 15, 0, tzinfo=BERLIN)
    assert end == datetime(2026, 11, 9, 16, 0, tzinfo=BERLIN)


def test_default_event_times_crosses_midnight() -> None:
    """A late-evening start moves the window into the next day."""
    now = datetime(2026, 11, 9, 23, 10, tzinfo=BERLIN)

    start, end = default_event_times(now)

    assert start == datetime(2026, 11, 10, 0, 0, tzinfo=BERLIN)
    assert end - start == timedelta(hours=1)


def test_format_event_when_uses_a_single_time_span_within_one_day() -> None:
    """Same-day events show the date once."""
    event = _event(
        datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN),
        datetime(2026, 11, 6, 10, 30, tzinfo=BERLIN),
    )

    assert format_event_when(event) == "Fri 06 Nov 2026 · 09:00–10:30"


def test_format_event_when_includes_both_days_for_overnight_events() -> None:
    """Overnight events show both dates in the time span."""
    event = _event(
        datetime(2026, 11, 6, 23, 0, tzinfo=BERLIN),
        datetime(2026, 11, 7, 1, 30, tzinfo=BERLIN),
    )

    assert format_event_when(event) == "Fri 06 Nov 2026 · 06 Nov 23:00 – 07 Nov 01:30"


def test_to_input_value_keeps_minute_precision() -> None:
    """Form values drop seconds and keep the UTC offset."""
    value = datetime(2026, 11, 9, 14, 20, 30, tzinfo=BERLIN)

    assert to_input_value(value) == "2026-11-09T14:20+01:00"


def test_format_event_when_shows_a_single_all_day_date() -> None:
    """A one-day all-day event is shown as just its date."""
    event = _event(
        datetime(2026, 11, 6, 0, 0, tzinfo=BERLIN),
        datetime(2026, 11, 7, 0, 0, tzinfo=BERLIN),
        all_day=True,
    )

    assert format_event_when(event) == "Fri 06 Nov 2026"


def test_format_event_when_shows_a_multi_day_all_day_span() -> None:
    """A multi-day all-day event shows its inclusive day range."""
    event = _event(
        datetime(2026, 11, 6, 0, 0, tzinfo=BERLIN),
        datetime(2026, 11, 9, 0, 0, tzinfo=BERLIN),
        all_day=True,
    )

    assert format_event_when(event) == "06 Nov 2026 – 08 Nov 2026"
