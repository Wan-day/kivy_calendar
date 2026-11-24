"""Tests for the week view widget and its place on the main screen.

Kivy is optional in CI, so these tests are skipped when it is not installed.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.metrics import dp  # noqa: E402

from kivy_calendar.api import CalendarEvent  # noqa: E402
from kivy_calendar.screens.week import GUTTER, HOUR_HEIGHT, WeekView  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
# Wednesday 11 Nov 2026, noon: the "now" of these tests.
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=BERLIN)
MONDAY = date(2026, 11, 9)


def _event(
    event_id: str,
    day: int,
    start_hour: int,
    end_hour: int,
    *,
    summary: str = "",
    all_day: bool = False,
) -> CalendarEvent:
    """Return an event on 2026-11-``day`` in Berlin."""
    return CalendarEvent(
        id=event_id,
        summary=summary or event_id,
        start=datetime(2026, 11, day, start_hour, tzinfo=BERLIN),
        end=datetime(2026, 11, day, end_hour, tzinfo=BERLIN)
        if not all_day
        else datetime(2026, 11, day, tzinfo=BERLIN) + timedelta(days=1),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        calendar_id="work@example.com",
        all_day=all_day,
    )


class Recorder:
    """Collects what the view reports."""

    def __init__(self) -> None:
        self.opened: list[CalendarEvent] = []
        self.new_starts: list[datetime] = []


def _week(*events: CalendarEvent) -> tuple[WeekView, Recorder]:
    """Return a week view of 2026-11-09..15 sized like a phone."""
    recorder = Recorder()
    view = WeekView(
        recorder.opened.append,
        recorder.new_starts.append,
        tz=BERLIN,
        now=lambda: NOW,
        size=(dp(371), dp(560)),
        size_hint=(None, None),
    )
    view.set_events(list(events))
    return view, recorder


def _centre(view: WeekView, block: Any) -> tuple[float, float]:
    """Return the window point at the middle of ``block``."""
    return block.x + block.width / 2, block.y + block.height / 2


def _day_holders(view: WeekView) -> list[Any]:
    """Return the seven day header cells, Monday first."""
    return list(reversed(view.day_header.children[:-1]))


def test_opens_on_the_current_week() -> None:
    """The title shows the week containing today, Monday first."""
    view, _ = _week()

    assert view.title_label.text == "9 – 15 Nov 2026"
    assert view.week_layout is not None
    assert view.week_layout.days[0] == MONDAY
    assert [h.day for h in _day_holders(view)] == view.week_layout.days


def test_week_navigation() -> None:
    """Arrows move by a week and Today returns."""
    view, _ = _week()

    view.next_button.dispatch("on_release")
    assert view.title_label.text == "16 – 22 Nov 2026"
    view.next_button.dispatch("on_release")
    view.previous_button.dispatch("on_release")
    view.previous_button.dispatch("on_release")
    view.previous_button.dispatch("on_release")
    assert view.title_label.text == "2 – 8 Nov 2026"
    view.today_button.dispatch("on_release")
    assert view.title_label.text == "9 – 15 Nov 2026"


def test_events_show_as_blocks_on_their_day_and_time() -> None:
    """A block sits in its column at its hour, one hour tall."""
    view, _ = _week(_event("standup", 11, 9, 10))
    view.grid._place()

    (block,) = view.blocks
    column = view.grid.column_width
    assert block.x > view.grid.x + GUTTER + 2 * column
    assert block.x < view.grid.x + GUTTER + 3 * column
    assert block.height == pytest.approx(HOUR_HEIGHT - dp(2))
    assert block.top == pytest.approx(view.grid.top - 9 * HOUR_HEIGHT - 1)
    assert block.text == "standup"


def test_overlapping_events_sit_side_by_side() -> None:
    """Two overlapping events split the column width."""
    view, _ = _week(_event("a", 11, 9, 11), _event("b", 11, 10, 12))

    first, second = sorted(view.blocks, key=lambda b: b.x)
    assert first.right <= second.x + 1
    assert first.width == pytest.approx(second.width)
    assert first.width < view.grid.column_width / 2


def test_tapping_a_block_opens_the_event() -> None:
    """A release on a block calls open_event with its event."""
    event = _event("standup", 11, 9, 10)
    view, recorder = _week(event)

    view.blocks[0].dispatch("on_release")

    assert recorder.opened == [event]
    assert recorder.new_starts == []


def test_all_day_events_fill_the_strip_and_open() -> None:
    """All-day events appear as chips above the grid; none means no strip."""
    view, recorder = _week()
    assert view.all_day_strip.height == 0

    event = _event("holiday", 12, 0, 0, all_day=True)
    view.set_events([event])

    assert view.all_day_strip.height > 0
    (chip,) = view.all_day_blocks
    assert view.blocks == []
    chip.dispatch("on_release")
    assert recorder.opened == [event]


def test_tapping_empty_space_asks_for_a_new_event_rounded_to_30_minutes() -> None:
    """A tap at 14:50 on Thursday becomes Thursday 14:30 in the local zone."""
    view, recorder = _week()
    grid = view.grid
    column = grid.column_width
    x = grid.x + GUTTER + 3.5 * column
    y = grid.top - (14 * 60 + 50) * grid.height / 1440

    assert grid.tap(x, y)

    assert recorder.new_starts == [datetime(2026, 11, 12, 14, 30, tzinfo=BERLIN)]
    assert recorder.new_starts[0].utcoffset() == timedelta(hours=1)


def test_tapping_the_hour_labels_does_nothing() -> None:
    """The time gutter is not a slot."""
    view, recorder = _week()
    grid = view.grid

    assert not grid.tap(grid.x + GUTTER / 2, grid.top - 5 * HOUR_HEIGHT)
    assert recorder.new_starts == []


def test_touch_on_empty_space_is_a_tap_but_a_drag_is_not() -> None:
    """A real touch down and up in place counts; a long drag does not."""
    from types import SimpleNamespace

    view, recorder = _week()
    grid = view.grid
    x = grid.x + GUTTER + 0.5 * grid.column_width
    y = grid.top - 8 * HOUR_HEIGHT - 5

    def touch(py: float) -> Any:
        return SimpleNamespace(pos=(x, py), x=x, y=py)

    still = touch(y)
    grid.on_touch_down(still)
    grid.on_touch_up(still)
    assert recorder.new_starts == [datetime(2026, 11, 9, 8, 0, tzinfo=BERLIN)]

    moved = touch(y)
    grid.on_touch_down(moved)
    moved.y = y - dp(80)
    moved.pos = (x, moved.y)
    grid.on_touch_up(moved)
    assert len(recorder.new_starts) == 1


def test_today_is_highlighted_and_marked_with_a_time_line() -> None:
    """Today's header is painted and its column has the current-time line."""
    view, _ = _week()
    view.grid._place()

    painted = [h.day for h in _day_holders(view) if "_paints" in h.children[0].__dict__]
    assert painted == [date(2026, 11, 11)]
    points = view.grid._now_line.points
    assert len(points) == 4
    assert points[1] == pytest.approx(view.grid.top - 12 * HOUR_HEIGHT)

    view.next_button.dispatch("on_release")
    assert view.grid._now_line.points == []


