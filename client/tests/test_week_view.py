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
    FollowEffect,
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


def test_touch_on_empty_space_is_a_tap_but_a_drag_is_not() -> None:
    """A real touch down and up in place counts; a long drag does not."""
    from types import SimpleNamespace

    view, recorder = _week()
    grid = view.grid
    x = grid.x + GUTTER + 0.5 * grid.column_width
    y = grid.y_of(8 * 60) - 5

    def touch(py: float) -> Any:
        return SimpleNamespace(pos=(x, py), opos=(x, py), x=x, y=py)

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


def test_scroll_view_does_not_bounce_and_hides_its_bar() -> None:
    """No overscroll effect, no bar over the Sunday column, no dead zone."""
    view, _ = _week()

    assert type(view.scroll.effect_y) is FollowEffect
    assert view.scroll.bar_width == 0
    assert view.scroll.effect_y.drag_threshold == 0
    assert view.scroll.scroll_timeout >= 150


def test_scroll_is_clamped_and_reset_when_the_week_changes() -> None:
    """A wild scroll value is pulled back; changing weeks returns to 07:00."""
    view, _ = _week()

    view.scroll.scroll_y = 7.5
    assert view.scroll.scroll_y == 1
    view.scroll.scroll_y = -3
    assert view.scroll.scroll_y == 0

    spare = view.grid.height - view.scroll.height
    for change in (
        lambda: view.shift_week(1),
        lambda: view.shift_week(-1),
        view.go_today,
        lambda: view.show_week(date(2026, 12, 1)),
    ):
        view.scroll.scroll_y = 0
        change()
        assert (1 - view.scroll.scroll_y) * spare == pytest.approx(7 * HOUR_HEIGHT)


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


def _touch(x: float, y: float, grab: Any = None) -> Any:
    """Return a real touch at a window point."""
    touch = _Touch("test", 1, {"x": x, "y": y})
    touch.scale_for_screen(WINDOW, WINDOW)
    touch.grab_current = grab
    return touch


def _move(touch: Any, x: float, y: float) -> None:
    """Move ``touch`` to a window point."""
    touch.sx, touch.sy = x / WINDOW, y / WINDOW
    touch.scale_for_screen(WINDOW, WINDOW)


def _quick_tap(view: WeekView, x: float, y: float, *, replay: bool = False) -> None:
    """Send down and up at once, as Kivy does to the grid.

    With ``replay`` it mimics ScrollView: the up reaches the grid with no
    grabber, then again with the pressed child as ``grab_current``, and that
    child (which grabbed the touch) gets its own release in the grab pass.
    """
    grid = view.grid
    touch = _touch(x, y)
    grid.on_touch_down(touch)
    if not replay:
        grid.on_touch_up(touch)
        return
    block = next((b for b in view.blocks if b.collide_point(x, y)), None)
    if block is not None:
        touch.grab_current = block
        block.on_touch_down(touch)
        touch.grab_current = None
    grid.on_touch_up(touch)
    if block is not None:
        touch.grab_current = block
        grid.on_touch_up(touch)
        touch.grab_current = None


@pytest.mark.parametrize("replay", [False, True])
def test_quick_tap_on_a_block_opens_only_the_event(replay: bool) -> None:
    """A tap on a block never also asks for a new event."""
    event = _event("standup", 11, 9, 10)
    view, recorder = _week(event)
    x, y = _centre(view, view.blocks[0])

    _quick_tap(view, x, y, replay=replay)

    assert recorder.new_starts == []
    assert recorder.opened == ([event] if replay else [])


def _settle(view: WeekView, scroll_y: float) -> None:
    """Scroll to ``scroll_y`` and let Kivy lay the viewport out."""
    from kivy.clock import Clock

    Clock.tick()
    view.scroll.scroll_y = scroll_y
    Clock.tick()


def _through_scroll_view(view: WeekView, x: float, y: float) -> None:
    """Quick-tap the window point (x, y) via the real ScrollView.

    ScrollView holds the touch, replays it to the grid on release and ends it
    0.2 s later with the grabbing child as ``grab_current``.
    """
    import time

    from kivy.clock import Clock

    touch = _touch(x, y)
    scroll = view.scroll
    scroll.on_touch_down(touch)
    scroll.on_touch_up(touch)
    time.sleep(0.25)
    Clock.tick()
    Clock.tick()


