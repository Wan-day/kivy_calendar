"""Tests for the Kivy screens.

Kivy is optional in CI, so these tests are skipped when it is not installed.
They run headless through the SDL dummy video driver.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
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
        self.sync_calls = 0
        self.synced = 0
        self.sync_error: BaseException | None = None
        self.list_calls = 0
        self.free_slots: list[Any] = []
        self.free_slot_requests: list[tuple[int, datetime, datetime, str]] = []
        self.calendar_calls = 0
        self.calendars: list[Any] | None = None
        self.calendar_error: BaseException | None = None
        self.time_zones: list[Any] | None = None

    def list_time_zones(self) -> list[Any]:
        """Return the configured zones, or a small curated list."""
        from kivy_calendar.api import TimeZoneOption

        if self.time_zones is not None:
            return list(self.time_zones)
        return [
            TimeZoneOption(name="Europe/Berlin", label="Berlin (UTC+01:00)"),
            TimeZoneOption(name="Asia/Kolkata", label="Kolkata (UTC+05:30)"),
            TimeZoneOption(name="America/New_York", label="New York (UTC-05:00)"),
        ]

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
        self.list_calls += 1
        return []

    def list_calendars(self) -> list[Any]:
        """Return the configured calendars, or a primary and a work calendar."""
        from kivy_calendar.api import CalendarSummary

        self.calendar_calls += 1
        if self.calendar_error is not None:
            raise self.calendar_error
        if self.calendars is not None:
            return list(self.calendars)
        return [
            CalendarSummary(id="primary", summary="Primary", primary=True),
            CalendarSummary(id="work@example.com", summary="Work"),
        ]

    def sync(self) -> int:
        """Record a sync and return the configured count."""
        self.sync_calls += 1
        if self.sync_error is not None:
            raise self.sync_error
        return self.synced

    def find_free_slots(
        self,
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        time_zone: str,
    ) -> list[Any]:
        """Record the request and return the configured slots."""
        self.free_slot_requests.append(
            (duration_minutes, window_start, window_end, time_zone),
        )
        return list(self.free_slots)


def _sample_event() -> Any:
    from kivy_calendar.api import CalendarEvent

    return CalendarEvent(
        id="event-1",
        summary="Standup",
        start=datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN),
        end=datetime(2026, 11, 9, 10, 0, tzinfo=BERLIN),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        calendar_id="work@example.com",
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


FIXED_NOW = datetime(2026, 11, 9, 12, 0, tzinfo=BERLIN)


class _FixedDateTime(datetime):
    """``datetime`` double whose ``now()`` is frozen."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        """Return the fixed time, converted to ``tz`` when given."""
        if tz is None:
            return FIXED_NOW
        return FIXED_NOW.astimezone(tz)


def _run_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run worker threads and scheduled Kivy callbacks immediately."""

    class InlineThread:
        """Thread double that runs its target synchronously on start."""

        def __init__(
            self,
            target: Callable[..., Any],
            args: tuple[Any, ...] = (),
            daemon: bool | None = None,
            **kwargs: Any,
        ) -> None:
            self._target = target
            self._args = args

        def start(self) -> None:
            """Run the target instead of starting a thread."""
            self._target(*self._args)

    from kivy.clock import ClockBase

    monkeypatch.setattr(threading, "Thread", InlineThread)

    def _run_immediately(
        self: object,
        callback: Callable[..., Any],
        *args: Any,
    ) -> None:
        """Run a scheduled one-shot callback immediately instead of later."""
        callback(0)

    monkeypatch.setattr(ClockBase, "schedule_once", _run_immediately)


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


def test_add_event_rejects_unparseable_times() -> None:
    """Text that is not an ISO date-time is rejected before the request."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start.text = "tomorrow at 3"

    assert add_event_screen._build_event() is None
    assert "Use local times" in add_event_screen.status_label.text


def test_add_event_reads_wall_clock_times_in_the_selected_zone() -> None:
    """A time without an offset is interpreted in the chosen IANA zone."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start.text = "2026-11-09T15:00"
    add_event_screen.end.text = "2026-11-09T16:00"
    add_event_screen.start_timezone.text = "Europe/Berlin"
    add_event_screen.end_timezone.text = "Europe/Berlin"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.start.isoformat() == "2026-11-09T15:00:00+01:00"


