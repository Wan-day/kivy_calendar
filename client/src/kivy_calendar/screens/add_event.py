"""Add-event screen that creates events in the backend calendar."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from kivy_calendar.api import BackendClient, BackendError, CalendarEvent
from kivy_calendar.formatting import (
    DEFAULT_TIME_ZONE,
    default_event_times,
    to_input_value,
)
from kivy_calendar.screens.ui import wrapped_label

ERROR_COLOR = (0.95, 0.42, 0.42, 1)
STATUS_COLOR = (0.68, 0.68, 0.68, 1)


def _field(caption: str, widget: Any) -> BoxLayout:
    """Stack a caption above a fixed-height form input."""
    box = BoxLayout(
        orientation="vertical",
        size_hint_y=None,
        height=widget.height + 24,
        spacing=2,
    )
    box.add_widget(
        wrapped_label(
            text=caption,
            size_hint_y=None,
            height=18,
            font_size="13sp",
            color=STATUS_COLOR,
        )
    )
    box.add_widget(widget)
    return box


def _input(
    hint: str,
    text: str = "",
    *,
    height: int = 44,
    multiline: bool = False,
) -> TextInput:
    """Create a padded text input for the event form."""
    return TextInput(
        text=text,
        hint_text=hint,
        multiline=multiline,
        size_hint_y=None,
        height=height,
        padding=(10, 10),
    )


class AddEventScreen(Screen):
    """Collect a new event and create it in the backend."""

    def __init__(
        self,
        client: BackendClient | None,
        refresh: Callable[[], None],
        time_zone: str = DEFAULT_TIME_ZONE,
        **kwargs: Any,
    ) -> None:
        """Create the screen with event fields and save/cancel actions."""
        super().__init__(**kwargs)
        self.client = client
        self.refresh = refresh
        self.time_zone = time_zone
        start, end = default_event_times()

        self.summary = _input("Team standup")
        self.start = _input("", to_input_value(start))
        self.end = _input("", to_input_value(end))
        self.start_timezone = _input("", self.time_zone)
        self.end_timezone = _input("", self.time_zone)
        self.description = _input("Optional notes", height=88, multiline=True)

        form = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=10,
            padding=(0, 4),
        )
        form.bind(minimum_height=form.setter("height"))
        form.add_widget(_field("Summary", self.summary))
        form.add_widget(_field("Start (ISO datetime with offset)", self.start))
        form.add_widget(_field("End (ISO datetime with offset)", self.end))
        form.add_widget(_field("Start time zone (IANA name)", self.start_timezone))
        form.add_widget(_field("End time zone (IANA name)", self.end_timezone))
        form.add_widget(_field("Description", self.description))
        scroll_view = ScrollView(bar_width=6)
        scroll_view.add_widget(form)

        self.status_label = wrapped_label(
            size_hint_y=None,
            height=40,
            font_size="14sp",
            color=STATUS_COLOR,
        )

        self.save_button = Button(text="Save", size_hint_y=None, height=48)
        self.save_button.bind(on_press=self.save_event)
        cancel_button = Button(text="Cancel", size_hint_y=None, height=48)
        cancel_button.bind(on_press=self.cancel)
        buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=48,
            spacing=8,
        )
        buttons.add_widget(cancel_button)
        buttons.add_widget(self.save_button)

        layout = BoxLayout(orientation="vertical", padding=12, spacing=8)
        layout.add_widget(
            wrapped_label(
                text="New event",
                bold=True,
                font_size="22sp",
                size_hint_y=None,
                height=44,
            )
        )
        layout.add_widget(scroll_view)
        layout.add_widget(self.status_label)
        layout.add_widget(buttons)
        self.add_widget(layout)

    def on_enter(self, *args: Any) -> None:
        """Clear any message left over from a previous visit."""
        self._set_status("")

    def save_event(self, *args: Any) -> None:
        """Validate the form and create the event in the background."""
        client = self.client
        if client is None:
            self._set_status("Backend client is not configured.", error=True)
            return
        event = self._build_event()
        if event is None:
            return
        self.save_button.disabled = True
        self._set_status("Saving event…")
        thread = threading.Thread(
            target=self._create_event,
            args=(client, event),
            daemon=True,
        )
        thread.start()

    def _create_event(self, client: BackendClient, event: CalendarEvent) -> None:
        """Create the event off the UI thread and hand the result back."""
        try:
            client.create_event(event)
        except BackendError as error:
            message = error.message
            Clock.schedule_once(
                lambda *_: self._on_create_failed(message),
            )
            return
        Clock.schedule_once(lambda *_: self._on_created())

    def _on_create_failed(self, message: str) -> None:
        """Re-enable the form and show the backend error."""
        self.save_button.disabled = False
        self._set_status(f"Could not create event: {message}", error=True)

    def _on_created(self) -> None:
        """Return to the main screen and refresh the event list."""
        self.save_button.disabled = False
        self._set_status("")
        self._reset_form()
        self.manager.current = "main"
        self.refresh()

    def _build_event(self) -> CalendarEvent | None:
        """Turn the form values into an event, reporting invalid input."""
        try:
            start = datetime.fromisoformat(self.start.text.strip())
            end = datetime.fromisoformat(self.end.text.strip())
        except ValueError:
            self._set_status(
                "Use ISO times such as 2026-11-09T14:00+01:00.",
                error=True,
            )
            return None
        if start.tzinfo is None or end.tzinfo is None:
            self._set_status(
                "Start and end must include a UTC offset or zone.",
                error=True,
            )
            return None
        start_timezone = self.start_timezone.text.strip() or self.time_zone
        end_timezone = self.end_timezone.text.strip() or self.time_zone
        for time_zone in (start_timezone, end_timezone):
            if not self._is_known_time_zone(time_zone):
                self._set_status(f"Unknown time zone: {time_zone}", error=True)
                return None
        if end <= start:
            self._set_status("End must be after start.", error=True)
            return None
        description = self.description.text.strip()
        return CalendarEvent(
            id=uuid4().hex,
            summary=self.summary.text.strip() or "Untitled event",
            start=start,
            end=end,
            start_timezone=start_timezone,
            end_timezone=end_timezone,
            description=description or None,
        )

    @staticmethod
    def _is_known_time_zone(name: str) -> bool:
        """Return whether ``name`` is an IANA time zone."""
        try:
            ZoneInfo(name)
        except (ValueError, ZoneInfoNotFoundError):
            return False
        return True

    def _reset_form(self) -> None:
        """Clear the form and prefill a fresh time window."""
        start, end = default_event_times()
        self.summary.text = ""
        self.description.text = ""
        self.start.text = to_input_value(start)
        self.end.text = to_input_value(end)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        """Show a status or error message below the form."""
        self.status_label.text = text
        self.status_label.color = ERROR_COLOR if error else STATUS_COLOR

    def cancel(self, *args: Any) -> None:
        """Close the add-event screen."""
        self.manager.current = "main"