def test_quick_tap_on_a_block_through_the_real_scroll_view() -> None:
    """Through ScrollView's delayed replay the event opens once, no new one."""
    event = _event("standup", 11, 9, 10)
    view, recorder = _week(event)
    _settle(view, 0.5)
    centres = [b.to_window(*b.center) for b in view.blocks]
    x, y = next(c for c in centres if view.scroll.collide_point(*c))

    _through_scroll_view(view, x, y)

    assert recorder.new_starts == []
    assert recorder.opened == [event]


def test_quick_tap_on_empty_space_through_the_real_scroll_view() -> None:
    """The same path on empty space creates exactly one event."""
    view, recorder = _week(_event("standup", 11, 9, 10))
    _settle(view, 0.5)
    grid = view.grid
    x = view.scroll.x + GUTTER + 6.5 * grid.column_width

    _through_scroll_view(view, x, view.scroll.center_y)

    assert recorder.opened == []
    assert len(recorder.new_starts) == 1


@pytest.mark.parametrize("replay", [False, True])
def test_quick_tap_on_empty_space_asks_for_a_new_event_only(replay: bool) -> None:
    """A tap away from every block creates, and never opens."""
    view, recorder = _week(_event("standup", 11, 9, 10))
    grid = view.grid
    x = grid.x + GUTTER + 0.5 * grid.column_width
    y = grid.y_of(15 * 60) - 5

    _quick_tap(view, x, y, replay=replay)

    assert recorder.opened == []
    assert recorder.new_starts == [datetime(2026, 11, 9, 15, 0, tzinfo=BERLIN)]
    # A later replay with another grabber must not add a second one.
    other = _touch(x, y, grab=object())
    view.grid.on_touch_up(other)
    assert len(recorder.new_starts) == 1


def test_a_drag_that_starts_on_a_block_does_nothing() -> None:
    """Scrolling by dragging over a block neither opens nor creates."""
    view, recorder = _week(_event("standup", 11, 9, 10))
    grid = view.grid
    x, y = _centre(view, view.blocks[0])
    touch = _touch(x, y)

    grid.on_touch_down(touch)
    _move(touch, x, y - dp(60))
    grid.on_touch_up(touch)

    assert recorder.opened == []
    assert recorder.new_starts == []


def test_a_tap_ending_on_a_block_after_starting_in_the_clear_is_no_new_event() -> None:
    """Even a tiny slide onto a block does not create at that slot."""
    view, recorder = _week(_event("standup", 11, 9, 10))
    grid = view.grid
    block = view.blocks[0]
    x = block.x + block.width / 2
    start = _touch(x, block.top + 2)

    grid.on_touch_down(start)
    _move(start, x, block.top - 2)
    grid.on_touch_up(start)

    assert recorder.new_starts == []


def _gesture(
    view: WeekView,
    points: list[tuple[float, float]],
    *,
    pause: float = 0.0,
    wait: float = 0.0,
    merged: bool = False,
) -> Any:
    """Swipe through ``points`` on the real ScrollView, as the Window does.

    Every move goes first to the ScrollView as a plain touch and then, with
    ``grab_current`` set, to each widget that grabbed the touch.  ``pause`` is
    the real time between moves, ``wait`` a hold before the first move, and
    ``merged`` mimics a slow phone that merges down, moves and up into a
    single frame: the touch already sits at its last point when it goes down.
    """
    import time

    from kivy.clock import Clock

    scroll = view.scroll
    touch = _touch(*points[0])

    def send(name: str) -> None:
        touch.grab_current = None
        getattr(scroll, name)(touch)
        for ref in list(touch.grab_list):
            widget = ref()
            if widget is not None:
                touch.grab_current = widget
                getattr(widget, name)(touch)
        touch.grab_current = None

    if merged:
        _move(touch, *points[-1])
    scroll.on_touch_down(touch)
    if wait:
        for _ in range(4):
            time.sleep(wait / 4)
            Clock.tick()
    if not merged:
        for point in points[1:]:
            if pause:
                time.sleep(pause)
            Clock.tick()
            _move(touch, *point)
            send("on_touch_move")
    send("on_touch_up")
    time.sleep(0.25)
    Clock.tick()
    Clock.tick()
    return touch


