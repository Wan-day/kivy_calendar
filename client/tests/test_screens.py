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

    def __init__(self) -> None:
        self.created: list[Any] = []
        self.updated: list[Any] = []
        self.deleted: list[str] = []

    def create_event(self, event: Any) -> Any:
        """Record a create and return the event unchanged."""
        self.created.append(event)
        return event

    def update_event(self, event: Any) -> Any:
        """Record an update and return the event unchanged."""
        self.updated.append(event)
        return event

    def delete_event(self, event_id: str) -> None:
        """Record a delete."""
        self.deleted.append(event_id)

    def list_events(self) -> list[Any]:
        """Return no events."""
        return []


def _sample_event() -> Any:
    from kivy_calendar.api import CalendarEvent

    return CalendarEvent(
        id="event-1",
        summary="Standup",
        start=datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN),
        end=datetime(2026, 11, 9, 10, 0, tzinfo=BERLIN),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        recurrence=["FREQ=WEEKLY"],
        extended_properties={"source": "kivy-calendar"},
    )


def _make_screens(
    client: FakeClient | None = None,
) -> tuple[Any, Any, Any]:
    """Build a screen manager with the main and event-form screens."""
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

    main_screen._show_events([_sample_event()])

    assert len(main_screen.event_list.children) == 1
    assert main_screen.status_label.text == "1 event"


def test_tapping_an_event_opens_the_form_in_edit_mode() -> None:
    """Tapping a row opens the form with the event loaded."""
    manager, main_screen, add_event_screen = _make_screens(FakeClient())
    event = _sample_event()
    main_screen._show_events([event])
    row = main_screen.event_list.children[0]

    row.dispatch("on_release")

    assert manager.current == "add_event"
    assert add_event_screen.event is event
    assert add_event_screen.summary.text == "Standup"
    assert not add_event_screen.delete_button.disabled


def test_new_event_form_disables_delete() -> None:
    """A new event cannot be deleted before it exists."""
    _, _, add_event_screen = _make_screens(FakeClient())

    add_event_screen.open_for(None)

    assert add_event_screen.delete_button.disabled
    assert add_event_screen.title_label.text == "New event"


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


def test_edit_form_keeps_the_id_and_hidden_fields() -> None:
    """Editing keeps the backend id, recurrence and extended properties."""
    _, _, add_event_screen = _make_screens(FakeClient())
    original = _sample_event()
    add_event_screen.open_for(original)
    add_event_screen.summary.text = "Standup (moved)"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.id == original.id
    assert event.summary == "Standup (moved)"
    assert event.recurrence == original.recurrence
    assert event.extended_properties == original.extended_properties


def test_editing_saves_through_update_event() -> None:
    """Editing an event uses PATCH rather than create."""
    client = FakeClient()
    _, _, add_event_screen = _make_screens(client)
    event = _sample_event()
    add_event_screen.open_for(event)

    add_event_screen._persist_event(client, event, editing=True)

    assert client.updated == [event]
    assert client.created == []


def test_deleting_sends_the_event_id() -> None:
    """Deleting an event calls the backend with its id."""
    client = FakeClient()
    _, _, add_event_screen = _make_screens(client)
    add_event_screen.open_for(_sample_event())

    add_event_screen._delete_event(client, "event-1")

    assert client.deleted == ["event-1"]
