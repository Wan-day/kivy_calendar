"""Tests for the month view widget and its place on the main screen.

Kivy is optional in CI, so these tests are skipped when it is not installed.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.metrics import dp  # noqa: E402

from kivy_calendar.api import CalendarEvent  # noqa: E402
from kivy_calendar.screens.month import MonthView  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
# Wednesday 11 Nov 2026, noon: the "now" of these tests.
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=BERLIN)


def _event(
    event_id: str,
    day: int,
    start_hour: int = 9,
    end_hour: int = 10,
    *,
    all_day: bool = False,
) -> CalendarEvent:
    """Return an event on 2026-11-``day`` in Berlin."""
    return CalendarEvent(
        id=event_id,
        summary=event_id,
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
        self.weeks: list[date] = []


def _month(*events: CalendarEvent) -> tuple[MonthView, Recorder]:
    """Return a month view of November 2026 sized like a phone."""
    recorder = Recorder()
    view = MonthView(
        recorder.opened.append,
        recorder.new_starts.append,
        recorder.weeks.append,
        tz=BERLIN,
        now=lambda: NOW,
        size=(dp(411), dp(480)),
        size_hint=(None, None),
    )
    view.do_layout()
    view.grid.do_layout()
    view.set_events(list(events))
    view.grid.do_layout()
    return view, recorder


class FakeTouch:
    """A touch with the parts of a Kivy touch that buttons and cells use."""

    is_mouse_scrolling = False
    button = "left"

    def __init__(self, x: float, y: float) -> None:
        self.pos = (x, y)
        self.x = x
        self.y = y
        self.ud: dict[Any, Any] = {}
        self.grab_current: Any = None
        self.grabbed: list[Any] = []

    def grab(self, widget: Any) -> None:
        """Remember ``widget`` as a grabber."""
        self.grabbed.append(widget)

    def ungrab(self, widget: Any) -> None:
        """Forget ``widget`` as a grabber."""
        if widget in self.grabbed:
            self.grabbed.remove(widget)


def _touch(x: float, y: float) -> Any:
    """Return a minimal touch at a window point."""
    return FakeTouch(x, y)


def _quick_tap(cell: Any, x: float, y: float) -> None:
    """Dispatch down and up like the window does, grab pass included."""
    touch = _touch(x, y)
    cell.dispatch("on_touch_down", touch)
    for grabber in list(touch.grabbed):
        touch.grab_current = grabber
        grabber.dispatch("on_touch_up", touch)
    touch.grab_current = None
    cell.dispatch("on_touch_up", touch)


def test_cells_cover_the_month_with_neighbouring_days() -> None:
    """November 2026 is six Monday-first rows, 26 Oct to 6 Dec."""
    view, _ = _month()

    assert view.title_label.text == "November 2026"
    assert len(view.cells) == 42
    assert view.cells[0].day == date(2026, 10, 26)
    assert view.cells[-1].day == date(2026, 12, 6)
    assert [c.day.weekday() for c in view.cells[:7]] == list(range(7))
    assert not view.cells[0].in_month
    assert view.cell_for(date(2026, 11, 1)).in_month  # type: ignore[union-attr]
    assert view.cells[0].number.color != view.cell_for(date(2026, 11, 1)).number.color  # type: ignore[union-attr]
    # Cells share the grid evenly: seven columns, six rows.
    assert view.cells[0].width == pytest.approx(view.cells[1].width)
    assert view.cells[0].y > view.cells[-1].y


def test_today_is_highlighted() -> None:
    """Only today's cell is marked."""
    view, _ = _month()

    assert [c.day for c in view.cells if c.is_today] == [date(2026, 11, 11)]


def test_navigation_and_today() -> None:
    """Arrows move by month, across a year boundary; Today returns."""
    view, _ = _month()

    view.next_button.dispatch("on_release")
    assert view.title_label.text == "December 2026"
    view.next_button.dispatch("on_release")
    assert view.title_label.text == "January 2027"
    assert view.cells[0].day == date(2026, 12, 28)
    view.previous_button.dispatch("on_release")
    view.previous_button.dispatch("on_release")
    view.previous_button.dispatch("on_release")
    assert view.title_label.text == "October 2026"
    assert len(view.cells) == 35
    view.today_button.dispatch("on_release")
    assert view.title_label.text == "November 2026"


