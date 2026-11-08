"""Kivy application entry point for the calendar client."""

from __future__ import annotations

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager

from kivy_calendar.api import BackendClient
from kivy_calendar.screens.add_event import AddEventScreen
from kivy_calendar.screens.main import MainScreen


class KivyCalendarApp(App):
    """Basic Kivy application hosting the calendar screens."""

    def build(self) -> ScreenManager:
        """Build the screen manager with the main and add-event screens."""
        client = BackendClient()
        screen_manager = ScreenManager()
        main_screen = MainScreen(client=client)
        add_event_screen = AddEventScreen(
            client=client,
            refresh=main_screen.load_events,
        )
        screen_manager.add_widget(main_screen)
        screen_manager.add_widget(add_event_screen)
        self.main_screen = main_screen
        return screen_manager

    def on_start(self) -> None:
        """Load the event list when the app starts."""
        self.main_screen.load_events()
