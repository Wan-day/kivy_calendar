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

from kivy.input.motionevent import MotionEvent  # noqa: E402
from kivy.metrics import dp  # noqa: E402

from kivy_calendar.api import CalendarEvent  # noqa: E402
from kivy_calendar.screens.week import (  # noqa: E402
    GUTTER,
    HOUR_HEIGHT,
    TAP_SLOP,
    TOP_INSET,
    WeekView,
)

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
    assert block.top == pytest.approx(view.grid.y_of(9 * 60) - 1)
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

    view.grid.activate(*_centre(view, view.blocks[0]))

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
    y = grid.y_of(14 * 60 + 50)

    assert grid.tap(x, y)

    assert recorder.new_starts == [datetime(2026, 11, 12, 14, 30, tzinfo=BERLIN)]
    assert recorder.new_starts[0].utcoffset() == timedelta(hours=1)


def test_tapping_the_hour_labels_does_nothing() -> None:
    """The time gutter is not a slot."""
    view, recorder = _week()
    grid = view.grid

    assert not grid.tap(grid.x + GUTTER / 2, grid.y_of(5 * 60))
    assert recorder.new_starts == []


def test_today_is_highlighted_and_marked_with_a_time_line() -> None:
    """Today's header is painted and its column has the current-time line."""
    view, _ = _week()
    view.grid._place()

    painted = [h.day for h in _day_holders(view) if "_paints" in h.children[0].__dict__]
    assert painted == [date(2026, 11, 11)]
    points = view.grid._now_line.points
    assert len(points) == 4
    assert points[1] == pytest.approx(view.grid.y_of(12 * 60))

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


def test_titles_wrap_in_the_block_and_clip_without_an_ellipsis() -> None:
    """The title box is the block's inner size; nothing is shortened."""
    view, _ = _week(_event("long", 11, 9, 10, summary="A very long event title " * 5))

    (block,) = view.blocks
    assert not block.shorten
    assert block.halign == "left"
    assert block.valign == "top"
    assert 0 < block.text_size[0] < block.width
    assert 0 < block.text_size[1] < block.height
    assert block.font_size <= dp(11)


def test_nav_row_items_share_height_and_centre() -> None:
    """Today is as tall as the arrows and all sit on the row's middle."""
    view, _ = _week()

    buttons = (view.previous_button, view.next_button, view.today_button)
    assert len({b.height for b in buttons}) == 1
    assert all(b.pos_hint == {"center_y": 0.5} for b in buttons)


def test_first_hour_label_is_not_clipped_at_the_grid_top() -> None:
    """The 00:00 label has room above the first hour line."""
    view, _ = _week()
    grid = view.grid

    first = grid.hour_labels[0]
    assert first.text == "00:00"
    assert first.top <= grid.top
    assert grid.y_of(0) == pytest.approx(grid.top - TOP_INSET)


WINDOW = 10_000.0


class _Touch(MotionEvent):
    """A real Kivy touch placed at window point (x, y), so grab() works."""

    def depack(self, args: Any) -> None:
        """Take the position from ``args``, scaled like a window touch."""
        self.is_touch = True
        self.profile = ["pos"]
        self.sx, self.sy = args["x"] / WINDOW, args["y"] / WINDOW
        super().depack(args)


def _touch(x: float, y: float) -> Any:
    """Return a real touch at a window point."""
    touch = _Touch("test", 1, {"x": x, "y": y})
    touch.scale_for_screen(WINDOW, WINDOW)
    touch.grab_current = None
    return touch


def _move(touch: Any, x: float, y: float) -> None:
    """Move ``touch`` to a window point."""
    touch.sx, touch.sy = x / WINDOW, y / WINDOW
    touch.scale_for_screen(WINDOW, WINDOW)


def _send(view: WeekView, touch: Any, name: str) -> None:
    """Dispatch an event as the Window does: plain pass, then the grabbers."""
    touch.grab_current = None
    getattr(view.viewport, name)(touch)
    for ref in list(touch.grab_list):
        widget = ref()
        if widget is not None:
            touch.grab_current = widget
            getattr(widget, name)(touch)
    touch.grab_current = None


def _swipe(view: WeekView, points: list[tuple[float, float]]) -> Any:
    """Touch down at the first point, move through the rest, release at the last.

    A single point goes down and up in place.  The release is sent at the last
    point, so ``[start, end]`` is a swipe whose only move is the release.
    """
    touch = _touch(*points[0])
    _send(view, touch, "on_touch_down")
    for point in points[1:-1]:
        _move(touch, *point)
        _send(view, touch, "on_touch_move")
    _move(touch, *points[-1])
    _send(view, touch, "on_touch_up")
    return touch


def _settled(view: WeekView) -> WeekView:
    """Let Kivy lay the view out, then show 07:00 at the top."""
    from kivy.clock import Clock

    Clock.tick()
    view.scroll_to_hour()
    return view


