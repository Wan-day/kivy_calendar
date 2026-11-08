"""Main screen listing the backend calendar events."""

from __future__ import annotations

from typing import Any

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from kivy_calendar.api import BackendClient, BackendError, CalendarEvent


class MainScreen(Screen):
    """List backend events and open the add-event screen."""

    def __init__(self, client: BackendClient, **kwargs: Any) -> None:
        """Create the screen with a scrollable event list and an add button."""
        super().__init__(**kwargs)
        self.client = client
        self.events: list[CalendarEvent] = []
        self.event_list = BoxLayout(orientation="vertical")
        scroll_view = ScrollView(size_hint=(1, 1))
        scroll_view.add_widget(self.event_list)
        self.status_label = Label(text="Loading events…", size_hint_y=0)
        add_button = Button(text="Add event", size_hint=(1, 0.1))
        add_button.bind(on_press=self.open_add_event)
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(self.status_label)
        layout.add_widget(scroll_view)
        layout.add_widget(add_button)
        self.add_widget(layout)
        self.load_events()

    def load_events(self) -> None:
        """Fetch events from the backend and refresh the list."""
        try:
            self.events = self.client.list_events()
        except BackendError as error:
            self.status_label.text = f"Could not load events: {error.message}"
            return
        self.status_label.text = f"{len(self.events)} events"
        self.event_list.clear_widgets()
        for event in self.events:
            self.event_list.add_widget(Label(text=f"{event.start} {event.summary}"))

    def open_add_event(self, *args: Any) -> None:
        """Open the add-event screen."""
        self.manager.current = "add_event"