def test_chips_show_events_on_every_covered_day() -> None:
    """A multi-day all-day event has a chip in each cell it covers."""
    trip = CalendarEvent(
        id="trip",
        summary="trip",
        start=datetime(2026, 11, 10, tzinfo=BERLIN),
        end=datetime(2026, 11, 13, tzinfo=BERLIN),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        calendar_id="work@example.com",
        all_day=True,
    )
    view, _ = _month(trip, _event("a", 11))

    shown = {c.day.day: [chip.text for chip in c.chips] for c in view.cells}
    assert shown[10] == ["trip"]
    assert shown[11] == ["trip", "a"]
    assert shown[12] == ["trip"]
    assert shown[13] == []
    assert view.cell_for(date(2026, 11, 11)).more is None  # type: ignore[union-attr]


def test_set_events_redraws_and_other_months_hide_events() -> None:
    """New events replace the old chips; another month shows its own."""
    view, _ = _month(_event("a", 11))
    assert [c.text for c in view.chips] == ["a"]

    view.set_events([_event("b", 12)])
    assert [c.text for c in view.chips] == ["b"]
    view.shift_month(1)
    assert view.chips == []
    view.set_events([])
    assert view.chips == []


def test_chips_use_the_calendar_colour_and_one_line() -> None:
    """A chip takes its calendar's colour and keeps its title on one line."""
    recorder = Recorder()
    colour = (0.1, 0.2, 0.3, 1.0)
    view = MonthView(
        recorder.opened.append,
        recorder.new_starts.append,
        colour_for=lambda _id: colour,
        tz=BERLIN,
        now=lambda: NOW,
        size=(dp(411), dp(480)),
        size_hint=(None, None),
    )
    view.do_layout()
    view.grid.do_layout()
    view.set_events([_event("A very long event title " * 4, 11)])
    view.grid.do_layout()

    (chip,) = view.chips
    assert tuple(chip.paint.border_color.rgba) == colour
    assert not chip.shorten  # clipped by texture_update, no ellipsis
    assert chip.max_lines == 1
    assert chip.text_size[0] <= chip.width


def test_overflow_shows_a_plus_line_instead_of_chips_that_do_not_fit() -> None:
    """Chips that do not fit are replaced by a "+N" line."""
    events = [_event(f"e{i}", 11, 8 + i, 9 + i) for i in range(6)]
    view, _ = _month(*events)

    cell = view.cell_for(date(2026, 11, 11))
    assert cell is not None
    capacity = cell.capacity
    assert 2 <= capacity < 6
    assert [c.text for c in cell.chips] == [f"e{i}" for i in range(capacity - 1)]
    assert cell.more is not None
    assert cell.more.text == f"+{6 - (capacity - 1)}"
    # The chips and the "+N" line stay inside the cell.
    cell.do_layout()
    lowest = cell.more
    assert lowest.y >= cell.y - 1


def test_tapping_a_chip_opens_the_event_only() -> None:
    """A chip tap opens its event and does not start a new one."""
    event = _event("a", 11)
    view, recorder = _month(event)

    view.chips[0].dispatch("on_release")

    assert recorder.opened == [event]
    assert recorder.new_starts == []


def test_a_quick_tap_on_a_chip_fires_only_that_chip() -> None:
    """Down+up on a chip opens its event once and adds nothing else."""
    event = _event("a", 11)
    view, recorder = _month(event)
    cell = view.cell_for(date(2026, 11, 11))
    assert cell is not None
    chip = cell.chips[0]

    cell.do_layout()
    _quick_tap(cell, *chip.center)

    assert recorder.opened == [event]
    assert recorder.new_starts == []
    assert recorder.weeks == []


def test_a_quick_tap_on_plus_fires_only_show_week() -> None:
    """Down+up on "+N" shows the week and never starts a new event."""
    events = [_event(f"e{i}", 11, 8 + i, 9 + i) for i in range(6)]
    view, recorder = _month(*events)
    cell = view.cell_for(date(2026, 11, 11))
    assert cell is not None and cell.more is not None

    cell.do_layout()
    _quick_tap(cell, *cell.more.center)

    assert recorder.weeks == [date(2026, 11, 11)]
    assert recorder.new_starts == []
    assert recorder.opened == []


def test_a_quick_tap_on_empty_space_fires_only_new_event() -> None:
    """Down+up on empty space starts exactly one new event."""
    view, recorder = _month(_event("a", 11))
    cell = view.cell_for(date(2026, 11, 11))
    assert cell is not None
    cell.do_layout()
    chip = cell.chips[0]

    _quick_tap(cell, cell.center_x, chip.y - dp(3))
    _quick_tap(cell, cell.center_x, cell.y + dp(3))

    assert recorder.new_starts == [datetime(2026, 11, 11, 9, 0, tzinfo=BERLIN)] * 2
    assert recorder.opened == []
    assert recorder.weeks == []