def test_selected_zone_decides_the_instant_not_a_typed_offset() -> None:
    """Choosing New York for 15:00+01:00 saves 15:00 New York time."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start.text = "2026-11-09T15:00+01:00"
    add_event_screen.end.text = "2026-11-09T16:00+01:00"
    add_event_screen.start_timezone.text = "America/New_York"
    add_event_screen.end_timezone.text = "America/New_York"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.start.isoformat() == "2026-11-09T15:00:00-05:00"
    assert event.start_timezone == "America/New_York"
    assert event.end.isoformat() == "2026-11-09T16:00:00-05:00"


def test_add_event_applies_daylight_saving_time_per_date() -> None:
    """15:00 Berlin is +01:00 in January and +02:00 in July."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start_timezone.text = "Europe/Berlin"
    add_event_screen.end_timezone.text = "Europe/Berlin"
    offsets = []
    for day in ("2026-01-15", "2026-07-15"):
        add_event_screen.start.text = f"{day}T15:00"
        add_event_screen.end.text = f"{day}T16:00"
        event = add_event_screen._build_event()
        assert event is not None
        offsets.append(event.start.isoformat()[-6:])

    assert offsets == ["+01:00", "+02:00"]


def test_add_event_rejects_a_time_skipped_by_daylight_saving() -> None:
    """2026-03-29 02:30 does not exist in Berlin and is reported."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start.text = "2026-03-29T02:30"
    add_event_screen.end.text = "2026-03-29T04:00"
    add_event_screen.start_timezone.text = "Europe/Berlin"
    add_event_screen.end_timezone.text = "Europe/Berlin"

    assert add_event_screen._build_event() is None
    assert "does not exist" in add_event_screen.status_label.text


def test_edit_form_shows_the_event_as_wall_clock_in_its_zone() -> None:
    """An event stored in UTC is shown in its own zone without an offset."""
    from kivy_calendar.api import CalendarEvent

    _, _, add_event_screen = _make_screens(FakeClient())
    event = CalendarEvent(
        id="e1",
        summary="Call",
        start=datetime(2026, 7, 15, 13, 0, tzinfo=ZoneInfo("UTC")),
        end=datetime(2026, 7, 15, 14, 0, tzinfo=ZoneInfo("UTC")),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
    )

    add_event_screen.open_for(event)

    assert add_event_screen.start.text == "2026-07-15T15:00"
    assert add_event_screen.end.text == "2026-07-15T16:00"
    built = add_event_screen._build_event()
    assert built is not None
    assert built.start == event.start


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
    assert event.calendar_id == original.calendar_id
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


def test_sync_button_syncs_and_reloads_the_event_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Sync button runs a sync, shows the count and reloads events."""
    client = FakeClient()
    client.synced = 3
    _, main_screen, _ = _make_screens(client)
    _run_inline(monkeypatch)

    main_screen.sync_button.dispatch("on_press")

    assert client.sync_calls == 1
    assert client.list_calls == 1
    assert main_screen.status_label.text == "Synced 3 events"
    assert not main_screen.sync_button.disabled