def _on_block(view: WeekView) -> tuple[float, float]:
    """Return a window point on the first block, with the grid at mid-scroll."""
    _settle(view, 0.5)
    centres = [b.to_window(*b.center) for b in view.blocks]
    return next(c for c in centres if view.scroll.collide_point(*c))


def _on_empty(view: WeekView) -> tuple[float, float]:
    """Return a window point on empty grid space, with the grid at mid-scroll."""
    _settle(view, 0.5)
    x = view.scroll.x + GUTTER + 6.5 * view.grid.column_width
    return x, view.scroll.center_y


@pytest.mark.parametrize("on_block", [True, False])
@pytest.mark.parametrize(
    "shape",
    ["fast few moves", "merged into one frame", "held then moved", "handed over"],
)
def test_a_swipe_never_opens_anything(shape: str, on_block: bool) -> None:
    """Whatever ScrollView decides, travel past the tap slop is never a tap."""
    event = _event("standup", 11, 9, 10)
    view, recorder = _week(event)
    x, y = _on_block(view) if on_block else _on_empty(view)
    if shape == "handed over":
        view.scroll.scroll_timeout = 30
    path = [(x, y), (x, y + dp(40)), (x, y + dp(90))]

    if shape == "fast few moves":
        _gesture(view, path)
    elif shape == "merged into one frame":
        _gesture(view, path, merged=True)
    elif shape == "held then moved":
        _gesture(view, path, wait=view.scroll.scroll_timeout / 1000 + 0.1)
    else:
        _gesture(view, path, wait=0.2)

    assert recorder.opened == []
    assert recorder.new_starts == []


def test_a_merged_swipe_still_scrolls() -> None:
    """A swipe whose moves arrive with the release moves the grid."""
    view, _ = _week(_event("standup", 11, 9, 10))
    x, y = _on_empty(view)
    before = view.scroll.scroll_y

    _gesture(view, [(x, y), (x, y + dp(120))], merged=True)

    assert view.scroll.scroll_y < before


def test_scroll_settings_favour_both_taps_and_swipes() -> None:
    """Scrolling starts below the tap slop, and a slow first move still counts."""
    view, _ = _week()

    assert view.scroll.scroll_distance < TAP_SLOP
    assert view.scroll.scroll_timeout >= 500


def _grid_top(view: WeekView) -> float:
    """Return how many pixels of the grid are scrolled off the top."""
    return (1 - view.scroll.scroll_y) * (view.grid.height - view.scroll.height)


@pytest.mark.parametrize("pause", [0.0, 0.02, 0.12])
def test_a_drag_moves_the_grid_exactly_with_the_finger(pause: float) -> None:
    """Every move scrolls by the finger's own travel, from the first pixel."""
    import time

    from kivy.clock import Clock

    view, _ = _week()
    _settle(view, 0.5)
    scroll = view.scroll
    x, y = scroll.center_x, scroll.y + dp(50)
    touch = _touch(x, y)
    scroll.on_touch_down(touch)
    start = _grid_top(view)

    for step in range(1, 11):
        time.sleep(pause)
        Clock.tick()
        _move(touch, x, y + step * dp(30))
        touch.grab_current = None
        scroll.on_touch_move(touch)
        touch.grab_current = scroll
        scroll.on_touch_move(touch)
        touch.grab_current = None
        assert _grid_top(view) == pytest.approx(start + step * dp(30), abs=0.5)


def test_a_drag_that_pauses_before_moving_still_scrolls() -> None:
    """A finger resting longer than a short timeout does not lose the drag."""
    view, _ = _week()
    x, y = _on_empty(view)
    before = _grid_top(view)

    _gesture(view, [(x, y), (x, y + dp(100))], wait=0.45)

    assert _grid_top(view) > before + dp(60)


