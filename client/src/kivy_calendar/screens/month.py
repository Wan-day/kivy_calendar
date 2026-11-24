"""The month view: a grid of day cells with compact event chips."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, tzinfo
from typing import Any

from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from kivy_calendar.grid_layout import MonthLayout, at_local, build_month, month_title
from kivy_calendar.models import CalendarEvent
from kivy_calendar.screens.date_picker import WEEKDAYS, shift_month
from kivy_calendar.screens.theme import (
    BORDER,
    CALENDAR_DOTS,
    CLEAR,
    DEEP_SKY,
    FONT,
    FONT_SEMIBOLD,
    INK,
    LINK,
    MUTED,
    NOW_TINT,
    SKY,
    Paint,
    chip_button,
    icon_button,
)
from kivy_calendar.screens.week import TAP_SLOP, ColourFor, EventBlock

NEW_EVENT_MINUTE = 9 * 60
NUMBER_ROW = dp(20)
CHIP_HEIGHT = dp(15)
CHIP_GAP = dp(1)
CELL_PADDING = dp(2)
# Day numbers and chips of the days around the month, clearly lighter.
OTHER_MONTH_NUMBER = (*MUTED[:3], 0.45)
OTHER_MONTH_CHIP_OPACITY = 0.55


class EventChip(EventBlock):
    """A one-line event chip small enough for a phone's day cell."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create the chip; its title is clipped, not shortened with "..."."""
        super().__init__(*args, **kwargs)
        self.shorten = False

    def _fit_text(self, *_: Any) -> None:
        """Keep the title on one line; ``texture_update`` clips it."""
        self.text_size = (max(self.width - dp(4), dp(4)), self.height)
        self.max_lines = 1

    def texture_update(self, *args: Any) -> None:
        """Draw as many characters of the title as fit, with no ellipsis."""
        label = self._label
        label.text = self._clip(self.text, self.text_size[0] or 0)
        super().texture_update(*args)

    def _clip(self, text: str, room: float) -> str:
        """Return the longest start of ``text`` that is at most ``room`` wide."""
        if not text or room <= 0:
            return text
        extents = self._label.get_extents
        if extents(text)[0] <= room:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if extents(text[:mid])[0] <= room:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip()


class MoreLine(ButtonBehavior, Label):
    """The "+N" line of a day cell with more events than fit."""

    def __init__(self, count: int, **kwargs: Any) -> None:
        """Create the line for ``count`` hidden events."""
        super().__init__(
            text=f"+{count}",
            font_name=FONT_SEMIBOLD,
            font_size="10sp",
            color=LINK,
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=CHIP_HEIGHT,
            **kwargs,
        )
        self.count = count
        self.bind(size=lambda lbl, size: setattr(lbl, "text_size", size))