def _on_block(view: WeekView) -> tuple[float, float]:
    """Return a window point on the first block, inside the viewport."""
    _settled(view)
    return _centre(view, view.blocks[0])


def _on_empty(view: WeekView) -> tuple[float, float]:
    """Return a window point on empty grid space, inside the viewport."""
    _settled(view)
    viewport = view.viewport
    return viewport.x + GUTTER + 6.5 * view.grid.column_width, viewport.center_y


def test_quick_tap_on_a_block_opens_the_event_once() -> None:
    """A tap on a block opens it, and never also creates an event."""
    event = _event("standup", 11, 9, 10)
    view, recorder = _week(event)
    x, y = _on_block(view)

    _swipe(view, [(x, y)])

    assert recorder.opened == [event]
    assert recorder.new_starts == []


def test_quick_tap_on_empty_space_creates_once_at_the_rounded_time() -> None:
    """A tap on a free slot asks for exactly one new event."""
    view, recorder = _week(_event("standup", 11, 9, 10))
    _settled(view)
    grid = view.grid
    x = grid.x + GUTTER + 0.5 * grid.column_width
    y = grid.y_of(15 * 60 + 20)

    _swipe(view, [(x, y)])

    assert recorder.opened == []
    assert recorder.new_starts == [datetime(2026, 11, 9, 15, 0, tzinfo=BERLIN)]


def test_a_touch_outside_the_viewport_is_ignored() -> None:
    """Touches on the header are not the viewport's."""
    view, recorder = _week()
    _settled(view)
    touch = _touch(view.viewport.x + 5, view.viewport.top + dp(20))

    assert not view.viewport.on_touch_down(touch)
    assert recorder.new_starts == []


@pytest.mark.parametrize("on_block", [True, False])
@pytest.mark.parametrize(
    "shape",
    ["fast single move", "up far from down", "short 150 px", "slow drag"],
)
def test_a_swipe_never_opens_anything(shape: str, on_block: bool) -> None:
    """Any travel past the tap slop is a drag, never a tap."""
    event = _event("standup", 11, 9, 10)
    view, recorder = _week(event)
    x, y = _on_block(view) if on_block else _on_empty(view)
    paths = {
        "fast single move": [(x, y), (x, y + dp(40)), (x, y + dp(90))],
        "up far from down": [(x, y), (x, y + dp(120))],
        "short 150 px": [(x, y), (x, y + 150)],
        "slow drag": [(x, y + step * dp(5)) for step in range(40)],
    }

    _swipe(view, paths[shape])

    assert recorder.opened == []
    assert recorder.new_starts == []


def test_a_drag_that_comes_back_to_the_start_is_still_no_tap() -> None:
    """Once past the slop the gesture is a drag for good."""
    view, recorder = _week(_event("standup", 11, 9, 10))
    x, y = _on_block(view)

    _swipe(view, [(x, y), (x, y + dp(60)), (x, y)])

    assert recorder.opened == []
    assert recorder.new_starts == []


def test_a_small_wobble_inside_the_slop_is_still_a_tap() -> None:
    """Finger jitter below the slop does not turn a tap into a drag."""
    event = _event("standup", 11, 9, 10)
    view, recorder = _week(event)
    x, y = _on_block(view)
    before = view.viewport.offset

    _swipe(view, [(x, y), (x + dp(3), y + dp(4)), (x + dp(2), y + dp(3))])

    assert recorder.opened == [event]
    assert view.viewport.offset == before


@pytest.mark.parametrize("pause", [0.0, 0.02])
def test_a_drag_moves_the_grid_exactly_with_the_finger(pause: float) -> None:
    """The grid sits at start offset plus the finger's travel, from the slop on."""
    import time

    view, _ = _week()
    _settled(view)
    viewport = view.viewport
    x, y = viewport.center_x, viewport.center_y
    touch = _touch(x, y)
    _send(view, touch, "on_touch_down")
    start = viewport.offset

    for step in range(1, 11):
        time.sleep(pause)
        _move(touch, x, y + step * dp(12))
        _send(view, touch, "on_touch_move")
        if step * dp(12) > TAP_SLOP:
            assert viewport.offset == pytest.approx(start + step * dp(12), abs=0.05)
    _send(view, touch, "on_touch_up")

    assert viewport.offset == pytest.approx(start + 10 * dp(12), abs=0.05)
    assert view.grid.top == pytest.approx(viewport.top + viewport.offset)


def test_a_swipe_whose_moves_arrive_with_the_release_still_scrolls() -> None:
    """A release far from the press moves the grid by the whole travel."""
    view, _ = _week()
    _settled(view)
    before = view.viewport.offset
    x, y = view.viewport.center

    _swipe(view, [(x, y), (x, y - dp(120))])

    assert view.viewport.offset == pytest.approx(before - dp(120), abs=0.05)


