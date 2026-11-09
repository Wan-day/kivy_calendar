"""Tests for the Google Calendar recurrence expansion."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from domain.event import Event
from google_calendar.recurrence import expand_event

BERLIN = ZoneInfo("Europe/Berlin")


def _event(
    event_id: str = "event1",
    *,
    summary: str = "Team standup",
    start: datetime | None = None,
    end: datetime | None = None,
    recurrence: list[str] | None = None,
) -> Event:
    """Return a timed event around ``start``."""
    start_time = start if start is not None else datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN)
    end_time = end if end is not None else start_time + timedelta(minutes=30)
    return Event(
        id=event_id,
        calendar_id="primary",
        summary=summary,
        start=start_time,
        end=end_time,
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        recurrence=recurrence,
        extended_properties={},
    )


def test_expand_event_without_recurrence_returns_the_event() -> None:
    """A timed event without a rule maps to itself."""
    event = _event()

    assert expand_event(event) == [event]


def test_expand_event_turns_a_weekly_rule_into_occurrences() -> None:
    """A weekly rule with a count becomes that many concrete events."""
    event = _event(recurrence=["RRULE:FREQ=WEEKLY;COUNT=3"])

    occurrences = expand_event(event)

    assert len(occurrences) == 3
    assert [occurrence.start for occurrence in occurrences] == [
        datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN),
        datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN),
        datetime(2026, 11, 20, 9, 0, tzinfo=BERLIN),
    ]
    assert all(occurrence.recurrence is None for occurrence in occurrences)
    assert len({occurrence.id for occurrence in occurrences}) == 3


def test_expand_event_keeps_the_occurrence_times_in_the_event_zone() -> None:
    """Occurrence ids embed the UTC instant so repeats stay unique."""
    event = _event(recurrence=["RRULE:FREQ=DAILY;COUNT=2"])

    occurrences = expand_event(event)

    assert [occurrence.start for occurrence in occurrences] == [
        datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN),
        datetime(2026, 11, 7, 9, 0, tzinfo=BERLIN),
    ]
    assert occurrences[0].id != occurrences[1].id


def test_expand_event_respects_an_until_bound() -> None:
    """An ``UNTIL`` bound ends the expansion without going past it."""
    event = _event(
        start=datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN),
        end=datetime(2026, 11, 6, 9, 30, tzinfo=BERLIN),
        recurrence=["RRULE:FREQ=DAILY;UNTIL=2026-11-08T00:00:00Z"],
    )

    occurrences = expand_event(event)

    assert [occurrence.start for occurrence in occurrences] == [
        datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN),
        datetime(2026, 11, 7, 9, 0, tzinfo=BERLIN),
    ]


def test_expand_event_falls_back_when_the_frequency_is_unsupported() -> None:
    """An unexpandable rule keeps the series event instead of failing."""
    event = _event(recurrence=["RRULE:FREQ=HOURLY"])

    assert expand_event(event) == [event]


def test_expand_event_bounds_open_ended_rules() -> None:
    """An open-ended rule expands up to a fixed horizon from the series start."""
    event = _event(recurrence=["RRULE:FREQ=WEEKLY"])

    occurrences = expand_event(event)

    assert len(occurrences) > 1
    assert occurrences[0].start == event.start
    assert occurrences[0].recurrence is None
    assert all(occurrence.recurrence is None for occurrence in occurrences)
