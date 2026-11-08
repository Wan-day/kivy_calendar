"""Add-event screen that creates events in the backend calendar."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput

from kivy_calendar.api import BackendClient, BackendError, CalendarEvent


class AddEventScreen(Screen):
    """Collect a new event and create it in the backend."""

    def __init__(
        self,
        client: BackendClient,
        refresh: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        """Create the screen with event fields and save/cancel actions."""
        super().__init__(**kwargs)
        self.client = client
        self.refresh = refresh
        self.status_label = Label(text="", size_hint_y=0)
        self.summary = TextInput(hint_text="Summary", multiline=False)
        self.start = TextInput(hint_text="Start (ISO datetime with offset)")
        self.end = TextInput(hint_text="End (ISO datetime with offset)")
        self.start_timezone = TextInput(
            hint_text="Start timezone",
            text="Europe/Berlin",
        )
        self.end_timezone = TextInput(
            hint_text="End timezone",
            text="Europe/Berlin",
        )
        save_button = Button(text="Save", size_hint=(1, 0.1))
        save_button.bind(on_press=self.save_event)
        cancel_button = Button(text="Cancel", size_hint=(1, 0.1))
        cancel_button.bind(on_press=self.cancel)
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(self.status_label)
        layout.add_widget(self.summary)
        layout.add_widget(self.start)
        layout.add_widget(self.end)
        layout.add_widget(self.start_timezone)
        layout.add_widget(self.end_timezone)
        layout.add_widget(save_button)
        layout.add_widget(cancel_button)
        self.add_widget(layout)

    def save_event(self, *args: Any) -> None:
        """Create the event in the backend and reload the main screen."""
        start_text = self.start.text.strip()
        end_text = self.end.text.strip()
        try:
            start = datetime.fromisoformat(start_text)
            end = datetime.fromisoformat(end_text)
        except ValueError as error:
            self.status_label.text = f"Invalid event times: {error}"
            return
        if start.tzinfo is None or end.tzinfo is None:
            self.status_label.text = "Start and end must include time zone information."
            return
        event = CalendarEvent(
            id=uuid4().hex,
            summary=self.summary.text.strip() or "Untitled event",
            start=start,
            end=end,
            start_timezone=self.start_timezone.text.strip() or "Europe/Berlin",
            end_timezone=self.end_timezone.text.strip() or "Europe/Berlin",
        )
        try:
            self.client.create_event(event)
        except BackendError as error:
            self.status_label.text = f"Could not create event: {error.message}"
            return
        self.manager.current = "main"
        self.refresh()

    def cancel(self, *args: Any) -> None:
        """Close the add-event screen."""
        self.manager.current = "main"