@pytest.mark.parametrize("towards_top", [True, False])
def test_dragging_past_either_end_stays_at_the_end(towards_top: bool) -> None:
    """The grid never leaves 00:00 at the top or 24:00 at the bottom."""
    view, _ = _week()
    _settled(view)
    viewport = view.viewport
    x, y = viewport.center
    sign = 1 if towards_top else -1
    touch = _touch(x, y)
    _send(view, touch, "on_touch_down")

    for step in range(1, 60):
        _move(touch, x, y + sign * step * dp(40))
        _send(view, touch, "on_touch_move")
    _send(view, touch, "on_touch_up")

    assert viewport.offset == pytest.approx(viewport.max_offset if towards_top else 0)
    if towards_top:
        assert view.grid.y == pytest.approx(viewport.y)
    else:
        assert view.grid.top == pytest.approx(viewport.top)


def test_a_grid_shorter_than_the_viewport_is_pinned_to_the_top() -> None:
    """With nothing to scroll the grid stays at the top."""
    view, _ = _week()
    _settled(view)

    view.viewport.height = view.grid.height + dp(100)
    view.viewport.set_offset(dp(200))

    assert view.viewport.offset == 0
    assert view.grid.top == pytest.approx(view.viewport.top)


def test_a_nan_offset_keeps_the_position() -> None:
    """A broken value does not throw the grid anywhere."""
    view, _ = _week()
    _settled(view)
    view.viewport.set_offset(dp(100))

    view.viewport.set_offset(float("nan"))

    assert view.viewport.offset == pytest.approx(dp(100))


def test_scroll_is_clamped_and_reset_when_the_week_changes() -> None:
    """A wild offset is pulled back; changing weeks returns to 07:00."""
    view, _ = _week()
    _settled(view)

    view.viewport.set_offset(1e9)
    assert view.viewport.offset == view.viewport.max_offset
    view.viewport.set_offset(-5)
    assert view.viewport.offset == 0

    for change in (
        lambda: view.shift_week(1),
        lambda: view.shift_week(-1),
        view.go_today,
        lambda: view.show_week(date(2026, 12, 1)),
    ):
        view.viewport.set_offset(0)
        change()
        assert view.viewport.offset == pytest.approx(7 * HOUR_HEIGHT)


def test_the_opening_position_is_kept_until_the_user_drags() -> None:
    """A resize before the first drag re-applies 07:00; after it, it does not."""
    view, _ = _week()
    _settled(view)
    view.viewport.set_offset(0)

    view.viewport.height += dp(10)
    assert view.viewport.offset == pytest.approx(7 * HOUR_HEIGHT)

    x, y = view.viewport.center
    _swipe(view, [(x, y), (x, y + dp(60))])
    moved = view.viewport.offset
    view.viewport.height += dp(10)
    assert view.viewport.offset == pytest.approx(moved)


def test_the_time_line_refreshes_while_the_view_is_on_screen() -> None:
    """A clock interval redraws the line when shown and stops when hidden."""
    from kivy.uix.widget import Widget

    clock = [NOW]
    view, _ = _week()
    view._now = lambda: clock[0]
    assert view._tick is None
    holder = Widget()

    holder.add_widget(view)
    assert view._tick is not None
    assert view._tick.timeout == 60
    before = list(view.grid._now_line.points)

    clock[0] = NOW + timedelta(hours=2)
    view._refresh_time()
    assert view.grid._now_line.points != before
    assert view.grid._now_line.points[1] == pytest.approx(view.grid.y_of(14 * 60))

    tick = view._tick
    holder.remove_widget(view)
    assert view._tick is None
    assert not tick.is_triggered


def test_opens_scrolled_to_seven_in_the_morning() -> None:
    """The grid starts at 07:00 rather than midnight."""
    view, _ = _week()

    view.scroll_to_hour()

    assert view.viewport.offset == pytest.approx(7 * HOUR_HEIGHT)


class FakeClient:
    """Backend double that returns the events it is given."""

    def __init__(self, events: list[CalendarEvent]) -> None:
        self.events = events

    def list_events(self) -> list[CalendarEvent]:
        """Return the configured events."""
        return list(self.events)

    def list_calendars(self) -> list[Any]:
        """Return no calendars."""
        return []

    def list_time_zones(self) -> list[Any]:
        """Return no time zones."""
        return []


