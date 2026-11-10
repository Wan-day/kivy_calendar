"""Tests for the Kivy-free formatting helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from kivy_calendar.api import CalendarEvent
from kivy_calendar.formatting import (
    UTC_OFFSET_LABELS,
    default_event_times,
    format_event_when,
    time_zone_for_offset,
    time_zone_from_label,
    time_zone_label,
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


def test_utc_offset_labels_cover_24_hours() -> None:
    """The dropdown offers one UTC offset per hour, from -11 to +12."""
    assert len(UTC_OFFSET_LABELS) == 24
    assert UTC_OFFSET_LABELS[0] == "UTC-11"
    assert UTC_OFFSET_LABELS[-1] == "UTC+12"
    assert "UTC+0" in UTC_OFFSET_LABELS


def test_time_zone_for_offset_uses_iana_fixed_offsets() -> None:
    """Labels map to real IANA fixed-offset zones."""
    assert time_zone_for_offset(0) == "UTC"
    assert time_zone_for_offset(1) == "Etc/GMT-1"
    assert time_zone_for_offset(-3) == "Etc/GMT+3"


def test_time_zone_labels_round_trip() -> None:
    """Every dropdown label maps to a zone and back to the same label."""
    for label in UTC_OFFSET_LABELS:
        zone = time_zone_from_label(label)
        assert zone is not None
        assert time_zone_label(zone) == label


def test_time_zone_label_keeps_city_zones() -> None:
    """Named zones stay untouched and unknown labels are rejected."""
    assert time_zone_label("Europe/Berlin") == "Europe/Berlin"
    assert time_zone_from_label("Europe/Berlin") is None
    assert time_zone_from_label("UTC+99") is None


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