@pytest.mark.parametrize("towards_bottom", [True, False])
@pytest.mark.parametrize("frame", [0.017, 0.1, 0.5, 1.0])
def test_a_drag_past_either_end_stays_there_however_slow_the_frames(
    towards_bottom: bool, frame: float
) -> None:
    """Pushing past 24:00 or 00:00 stops there; a long frame cannot flip it."""
    from kivy.clock import Clock

    view, _ = _week()
    _settle(view, 0.1 if towards_bottom else 0.9)
    scroll = view.scroll
    x, y = scroll.center_x, scroll.center_y
    sign = 1 if towards_bottom else -1
    touch = _touch(x, y)
    scroll.on_touch_down(touch)
    for step in range(1, 25):
        _move(touch, x, y + sign * step * dp(40))
        touch.grab_current = scroll
        scroll.on_touch_move(touch)
        touch.grab_current = None
        Clock.tick()
    touch.grab_current = None
    scroll.on_touch_up(touch)
    end = 0.0 if towards_bottom else 1.0
    assert scroll.scroll_y == pytest.approx(end)

    effect = scroll.effect_y
    for _ in range(40):
        effect.update_velocity(frame)
        assert scroll.scroll_y == pytest.approx(end)
    assert abs(effect.velocity) <= 2000 * dp(1)


def test_the_release_speed_is_sane_after_pushing_against_an_end() -> None:
    """The fling speed is measured over the real drag, not a few microseconds."""
    view, _ = _week()
    _settle(view, 0.1)
    scroll = view.scroll
    x, y = scroll.center_x, scroll.center_y
    touch = _touch(x, y)
    scroll.on_touch_down(touch)
    for step in range(1, 30):
        _move(touch, x, y + step * dp(40))
        touch.grab_current = scroll
        scroll.on_touch_move(touch)
        touch.grab_current = None
    scroll.on_touch_up(touch)

    assert abs(scroll.effect_y.velocity) <= 2000 * dp(1)


def test_a_nan_scroll_value_does_not_throw_the_grid_to_the_top() -> None:
    """A broken value keeps the position the grid had."""
    view, _ = _week()
    _settle(view, 0.25)

    view.scroll.scroll_y = float("nan")

    assert view.scroll.scroll_y == pytest.approx(0.25)


def test_changing_week_while_the_grid_still_coasts_returns_to_seven() -> None:
    """A fling in progress is stopped, and does not drag the grid off 07:00."""
    from kivy.clock import Clock

    view, _ = _week()
    _settle(view, 0.5)
    effect = view.scroll.effect_y
    effect.velocity = 1500
    effect.trigger_velocity_update()

    view.shift_week(1)
    for _ in range(10):
        Clock.tick()

    spare = view.grid.height - view.scroll.height
    assert effect.velocity == 0
    assert (1 - view.scroll.scroll_y) * spare == pytest.approx(7 * HOUR_HEIGHT)


def test_opens_scrolled_to_seven_in_the_morning() -> None:
    """The grid starts at 07:00 rather than midnight."""
    view, _ = _week()

    view.scroll_to_hour()

    spare = view.grid.height - view.scroll.height
    assert (1 - view.scroll.scroll_y) * spare == pytest.approx(7 * HOUR_HEIGHT)


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


def test_switching_to_week_swaps_the_body_and_hides_the_list_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Week replaces the list and drops the date chips and sort spinner."""
    _, main_screen, _ = _main(monkeypatch, _event("a", 11, 9, 10))
    assert main_screen.filter_panel.parent is not None

    main_screen.view_buttons["week"].dispatch("on_release")

    assert main_screen.current_view == "week"
    assert main_screen.view_body.children == [main_screen.week_view]
    assert main_screen.filter_panel.parent is None
    assert [b.text for b in main_screen.week_view.blocks] == ["a"]
    assert main_screen.status_label.text == ""

    main_screen.view_buttons["list"].dispatch("on_release")

    assert main_screen.current_view == "list"
    assert main_screen.filter_panel.parent is not None
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

    main_screen.week_view.blocks[0].dispatch("on_release")

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
