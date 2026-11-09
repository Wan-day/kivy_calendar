"""Kivy application entry point for the calendar client."""

from __future__ import annotations

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager

from kivy_calendar.api import TOKEN_ENV, BackendClient
from kivy_calendar.screens.add_event import AddEventScreen
from kivy_calendar.screens.main import MainScreen


def build_client() -> tuple[BackendClient | None, str | None]:
    """Build the backend client, reporting configuration problems.

    The application still starts without a client so the window shows what is
    missing instead of crashing on import.
    """
    try:
        return BackendClient(), None
    except ValueError as error:
        message = (
            f"Backend client is not configured: {error}. "
            f"Set {TOKEN_ENV} and restart the app."
        )
        return None, message


class KivyCalendarApp(App):
    """Basic Kivy application hosting the calendar screens."""

    title = "Kivy Calendar"

    def build(self) -> ScreenManager:
        """Build the screen manager with the main and add-event screens."""
        Window.size = (420, 760)
        client, configuration_error = build_client()
        screen_manager = ScreenManager()
        main_screen = MainScreen(
            name="main",
            client=client,
            configuration_error=configuration_error,
        )
        add_event_screen = AddEventScreen(
            name="add_event",
            client=client,
            refresh=main_screen.load_events,
        )
        screen_manager.add_widget(main_screen)
        screen_manager.add_widget(add_event_screen)
        self.main_screen = main_screen
        return screen_manager

    def on_start(self) -> None:
        """Load the event list when the app starts."""
        if self.main_screen is not None:
            self.main_screen.load_events()
