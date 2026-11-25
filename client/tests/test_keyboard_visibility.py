"""A focused text field must stay visible above the on-screen keyboard."""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.base import EventLoop  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.uix.screenmanager import NoTransition  # noqa: E402
from test_screens import FakeClient, _make_screens  # noqa: E402

from kivy_calendar.screens import add_event  # noqa: E402
from kivy_calendar.screens.keyboard import (  # noqa: E402
    ASSUMED_KEYBOARD_SHARE,
    keyboard_inset,
)


def _tick(frames: int = 4) -> None:
    for _ in range(frames):
        Clock.tick()


def _open_form(monkeypatch: pytest.MonkeyPatch, keyboard: list[float]) -> Any:
    """An open form on a short screen; ``keyboard[0]`` is the reported height."""
    monkeypatch.setattr(add_event, "reported_keyboard_height", lambda: keyboard[0])
    manager, _, form = _make_screens(FakeClient())
    manager.transition = NoTransition()
    EventLoop.window.add_widget(manager)
    manager.current = "add_event"
    _tick()
    return manager, form


def _visible_above(form: Any, field: Any, keyboard_height: float) -> bool:
    """Whether ``field`` lies fully above the keyboard (window coordinates)."""
    bottom = field.to_window(0, field.y)[1]
    top = bottom + field.height
    scroll_top = form.scroll_view.to_window(0, form.scroll_view.top)[1]
    return bottom >= keyboard_height and top <= scroll_top


def test_inset_is_zero_without_a_focused_field() -> None:
    """No field in focus means no keyboard, whatever Kivy reports."""
    assert keyboard_inset(300, 700, mobile=True, focused=False) == 0


def test_inset_uses_the_reported_height() -> None:
    """A height Kivy reports is used as it is."""
    assert keyboard_inset(300, 700, mobile=True, focused=True) == 300


def test_inset_assumes_a_height_on_a_phone_that_reports_none() -> None:
    """Android's SDL2 window reports 0, so a share of the screen is assumed."""
    assert keyboard_inset(0, 700, mobile=True, focused=True) == pytest.approx(
        700 * ASSUMED_KEYBOARD_SHARE
    )
    assert keyboard_inset(0, 700, mobile=False, focused=True) == 0


def test_focusing_notes_lifts_it_above_the_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Notes sit low in the form; with the keyboard up they are scrolled clear."""
    keyboard = [0.0]
    manager, form = _open_form(monkeypatch, keyboard)
    try:
        header_before = form.cancel_button.to_window(0, form.cancel_button.y)[1]
        keyboard[0] = 300.0
        form.description.focus = True
        _tick()
        assert form._layout.padding[3] == 300.0
        assert _visible_above(form, form.description, 300.0)
        # The header stays where it was.
        header_after = form.cancel_button.to_window(0, form.cancel_button.y)[1]
        assert header_after == header_before
    finally:
        form.description.focus = False
        EventLoop.window.remove_widget(manager)


def test_a_late_keyboard_height_still_lifts_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keyboard slides in after the tap; the field follows its real height."""
    keyboard = [0.0]
    manager, form = _open_form(monkeypatch, keyboard)
    try:
        form.description.focus = True
        _tick()
        keyboard[0] = 320.0
        form._update_keyboard_inset()
        _tick()
        assert _visible_above(form, form.description, 320.0)
    finally:
        form.description.focus = False
        EventLoop.window.remove_widget(manager)


def test_unfocusing_gives_the_room_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """When editing ends the form takes its full height again."""
    keyboard = [300.0]
    manager, form = _open_form(monkeypatch, keyboard)
    try:
        form.description.focus = True
        _tick()
        assert form._layout.padding[3] == 300.0
        form.description.focus = False
        _tick()
        assert form._layout.padding[3] == 0
        assert not form._watching_keyboard
    finally:
        EventLoop.window.remove_widget(manager)