class DayCell(BoxLayout):
    """One day: its number, as many chips as fit, and a "+N" line."""

    def __init__(
        self,
        day: date,
        events: Sequence[CalendarEvent],
        *,
        is_today: bool,
        in_month: bool,
        open_event: Callable[[CalendarEvent], None],
        on_tap: Callable[[date], None],
        on_more: Callable[[date], None],
        colour_for: ColourFor,
        **kwargs: Any,
    ) -> None:
        """Create the cell for ``day`` showing ``events``."""
        super().__init__(
            orientation="vertical",
            padding=CELL_PADDING,
            spacing=CHIP_GAP,
            **kwargs,
        )
        self.day = day
        self.events = list(events)
        self.open_event = open_event
        self.on_tap = on_tap
        self.on_more = on_more
        self.colour_for = colour_for
        self.in_month = in_month
        self.is_today = is_today
        self.chips: list[EventChip] = []
        self.more: MoreLine | None = None
        self._tap_start: tuple[float, float] | None = None
        self._on_child = False
        # Fills the room under the chips so the number and chips sit on top.
        self._filler = Widget()

        Paint(self, NOW_TINT if is_today else CLEAR, radius=4, border=BORDER)
        self.number = Label(
            text=str(day.day),
            font_name=FONT_SEMIBOLD if is_today else FONT,
            font_size="12sp",
            color=INK if is_today or in_month else OTHER_MONTH_NUMBER,
            size_hint=(None, None),
            size=(dp(22), NUMBER_ROW - dp(2)),
        )
        if is_today:
            Paint(self.number, SKY, radius=10)
        self.add_widget(self.number)
        self.add_widget(self._filler)
        self.bind(size=self._fill)
        self._fill()

    @property
    def capacity(self) -> int:
        """Return how many one-line rows fit under the day number."""
        room = self.height - 2 * CELL_PADDING - NUMBER_ROW
        return max(0, int((room + CHIP_GAP) // (CHIP_HEIGHT + CHIP_GAP)))

    def _fill(self, *_: Any) -> None:
        """Show the chips that fit, then "+N" for the rest."""
        for child in [*self.chips, *([self.more] if self.more else [])]:
            self.remove_widget(child)
        self.remove_widget(self._filler)
        self.chips = []
        self.more = None
        shown = len(self.events)
        if shown > self.capacity:
            shown = max(0, self.capacity - 1)
        for event in self.events[:shown]:
            chip = EventChip(event, self.colour_for(event.calendar_id), font_size="9sp")
            chip.size_hint = (1, None)
            chip.height = CHIP_HEIGHT
            if not self.in_month:
                chip.opacity = OTHER_MONTH_CHIP_OPACITY
            chip.bind(on_release=lambda c: self.open_event(c.event))
            self.chips.append(chip)
            self.add_widget(chip)
        hidden = len(self.events) - shown
        if hidden:
            self.more = MoreLine(hidden)
            self.more.bind(on_release=lambda *_: self.on_more(self.day))
            self.add_widget(self.more)
        self.add_widget(self._filler)

    def _hits_child(self, touch: Any) -> bool:
        """Return whether ``touch`` is on a chip or the "+N" line."""
        targets: list[Widget] = [*self.chips]
        if self.more is not None:
            targets.append(self.more)
        return any(child.collide_point(*touch.pos) for child in targets)

    def on_touch_down(self, touch: Any) -> bool:
        """Remember where a touch started so a drag is not taken as a tap."""
        inside = self.collide_point(*touch.pos)
        self._on_child = inside and self._hits_child(touch)
        # Only a touch that starts on empty space can become a day tap.
        self._tap_start = touch.pos if inside and not self._on_child else None
        return super().on_touch_down(touch)

    def on_touch_up(self, touch: Any) -> bool:
        """Treat a short touch on empty space as a tap on the day.

        A touch that started on a chip or "+N" belongs to that child, which
        fires its own action, so the day is never also tapped.
        """
        handled = super().on_touch_up(touch)
        start, self._tap_start = self._tap_start, None
        on_child, self._on_child = self._on_child, False
        if handled or on_child or start is None:
            return handled
        if getattr(touch, "grab_current", None) is not None:
            return False
        if not self.collide_point(*touch.pos) or self._hits_child(touch):
            return False
        if abs(touch.x - start[0]) > TAP_SLOP or abs(touch.y - start[1]) > TAP_SLOP:
            return False
        self.on_tap(self.day)
        return True


class MonthView(BoxLayout):
    """Navigation, weekday names and the grid of day cells.

    ``open_event`` gets a tapped chip's event; ``new_event_at`` gets the aware
    09:00 (grid zone) of a tapped empty day; ``show_week`` gets the day whose
    "+N" line was tapped.
    """

    def __init__(
        self,
        open_event: Callable[[CalendarEvent], None],
        new_event_at: Callable[[datetime], None],
        show_week: Callable[[date], None] | None = None,
        *,
        colour_for: ColourFor | None = None,
        tz: tzinfo | None = None,
        now: Callable[[], datetime] | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the view on the current month."""
        super().__init__(orientation="vertical", spacing=dp(6), **kwargs)
        self.open_event = open_event
        self.new_event_at = new_event_at
        self.show_week = show_week or (lambda _day: None)
        self.colour_for: ColourFor = colour_for or (lambda _id: CALENDAR_DOTS[0])
        self.tz = tz
        self._now = now or (lambda: datetime.now().astimezone())
        self.events: list[CalendarEvent] = []
        self.month_layout: MonthLayout | None = None
        self.cells: list[DayCell] = []

        self.previous_button = icon_button("chevron_left", border=None)
        self.previous_button.bind(on_release=lambda *_: self.shift_month(-1))
        self.next_button = icon_button("chevron_right", border=None)
        self.next_button.bind(on_release=lambda *_: self.shift_month(1))
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
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(4)
        )
        nav.add_widget(self.previous_button)
        nav.add_widget(self.title_label)
        nav.add_widget(self.next_button)
        nav.add_widget(self.today_button)

        names = GridLayout(cols=7, size_hint_y=None, height=dp(20))
        for name in WEEKDAYS:
            names.add_widget(
                Label(text=name, font_name=FONT, font_size="12sp", color=MUTED)
            )
        self.grid = GridLayout(cols=7, rows=6, spacing=dp(2))
        self.add_widget(nav)
        self.add_widget(names)
        self.add_widget(self.grid)

        self.anchor = self.today().replace(day=1)
        self._render()

    def today(self) -> date:
        """Return today's date in the grid zone."""
        return self._now().astimezone(self.tz).date()

    @property
    def chips(self) -> list[EventChip]:
        """Return the shown event chips, cell by cell."""
        return [chip for cell in self.cells for chip in cell.chips]

    def set_events(self, events: Sequence[CalendarEvent]) -> None:
        """Show ``events`` (already filtered) on the current month."""
        self.events = list(events)
        self._render()

    def show_month(self, day: date) -> None:
        """Show the month containing ``day``."""
        self.anchor = day.replace(day=1)
        self._render()

    def shift_month(self, months: int) -> None:
        """Move ``months`` months forward, or back when negative."""
        self.show_month(shift_month(self.anchor, months))

    def go_today(self) -> None:
        """Show the month containing today."""
        self.show_month(self.today())

    def cell_for(self, day: date) -> DayCell | None:
        """Return the cell showing ``day``, if it is on the grid."""
        return next((cell for cell in self.cells if cell.day == day), None)

    def _on_day_tap(self, day: date) -> None:
        """Turn a tapped empty day into an aware 09:00 start."""
        self.new_event_at(at_local(day, NEW_EVENT_MINUTE, self.tz))

    def _on_more(self, day: date) -> None:
        """Hand a tapped "+N" line to the ``show_week`` callback."""
        self.show_week(day)

    def _render(self) -> None:
        """Redraw the title and every day cell."""
        layout = build_month(self.events, self.anchor, self.tz)
        self.month_layout = layout
        today = self.today()
        self.title_label.text = month_title(self.anchor)
        self.grid.clear_widgets()
        # The rows share the grid's height, so every week stays on screen.
        self.grid.rows = len(layout.days) // 7
        self.cells = []
        for day in layout.days:
            cell = DayCell(
                day,
                layout.events[day],
                is_today=day == today,
                in_month=day.month == self.anchor.month,
                open_event=self.open_event,
                on_tap=self._on_day_tap,
                on_more=self._on_more,
                colour_for=self.colour_for,
            )
            self.cells.append(cell)
            self.grid.add_widget(cell)
