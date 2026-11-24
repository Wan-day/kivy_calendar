"""Date and time field for the event form: a month picker and a time sheet."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget

from kivy_calendar.formatting import short_date
from kivy_calendar.screens.date_picker import DatePicker
from kivy_calendar.screens.theme import (
    BACKGROUND,
    BORDER,
    CLEAR,
    CORAL,
    DIVIDER,
    FONT,
    FONT_BOLD,
    FONT_SEMIBOLD,
    INK,
    LINK,
    OVERLAY,
    SKY,
    SKY_TINT,
    SURFACE,
    FlatButton,
    Paint,
    fit_width,
)
from kivy_calendar.screens.ui import caption, wrapped_label

ROW_HEIGHT = dp(36)
GRID_ROW_HEIGHT = dp(44)
SHEET_HEIGHT = dp(590)
MINUTE_STEP = 5
DATE_PLACEHOLDER = "Pick date"
TIME_PLACEHOLDER = "Pick time"


def hour_choices() -> list[str]:
    """Return the hours offered in the first grid, ``00`` to ``23``."""
    return [f"{hour:02d}" for hour in range(24)]


def minute_choices(hour: int) -> list[str]:
    """Return ``HH:MM`` times for ``hour`` in five-minute steps."""
    return [f"{hour:02d}:{minute:02d}" for minute in range(0, 60, MINUTE_STEP)]


def _chip(text: str, font_name: str) -> FlatButton:
    """Return a light-blue chip for the date or the time."""
    chip = FlatButton(
        text=text,
        fill=SKY_TINT,
        text_color=INK,
        radius=10,
        font_name=font_name,
        font_size="14sp",
        size_hint=(None, None),
        height=ROW_HEIGHT,
    )
    fit_width(chip, 24)
    return chip


class DateTimeField(BoxLayout):
    """A date chip beside a time chip.

    The date chip opens a month calendar; the time chip opens a sheet with
    an hour grid and a five-minute grid.  ``text`` reads and writes the
    combined wall-clock value (``2026-11-09T14:05``), or just the date while
    the time is hidden for all-day events, so the form can treat it like a
    single text input.
    """

    def __init__(self, title: str = "Start", **kwargs: Any) -> None:
        """Create the date and time chips."""
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("height", ROW_HEIGHT)
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self.bind(minimum_width=self.setter("width"))
        self.title = title
        self.date_button = _chip(DATE_PLACEHOLDER, FONT)
        self.date_button.bind(on_release=lambda *_: self.open_date_picker())
        self.time_button = _chip(TIME_PLACEHOLDER, FONT_SEMIBOLD)
        self.time_button.bind(on_release=lambda *_: self.open_hour_picker())
        self.add_widget(self.date_button)
        self.add_widget(self.time_button)
        self._date = ""
        self._time = ""
        self._show_time = True
        self.date_picker: DatePicker | None = None
        self._sheet: ModalView | None = None
        self._pending_hour: int | None = None
        # Values the user picks from next: hours, then the minutes of the
        # chosen hour.  Empty while no time sheet is in use.
        self.choices: list[str] = []
        # The entry of ``choices`` matching the current time, if any.
        self.selected_choice = ""
        # Called with the previous ``text`` after the user picks a date or a
        # time; values the form sets do not trigger it.
        self.on_user_change: Callable[[str], None] | None = None

    @property
    def text(self) -> str:
        """Return the wall-clock value, or only the date without a time."""
        if not self._show_time or not self._time:
            return self._date
        return f"{self._date}T{self._time}"

    @text.setter
    def text(self, value: str) -> None:
        """Split ``value`` into its date and time parts."""
        day, _, time = value.strip().partition("T")
        self._set_date(day)
        self._set_time(time)

    @property
    def time(self) -> str:
        """Return the selected time text, empty when none is set."""
        return self._time

    @property
    def show_time(self) -> bool:
        """Return whether the time chip is shown (not an all-day event)."""
        return self._show_time

    @show_time.setter
    def show_time(self, value: bool) -> None:
        """Show the time chip for timed events, hide it for all-day ones."""
        if value == self._show_time:
            return
        self._show_time = value
        if value:
            self.add_widget(self.time_button)
        else:
            self.dismiss_picker()
            self.remove_widget(self.time_button)

    def open_date_picker(self) -> None:
        """Open the month calendar at the current date."""
        self.date_picker = DatePicker(self._parsed_date(), self._on_date_picked)
        if self.get_parent_window() is not None:
            self.date_picker.open()

    def select_date(self, day: date) -> None:
        """Set the date as the user's choice and report the change."""
        previous = self.text
        self._set_date(day.isoformat())
        if self.on_user_change is not None and self.text != previous:
            self.on_user_change(previous)

    def open_hour_picker(self) -> None:
        """Open the time sheet with the current hour selected."""
        current = self._time[:2]
        self.choices = hour_choices()
        self.selected_choice = current if current in self.choices else ""
        self._pending_hour = int(current) if self.selected_choice else None
        if self.get_parent_window() is not None:
            self._open_sheet()

    def select_hour(self, hour: int) -> None:
        """Remember ``hour`` and offer its five-minute steps."""
        values = minute_choices(hour)
        self._pending_hour = hour
        self.choices = values
        self.selected_choice = self._nearest_choice(values)
        self._render_sheet()

    def select_time(self, value: str) -> None:
        """Set the time from a ``HH:MM`` choice and close the sheet."""
        previous = self.text
        self._set_time(value)
        self.dismiss_picker()
        if self.on_user_change is not None and self.text != previous:
            self.on_user_change(previous)

    def dismiss_picker(self) -> None:
        """Close the time sheet if it is open."""
        sheet = self._sheet
        self._sheet = None
        if sheet is not None:
            sheet.dismiss()
        self.choices = []
        self.selected_choice = ""
        self._pending_hour = None

    def _on_date_picked(self, day: date | None) -> None:
        """Apply a date chosen in the month calendar."""
        self.date_picker = None
        if day is not None:
            self.select_date(day)

    def _open_sheet(self) -> None:
        """Build and show the bottom sheet with the hour and minute grids."""
        sheet = ModalView(
            size_hint=(1, None),
            height=SHEET_HEIGHT,
            pos_hint={"x": 0, "y": 0},
            background="",
            background_color=CLEAR,
            overlay_color=OVERLAY,
        )
        body = BoxLayout(
            orientation="vertical",
            padding=(dp(20), dp(10), dp(20), dp(20)),
            spacing=dp(12),
        )
        Paint(body, SURFACE, radius=[24, 24, 0, 0])

        handle_row = BoxLayout(size_hint_y=None, height=dp(4))
        handle_row.add_widget(Widget())
        handle = Widget(size_hint=(None, None), size=(dp(40), dp(4)))
        Paint(handle, BORDER, radius=2)
        handle_row.add_widget(handle)
        handle_row.add_widget(Widget())
        body.add_widget(handle_row)

        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40))
        header.add_widget(
            wrapped_label(
                text=f"{self.title} time", font_name=FONT_SEMIBOLD, font_size="18sp"
            )
        )
        self._readout = Label(
            font_name=FONT_BOLD,
            font_size="28sp",
            color=INK,
            halign="right",
            valign="middle",
        )
        self._readout.bind(size=lambda label, size: setattr(label, "text_size", size))
        header.add_widget(self._readout)
        body.add_widget(header)

        body.add_widget(caption("1. Hour"))
        self._hour_buttons: list[FlatButton] = []
        hours = GridLayout(cols=6, spacing=dp(6), size_hint_y=None)
        hours.bind(minimum_height=hours.setter("height"))
        for value in hour_choices():
            button = self._grid_button(value)
            button.bind(on_release=lambda btn: self.select_hour(int(btn.value)))
            hours.add_widget(button)
            self._hour_buttons.append(button)
        body.add_widget(hours)

        body.add_widget(caption("2. Minutes"))
        self._minute_buttons: list[FlatButton] = []
        minutes = GridLayout(cols=6, spacing=dp(6), size_hint_y=None)
        minutes.bind(minimum_height=minutes.setter("height"))
        for minute in range(0, 60, MINUTE_STEP):
            button = self._grid_button(f":{minute:02d}")
            button.minute = minute
            button.bind(on_release=self._on_minute)
            minutes.add_widget(button)
            self._minute_buttons.append(button)
        body.add_widget(minutes)

        body.add_widget(Widget())
        cancel = FlatButton(
            text="Cancel",
            fill=BACKGROUND,
            text_color=LINK,
            radius=14,
            size_hint_y=None,
            height=dp(48),
        )
        cancel.bind(on_release=lambda *_: self.dismiss_picker())
        body.add_widget(cancel)

        sheet.add_widget(body)
        sheet.bind(on_dismiss=self._on_sheet_dismissed)
        self._sheet = sheet
        self._render_sheet()
        sheet.open()

    @staticmethod
    def _grid_button(value: str) -> FlatButton:
        """Return one cell of the hour or minute grid."""
        button = FlatButton(
            text=value,
            fill=SURFACE,
            border=DIVIDER,
            text_color=INK,
            radius=10,
            font_name=FONT,
            size_hint_y=None,
            height=GRID_ROW_HEIGHT,
        )
        button.value = value
        return button

    def _on_minute(self, button: FlatButton) -> None:
        """Set the time from a tapped minute and the chosen hour."""
        if self._pending_hour is None:
            return
        self.select_time(f"{self._pending_hour:02d}:{button.minute:02d}")

    def _on_sheet_dismissed(self, sheet: ModalView) -> None:
        """Forget the sheet once it closes, e.g. after a tap outside it."""
        if self._sheet is sheet:
            self._sheet = None
            self.choices = []
            self.selected_choice = ""
            self._pending_hour = None

    def _render_sheet(self) -> None:
        """Highlight the chosen hour and minute and update the readout."""
        if self._sheet is None:
            return
        hour = self._pending_hour
        now_hour = datetime.now().hour
        for button in self._hour_buttons:
            value = int(button.value)
            chosen = value == hour
            button.font_name = FONT_SEMIBOLD if chosen else FONT
            button.set_colors(
                fill=SKY if chosen else SURFACE,
                border=CORAL if value == now_hour and not chosen else DIVIDER,
            )
        selected_minute = self.selected_choice[3:5] if hour is not None else ""
        for button in self._minute_buttons:
            chosen = selected_minute == f"{button.minute:02d}"
            button.disabled = hour is None
            button.font_name = FONT_SEMIBOLD if chosen else FONT
            button.set_colors(
                fill=SKY if chosen else SURFACE,
                border=None if chosen else DIVIDER,
            )
        hour_text = f"{hour:02d}" if hour is not None else "--"
        minute_text = selected_minute or "—"
        self._readout.text = f"{hour_text}:{minute_text}"

    def _nearest_choice(self, values: list[str]) -> str:
        """Return the minute choice at or just before the current time."""
        current = self._time[:5]
        if not values or current[:2] != values[0][:2]:
            return ""
        earlier = [value for value in values if value <= current]
        return earlier[-1] if earlier else values[0]

    def _parsed_date(self) -> date | None:
        """Return the date part as a date, or ``None`` when it is not one."""
        try:
            return date.fromisoformat(self._date)
        except ValueError:
            return None

    def _set_date(self, value: str) -> None:
        """Store the date text and show it on the date chip."""
        self._date = value
        parsed = self._parsed_date()
        if parsed is not None:
            self.date_button.text = short_date(parsed)
        else:
            self.date_button.text = value or DATE_PLACEHOLDER

    def _set_time(self, value: str) -> None:
        """Store the time text and show it on the time chip."""
        self._time = value
        self.time_button.text = value[:5] if value else TIME_PLACEHOLDER
