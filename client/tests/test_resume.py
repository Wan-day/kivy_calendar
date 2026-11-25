"""Pausing keeps the app; resuming redraws the window and reloads events."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.base import EventLoop  # noqa: E402
from kivy.clock import Clock  # noqa: E402

from kivy_calendar.app import RESUME_REDRAW_DELAY, KivyCalendarApp  # noqa: E402


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Iterator[KivyCalendarApp]:
    """The real app's screens, built over sample events."""
    monkeypatch.setenv("KIVY_CALENDAR_SERVICE", "memory")
    app = KivyCalendarApp()
    root = app.build()
    yield app
    EventLoop.window.unbind(on_keyboard=app.back_keys.on_keyboard)
    del root


def test_pause_keeps_the_app(app: KivyCalendarApp) -> None:
    """True means Android keeps the process instead of finishing it."""
    assert app.on_pause() is True


def test_resume_redraws_and_reloads(
    app: KivyCalendarApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming redraws at once and later, and asks for the events again."""
    window = EventLoop.window
    redraws: list[int] = []
    viewports: list[int] = []
    loads: list[int] = []
    real_redraw = app.redraw

    def counting_redraw(*args: object) -> None:
        redraws.append(1)
        real_redraw(*args)

    monkeypatch.setattr(app, "redraw", counting_redraw)
    monkeypatch.setattr(window, "update_viewport", lambda: viewports.append(1))
    monkeypatch.setattr(app.main_screen, "load_events", lambda: loads.append(1))
    app.on_resume()
    assert len(redraws) == 1  # at once
    assert viewports == [1]  # it resets the viewport
    assert loads == [1]
    # The two redraws scheduled for later (next frame and a short delay) run
    # once the clock has passed the delay.
    time.sleep(RESUME_REDRAW_DELAY + 0.05)
    Clock.tick()
    assert len(redraws) == 3


def test_resume_does_not_load_while_waiting_for_access(
    app: KivyCalendarApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without calendar access there is nothing to reload yet."""
    app.needs_access = True
    loads: list[int] = []
    monkeypatch.setattr(app.main_screen, "load_events", lambda: loads.append(1))
    app.on_resume()
    assert loads == []


def test_escape_on_the_real_app_keeps_it_open(
    app: KivyCalendarApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escape through the real Window dispatch is consumed; the app is not stopped."""
    stops: list[int] = []
    monkeypatch.setattr(KivyCalendarApp, "stop", lambda self, *a: stops.append(1))
    EventLoop.window.dispatch("on_keyboard", 27, 0, "", [])
    assert stops == []
    assert app.screen_manager.current == "main"