def test_sync_button_reports_backend_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed sync shows the error and re-enables the button."""
    from kivy_calendar.api import BackendError

    client = FakeClient()
    client.sync_error = BackendError(500, "sync_failed", "Google is down")
    _, main_screen, _ = _make_screens(client)
    _run_inline(monkeypatch)

    main_screen.sync_button.dispatch("on_press")

    assert "Google is down" in main_screen.status_label.text
    assert not main_screen.sync_button.disabled


def test_suggest_time_fills_the_form_with_the_first_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suggest time asks for the form duration and fills the first slot."""
    import kivy_calendar.screens.add_event as add_event_module
    from kivy_calendar.api import FreeSlot

    first = FreeSlot(
        start=datetime(2026, 11, 12, 9, 0, tzinfo=BERLIN),
        end=datetime(2026, 11, 12, 9, 30, tzinfo=BERLIN),
    )
    second = FreeSlot(
        start=datetime(2026, 11, 13, 14, 0, tzinfo=BERLIN),
        end=datetime(2026, 11, 13, 14, 30, tzinfo=BERLIN),
    )
    client = FakeClient()
    client.free_slots = [first, second]
    _, _, add_event_screen = _make_screens(client)
    add_event_screen.start.text = "2026-11-09T15:00+01:00"
    add_event_screen.end.text = "2026-11-09T16:30+01:00"
    add_event_screen.start_timezone.text = "Europe/Berlin"
    _run_inline(monkeypatch)
    monkeypatch.setattr(add_event_module, "datetime", _FixedDateTime)

    add_event_screen.suggest_button.dispatch("on_press")

    assert client.free_slot_requests == [
        (
            90,
            FIXED_NOW,
            FIXED_NOW + timedelta(days=7),
            "Europe/Berlin",
        ),
    ]
    assert add_event_screen.start.text == "2026-11-12T09:00"
    assert add_event_screen.end.text == "2026-11-12T09:30"
    assert add_event_screen.status_label.text == "Suggested a free time."
    assert not add_event_screen.suggest_button.disabled


def test_suggest_time_reports_when_no_slot_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty slot list shows the no-slot message and re-enables the button."""
    import kivy_calendar.screens.add_event as add_event_module

    client = FakeClient()
    client.free_slots = []
    _, _, add_event_screen = _make_screens(client)
    add_event_screen.start.text = "not a datetime"
    add_event_screen.end.text = "not a datetime"
    add_event_screen.start_timezone.text = "Europe/Berlin"
    _run_inline(monkeypatch)
    monkeypatch.setattr(add_event_module, "datetime", _FixedDateTime)

    add_event_screen.suggest_button.dispatch("on_press")

    assert client.free_slot_requests == [
        (
            60,
            FIXED_NOW,
            FIXED_NOW + timedelta(days=7),
            "Europe/Berlin",
        ),
    ]
    assert (
        add_event_screen.status_label.text
        == "No free slot found in the next 7 days."
    )
    assert not add_event_screen.suggest_button.disabled


def test_suggest_time_duration_uses_each_selected_zone() -> None:
    """The duration compares the instants of the two chosen zones."""
    client = FakeClient()
    _, _, add_event_screen = _make_screens(client)
    add_event_screen.start.text = "2026-11-09T15:00"
    add_event_screen.end.text = "2026-11-09T16:30"
    add_event_screen.start_timezone.text = "Europe/Berlin"
    add_event_screen.end_timezone.text = "Europe/Berlin"

    assert add_event_screen._duration_minutes() == 90

    add_event_screen.end_timezone.text = "America/New_York"

    assert add_event_screen._duration_minutes() == 6 * 60 + 90


def test_suggest_time_rejects_an_unknown_time_zone() -> None:
    """An invalid start time zone is reported before any request."""
    client = FakeClient()
    _, _, add_event_screen = _make_screens(client)
    add_event_screen.start_timezone.text = "Mars/Olympus"

    add_event_screen.suggest_button.dispatch("on_press")

    assert "Unknown time zone" in add_event_screen.status_label.text
    assert client.free_slot_requests == []


def test_main_screen_filters_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The name filter re-renders the rows and reports the visible count."""
    _, main_screen, _ = _make_screens(FakeClient())
    main_screen._show_events([_sample_event()])

    main_screen.name_filter.text = "Standup"
    _run_inline(monkeypatch)

    assert len(main_screen.event_list.children) == 1
    assert main_screen.status_label.text == "1 event"

    main_screen.name_filter.text = "Dentist"
    _run_inline(monkeypatch)

    assert len(main_screen.event_list.children) == 0
    assert main_screen.status_label.text == "No events match the filters."


