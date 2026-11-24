"""A month calendar popup for picking a date."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date
from typing import Any

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget

from kivy_calendar.screens.theme import (
    CLEAR,
    CORAL,
    FONT,
    FONT_SEMIBOLD,
    INK,
    LINK,
    MUTED,
    OVERLAY,
    SKY,
    SURFACE,
    FlatButton,
    Paint,
    ghost_button,
    icon_button,
)
from kivy_calendar.screens.ui import wrapped_label

WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
DAY_SIZE = 40


def month_grid(year: int, month: int) -> list[date | None]:
    """Return 42 cells for a Monday-first month view; blanks are ``None``."""
    cells: list[date | None] = [
        day if day.month == month else None
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
        for day in week
    ]
    return cells + [None] * (42 - len(cells))


def shift_month(day: date, months: int) -> date:
    """Return the first day of the month ``months`` after ``day``'s month."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


class DatePicker(ModalView):
    """A centered card with one month of days and month arrows.

    ``on_pick`` gets the chosen date, or ``None`` when ``allow_clear`` is set
    and the user clears the value.
    """

    def __init__(
        self,
        selected: date | None,
        on_pick: Callable[[date | None], None],
        *,
        allow_clear: bool = False,
        today: date | None = None,
        **kwargs: Any,
    ) -> None:
        """Build the card showing ``selected``'s month, or today's."""
        super().__init__(
            size_hint=(None, None),
            size=(7 * DAY_SIZE + 6 * 4 + 32, 440),
            background="",
            background_color=CLEAR,
            overlay_color=OVERLAY,
            **kwargs,
        )
        self.selected = selected
        self.today = today if today is not None else date.today()
        self.on_pick = on_pick
        self.month = (selected or self.today).replace(day=1)

        card = BoxLayout(orientation="vertical", padding=16, spacing=8)
        Paint(card, SURFACE, radius=20)

        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=44)
        previous = icon_button("chevron_left", fill=CLEAR, border=None)
        previous.bind(on_release=lambda *_: self.show_month(-1))
        following = icon_button("chevron_right", fill=CLEAR, border=None)
        following.bind(on_release=lambda *_: self.show_month(1))
        self.title_label = wrapped_label(font_name=FONT_SEMIBOLD, font_size="16sp")
        self.title_label.halign = "center"
        header.add_widget(previous)
        header.add_widget(self.title_label)
        header.add_widget(following)
        card.add_widget(header)

        names = GridLayout(cols=7, spacing=4, size_hint_y=None, height=20)
        for name in WEEKDAYS:
            label = wrapped_label(text=name, font_size="12sp", color=MUTED)
            label.halign = "center"
            names.add_widget(label)
        card.add_widget(names)

        self.grid = GridLayout(cols=7, spacing=4, size_hint_y=None)
        self.grid.bind(minimum_height=self.grid.setter("height"))
        card.add_widget(self.grid)
        card.add_widget(Widget())

        footer = BoxLayout(orientation="horizontal", size_hint_y=None, height=44)
        if allow_clear:
            clear = ghost_button("Clear", color=MUTED)
            clear.bind(on_release=lambda *_: self.pick(None))
            footer.add_widget(clear)
        cancel = ghost_button("Cancel", color=LINK)
        cancel.bind(on_release=lambda *_: self.dismiss())
        footer.add_widget(cancel)
        card.add_widget(footer)

        self.add_widget(card)
        self.day_buttons: list[FlatButton] = []
        self._render()

    def show_month(self, months: int) -> None:
        """Move the view ``months`` forward (or back when negative)."""
        self.month = shift_month(self.month, months)
        self._render()

    def pick(self, day: date | None) -> None:
        """Close the picker and report ``day``."""
        self.dismiss()
        self.on_pick(day)

    def _render(self) -> None:
        """Fill the grid with the days of the shown month."""
        self.title_label.text = f"{self.month:%B %Y}"
        self.grid.clear_widgets()
        self.day_buttons = []
        for day in month_grid(self.month.year, self.month.month):
            if day is None:
                self.grid.add_widget(
                    Widget(size_hint=(None, None), size=(DAY_SIZE, DAY_SIZE))
                )
                continue
            chosen = day == self.selected
            button = FlatButton(
                text=str(day.day),
                fill=SKY if chosen else CLEAR,
                border=CORAL if day == self.today and not chosen else None,
                text_color=INK,
                radius=None,
                font_name=FONT_SEMIBOLD if chosen else FONT,
                font_size="14sp",
                size_hint=(None, None),
                size=(DAY_SIZE, DAY_SIZE),
            )
            button.day = day
            button.bind(on_release=lambda btn: self.pick(btn.day))
            self.grid.add_widget(button)
            self.day_buttons.append(button)
