"""Date field with an hour-then-minute time picker for the event form."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.textinput import TextInput

ROW_HEIGHT = 44
DROPDOWN_MAX_HEIGHT = 320
MINUTE_STEP = 5
TIME_PLACEHOLDER = "Pick time"


def hour_choices() -> list[str]:
    """Return the hours offered in the first dropdown, ``00`` to ``23``."""
    return [f"{hour:02d}" for hour in range(24)]


def minute_choices(hour: int) -> list[str]:
    """Return ``HH:MM`` times for ``hour`` in five-minute steps."""
    return [f"{hour:02d}:{minute:02d}" for minute in range(0, 60, MINUTE_STEP)]


class DateTimeField(BoxLayout):
    """A date input beside a time button that opens hour, then minute lists.

    ``text`` reads and writes the combined wall-clock value
    (``2026-11-09T14:05``), or just the date while the time is hidden for
    all-day events, so the form can treat it like a single text input.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Create the date input and the time button."""
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", ROW_HEIGHT)
        kwargs.setdefault("spacing", 8)
        super().__init__(**kwargs)
        self.date_input = TextInput(
            hint_text="2026-11-09",
            multiline=False,
            size_hint_x=0.6,
            padding=(10, 10),
        )
        self.time_button = Button(text=TIME_PLACEHOLDER, size_hint_x=0.4)
        self.time_button.bind(on_release=lambda *_: self.open_hour_picker())
        self.add_widget(self.date_input)
        self.add_widget(self.time_button)
        self._time = ""
        self._show_time = True
        self._dropdown: DropDown | None = None
        # Values in the open hour or minute list, empty when none is open.
        self.choices: list[str] = []

    @property
    def text(self) -> str:
        """Return the wall-clock value, or only the date without a time."""
        day = self.date_input.text.strip()
        if not self._show_time or not self._time:
            return day
        return f"{day}T{self._time}"

    @text.setter
    def text(self, value: str) -> None:
        """Split ``value`` into its date and time parts."""
        day, _, time = value.strip().partition("T")
        self.date_input.text = day
        self._set_time(time)

    @property
    def time(self) -> str:
        """Return the selected time text, empty when none is set."""
        return self._time

    @property
    def show_time(self) -> bool:
        """Return whether the time button is shown (not an all-day event)."""
        return self._show_time

    @show_time.setter
    def show_time(self, value: bool) -> None:
        """Show the time button for timed events, hide it for all-day ones."""
        if value == self._show_time:
            return
        self._show_time = value
        if value:
            self.add_widget(self.time_button)
        else:
            self.dismiss_picker()
            self.remove_widget(self.time_button)

    def open_hour_picker(self) -> None:
        """Open the hour list below the time button."""
        self._open_dropdown(hour_choices(), lambda value: self.select_hour(int(value)))

    def select_hour(self, hour: int) -> None:
        """Remember ``hour`` and open the minute list for it."""
        values = minute_choices(hour)
        self.choices = values
        # Open on the next frame so the closing hour list does not swallow it.
        Clock.schedule_once(lambda *_: self._open_dropdown(values, self.select_time), 0)

    def select_time(self, value: str) -> None:
        """Set the time from a ``HH:MM`` choice."""
        self.choices = []
        self._set_time(value)

    def dismiss_picker(self) -> None:
        """Close any open hour or minute list."""
        if self._dropdown is not None:
            self._dropdown.dismiss()
            self._dropdown = None
        self.choices = []

    def _open_dropdown(self, values: list[str], on_pick: Callable[[str], None]) -> None:
        """Show ``values`` in a dropdown and pass the chosen one to ``on_pick``."""
        self.dismiss_picker()
        self.choices = values
        dropdown = DropDown(max_height=DROPDOWN_MAX_HEIGHT)
        for value in values:
            button = Button(text=value, size_hint_y=None, height=ROW_HEIGHT)
            button.bind(on_release=lambda btn: dropdown.select(btn.text))
            dropdown.add_widget(button)

        def picked(_: DropDown, value: str) -> None:
            self._dropdown = None
            on_pick(value)

        dropdown.bind(on_select=picked)
        self._dropdown = dropdown
        if self.get_parent_window() is not None:
            dropdown.open(self.time_button)

    def _set_time(self, value: str) -> None:
        """Store the time text and show it on the button."""
        self._time = value
        self.time_button.text = value[:5] if value else TIME_PLACEHOLDER