def test_set_events_redraws_the_week() -> None:
    """New events replace the old blocks."""
    view, _ = _week(_event("a", 11, 9, 10))
    assert len(view.blocks) == 1

    view.set_events([_event("b", 9, 8, 9), _event("c", 10, 8, 9)])

    assert sorted(b.text for b in view.blocks) == ["b", "c"]
    view.set_events([])
    assert view.blocks == []


def test_events_outside_the_week_do_not_show() -> None:
    """Another week's events are not drawn."""
    view, _ = _week(_event("later", 20, 9, 10))

    assert view.blocks == []
    view.shift_week(1)
    assert [b.text for b in view.blocks] == ["later"]


def test_long_titles_are_cut_to_the_block() -> None:
    """The title is truncated inside the block instead of overflowing."""
    view, _ = _week(_event("long", 11, 9, 10, summary="A very long event title " * 5))

    (block,) = view.blocks
    assert block.shorten
    assert block.text_size[0] <= block.width


def test_opens_scrolled_to_seven_in_the_morning() -> None:
    """The grid starts at 07:00 rather than midnight."""
    view, _ = _week()

    view.scroll_to_hour()

    spare = view.grid.height - view.scroll.height
    assert (1 - view.scroll.scroll_y) * spare == pytest.approx(7 * HOUR_HEIGHT)