def test_main_screen_filters_by_date_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The date bounds keep only events on the given local dates."""
    _, main_screen, _ = _make_screens(FakeClient())
    main_screen._show_events([_sample_event()])

    main_screen.date_from_filter.text = "2026-11-09"
    main_screen.date_to_filter.text = "2026-11-09"
    _run_inline(monkeypatch)

    assert len(main_screen.event_list.children) == 1

    main_screen.date_from_filter.text = "2026-11-10"
    main_screen.date_to_filter.text = "2026-11-10"
    _run_inline(monkeypatch)

    assert len(main_screen.event_list.children) == 0
    assert main_screen.status_label.text == "No events match the filters."


def test_main_screen_sorts_the_visible_events() -> None:
    """The sort spinner re-renders the list in the chosen order."""
    from kivy_calendar.api import CalendarEvent

    _, main_screen, _ = _make_screens(FakeClient())
    events = [
        CalendarEvent(
            id="event-2",
            summary="Zebra",
            start=datetime(2026, 11, 10, 9, 0, tzinfo=BERLIN),
            end=datetime(2026, 11, 10, 10, 0, tzinfo=BERLIN),
            start_timezone="Europe/Berlin",
            end_timezone="Europe/Berlin",
        ),
        CalendarEvent(
            id="event-1",
            summary="Alpha",
            start=datetime(2026, 11, 9, 9, 0, tzinfo=BERLIN),
            end=datetime(2026, 11, 9, 10, 0, tzinfo=BERLIN),
            start_timezone="Europe/Berlin",
            end_timezone="Europe/Berlin",
        ),
    ]
    main_screen._show_events(events)
    main_screen.sort_spinner.text = "Name: A-Z"

    assert main_screen.event_list.children[0].event.summary == "Alpha"


def test_main_screen_clear_filters_resets_the_list() -> None:
    """Clearing the filters restores the full event list."""
    _, main_screen, _ = _make_screens(FakeClient())
    main_screen._show_events([_sample_event()])
    main_screen.name_filter.text = "Standup"

    main_screen._clear_filters()

    assert len(main_screen.event_list.children) == 1
    assert main_screen.name_filter.text == ""
    assert main_screen.sort_spinner.text == "Start: oldest first"


def test_main_screen_reports_an_invalid_date_filter() -> None:
    """An unparsable date filter reports the error and keeps the rows."""
    _, main_screen, _ = _make_screens(FakeClient())
    main_screen._show_events([_sample_event()])
    main_screen.date_from_filter.text = "not-a-date"

    main_screen._rebuild_view()

    assert main_screen.status_label.text == "Use dates like YYYY-MM-DD."
    assert len(main_screen.event_list.children) == 1


def test_event_form_offers_backend_time_zones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dropdowns list the backend's IANA zones and default to the config."""
    from kivy.uix.spinner import Spinner

    _run_inline(monkeypatch)
    _, _, add_event_screen = _make_screens(FakeClient())

    assert isinstance(add_event_screen.start_timezone, Spinner)
    assert isinstance(add_event_screen.end_timezone, Spinner)
    assert "Kolkata (UTC+05:30)" in add_event_screen.start_timezone.values
    assert "Kolkata (UTC+05:30)" in add_event_screen.end_timezone.values
    assert add_event_screen.start_timezone.text == "Berlin (UTC+01:00)"
    assert add_event_screen.end_timezone.text == "Berlin (UTC+01:00)"