def test_numbers_and_chips_are_pinned_to_the_top() -> None:
    """Every day number sits at the same height in its cell, chips below."""
    view, _ = _month(_event("a", 11), _event("b", 11, 11, 12))
    for cell in view.cells:
        cell.do_layout()
    tops = {round(cell.top - cell.number.top, 1) for cell in view.cells}
    assert len(tops) == 1
    busy = view.cell_for(date(2026, 11, 11))
    assert busy is not None
    assert busy.chips[0].top <= busy.number.y
    assert busy.chips[1].top <= busy.chips[0].y


def test_other_month_days_are_clearly_muted() -> None:
    """Neighbouring days get a lighter number and faded chips."""
    october_event = replace(
        _event("o", 28),
        start=datetime(2026, 10, 28, 9, tzinfo=BERLIN),
        end=datetime(2026, 10, 28, 10, tzinfo=BERLIN),
    )
    view, _ = _month(_event("a", 11), october_event)
    october = view.cells[0]
    november = view.cell_for(date(2026, 11, 3))
    assert november is not None
    assert october.number.color[3] < 0.6
    assert november.number.color[3] == 1
    inside = view.cell_for(date(2026, 11, 11))
    assert inside is not None and inside.chips[0].opacity == 1
    faded = view.cell_for(date(2026, 10, 28))
    assert faded is not None and faded.chips
    assert faded.chips[0].opacity < 1


def test_chip_text_is_clipped_not_ellipsised() -> None:
    """A narrow chip shows as many characters as fit, with no ellipsis."""
    long_event = replace(_event("x", 11), summary="Quarterly planning review")
    view, _ = _month(long_event)
    chip = view.chips[0]
    chip.texture_update()
    shown = chip._label.text
    assert chip.text == "Quarterly planning review"
    assert "." not in shown and "…" not in shown
    assert 0 < len(shown) < len(chip.text)
    assert chip.text.startswith(shown)
    assert chip.texture_size[0] <= chip.width


def test_tapping_empty_space_starts_an_event_at_nine() -> None:
    """A tap on a day cell asks for a new event at 09:00 on that day."""
    view, recorder = _month(_event("a", 11))
    cell = view.cell_for(date(2026, 11, 20))
    assert cell is not None
    x, y = cell.x + cell.width / 2, cell.y + dp(4)

    _quick_tap(cell, x, y)

    assert recorder.new_starts == [datetime(2026, 11, 20, 9, 0, tzinfo=BERLIN)]
    assert recorder.new_starts[0].utcoffset() is not None


def test_tapping_an_other_month_day_uses_that_day() -> None:
    """The leading days of October are tappable too."""
    view, recorder = _month()
    cell = view.cells[0]

    down = _touch(cell.x + 3, cell.y + 3)
    cell.on_touch_down(down)
    cell.on_touch_up(down)

    assert recorder.new_starts == [datetime(2026, 10, 26, 9, 0, tzinfo=BERLIN)]


def test_a_drag_over_a_cell_is_not_a_tap() -> None:
    """A touch that moves far between down and up does nothing."""
    view, recorder = _month()
    cell = view.cell_for(date(2026, 11, 20))
    assert cell is not None
    x, y = cell.x + cell.width / 2, cell.y + dp(4)

    down = _touch(x, y)
    cell.on_touch_down(down)
    up = _touch(x, y + dp(60))
    cell.on_touch_up(up)

    assert recorder.new_starts == []


def test_plus_line_shows_the_week_of_that_day() -> None:
    """Tapping "+N" calls ``show_week`` with the day, not ``new_event_at``."""
    events = [_event(f"e{i}", 11, 8 + i, 9 + i) for i in range(6)]
    view, recorder = _month(*events)
    cell = view.cell_for(date(2026, 11, 11))
    assert cell is not None and cell.more is not None

    cell.more.dispatch("on_release")

    assert recorder.weeks == [date(2026, 11, 11)]
    assert recorder.new_starts == []


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
) -> tuple[Any, list[datetime]]:
    """Return the main screen with the clocks pinned to the test month."""
    from kivy.uix.screenmanager import ScreenManager

    from kivy_calendar.screens.add_event import AddEventScreen
    from kivy_calendar.screens.main import MainScreen

    starts: list[datetime] = []
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
    for view in (main_screen.week_view, main_screen.month_view):
        view.tz = BERLIN
        view._now = lambda: NOW
    main_screen.week_view.go_today()
    main_screen.month_view.go_today()
    main_screen._show_events(list(events))
    return main_screen, starts


