"""The week view: seven day columns over a scrolling 24-hour grid."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from kivy.clock import Clock
from kivy.graphics import Color, Line
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget

from kivy_calendar.grid_layout import (
    DAY_MINUTES,
    PlacedEvent,
    WeekLayout,
    at_local,
    build_week,
    round_down,
    week_title,
)
from kivy_calendar.models import CalendarEvent
from kivy_calendar.screens.theme import (
    BORDER,
    CALENDAR_DOTS,
    CORAL,
    DEEP_SKY,
    DIVIDER,
    FONT,
    FONT_SEMIBOLD,
    INK,
    MUTED,
    NOW_TINT,
    RGBA,
    SKY,
    Paint,
    chip_button,
    icon_button,
)

HOUR_HEIGHT = dp(48)
GUTTER = dp(36)
FIRST_VISIBLE_HOUR = 7
ALL_DAY_ROW = dp(20)
TAP_SLOP = dp(10)
SNAP_MINUTES = 30
# Room above the 00:00 line, so the first hour label is not cut off.
TOP_INSET = dp(8)
GRID_HEIGHT = 24 * HOUR_HEIGHT + TOP_INSET
# Padding between a block's outline and its title.
TEXT_PAD = dp(3)
NAV_HEIGHT = dp(44)
# Seconds between redraws of the current-time line.
NOW_REFRESH = 60

ColourFor = Callable[[str], RGBA]


def _tint(colour: RGBA, weight: float = 0.22) -> RGBA:
    """Return ``colour`` faded towards white, as an opaque fill."""
    red, green, blue, _ = colour
    return (
        1 - weight * (1 - red),
        1 - weight * (1 - green),
        1 - weight * (1 - blue),
        1.0,
    )


class EventBlock(ButtonBehavior, Label):
    """A tappable event box: tinted fill, calendar-coloured outline, title."""

    def __init__(
        self,
        event: CalendarEvent,
        colour: RGBA,
        *,
        font_size: str = "11sp",
        **kwargs: Any,
    ) -> None:
        """Create the block for ``event`` in ``colour``."""
        super().__init__(
            text=event.summary or "(no title)",
            font_name=FONT_SEMIBOLD,
            font_size=font_size,
            color=INK,
            halign="left",
            valign="top",
            shorten=True,
            shorten_from="right",
            size_hint=(None, None),
            **kwargs,
        )
        self.event = event
        self.paint = Paint(self, _tint(colour), radius=6, border=colour)
        self.bind(size=self._fit_text)

    def _fit_text(self, *_: Any) -> None:
        """Keep the title inside the block, cut with an ellipsis."""
        width = max(self.width - dp(8), dp(4))
        height = max(self.height - dp(6), dp(4))
        self.text_size = (width, height)
        line = max(self.font_size * 1.3, 1)
        self.max_lines = max(1, int(height // line))


class TitleBlock(EventBlock):
    """An event box whose title wraps and is clipped, never given an ellipsis.

    Shows as many characters as fit, like Google Calendar: the title starts at
    the top left, wraps onto more lines when the box is tall enough and is cut
    off when space runs out.
    """

    def __init__(
        self,
        event: CalendarEvent,
        colour: RGBA,
        *,
        font_size: str = "10sp",
        **kwargs: Any,
    ) -> None:
        """Create the block for ``event`` in ``colour``."""
        super().__init__(event, colour, font_size=font_size, **kwargs)
        self.shorten = False
        self.max_lines = 0

    def _fit_text(self, *_: Any) -> None:
        """Make the title's box the block's inner size, so it wraps and clips."""
        self.text_size = (
            max(self.width - 2 * TEXT_PAD, 1),
            max(self.height - 2 * TEXT_PAD, 1),
        )


class TimeGrid(FloatLayout):
    """Hour lines, hour labels, event blocks and the current-time line.

    Blocks are placed by hand from the ``WeekLayout``.  The grid never gets
    touches itself: ``GridViewport`` owns them and calls ``activate``.
    """

    def __init__(
        self,
        open_event: Callable[[CalendarEvent], None],
        on_empty_tap: Callable[[date, int], None],
        colour_for: ColourFor,
        **kwargs: Any,
    ) -> None:
        """Create an empty 24-hour grid."""
        super().__init__(size_hint_y=None, height=GRID_HEIGHT, **kwargs)
        self.open_event = open_event
        self.on_empty_tap = on_empty_tap
        self.colour_for = colour_for
        self.layout: WeekLayout | None = None
        self.today: date | None = None
        self.now_minute = 0
        self.blocks: list[tuple[TitleBlock, PlacedEvent]] = []
        self.hour_labels: list[Label] = []

        with self.canvas.before:
            Color(*DIVIDER)
            self._hour_lines = [Line(width=dp(1)) for _ in range(24)]
            Color(*BORDER)
            self._day_lines = [Line(width=dp(1)) for _ in range(8)]
        with self.canvas.after:
            self._now_colour = Color(*CORAL)
            self._now_line = Line(width=dp(1.5))
        for hour in range(24):
            label = Label(
                text=f"{hour:02d}:00",
                font_name=FONT,
                font_size="10sp",
                color=MUTED,
                halign="right",
                valign="middle",
                size_hint=(None, None),
            )
            label.bind(size=lambda lbl, size: setattr(lbl, "text_size", size))
            self.hour_labels.append(label)
            self.add_widget(label)
        self.bind(pos=self._place, size=self._place)

    @property
    def column_width(self) -> float:
        """Return the width of one day column."""
        return max(self.width - GUTTER, 0) / 7

    def render(self, layout: WeekLayout, today: date, now_minute: int) -> None:
        """Replace the event blocks with those of ``layout``."""
        for block, _ in self.blocks:
            self.remove_widget(block)
        self.blocks = []
        self.layout = layout
        self.today = today
        self.now_minute = now_minute
        for day in layout.days:
            for placed in layout.timed[day]:
                block = TitleBlock(
                    placed.event, self.colour_for(placed.event.calendar_id)
                )
                self.blocks.append((block, placed))
                self.add_widget(block)
        self._place()

    def y_of(self, minute: float) -> float:
        """Return the window y of ``minute`` minutes after midnight."""
        return self._top - TOP_INSET - minute * self._day_height / DAY_MINUTES

    @property
    def _top(self) -> float:
        """Return the top edge, from ``y`` (the ``top`` alias can lag a move)."""
        return self.y + self.height

    @property
    def _day_height(self) -> float:
        """Return the height of the 24 hours, without the top inset."""
        return max(self.height - TOP_INSET, 0)

    def _place(self, *_: Any) -> None:
        """Position every line, label and block from the current size."""
        scale = self._day_height / 24
        column = self.column_width
        left = self.x + GUTTER
        right = self.x + self.width
        for hour, line in enumerate(self._hour_lines):
            y = self._top - TOP_INSET - hour * scale
            line.points = [left, y, right, y]
        for index, line in enumerate(self._day_lines):
            x = left + index * column
            line.points = [x, self.y, x, self._top]
        for hour, label in enumerate(self.hour_labels):
            label.size = (GUTTER - dp(6), dp(14))
            label.pos = (self.x, self._top - TOP_INSET - hour * scale - dp(7))
        for block, placed in self.blocks:
            lane_width = column / placed.lanes
            block.pos = (
                left
                + self._column_of(placed.day) * column
                + placed.lane * lane_width
                + 1,
                self.y_of(placed.end_minute) + 1,
            )
            block.size = (
                max(lane_width - dp(3), 1),
                max((placed.end_minute - placed.start_minute) * scale / 60 - dp(2), 1),
            )
        self._place_now(left, column)

    def _place_now(self, left: float, column: float) -> None:
        """Draw the current-time line across today's column, if shown."""
        index = self._column_of(self.today) if self.today is not None else -1
        if index < 0:
            self._now_line.points = []
            return
        y = self.y_of(self.now_minute)
        x = left + index * column
        self._now_line.points = [x, y, x + column, y]

    def _column_of(self, day: date) -> int:
        """Return the column index of ``day``, or -1 outside the week."""
        if self.layout is None or day not in self.layout.days:
            return -1
        return self.layout.days.index(day)

    def slot_at(self, x: float, y: float) -> tuple[date, int] | None:
        """Return the day and the 30-minute-rounded minute under a point."""
        if self.layout is None or not self.collide_point(x, y):
            return None
        index = int((x - self.x - GUTTER) // self.column_width) if self.width else -1
        if x - self.x < GUTTER or not 0 <= index < 7:
            return None
        minute = round_down(
            int((self._top - TOP_INSET - y) * DAY_MINUTES / (self._day_height or 1)),
            SNAP_MINUTES,
        )
        return self.layout.days[index], min(max(minute, 0), DAY_MINUTES - SNAP_MINUTES)

    def tap(self, x: float, y: float) -> bool:
        """Report a tap at a window point; return whether it hit a slot."""
        slot = self.slot_at(x, y)
        if slot is None:
            return False
        self.on_empty_tap(*slot)
        return True

    def event_at(self, x: float, y: float) -> CalendarEvent | None:
        """Return the event whose block is under a window point, if any."""
        for block, _ in reversed(self.blocks):
            if block.collide_point(x, y):
                return block.event
        return None

    def activate(self, x: float, y: float) -> None:
        """Handle a tap at a window point: open a block or create at a slot."""
        event = self.event_at(x, y)
        if event is not None:
            self.open_event(event)
        else:
            self.tap(x, y)


class GridViewport(StencilView):
    """A clipped window onto the tall grid that owns every touch inside it.

    There is one decision point per gesture.  A touch is grabbed on the way
    down.  Once the finger has travelled more than ``TAP_SLOP`` from where it
    went down, the gesture is a drag for good and the grid follows the finger
    one to one.  A touch that never did, and ends within the slop, is a tap
    handled on release.  Nothing is timed or replayed.
    """

    __events__ = ("on_drag_start",)

    def __init__(self, grid: TimeGrid, **kwargs: Any) -> None:
        """Create a viewport showing ``grid``, scrolled to its top."""
        super().__init__(**kwargs)
        self.grid = grid
        self.offset = 0.0
        self._touch: Any = None
        self._start = (0.0, 0.0)
        self._start_offset = 0.0
        self._dragging = False
        self.add_widget(grid)
        self.bind(pos=self._layout, size=self._layout)
        self._layout()

    def on_drag_start(self) -> None:
        """Default handler of the event fired when a drag begins."""

    @property
    def max_offset(self) -> float:
        """Return how far the grid can move up; 0 when it fits."""
        return max(self.grid.height - self.height, 0.0)

    def set_offset(self, value: float) -> None:
        """Scroll so ``value`` pixels of the grid are above the top edge."""
        if value != value:
            return
        self.offset = min(max(value, 0.0), self.max_offset)
        self._layout()

    def _layout(self, *_: Any) -> None:
        """Place the grid at the clamped offset, as wide as the viewport."""
        self.offset = min(max(self.offset, 0.0), self.max_offset)
        self.grid.width = self.width
        self.grid.x = self.x
        self.grid.y = self.y + self.height + self.offset - self.grid.height

    def _moved_beyond_slop(self, touch: Any) -> bool:
        """Return whether ``touch`` is now further than the slop from its start."""
        return (
            abs(touch.x - self._start[0]) > TAP_SLOP
            or abs(touch.y - self._start[1]) > TAP_SLOP
        )

    def _follow(self, touch: Any) -> None:
        """Put the grid where the finger drags it."""
        self.set_offset(self._start_offset + touch.y - self._start[1])

    def on_touch_down(self, touch: Any) -> bool:
        """Grab a touch that lands inside, and remember where it began."""
        if not self.collide_point(*touch.pos):
            return False
        if touch.is_mouse_scrolling:
            step = dp(48) if touch.button == "scrollup" else -dp(48)
            self.set_offset(self.offset - step)
            return True
        if self._touch is not None:
            self._touch.ungrab(self)
        touch.grab(self)
        self._touch = touch
        self._start = (touch.x, touch.y)
        self._start_offset = self.offset
        self._dragging = False
        return True

    def on_touch_move(self, touch: Any) -> bool:
        """Drag the grid with the finger once it has left the tap slop."""
        if touch.grab_current is not self or touch is not self._touch:
            return False
        if not self._dragging and self._moved_beyond_slop(touch):
            self._dragging = True
            self.dispatch("on_drag_start")
        if self._dragging:
            self._follow(touch)
        return True

    def on_touch_up(self, touch: Any) -> bool:
        """Finish a gesture: a short, still touch is a tap, anything else is not."""
        if touch.grab_current is not self or touch is not self._touch:
            return False
        touch.ungrab(self)
        self._touch = None
        if self._dragging or self._moved_beyond_slop(touch):
            if not self._dragging:
                self.dispatch("on_drag_start")
            self._dragging = False
            self._follow(touch)
            return True
        if self.collide_point(touch.x, touch.y):
            self.grid.activate(touch.x, touch.y)
        return True


class WeekView(BoxLayout):
    """Navigation, day headers, an all-day strip and the time grid.

    ``open_event`` gets a tapped event; ``new_event_at`` gets the aware start
    (local zone, rounded down to 30 minutes) of a tapped empty slot.
    """

    def __init__(
        self,
        open_event: Callable[[CalendarEvent], None],
        new_event_at: Callable[[datetime], None],
        *,
        colour_for: ColourFor | None = None,
        tz: tzinfo | None = None,
        now: Callable[[], datetime] | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the view on the current week."""
        super().__init__(orientation="vertical", spacing=dp(6), **kwargs)
        self.open_event = open_event
        self.new_event_at = new_event_at
        self.colour_for: ColourFor = colour_for or (lambda _id: CALENDAR_DOTS[0])
        self.tz = tz
        self._now = now or (lambda: datetime.now().astimezone())
        self.events: list[CalendarEvent] = []
        self.week_layout: WeekLayout | None = None
        self._scroll_pending = True
        self._tick: Any = None

        self.previous_button = icon_button("chevron_left", border=None)
        self.previous_button.bind(on_release=lambda *_: self.shift_week(-1))
        self.next_button = icon_button("chevron_right", border=None)
        self.next_button.bind(on_release=lambda *_: self.shift_week(1))
        self.today_button = chip_button("Today", text_color=DEEP_SKY, fill=NOW_TINT)
        self.today_button.bind(on_release=lambda *_: self.go_today())
        self.title_label = Label(
            font_name=FONT_SEMIBOLD,
            font_size="15sp",
            color=INK,
            halign="center",
            valign="middle",
            shorten=True,
        )
        self.title_label.bind(size=lambda lbl, size: setattr(lbl, "text_size", size))
        nav = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=NAV_HEIGHT,
            spacing=dp(4),
        )
        for button in (self.previous_button, self.next_button, self.today_button):
            button.height = NAV_HEIGHT
            button.pos_hint = {"center_y": 0.5}
        nav.add_widget(self.previous_button)
        nav.add_widget(self.title_label)
        nav.add_widget(self.next_button)
        nav.add_widget(self.today_button)

        self.day_header = BoxLayout(orientation="horizontal", size_hint_y=None)
        self.day_header.height = dp(46)
        self.all_day_strip = BoxLayout(orientation="horizontal", size_hint_y=None)
        self.all_day_strip.height = 0
        self.grid = TimeGrid(self.open_event, self._on_empty_tap, self.colour_for)
        self.grid.size_hint_x = None
        self.viewport = GridViewport(self.grid)
        self.viewport.bind(size=self._apply_pending_scroll)
        self.viewport.bind(on_drag_start=self._stop_pending_scroll)
        self.bind(parent=self._on_parent)
        self.add_widget(nav)
        self.add_widget(self.day_header)
        self.add_widget(self.all_day_strip)
        self.add_widget(self.viewport)

        self.anchor = self.today()
        self._render()

    def today(self) -> date:
        """Return today's date in the grid zone."""
        return self._now().astimezone(self.tz).date()

    @property
    def blocks(self) -> list[TitleBlock]:
        """Return the timed event blocks, day by day."""
        return [block for block, _ in self.grid.blocks]

    @property
    def all_day_blocks(self) -> list[TitleBlock]:
        """Return the all-day chips, left to right."""
        return [
            chip
            for column in reversed(self.all_day_strip.children)
            for chip in reversed(column.children)
            if isinstance(chip, TitleBlock)
        ]

    def set_events(self, events: Sequence[CalendarEvent]) -> None:
        """Show ``events`` (already filtered) on the current week."""
        self.events = list(events)
        self._render()

    def show_week(self, day: date) -> None:
        """Show the week containing ``day``."""
        self.anchor = day
        self._render()
        self._reset_scroll()

    def shift_week(self, weeks: int) -> None:
        """Move ``weeks`` weeks forward, or back when negative."""
        self.show_week(self.anchor + timedelta(weeks=weeks))

    def go_today(self) -> None:
        """Show the week containing today."""
        self.show_week(self.today())

    def scroll_to_hour(self, hour: int = FIRST_VISIBLE_HOUR) -> None:
        """Scroll the grid so ``hour`` is at the top of the view."""
        self.viewport.set_offset(hour * HOUR_HEIGHT)

    def _reset_scroll(self) -> None:
        """Go back to 07:00, also after the size settles."""
        self._scroll_pending = True
        self.scroll_to_hour()

    def _on_parent(self, _view: Any, parent: Any) -> None:
        """Start at 07:00 and keep the time line moving while on screen."""
        if self._tick is not None:
            self._tick.cancel()
            self._tick = None
        if parent is not None:
            self._reset_scroll()
            self._render()
            self._tick = Clock.schedule_interval(self._refresh_time, NOW_REFRESH)

    def _refresh_time(self, _dt: float = 0) -> None:
        """Redraw so the current-time line and today's header follow the clock."""
        self._render()

    def _apply_pending_scroll(self, *_: Any) -> None:
        """Keep 07:00 at the top while the view settles to its real size."""
        if self._scroll_pending and self.viewport.height > dp(100):
            self.scroll_to_hour()

    def _stop_pending_scroll(self, *_: Any) -> None:
        """Stop re-applying the opening position once the user scrolls."""
        self._scroll_pending = False

    def _on_empty_tap(self, day: date, minute: int) -> None:
        """Turn a tapped slot into an aware start time."""
        self.new_event_at(at_local(day, minute, self.tz))

    def _render(self) -> None:
        """Redraw the title, day headers, all-day strip and grid."""
        layout = build_week(self.events, self.anchor, self.tz)
        self.week_layout = layout
        today = self.today()
        self.title_label.text = week_title(layout.days)
        self._render_headers(layout, today)
        self._render_all_day(layout)
        now = self._now().astimezone(self.tz).replace(tzinfo=None)
        self.grid.render(layout, today, now.hour * 60 + now.minute)

    def _render_headers(self, layout: WeekLayout, today: date) -> None:
        """Fill the weekday and day-number row."""
        self.day_header.clear_widgets()
        self.day_header.add_widget(Widget(size_hint_x=None, width=GUTTER))
        for day in layout.days:
            is_today = day == today
            label = Label(
                text=f"{day:%a}\n{day.day}",
                font_name=FONT_SEMIBOLD if is_today else FONT,
                font_size="13sp",
                color=INK if is_today else MUTED,
                halign="center",
                valign="middle",
            )
            if is_today:
                Paint(label, SKY, radius=10)
            holder = BoxLayout(padding=dp(1))
            holder.add_widget(label)
            holder.day = day
            self.day_header.add_widget(holder)

    def _render_all_day(self, layout: WeekLayout) -> None:
        """Fill the strip of all-day events, which collapses when empty."""
        self.all_day_strip.clear_widgets()
        most = max((len(layout.all_day[d]) for d in layout.days), default=0)
        self.all_day_strip.height = most * (ALL_DAY_ROW + dp(2)) + dp(2) if most else 0
        self.all_day_strip.opacity = 1 if most else 0
        if not most:
            return
        tag = Label(
            text="all day",
            font_name=FONT,
            font_size="9sp",
            color=MUTED,
            size_hint_x=None,
            width=GUTTER,
        )
        self.all_day_strip.add_widget(tag)
        for day in layout.days:
            column = BoxLayout(orientation="vertical", spacing=dp(2), padding=dp(1))
            for event in layout.all_day[day]:
                chip = TitleBlock(
                    event, self.colour_for(event.calendar_id), font_size="10sp"
                )
                chip.size_hint = (1, None)
                chip.height = ALL_DAY_ROW
                chip.bind(on_release=lambda c: self.open_event(c.event))
                column.add_widget(chip)
            column.add_widget(Widget())
            self.all_day_strip.add_widget(column)
