"""Tests for the Kivy screens.

Kivy is optional in CI, so these tests are skipped when it is not installed.
They run headless through the SDL dummy video driver.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

BERLIN = ZoneInfo("Europe/Berlin")


class FakeClient:
    """Minimal backend client double for the screen tests."""

    def create_event(self, event: Any) -> Any:
        """Return the event unchanged."""
        return event

    def list_events(self) -> list[Any]:
        """Return no events."""
        return []


def _make_screens(
    client: FakeClient | None = None,
) -> tuple[Any, Any, Any]:
    """Build a screen manager with the main and add-event screens."""
    from kivy.uix.screenmanager import ScreenManager

    from kivy_calendar.screens.add_event import AddEventScreen
    from kivy_calendar.screens.main import MainScreen

    manager = ScreenManager()
    main_screen = MainScreen(name="main", client=client)
    add_event_screen = AddEventScreen(
        name="add_event",
        client=client,
        refresh=lambda: None,
    )
    manager.add_widget(main_screen)
    manager.add_widget(add_event_screen)
    return manager, main_screen, add_event_screen


def test_screens_are_reachable_by_name() -> None:
    """The screen manager can switch between the named screens."""
    manager, _, _ = _make_screens(FakeClient())

    manager.current = "add_event"
    assert manager.current == "add_event"

    manager.current = "main"
    assert manager.current == "main"


def test_main_screen_without_a_client_shows_configuration_error() -> None:
    """Without a backend client the main screen explains what is missing."""
    _, main_screen, _ = _make_screens(None)

    assert main_screen.add_button.disabled
    assert "not configured" in main_screen.status_label.text


def test_main_screen_lists_events() -> None:
    """Events returned by the backend become rows in the event list."""
    _, main_screen, _ = _make_screens(FakeClient())
    start = datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN)

    from kivy_calendar.api import CalendarEvent

    main_screen._show_events(
        [
            CalendarEvent(
                id="event-1",
                summary="Standup",
                start=start,
                end=start.replace(hour=10),
                start_timezone="Europe/Berlin",
                end_timezone="Europe/Berlin",
            )
        ]
    )

    assert len(main_screen.event_list.children) == 1
    assert main_screen.status_label.text == "1 event"


def test_add_event_rejects_a_naive_start() -> None:
    """A start without a UTC offset is rejected before the request."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start.text = "2026-11-09T15:00"

    assert add_event_screen._build_event() is None
    assert "UTC offset" in add_event_screen.status_label.text


def test_add_event_rejects_an_unknown_time_zone() -> None:
    """An unknown IANA zone is rejected before the request."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start.text = "2026-11-09T15:00+01:00"
    add_event_screen.end.text = "2026-11-09T16:00+01:00"
    add_event_screen.start_timezone.text = "Mars/Olympus"

    assert add_event_screen._build_event() is None
    assert "Unknown time zone" in add_event_screen.status_label.text


def test_add_event_builds_a_valid_event() -> None:
    """A filled-in form becomes an event with a client-generated id."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.summary.text = "Dentist"
    add_event_screen.start.text = "2026-11-09T15:00+01:00"
    add_event_screen.end.text = "2026-11-09T16:30+01:00"
    add_event_screen.start_timezone.text = "Europe/Berlin"
    add_event_screen.end_timezone.text = "Europe/Berlin"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.summary == "Dentist"
    assert event.id
    assert event.end > event.start
