"""The main screen waits for a screen slide to end before rebuilding views.

Kivy is optional in CI, so these tests are skipped when it is not installed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("kivy")

from kivy_calendar.models import CalendarEvent  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")


def _event(name: str, hour: int) -> CalendarEvent:
    """Return a one-hour event today."""
    start = datetime.now(BERLIN).replace(hour=hour, minute=0, second=0, microsecond=0)
    return CalendarEvent(
        id=name,
        summary=name,
        start=start,
        end=start + timedelta(hours=1),
        calendar_id="primary",
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
    )


def _screens() -> tuple[Any, Any]:
    """Return a screen manager showing the main screen, and the main screen."""
    from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition

    from kivy_calendar.screens.main import MainScreen

    manager = ScreenManager(transition=SlideTransition(duration=0.3))
    main_screen = MainScreen(name="main", client=None)
    manager.add_widget(main_screen)
    manager.add_widget(Screen(name="other"))
    return manager, main_screen


def test_rebuild_waits_for_a_running_slide_and_then_runs_once() -> None:
    """Events that arrive mid-slide are drawn when the slide completes."""
    manager, main_screen = _screens()
    manager.current = "other"
    manager.current = "main"
    assert manager.transition.is_active

    main_screen._show_events([_event("Standup", 9)])

    assert main_screen.events != []
    assert main_screen.rows == []

    # More changes during the same slide do not queue extra renders.
    main_screen._show_events([_event("Standup", 9), _event("Lunch", 12)])
    main_screen._rebuild_view()
    assert main_screen.rows == []

    renders: list[str] = []
    original = main_screen._render_view
    main_screen._render_view = lambda: (renders.append("x"), original())[1]
    manager.transition.stop()
    manager.transition.dispatch("on_complete")

    assert renders == ["x"]
    assert [row.event.summary for row in main_screen.rows] == ["Standup", "Lunch"]
    assert main_screen._deferred_on is None


def test_rebuild_is_immediate_without_a_slide() -> None:
    """With no transition running the view is drawn at once."""
    _, main_screen = _screens()

    main_screen._show_events([_event("Standup", 9)])

    assert [row.event.summary for row in main_screen.rows] == ["Standup"]


def test_status_text_stays_immediate_during_a_slide() -> None:
    """Notices and loading text are cheap and do not wait."""
    manager, main_screen = _screens()
    manager.current = "other"
    manager.current = "main"

    main_screen.set_notice("Saved on the phone.")

    assert main_screen.status_label.text == "Saved on the phone."
    assert main_screen.rows == []


def test_only_the_shown_view_is_rebuilt() -> None:
    """Hidden views are filled when they are shown, not on every reload."""
    _, main_screen = _screens()
    sets: list[str] = []
    main_screen.week_view.set_events = lambda events: sets.append("week")
    main_screen.month_view.set_events = lambda events: sets.append("month")

    main_screen._show_events([_event("Standup", 9)])
    assert sets == []
    assert len(main_screen.rows) == 1

    main_screen.show_view("week")
    assert sets == ["week"]

    main_screen._show_events([_event("Lunch", 12)])
    assert sets == ["week", "week"]