def test_add_event_saves_the_iana_zone_behind_a_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Picking a half-hour zone saves its IANA name, not a fixed offset."""
    _run_inline(monkeypatch)
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.summary.text = "Call"
    add_event_screen.start.text = "2026-11-09T15:00+05:30"
    add_event_screen.end.text = "2026-11-09T16:30+05:30"
    add_event_screen.start_timezone.text = "Kolkata (UTC+05:30)"
    add_event_screen.end_timezone.text = "Kolkata (UTC+05:30)"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.start_timezone == "Asia/Kolkata"
    assert event.end_timezone == "Asia/Kolkata"


def test_edit_form_keeps_a_zone_missing_from_the_curated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An event's own zone stays selectable even when the backend omits it."""
    from kivy_calendar.api import CalendarEvent

    _run_inline(monkeypatch)
    client = FakeClient()
    _, _, add_event_screen = _make_screens(client)
    event = CalendarEvent(
        id="e1",
        summary="Odd",
        start=datetime(2026, 11, 9, 15, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        end=datetime(2026, 11, 9, 16, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        start_timezone="Europe/Oslo",
        end_timezone="Europe/Oslo",
    )

    add_event_screen.open_for(event)

    assert add_event_screen.start_timezone.text == "Europe/Oslo"
    assert "Europe/Oslo" in add_event_screen.start_timezone.values
    assert "Berlin (UTC+01:00)" in add_event_screen.start_timezone.values
    built = add_event_screen._build_event()
    assert built is not None
    assert built.start_timezone == "Europe/Oslo"


def test_edit_form_can_return_to_the_default_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After picking another zone, Berlin is still in the dropdown."""
    _run_inline(monkeypatch)
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.start_timezone.text = "New York (UTC-05:00)"
    add_event_screen.start_timezone.text = "Berlin (UTC+01:00)"

    assert add_event_screen._resolved_time_zone(
        add_event_screen.start_timezone.text
    ) == "Europe/Berlin"


def test_event_form_lists_calendars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The form offers the connected account's calendars as a dropdown."""
    _run_inline(monkeypatch)
    _, _, add_event_screen = _make_screens(FakeClient())

    assert add_event_screen.calendar.values == ["Primary", "Work"]
    assert add_event_screen.calendar.text == "Primary"
    assert add_event_screen.calendar.disabled is False


def test_add_event_uses_the_selected_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new event is written to the calendar picked in the dropdown."""
    _run_inline(monkeypatch)
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.summary.text = "Dentist"
    add_event_screen.start.text = "2026-11-09T15:00+01:00"
    add_event_screen.end.text = "2026-11-09T16:30+01:00"
    add_event_screen.calendar.text = "Work"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.calendar_id == "work@example.com"


def test_edit_form_selects_the_event_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Editing preselects the calendar the event belongs to."""
    _run_inline(monkeypatch)
    _, _, add_event_screen = _make_screens(FakeClient())

    add_event_screen.open_for(_sample_event())

    assert add_event_screen.calendar.text == "Work"


def test_calendar_load_failure_keeps_the_form_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed calendar list is reported without blocking the save fallback."""
    from kivy_calendar.api import BackendError

    client = FakeClient()
    client.calendar_error = BackendError(0, "network_error", "offline")
    _run_inline(monkeypatch)
    _, _, add_event_screen = _make_screens(client)
    add_event_screen.summary.text = "Dentist"
    add_event_screen.start.text = "2026-11-09T15:00+01:00"
    add_event_screen.end.text = "2026-11-09T16:30+01:00"

    event = add_event_screen._build_event()

    assert add_event_screen.calendar.disabled
    assert "Could not load calendars" in add_event_screen.status_label.text
    assert event is not None
    assert event.calendar_id == ""


def test_add_event_builds_an_all_day_event() -> None:
    """An all-day form builds a midnight-to-midnight event."""
    _, _, add_event_screen = _make_screens(FakeClient())
    add_event_screen.all_day.active = True
    add_event_screen.summary.text = "Holiday"
    add_event_screen.start.text = "2026-11-09"
    add_event_screen.end.text = "2026-11-09"
    add_event_screen.start_timezone.text = "Europe/Berlin"
    add_event_screen.end_timezone.text = "Europe/Berlin"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.all_day is True
    assert event.start.date().isoformat() == "2026-11-09"
    assert event.end.date().isoformat() == "2026-11-10"


def test_edit_form_keeps_all_day_flag() -> None:
    """Editing an all-day event preserves its all-day flag."""
    from kivy_calendar.api import CalendarEvent

    _, _, add_event_screen = _make_screens(FakeClient())
    original = CalendarEvent(
        id="event-all-day",
        summary="Holiday",
        start=datetime(2026, 11, 9, 0, 0, tzinfo=BERLIN),
        end=datetime(2026, 11, 10, 0, 0, tzinfo=BERLIN),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        all_day=True,
    )
    add_event_screen.open_for(original)
    add_event_screen.summary.text = "Holiday (moved)"

    event = add_event_screen._build_event()

    assert event is not None
    assert event.id == original.id
    assert event.all_day is True
    assert event.summary == "Holiday (moved)"
