"""Ask for calendar access before showing the phone's events (Android)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget

from kivy_calendar.screens.theme import (
    FONT_BOLD,
    MUTED,
    IconView,
    outline_button,
    primary_button,
)
from kivy_calendar.screens.ui import StatusBanner, wrapped_label
from kivy_calendar.service import AccessGate

ASK_TEXT = (
    "Kivy Calendar shows and edits the events in your phone's calendars, "
    "including the Google calendars on this phone. Android asks you to allow "
    "calendar access first."
)
DENIED_TEXT = (
    "Calendar access was not allowed. Tap Allow access to ask again, or open "
    "the app settings and turn on Calendar under Permissions."
)


class PermissionScreen(Screen):
    """Explain why calendar access is needed and ask for it."""

    def __init__(
        self,
        gate: AccessGate,
        on_granted: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        """Create the screen; ``on_granted`` runs once access is allowed."""
        super().__init__(**kwargs)
        self.gate = gate
        self.on_granted = on_granted

        self.title_label = wrapped_label(
            text="Allow calendar access",
            font_name=FONT_BOLD,
            font_size="26sp",
            size_hint_y=None,
            height=dp(72),
        )
        self.body_label = wrapped_label(
            text=ASK_TEXT,
            font_size="15sp",
            color=MUTED,
            size_hint_y=None,
        )
        # Grow with the wrapped text.
        self.body_label.bind(
            texture_size=lambda label, size: setattr(label, "height", size[1])
        )
        self.status_label = StatusBanner(collapse=True)
        self.allow_button = primary_button(
            "Allow access", size_hint_y=None, height=dp(52), font_size="16sp"
        )
        self.allow_button.bind(on_release=lambda *_: self.request_access())
        self.settings_button = outline_button(
            "Open app settings", radius=14, size_hint_y=None, height=dp(48)
        )
        self.settings_button.bind(on_release=lambda *_: self.gate.open_settings())
        # Holds the settings button only after access was refused.
        self._settings_slot = BoxLayout(size_hint_y=None, height=dp(48))

        icon_row = BoxLayout(size_hint_y=None, height=dp(56))
        icon_row.add_widget(IconView("calendar", icon_size=48))
        icon_row.add_widget(Widget())

        layout = BoxLayout(
            orientation="vertical",
            padding=(dp(24), dp(48), dp(24), dp(32)),
            spacing=dp(16),
        )
        layout.add_widget(icon_row)
        layout.add_widget(self.title_label)
        layout.add_widget(self.body_label)
        layout.add_widget(self.status_label)
        layout.add_widget(Widget())
        layout.add_widget(self.allow_button)
        layout.add_widget(self._settings_slot)
        self.add_widget(layout)

    def request_access(self) -> None:
        """Show Android's permission dialog."""
        self.allow_button.disabled = True
        self.gate.request_access(self._on_result_from_any_thread)

    def _on_result_from_any_thread(self, granted: bool) -> None:
        """Android reports the answer on a Java thread; continue on the UI thread."""
        Clock.schedule_once(lambda *_: self.show_result(granted))

    def show_result(self, granted: bool) -> None:
        """Continue to the events, or explain how to allow access."""
        self.allow_button.disabled = False
        if granted:
            self.status_label.show("")
            self.on_granted()
            return
        self.body_label.text = DENIED_TEXT
        self.status_label.show("Calendar access is off.", error=True)
        if self.settings_button.parent is None:
            self._settings_slot.add_widget(self.settings_button)