def test_month_button_is_enabled_and_swaps_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Month replaces the list and drops the date chips and sort spinner."""
    main_screen, _ = _main(monkeypatch, _event("a", 11))
    assert not main_screen.view_buttons["month"].disabled
    assert main_screen.filter_panel.parent is not None

    main_screen.view_buttons["month"].dispatch("on_release")

    assert main_screen.current_view == "month"
    assert main_screen.view_body.children == [main_screen.month_view]
    assert main_screen.filter_panel.parent is None
    assert [c.text for c in main_screen.month_view.chips] == ["a"]
    # A plain count folds away in grid views.
    assert main_screen.status_label.text == ""
    assert main_screen.status_label.height == 0

    main_screen.view_buttons["list"].dispatch("on_release")

    assert main_screen.current_view == "list"
    assert main_screen.filter_panel.parent is not None
    assert main_screen.status_label.text == "1 event"
    assert main_screen.status_label.height > 0
    assert main_screen.content.padding[3] == 0


def test_month_chip_opens_the_event_form_and_empty_day_adds_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Taps on the main screen's month go to the event form."""
    event = _event("a", 11)
    main_screen, starts = _main(monkeypatch, event)
    main_screen.show_view("month")
    opened: list[Any] = []
    monkeypatch.setattr(
        main_screen.manager.get_screen("add_event"), "open_for", opened.append
    )

    main_screen.month_view.chips[0].dispatch("on_release")
    cell = main_screen.month_view.cell_for(date(2026, 11, 20))
    down = _touch(cell.x + 3, cell.y + 3)
    cell.on_touch_down(down)
    cell.on_touch_up(down)

    assert opened == [event]
    assert starts == [datetime(2026, 11, 20, 9, 0, tzinfo=BERLIN)]


def test_plus_line_switches_the_main_screen_to_that_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "+N" opens the week view on the week containing the day."""
    events = [_event(f"e{i}", 20, 8 + i, 9 + i) for i in range(8)]
    main_screen, _ = _main(monkeypatch, *events)
    main_screen.show_view("month")
    main_screen.month_view.grid.do_layout()
    cell = main_screen.month_view.cell_for(date(2026, 11, 20))
    assert cell is not None
    cell._fill()
    assert cell.more is not None

    cell.more.dispatch("on_release")

    assert main_screen.current_view == "week"
    assert main_screen.view_body.children == [main_screen.week_view]
    assert main_screen.week_view.week_layout is not None
    assert main_screen.week_view.week_layout.days[0] == date(2026, 11, 16)
    assert len(main_screen.week_view.blocks) == 8


def test_month_view_uses_the_name_filter_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The name filter narrows the month; a reload redraws it."""
    main_screen, _ = _main(
        monkeypatch, _event("Standup", 11, 9, 10), _event("Lunch", 11, 12, 13)
    )
    main_screen.show_view("month")
    assert len(main_screen.month_view.chips) == 2

    main_screen.name_filter.text = "lunch"
    main_screen._apply_filters()

    assert [c.text for c in main_screen.month_view.chips] == ["Lunch"]
    assert main_screen.status_label.text == ""

    main_screen.name_filter.text = "zzz"
    main_screen._apply_filters()

    assert main_screen.month_view.chips == []
    assert main_screen.status_label.text == "No events match the filters."

    main_screen.name_filter.text = ""
    main_screen._show_events([_event("New", 10, 8, 9)])
    assert [c.text for c in main_screen.month_view.chips] == ["New"]


def test_grid_views_end_above_the_new_event_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 6-row month fits the room above the floating button."""
    main_screen, _ = _main(monkeypatch, _event("a", 11))
    root = main_screen.children[0]
    root.size = (dp(411), dp(914))
    main_screen.show_view("month")
    for widget in (
        root,
        main_screen.content,
        main_screen.view_body,
        main_screen.month_view,
        main_screen.month_view.grid,
    ):
        widget.do_layout()

    button = main_screen.add_button
    cells = main_screen.month_view.cells
    assert len(cells) == 42
    assert all(cell.height > dp(40) for cell in cells)
    assert min(cell.y for cell in cells) >= button.top

    main_screen.show_view("list")
    assert main_screen.content.padding[3] == 0


def test_nav_row_chip_and_arrows_share_a_vertical_centre() -> None:
    """Today is as tall as the arrows and sits on the same centre line."""
    view, _ = _month()
    nav = view.previous_button.parent
    nav.do_layout()

    buttons = (view.previous_button, view.next_button, view.today_button)
    assert len({b.height for b in buttons}) == 1
    centres = {round(b.center_y, 3) for b in buttons}
    assert centres == {round(nav.center_y, 3)}
