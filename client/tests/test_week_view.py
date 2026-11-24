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
    # The new-event handler belongs to another change; stub it here.
    monkeypatch.setattr(
        MainScreen,
        "open_add_event_at",
        lambda self, start: starts.append(start),
        raising=False,
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


def test_list_is_the_default_view_and_month_is_not_available_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switcher starts on List; Week works; Month stays disabled."""
    _, main_screen, _ = _main(monkeypatch, _event("a", 11, 9, 10))

    assert main_screen.current_view == "list"
    buttons = main_screen.view_buttons
    assert [b.text for b in buttons.values()] == ["List", "Week", "Month"]
    assert not buttons["list"].disabled
    assert not buttons["week"].disabled
    assert buttons["month"].disabled
    assert len(main_screen.rows) == 1

    main_screen.show_view("month")
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
    assert main_screen.status_label.text == "1 event"

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
    y = grid.top - (10 * 60 + 29) * grid.height / 1440

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
    assert main_screen.status_label.text == "1 event"

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
