"""Tests for the Kivy-free formatting helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from kivy_calendar.api import CalendarEvent
from kivy_calendar.formatting import (
    default_event_times,
    format_event_when,
    localize_wall_clock,
    to_input_value,
    to_wall_clock_value,
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


def test_localize_wall_clock_follows_daylight_saving_time() -> None:
    """15:00 Europe/Berlin is +01:00 in January and +02:00 in July."""
    winter = localize_wall_clock("2026-01-15T15:00", "Europe/Berlin")
    summer = localize_wall_clock("2026-07-15T15:00", "Europe/Berlin")

    assert winter.isoformat() == "2026-01-15T15:00:00+01:00"
    assert summer.isoformat() == "2026-07-15T15:00:00+02:00"
    assert winter.tzinfo == BERLIN


def test_localize_wall_clock_supports_half_hour_zones() -> None:
    """Half-hour zones such as India keep their real offset."""
    value = localize_wall_clock("2026-11-09T15:00", "Asia/Kolkata")

    assert value.isoformat() == "2026-11-09T15:00:00+05:30"


def test_localize_wall_clock_ignores_a_typed_offset() -> None:
    """Only the chosen zone decides the instant."""
    value = localize_wall_clock("2026-11-09T15:00+01:00", "America/New_York")

    assert value.isoformat() == "2026-11-09T15:00:00-05:00"


def test_localize_wall_clock_rejects_bad_input() -> None:
    """Garbage, unknown zones and DST gaps raise ValueError."""
    with pytest.raises(ValueError):
        localize_wall_clock("nope", "Europe/Berlin")
    with pytest.raises(ValueError):
        localize_wall_clock("2026-11-09T15:00", "Mars/Olympus")
    with pytest.raises(ValueError):
        localize_wall_clock("2026-03-29T02:30", "Europe/Berlin")


def test_to_wall_clock_value_converts_into_the_zone() -> None:
    """The instant is shown as wall-clock time in the given zone."""
    value = datetime(2026, 7, 15, 13, 0, tzinfo=ZoneInfo("UTC"))

    assert to_wall_clock_value(value, "Europe/Berlin") == "2026-07-15T15:00"
