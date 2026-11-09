"""Create and edit events in the backend calendar."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from kivy_calendar.api import BackendClient, BackendError, CalendarEvent, FreeSlot
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
    """Create a new event or edit an existing one in the backend."""

    def __init__(
        self,
        client: BackendClient | None,
        refresh: Callable[[], None],
        time_zone: str = DEFAULT_TIME_ZONE,
        event: CalendarEvent | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the screen with event fields, save, delete and cancel."""
        super().__init__(**kwargs)
        self.client = client
        self.refresh = refresh
        self.time_zone = time_zone
        self.event: CalendarEvent | None = None

        self.summary = _input("Team standup")
        self.start = _input("")
        self.end = _input("")
        self.start_timezone = _input("")
        self.end_timezone = _input("")
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

        self.delete_button = Button(text="Delete", size_hint_y=None, height=48)
        self.delete_button.bind(on_press=self.confirm_delete)
        self.cancel_button = Button(text="Cancel", size_hint_y=None, height=48)
        self.cancel_button.bind(on_press=self.cancel)
        self.save_button = Button(text="Save", size_hint_y=None, height=48)
        self.save_button.bind(on_press=self.save_event)
        self.suggest_button = Button(
            text="Suggest time",
            size_hint_y=None,
            height=48,
        )
        self.suggest_button.bind(on_press=self.suggest_free_time)
        buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=48,
            spacing=8,
        )
        buttons.add_widget(self.delete_button)
        buttons.add_widget(self.cancel_button)
        buttons.add_widget(self.save_button)

        self.title_label = wrapped_label(
            text="New event",
            bold=True,
            font_size="22sp",
            size_hint_y=None,
            height=44,
        )
        layout = BoxLayout(orientation="vertical", padding=12, spacing=8)
        layout.add_widget(self.title_label)
        layout.add_widget(scroll_view)
        layout.add_widget(self.status_label)
        layout.add_widget(self.suggest_button)
        layout.add_widget(buttons)
        self.add_widget(layout)

        self.open_for(event)

    def open_for(self, event: CalendarEvent | None) -> None:
        """Fill the form for creating a new event or editing ``event``."""
        self.event = event
        if event is None:
            self.title_label.text = "New event"
            self._reset_form()
        else:
            self.title_label.text = "Edit event"
            self.summary.text = event.summary
            self.start.text = to_input_value(event.start)
            self.end.text = to_input_value(event.end)
            self.start_timezone.text = event.start_timezone
            self.end_timezone.text = event.end_timezone
            self.description.text = event.description or ""
        self._set_buttons_enabled(True)
        self._set_status("")

    def on_enter(self, *args: Any) -> None:
        """Clear any message left over from a previous visit."""
        self._set_status("")

    def save_event(self, *args: Any) -> None:
        """Validate the form and save the event in the background."""
        client = self.client
        if client is None:
            self._set_status("Backend client is not configured.", error=True)
            return
        event = self._build_event()
        if event is None:
            return
        editing = self.event is not None
        self._set_buttons_enabled(False)
        self._set_status("Saving event…")
        thread = threading.Thread(
            target=self._persist_event,
            args=(client, event, editing),
            daemon=True,
        )
        thread.start()

    def _persist_event(
        self,
        client: BackendClient,
        event: CalendarEvent,
        editing: bool,
    ) -> None:
        """Create or update the event off the UI thread."""
        try:
            if editing:
                client.update_event(event)
            else:
                client.create_event(event)
        except BackendError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_save_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_saved())

    def _on_save_failed(self, message: str) -> None:
        """Re-enable the form and show the backend error."""
        self._set_buttons_enabled(True)
        self._set_status(f"Could not save event: {message}", error=True)

    def _on_saved(self) -> None:
        """Return to the main screen and refresh the event list."""
        self._return_to_main()

    def suggest_free_time(self, *args: Any) -> None:
        """Ask the backend for a free window and fill the form with it."""
        client = self.client
        if client is None:
            self._set_status("Backend client is not configured.", error=True)
            return
        time_zone = self.start_timezone.text.strip() or self.time_zone
        if not self._is_known_time_zone(time_zone):
            self._set_status(f"Unknown time zone: {time_zone}", error=True)
            return
        duration_minutes = self._duration_minutes()
        zone = ZoneInfo(time_zone)
        window_start = datetime.now(zone)
        window_end = window_start + timedelta(days=7)
        self.suggest_button.disabled = True
        self._set_status("Looking for a free time…")
        thread = threading.Thread(
            target=self._find_free_slots,
            args=(
                client,
                duration_minutes,
                window_start,
                window_end,
                time_zone,
            ),
            daemon=True,
        )
        thread.start()

    def _duration_minutes(self) -> int:
        """Return the form duration, or an hour when the times are unusable."""
        try:
            start = datetime.fromisoformat(self.start.text.strip())
            end = datetime.fromisoformat(self.end.text.strip())
            if (start.tzinfo is None) != (end.tzinfo is None):
                return 60
            difference = end - start
        except (TypeError, ValueError):
            return 60
        if difference <= timedelta(0):
            return 60
        return max(1, int(difference.total_seconds() // 60))

    def _find_free_slots(
        self,
        client: BackendClient,
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        time_zone: str,
    ) -> None:
        """Find free slots off the UI thread and hand them back to the UI."""
        try:
            slots = client.find_free_slots(
                duration_minutes,
                window_start,
                window_end,
                time_zone,
            )
        except BackendError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_suggest_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_slots_found(slots))

    def _on_suggest_failed(self, message: str) -> None:
        """Re-enable the suggest button and show the backend error."""
        self.suggest_button.disabled = False
        self._set_status(message, error=True)

    def _on_slots_found(self, slots: list[FreeSlot]) -> None:
        """Fill the form with the first free slot, or report that none exist."""
        self.suggest_button.disabled = False
        if not slots:
            self._set_status("No free slot found in the next 7 days.")
            return
        slot = slots[0]
        self.start.text = to_input_value(slot.start)
        self.end.text = to_input_value(slot.end)
        self._set_status("Suggested a free time.")

    def confirm_delete(self, *args: Any) -> None:
        """Ask for confirmation before deleting the current event."""
        event = self.event
        if event is None:
            return
        summary = event.summary or "Untitled event"
        content = BoxLayout(orientation="vertical", spacing=8, padding=8)
        content.add_widget(
            wrapped_label(
                text=f"Delete \u201c{summary}\u201d?",
                size_hint_y=None,
                height=40,
            )
        )
        buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=48,
            spacing=8,
        )
        keep_button = Button(text="Keep")
        delete_button = Button(text="Delete")
        buttons.add_widget(keep_button)
        buttons.add_widget(delete_button)
        content.add_widget(buttons)
        popup = Popup(
            title="Delete event",
            content=content,
            size_hint=(0.85, 0.35),
            auto_dismiss=False,
        )

        def keep(*_: Any) -> None:
            popup.dismiss()

        def confirmed(*_: Any) -> None:
            popup.dismiss()
            self._delete_current_event()

        keep_button.bind(on_release=keep)
        delete_button.bind(on_release=confirmed)
        popup.open()

    def _delete_current_event(self) -> None:
        """Delete the current event in the background."""
        client = self.client
        event = self.event
        if client is None or event is None:
            return
        self._set_buttons_enabled(False)
        self._set_status("Deleting event…")
        thread = threading.Thread(
            target=self._delete_event,
            args=(client, event.id),
            daemon=True,
        )
        thread.start()

    def _delete_event(self, client: BackendClient, event_id: str) -> None:
        """Delete the event off the UI thread and hand the result back."""
        try:
            client.delete_event(event_id)
        except BackendError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_delete_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_deleted())

    def _on_delete_failed(self, message: str) -> None:
        """Re-enable the form and show the backend error."""
        self._set_buttons_enabled(True)
        self._set_status(f"Could not delete event: {message}", error=True)

    def _on_deleted(self) -> None:
        """Return to the main screen and refresh the event list."""
        self._return_to_main()

    def _return_to_main(self) -> None:
        """Reset the form and show the refreshed event list."""
        self._set_buttons_enabled(True)
        self._set_status("")
        self.event = None
        self._reset_form()
        manager = self.manager
        if manager is not None:
            manager.current = "main"
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
        existing = self.event
        description = self.description.text.strip()
        return CalendarEvent(
            id=existing.id if existing is not None else uuid4().hex,
            summary=self.summary.text.strip() or "Untitled event",
            start=start,
            end=end,
            start_timezone=start_timezone,
            end_timezone=end_timezone,
            calendar_id=existing.calendar_id if existing is not None else "",
            description=description or None,
            recurrence=existing.recurrence if existing is not None else None,
            extended_properties=(
                dict(existing.extended_properties or {})
                if existing is not None
                else {}
            ),
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
        """Clear the form and prefill a fresh time window and time zone."""
        start, end = default_event_times()
        self.summary.text = ""
        self.description.text = ""
        self.start.text = to_input_value(start)
        self.end.text = to_input_value(end)
        self.start_timezone.text = self.time_zone
        self.end_timezone.text = self.time_zone

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable the form actions."""
        self.save_button.disabled = not enabled
        self.cancel_button.disabled = not enabled
        self.delete_button.disabled = not enabled or self.event is None
        self.suggest_button.disabled = not enabled

    def _set_status(self, text: str, *, error: bool = False) -> None:
        """Show a status or error message below the form."""
        self.status_label.text = text
        self.status_label.color = ERROR_COLOR if error else STATUS_COLOR

    def cancel(self, *args: Any) -> None:
        """Close the event form."""
        manager = self.manager
        if manager is not None:
            manager.current = "main"
