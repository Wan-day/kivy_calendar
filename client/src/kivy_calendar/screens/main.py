"""Main screen listing the backend calendar events."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.utils import escape_markup

from kivy_calendar.api import BackendClient, BackendError, CalendarEvent
from kivy_calendar.formatting import format_event_when
from kivy_calendar.screens.ui import wrapped_label

ERROR_COLOR = (0.95, 0.42, 0.42, 1)
STATUS_COLOR = (0.68, 0.68, 0.68, 1)
ROW_COLOR = (0.16, 0.18, 0.22, 1)


class EventRow(Button):
    """A tappable event row with a bold summary and its time span."""

    def __init__(
        self,
        event: CalendarEvent,
        open_event: Callable[[CalendarEvent], None],
        **kwargs: Any,
    ) -> None:
        """Create the row from an event."""
        summary = escape_markup(event.summary or "Untitled event")
        when = escape_markup(format_event_when(event))
        super().__init__(
            text=f"[b]{summary}[/b]\n{when}",
            markup=True,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=72,
            background_normal="",
            background_down="",
            background_color=ROW_COLOR,
            **kwargs,
        )
        self.event = event
        self.bind(on_release=lambda *_: open_event(event))
        self.bind(width=self._sync_text_size)
        self._sync_text_size()

    def _sync_text_size(self, *args: Any) -> None:
        """Keep the wrapped text width in sync with the row width."""
        width = self.width if self.width > 24 else 24
        self.text_size = (width - 24, None)


class MainScreen(Screen):
    """List backend events and open the add-event screen."""

    def __init__(
        self,
        client: BackendClient | None,
        configuration_error: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the screen with a scrollable event list and an add button."""
        super().__init__(**kwargs)
        self.client = client
        self.configuration_error = configuration_error
        self.events: list[CalendarEvent] = []

        self.title = wrapped_label(
            text="Kivy Calendar",
            bold=True,
            font_size="22sp",
            size_hint_y=None,
            height=48,
        )
        self.refresh_button = Button(text="Refresh", size_hint=(None, 1), width=110)
        self.refresh_button.bind(on_press=lambda *_: self.load_events())
        self.sync_button = Button(text="Sync", size_hint=(None, 1), width=90)
        self.sync_button.bind(on_press=lambda *_: self.sync_events())
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=48,
            spacing=8,
        )
        header.add_widget(self.title)
        header.add_widget(self.refresh_button)
        header.add_widget(self.sync_button)

        self.status_label = wrapped_label(
            size_hint_y=None,
            height=40,
            font_size="14sp",
            color=STATUS_COLOR,
        )

        self.event_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=4,
        )
        self.event_list.bind(minimum_height=self.event_list.setter("height"))
        scroll_view = ScrollView(bar_width=6)
        scroll_view.add_widget(self.event_list)

        self.add_button = Button(
            text="Add event",
            size_hint_y=None,
            height=52,
            font_size="16sp",
        )
        self.add_button.bind(on_press=self.open_add_event)

        layout = BoxLayout(orientation="vertical", padding=12, spacing=8)
        layout.add_widget(header)
        layout.add_widget(self.status_label)
        layout.add_widget(scroll_view)
        layout.add_widget(self.add_button)
        self.add_widget(layout)

        if self.client is None:
            self.add_button.disabled = True
            self._set_status(
                self.configuration_error or "Backend client is not configured.",
                error=True,
            )
        else:
            self._set_status("Events have not been loaded yet.")

    def load_events(self) -> None:
        """Fetch events from the backend in a background thread."""
        client = self.client
        if client is None:
            self._set_status(
                self.configuration_error or "Backend client is not configured.",
                error=True,
            )
            return
        self._set_status("Loading events…")
        thread = threading.Thread(
            target=self._fetch_events,
            args=(client,),
            daemon=True,
        )
        thread.start()

    def _fetch_events(self, client: BackendClient) -> None:
        """Fetch events off the UI thread and hand them back to the UI."""
        try:
            events = client.list_events()
        except BackendError as error:
            message = error.message
            Clock.schedule_once(
                lambda *_: self._set_status(
                    f"Could not load events: {message}",
                    error=True,
                )
            )
            return
        Clock.schedule_once(lambda *_: self._show_events(events))

    def sync_events(self) -> None:
        """Rebuild the backend cache in a background thread."""
        client = self.client
        if client is None:
            self._set_status(
                self.configuration_error or "Backend client is not configured.",
                error=True,
            )
            return
        self.sync_button.disabled = True
        self._set_status("Syncing…")
        thread = threading.Thread(
            target=self._run_sync,
            args=(client,),
            daemon=True,
        )
        thread.start()

    def _run_sync(self, client: BackendClient) -> None:
        """Run the sync off the UI thread and hand the count back to the UI."""
        try:
            synced = client.sync()
        except BackendError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_sync_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_synced(synced))

    def _on_sync_failed(self, message: str) -> None:
        """Re-enable the sync button and show the backend error."""
        self.sync_button.disabled = False
        self._set_status(f"Could not sync: {message}", error=True)

    def _on_synced(self, synced: int) -> None:
        """Show the synced count and reload the event list."""
        self.sync_button.disabled = False
        self.load_events()
        self._set_status(
            f"Synced {synced} event" + ("" if synced == 1 else "s"),
        )

    def _show_events(self, events: list[CalendarEvent]) -> None:
        """Replace the event list with the fetched events."""
        self.events = events
        self.event_list.clear_widgets()
        if not events:
            self._set_status("No events yet. Tap Add event to create one.")
            return
        count = len(events)
        self._set_status(f"{count} event" + ("" if count == 1 else "s"))
        for event in events:
            self.event_list.add_widget(EventRow(event, self.open_event))

    def _set_status(self, text: str, *, error: bool = False) -> None:
        """Show a status or error message above the event list."""
        self.status_label.text = text
        self.status_label.color = ERROR_COLOR if error else STATUS_COLOR

    def open_event(self, event: CalendarEvent) -> None:
        """Open the event form for an existing event."""
        manager = self.manager
        if manager is None:
            return
        form = manager.get_screen("add_event")
        form.open_for(event)
        manager.current = "add_event"

    def open_add_event(self, *args: Any) -> None:
        """Open the event form for a new event."""
        manager = self.manager
        if manager is None:
            return
        form = manager.get_screen("add_event")
        form.open_for(None)
        manager.current = "add_event"
