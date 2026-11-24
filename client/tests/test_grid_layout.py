"""Tests for the pure week-grid layout."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from kivy_calendar.api import CalendarEvent
from kivy_calendar.grid_layout import (
    at_local,
    build_month,
    build_week,
    month_title,
    month_weeks,
    round_down,
    week_days,
    week_title,
)

BERLIN = ZoneInfo("Europe/Berlin")
# Monday 9 Nov 2026 starts the week of the tests.
MONDAY = date(2026, 11, 9)
TUESDAY = date(2026, 11, 10)


def _event(
    event_id: str,
    start: datetime,
    end: datetime,
    *,
    all_day: bool = False,
) -> CalendarEvent:
    """Return an event in Berlin."""
    return CalendarEvent(
        id=event_id,
        summary=event_id,
        start=start,
        end=end,
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        all_day=all_day,
    )


def _timed(
    event_id: str, day: int, start: tuple[int, int], end: tuple[int, int]
) -> CalendarEvent:
    """Return a timed event on 2026-11-``day`` from ``start`` to ``end``."""
    return _event(
        event_id,
        datetime(2026, 11, day, *start, tzinfo=BERLIN),
        datetime(2026, 11, day, *end, tzinfo=BERLIN),
    )


def test_week_days_start_on_monday() -> None:
    """Any day of the week gives the same Monday-to-Sunday list."""
    expected = [MONDAY + timedelta(days=i) for i in range(7)]
    assert week_days(MONDAY) == expected
    assert week_days(date(2026, 11, 11)) == expected
    assert week_days(date(2026, 11, 15)) == expected
    assert week_days(date(2026, 11, 16))[0] == date(2026, 11, 16)


def test_week_days_cross_a_year_end() -> None:
    """A week can span two years."""
    days = week_days(date(2026, 12, 31))
    assert days[0] == date(2026, 12, 28)
    assert days[-1] == date(2027, 1, 3)


def test_week_title_forms() -> None:
    """The title names the range once per month and year."""
    assert week_title(week_days(MONDAY)) == "9 – 15 Nov 2026"
    assert week_title(week_days(date(2026, 11, 30))) == "30 Nov – 6 Dec 2026"
    assert week_title(week_days(date(2026, 12, 31))) == "28 Dec 2026 – 3 Jan 2027"


def test_empty_week() -> None:
    """A week without events has seven empty days."""
    layout = build_week([], MONDAY, BERLIN)

    assert layout.is_empty
    assert len(layout.days) == 7
    assert all(layout.timed[d] == [] and layout.all_day[d] == [] for d in layout.days)


def test_timed_event_gets_minutes_in_its_day() -> None:
    """A single event fills its day column from start to end."""
    layout = build_week([_timed("a", 11, (9, 30), (10, 45))], MONDAY, BERLIN)

    (placed,) = layout.timed[date(2026, 11, 11)]
    assert (placed.start_minute, placed.end_minute) == (570, 645)
    assert (placed.lane, placed.lanes) == (0, 1)
    assert not layout.is_empty


def test_events_outside_the_week_are_left_out() -> None:
    """Events before or after the week do not show."""
    before = _timed("before", 8, (23, 0), (23, 59))
    after = _timed("after", 16, (0, 0), (1, 0))

    assert build_week([before, after], MONDAY, BERLIN).is_empty


def test_event_ending_at_midnight_stays_on_its_day() -> None:
    """An event ending exactly at midnight does not leak into the next day."""
    event = _event(
        "late",
        datetime(2026, 11, 9, 22, 0, tzinfo=BERLIN),
        datetime(2026, 11, 10, 0, 0, tzinfo=BERLIN),
    )
    layout = build_week([event], MONDAY, BERLIN)

    assert [p.end_minute for p in layout.timed[MONDAY]] == [1440]
    assert layout.timed[TUESDAY] == []


def test_event_crossing_midnight_appears_on_each_day() -> None:
    """A night event is clipped to every day it touches."""
    event = _event(
        "night",
        datetime(2026, 11, 9, 22, 0, tzinfo=BERLIN),
        datetime(2026, 11, 10, 2, 0, tzinfo=BERLIN),
    )
    layout = build_week([event], MONDAY, BERLIN)

    (first,) = layout.timed[MONDAY]
    (second,) = layout.timed[TUESDAY]
    assert (first.start_minute, first.end_minute) == (1320, 1440)
    assert (second.start_minute, second.end_minute) == (0, 120)


def test_multi_day_timed_event_fills_the_middle_days() -> None:
    """A three-day event covers the whole middle day."""
    event = _event(
        "trip",
        datetime(2026, 11, 9, 18, 0, tzinfo=BERLIN),
        datetime(2026, 11, 11, 6, 0, tzinfo=BERLIN),
    )
    layout = build_week([event], MONDAY, BERLIN)

    spans = [
        (p.start_minute, p.end_minute) for d in layout.days for p in layout.timed[d]
    ]
    assert spans == [(1080, 1440), (0, 1440), (0, 360)]


def test_event_from_the_previous_week_clips_into_this_one() -> None:
    """An event that began on Sunday last week shows on Monday."""
    event = _event(
        "carry",
        datetime(2026, 11, 8, 23, 0, tzinfo=BERLIN),
        datetime(2026, 11, 9, 1, 0, tzinfo=BERLIN),
    )
    layout = build_week([event], MONDAY, BERLIN)

    (placed,) = layout.timed[MONDAY]
    assert (placed.start_minute, placed.end_minute) == (0, 60)


def test_overlapping_events_share_lanes() -> None:
    """Two overlapping events sit side by side; a later one reuses lane 0."""
    a = _timed("a", 9, (9, 0), (11, 0))
    b = _timed("b", 9, (10, 0), (12, 0))
    c = _timed("c", 9, (11, 0), (12, 0))
    layout = build_week([c, b, a], MONDAY, BERLIN)

    lanes = {p.event.id: (p.lane, p.lanes) for p in layout.timed[MONDAY]}
    assert lanes == {"a": (0, 2), "b": (1, 2), "c": (0, 2)}


def test_separate_clusters_do_not_share_lane_counts() -> None:
    """Events that only touch end to end keep one full-width lane each."""
    a = _timed("a", 9, (9, 0), (10, 0))
    b = _timed("b", 9, (10, 0), (11, 0))
    layout = build_week([a, b], MONDAY, BERLIN)

    assert {(p.lane, p.lanes) for p in layout.timed[MONDAY]} == {(0, 1)}


def test_three_way_overlap_uses_three_lanes() -> None:
    """Three events at the same time get three lanes."""
    events = [_timed(name, 9, (9, 0), (10, 0)) for name in "abc"]
    layout = build_week(events, MONDAY, BERLIN)

    assert sorted(p.lane for p in layout.timed[MONDAY]) == [0, 1, 2]
    assert {p.lanes for p in layout.timed[MONDAY]} == {3}


def test_short_events_get_a_minimum_height() -> None:
    """A zero-length event is stretched so it can be tapped."""
    event = _timed("blip", 9, (9, 0), (9, 0))
    layout = build_week([event], MONDAY, BERLIN)

    (placed,) = layout.timed[MONDAY]
    assert (placed.start_minute, placed.end_minute) == (540, 555)


def test_all_day_events_go_to_the_strip_on_each_covered_day() -> None:
    """An all-day event is listed per day and never placed in the grid."""
    single = _event(
        "holiday",
        datetime(2026, 11, 10, 0, 0, tzinfo=BERLIN),
        datetime(2026, 11, 11, 0, 0, tzinfo=BERLIN),
        all_day=True,
    )
    span = _event(
        "conference",
        datetime(2026, 11, 12, 0, 0, tzinfo=BERLIN),
        datetime(2026, 11, 15, 0, 0, tzinfo=BERLIN),
        all_day=True,
    )
    layout = build_week([span, single], MONDAY, BERLIN)

    listed = {d.day: [e.id for e in layout.all_day[d]] for d in layout.days}
    assert listed == {
        9: [],
        10: ["holiday"],
        11: [],
        12: ["conference"],
        13: ["conference"],
        14: ["conference"],
        15: [],
    }
    assert all(layout.timed[d] == [] for d in layout.days)


def test_all_day_event_running_into_the_week_is_listed() -> None:
    """A multi-day all-day event that started last week shows from Monday."""
    event = _event(
        "camp",
        datetime(2026, 11, 7, 0, 0, tzinfo=BERLIN),
        datetime(2026, 11, 10, 0, 0, tzinfo=BERLIN),
        all_day=True,
    )
    layout = build_week([event], MONDAY, BERLIN)

    assert [d.day for d in layout.days if layout.all_day[d]] == [9]


def test_timed_event_of_exactly_24_hours_stays_in_the_grid() -> None:
    """Only ``all_day`` events use the strip; a 24 h timed event is a block."""
    event = _event(
        "long",
        datetime(2026, 11, 10, 0, 0, tzinfo=BERLIN),
        datetime(2026, 11, 11, 0, 0, tzinfo=BERLIN),
    )
    layout = build_week([event], MONDAY, BERLIN)

    spans = [(p.start_minute, p.end_minute) for p in layout.timed[TUESDAY]]
    assert spans == [(0, 1440)]
    assert all(layout.all_day[d] == [] for d in layout.days)


def test_times_are_converted_to_the_grid_zone() -> None:
    """A UTC event shows at its Berlin wall-clock time (UTC+1 in November)."""
    event = _event(
        "utc",
        datetime(2026, 11, 9, 8, 0, tzinfo=UTC),
        datetime(2026, 11, 9, 9, 0, tzinfo=UTC),
    )
    layout = build_week([event], MONDAY, BERLIN)

    (placed,) = layout.timed[MONDAY]
    assert (placed.start_minute, placed.end_minute) == (540, 600)


def test_events_move_to_the_day_they_fall_on_in_the_grid_zone() -> None:
    """Late evening UTC is already the next day in Berlin."""
    event = _event(
        "late",
        datetime(2026, 11, 9, 23, 30, tzinfo=UTC),
        datetime(2026, 11, 10, 0, 30, tzinfo=UTC),
    )
    layout = build_week([event], MONDAY, BERLIN)

    assert layout.timed[MONDAY] == []
    (placed,) = layout.timed[TUESDAY]
    assert placed.start_minute == 30


def test_at_local_builds_aware_times_and_round_down_snaps() -> None:
    """Tapped slots become aware datetimes on the half hour."""
    value = at_local(MONDAY, 9 * 60 + 30, BERLIN)

    assert value == datetime(2026, 11, 9, 9, 30, tzinfo=BERLIN)
    assert at_local(date(2026, 7, 1), 60).utcoffset() is not None
    assert [round_down(m) for m in (0, 29, 30, 59, 61)] == [0, 0, 30, 30, 60]


def test_month_weeks_include_neighbouring_days() -> None:
    """November 2026 spans Mon 26 Oct to Sun 6 Dec: six full rows."""
    weeks = month_weeks(date(2026, 11, 15))

    assert len(weeks) == 6
    assert all(len(week) == 7 for week in weeks)
    assert weeks[0][0] == date(2026, 10, 26)
    assert weeks[-1][-1] == date(2026, 12, 6)
    assert all(week[0].weekday() == 0 for week in weeks)


def test_month_weeks_have_five_rows_when_the_month_fits() -> None:
    """October 2026 needs only five Monday-first rows."""
    weeks = month_weeks(date(2026, 10, 1))

    assert len(weeks) == 5
    assert weeks[0][0] == date(2026, 9, 28)
    assert weeks[-1][-1] == date(2026, 11, 1)


def test_month_title() -> None:
    """The title is the full month name and the year."""
    assert month_title(date(2026, 11, 24)) == "November 2026"


def test_month_lists_multi_day_and_all_day_events_on_every_day() -> None:
    """A three-day all-day event and an overnight event fill each day."""
    holiday = _event(
        "holiday",
        datetime(2026, 11, 10, tzinfo=BERLIN),
        datetime(2026, 11, 13, tzinfo=BERLIN),
        all_day=True,
    )
    night = _event(
        "night",
        datetime(2026, 11, 10, 22, tzinfo=BERLIN),
        datetime(2026, 11, 11, 2, tzinfo=BERLIN),
    )

    layout = build_month([holiday, night], date(2026, 11, 1), BERLIN)

    def ids(day: int) -> list[str]:
        return [e.id for e in layout.events[date(2026, 11, day)]]

    assert ids(9) == []
    assert ids(10) == ["holiday", "night"]
    assert ids(11) == ["holiday", "night"]
    assert ids(12) == ["holiday"]
    assert ids(13) == []


def test_month_event_ending_at_midnight_does_not_touch_the_next_day() -> None:
    """A timed event ending exactly at 00:00 stays on its own day."""
    evening = _event(
        "evening",
        datetime(2026, 11, 10, 20, tzinfo=BERLIN),
        datetime(2026, 11, 11, 0, tzinfo=BERLIN),
    )

    layout = build_month([evening], date(2026, 11, 1), BERLIN)

    assert [e.id for e in layout.events[date(2026, 11, 10)]] == ["evening"]
    assert layout.events[date(2026, 11, 11)] == []


def test_month_sorts_all_day_first_then_by_start() -> None:
    """Within a day, all-day events come first, then timed ones by start."""
    late = _timed("late", 10, (15, 0), (16, 0))
    early = _timed("early", 10, (8, 0), (9, 0))
    all_day = _event(
        "all-day",
        datetime(2026, 11, 10, tzinfo=BERLIN),
        datetime(2026, 11, 11, tzinfo=BERLIN),
        all_day=True,
    )

    layout = build_month([late, all_day, early], date(2026, 11, 1), BERLIN)

    assert [e.id for e in layout.events[date(2026, 11, 10)]] == [
        "all-day",
        "early",
        "late",
    ]


def test_month_shows_events_on_neighbouring_month_days_and_skips_others() -> None:
    """Leading and trailing cells get events; days off the grid are dropped."""
    leading = _timed("leading", 1, (9, 0), (10, 0))
    october = _event(
        "october",
        datetime(2026, 10, 28, 9, tzinfo=BERLIN),
        datetime(2026, 10, 28, 10, tzinfo=BERLIN),
    )
    far = _event(
        "far",
        datetime(2026, 9, 1, 9, tzinfo=BERLIN),
        datetime(2026, 9, 1, 10, tzinfo=BERLIN),
    )

    layout = build_month([leading, october, far], date(2026, 11, 1), BERLIN)

    assert [e.id for e in layout.events[date(2026, 10, 28)]] == ["october"]
    assert "far" not in [e.id for d in layout.events.values() for e in d]
    assert layout.days[0] == date(2026, 10, 26)
    assert not layout.is_empty


def test_month_converts_times_to_the_grid_zone() -> None:
    """A late-evening UTC event lands on the next day in Berlin."""
    event = _event(
        "utc",
        datetime(2026, 11, 10, 23, 30, tzinfo=UTC),
        datetime(2026, 11, 11, 0, 30, tzinfo=UTC),
    )

    layout = build_month([event], date(2026, 11, 1), BERLIN)

    assert layout.events[date(2026, 11, 10)] == []
    assert [e.id for e in layout.events[date(2026, 11, 11)]] == ["utc"]
    assert build_month([], date(2026, 11, 1), BERLIN).is_empty
