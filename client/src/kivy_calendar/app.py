"""Kivy application entry point for the calendar client."""

from __future__ import annotations

from typing import Any

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager
from kivy.utils import platform

from kivy_calendar.formatting import DEFAULT_TIME_ZONE
from kivy_calendar.screens.add_event import AddEventScreen
from kivy_calendar.screens.main import MainScreen
from kivy_calendar.screens.permission import PermissionScreen
from kivy_calendar.screens.theme import BACKGROUND
from kivy_calendar.screens.ui import EaseOutSlide
from kivy_calendar.service import AccessGate, CalendarService, choose_service


def build_client() -> tuple[CalendarService | None, str | None]:
    """Return the calendar service for this platform and any setup error."""
    return choose_service(platform=platform)


def default_time_zone() -> str:
    """The zone new events start in: the phone's own zone on Android."""
    if platform == "android":
        try:
            from phone_calendar import device_time_zone  # Android build only

            return device_time_zone(DEFAULT_TIME_ZONE)
        except ImportError:
            pass
    return DEFAULT_TIME_ZONE


class FormTransition(EaseOutSlide):
    """Slide between screens: left into the form, right back out of it.

    A short slide (0.3 s) that starts fast and settles gently, so it feels
    smooth on a phone without hiding the next screen for long.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Create the transition with the app's duration."""
        kwargs.setdefault("duration", 0.3)
        super().__init__(**kwargs)

    def start(self, manager: ScreenManager) -> None:
        """Pick the direction from the screens, then start sliding."""
        leaving = getattr(self.screen_out, "name", "")
        self.direction = "right" if leaving == "add_event" else "left"
        super().start(manager)


class KivyCalendarApp(App):
    """Basic Kivy application hosting the calendar screens."""

    title = "Kivy Calendar"

    def build(self) -> ScreenManager:
        """Build the screens; ask for calendar access first when it is needed."""
        if platform not in ("android", "ios"):
            # A phone-sized window on desktop; phones use their own screen.
            Window.size = (420, 760)
        Window.clearcolor = BACKGROUND
        client, configuration_error = build_client()
        screen_manager = ScreenManager(transition=FormTransition())
        main_screen = MainScreen(
            name="main",
            client=client,
            configuration_error=configuration_error,
        )
        add_event_screen = AddEventScreen(
            name="add_event",
            client=client,
            refresh=main_screen.load_events,
            time_zone=default_time_zone(),
        )
        screen_manager.add_widget(main_screen)
        screen_manager.add_widget(add_event_screen)
        self.main_screen = main_screen
        self.screen_manager = screen_manager
        self.needs_access = isinstance(client, AccessGate) and not client.has_access()
        if isinstance(client, AccessGate) and self.needs_access:
            screen_manager.add_widget(
                PermissionScreen(
                    client, on_granted=self.show_events, name="permission"
                )
            )
            screen_manager.current = "permission"
        return screen_manager

    def on_start(self) -> None:
        """Load the event list, unless the app is waiting for calendar access."""
        if not self.needs_access:
            self.main_screen.load_events()

    def show_events(self) -> None:
        """Access was granted: switch to the event list and load it."""
        self.needs_access = False
        self.screen_manager.current = "main"
        self.main_screen.load_events()
