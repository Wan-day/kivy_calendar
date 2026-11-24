"""Kivy application entry point for the calendar client."""

from __future__ import annotations

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager
from kivy.utils import platform

from kivy_calendar.screens.add_event import AddEventScreen
from kivy_calendar.screens.main import MainScreen
from kivy_calendar.screens.theme import BACKGROUND
from kivy_calendar.service import CalendarService, choose_service


def build_client() -> tuple[CalendarService | None, str | None]:
    """Return the calendar service for this platform and any setup error."""
    return choose_service(platform=platform)


class KivyCalendarApp(App):
    """Basic Kivy application hosting the calendar screens."""

    title = "Kivy Calendar"

    def build(self) -> ScreenManager:
        """Build the screen manager with the main and add-event screens."""
        if platform not in ("android", "ios"):
            # A phone-sized window on desktop; phones use their own screen.
            Window.size = (420, 760)
        Window.clearcolor = BACKGROUND
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