def _main(
    monkeypatch: pytest.MonkeyPatch, *events: CalendarEvent
) -> tuple[Any, Any, list[datetime]]:
    """Return the manager and main screen on the test week, with events."""
    from kivy.uix.screenmanager import ScreenManager

    from kivy_calendar.screens.add_event import AddEventScreen
    from kivy_calendar.screens.main import MainScreen

    starts: list[datetime] = []
    # Record tapped slots instead of opening the form.
    monkeypatch.setattr(
        MainScreen, "open_add_event_at", lambda self, start: starts.append(start)
    )
    client = FakeClient(list(events))
    manager = ScreenManager()
    main_screen = MainScreen(name="main", client=client)
    manager.add_widget(main_screen)
    manager.add_widget(
        AddEventScreen(name="add_event", client=client, refresh=lambda: None)
    )
    main_screen.week_view.tz = BERLIN
    main_screen.week_view._now = lambda: NOW
    main_screen.week_view.go_today()
    main_screen._show_events(list(events))
    return manager, main_screen, starts


def test_list_is_the_default_view_and_week_and_month_are_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switcher starts on List; Week and Month are enabled."""
    _, main_screen, _ = _main(monkeypatch, _event("a", 11, 9, 10))

    assert main_screen.current_view == "list"
    buttons = main_screen.view_buttons
    assert [b.text for b in buttons.values()] == ["List", "Week", "Month"]
    assert not buttons["list"].disabled
    assert not buttons["week"].disabled
    assert not buttons["month"].disabled
    assert len(main_screen.rows) == 1

    main_screen.show_view("nonsense")
    assert main_screen.current_view == "list"


def test_switching_to_week_swaps_the_body_and_keeps_the_list_filters_in_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Week replaces the list and drops the date chips and sort spinner."""
    _, main_screen, _ = _main(monkeypatch, _event("a", 11, 9, 10))
    assert main_screen.filter_panel.parent is main_screen.views["list"]

    main_screen.view_buttons["week"].dispatch("on_release")

    assert main_screen.current_view == "week"
    assert main_screen.view_body.current == "week"
    assert main_screen.week_view.parent is main_screen._holders["week"]
    # The chips and sort spinner stay in the list's own page.
    assert main_screen.filter_panel.parent is main_screen.views["list"]
    assert [b.text for b in main_screen.week_view.blocks] == ["a"]
    assert main_screen.status_label.text == ""

    main_screen.view_buttons["list"].dispatch("on_release")

    assert main_screen.current_view == "list"
    assert main_screen.view_body.current == "list"
    assert len(main_screen.rows) == 1


def test_week_blocks_open_the_event_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tapping a block opens the form for that event."""
    event = _event("a", 11, 9, 10)
    manager, main_screen, _ = _main(monkeypatch, event)
    main_screen.show_view("week")
    opened: list[Any] = []
    form = manager.get_screen("add_event")
    monkeypatch.setattr(form, "open_for", opened.append)

    view = main_screen.week_view
    view.grid.activate(*_centre(view, view.blocks[0]))

    assert opened == [event]
    assert manager.current == "add_event"


def test_tapping_empty_week_space_calls_open_add_event_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The main screen hands tapped slots to ``open_add_event_at``."""
    _, main_screen, starts = _main(monkeypatch)
    main_screen.show_view("week")
    grid = main_screen.week_view.grid
    x = grid.x + GUTTER + 4.5 * grid.column_width
    y = grid.y_of(10 * 60 + 29)

    grid.tap(x, y)

    assert starts == [datetime(2026, 11, 13, 10, 0, tzinfo=BERLIN)]


def test_week_view_uses_the_name_filter_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The name filter narrows the week; a reload redraws it."""
    standup = _event("Standup", 11, 9, 10)
    lunch = _event("Lunch", 11, 12, 13)
    _, main_screen, _ = _main(monkeypatch, standup, lunch)
    main_screen.show_view("week")
    assert len(main_screen.week_view.blocks) == 2

    main_screen.name_filter.text = "lunch"
    main_screen._apply_filters()

    assert [b.text for b in main_screen.week_view.blocks] == ["Lunch"]
    assert main_screen.status_label.text == ""

    main_screen.name_filter.text = "zzz"
    main_screen._apply_filters()

    assert main_screen.week_view.blocks == []
    assert main_screen.status_label.text == "No events match the filters."

    main_screen.name_filter.text = ""
    main_screen._show_events([_event("New", 10, 8, 9)])
    assert [b.text for b in main_screen.week_view.blocks] == ["New"]


def test_week_blocks_use_the_calendar_colour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A block takes the dot colour of its calendar."""
    from kivy_calendar.api import CalendarSummary

    _, main_screen, _ = _main(monkeypatch)
    main_screen._show_events(
        [_event("a", 11, 9, 10)],
        [
            CalendarSummary(id="primary", summary="Primary", primary=True),
            CalendarSummary(id="work@example.com", summary="Work"),
        ],
    )
    main_screen.show_view("week")

    (block,) = main_screen.week_view.blocks
    assert tuple(block.paint.border_color.rgba) == tuple(
        main_screen._calendar_dots["work@example.com"]
    )
