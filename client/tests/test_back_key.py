"""Back (Android) and Escape (desktop) close things in order, then leave."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.base import EventLoop  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.uix.button import Button  # noqa: E402
from kivy.uix.dropdown import DropDown  # noqa: E402
from kivy.uix.modalview import ModalView  # noqa: E402
from kivy.uix.screenmanager import NoTransition, Screen  # noqa: E402
from test_screens import FakeClient, _make_screens  # noqa: E402

from kivy_calendar.back_key import BACK_KEY, BackKeyHandler  # noqa: E402


class Setup:
    """The screens, a handler and the calls its background hook received."""

    def __init__(self) -> None:
        self.manager, self.main, self.form = _make_screens(FakeClient())
        self.manager.transition = NoTransition()
        EventLoop.window.add_widget(self.manager)
        self.backgrounded = 0
        self.handler = BackKeyHandler(self.manager, self.background)

    def background(self) -> None:
        self.backgrounded += 1

    def back(self) -> bool:
        return self.handler.on_keyboard(EventLoop.window, BACK_KEY, 0, "", [])


@pytest.fixture
def setup() -> Iterator[Setup]:
    """A main screen with a handler, removed from the window afterwards."""
    state = Setup()
    yield state
    EventLoop.window.remove_widget(state.manager)


def _open_popup() -> ModalView:
    popup = ModalView(auto_dismiss=False)  # a dialog that ignores Escape itself
    popup.open(animation=False)
    return popup


def _open_dropdown(setup: Setup) -> DropDown:
    anchor = Button(size_hint=(None, None), size=(100, 40))
    setup.main.add_widget(anchor)
    drop = DropDown()
    drop.add_widget(Button(size_hint_y=None, height=40))
    drop.open(anchor)
    return drop


def test_other_keys_are_left_alone(setup: Setup) -> None:
    """Only key 27 is taken."""
    assert setup.handler.on_keyboard(EventLoop.window, 97, 0, "a", []) is False
    assert setup.backgrounded == 0


def test_back_dismisses_a_popup_first(setup: Setup) -> None:
    """An open popup closes before anything else, even over the form."""
    setup.manager.current = "add_event"
    setup.form.summary.focus = True
    popup = _open_popup()
    dismissed: list[bool] = []
    popup.bind(on_dismiss=lambda *_: dismissed.append(True))
    drop = _open_dropdown(setup)
    try:
        assert setup.back() is True
        assert dismissed == [True]
        assert drop.parent is not None  # the dropdown waits for the next press
        assert setup.form.summary.focus
        assert setup.manager.current == "add_event"
        assert setup.backgrounded == 0
    finally:
        popup.dismiss(animation=False, force=True)
        drop.dismiss()
        Clock.tick()


def test_back_closes_a_dropdown_next(setup: Setup) -> None:
    """With no popup, an open dropdown closes before focus or screens change."""
    setup.manager.current = "add_event"
    setup.form.summary.focus = True
    drop = _open_dropdown(setup)
    assert setup.back() is True
    for _ in range(3):
        Clock.tick()
    assert drop.parent is None
    assert setup.form.summary.focus
    assert setup.manager.current == "add_event"


def test_back_unfocuses_the_text_field_next(setup: Setup) -> None:
    """A focused field is unfocused (the keyboard hides) before leaving the form."""
    setup.manager.current = "add_event"
    setup.form.description.focus = True
    assert setup.back() is True
    assert not setup.form.description.focus
    assert setup.manager.current == "add_event"


def test_back_leaves_the_form_without_saving(setup: Setup) -> None:
    """On the form, Back acts like the back arrow."""
    setup.manager.current = "add_event"
    setup.form.summary.text = "Draft"
    assert setup.back() is True
    assert setup.manager.current == "main"
    assert setup.form.client.created == []  # nothing was saved
    assert setup.backgrounded == 0


def test_back_on_main_moves_the_app_to_the_background(setup: Setup) -> None:
    """On the main screen Back backgrounds the app, once per press."""
    assert setup.manager.current == "main"
    assert setup.back() is True
    assert setup.backgrounded == 1
    assert setup.back() is True
    assert setup.backgrounded == 2
    assert setup.manager.current == "main"


@pytest.mark.parametrize("view", ["week", "month"])
def test_back_in_week_or_month_still_backgrounds(setup: Setup, view: str) -> None:
    """Views are tabs: Back does not step back to the list."""
    setup.main.show_view(view)
    assert setup.back() is True
    assert setup.backgrounded == 1


def test_back_on_the_permission_screen_backgrounds(setup: Setup) -> None:
    """The permission screen leaves the app the same way."""
    setup.manager.add_widget(Screen(name="permission"))
    setup.manager.current = "permission"
    assert setup.back() is True
    assert setup.backgrounded == 1


def test_escape_on_desktop_main_does_nothing(setup: Setup) -> None:
    """No background hook (desktop): the key is consumed and the app stays."""
    stopped: list[bool] = []
    handler = BackKeyHandler(setup.manager, None)
    original = EventLoop.window.dispatch

    def spy(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "on_request_close":
            stopped.append(True)
        return original(name, *args, **kwargs)

    EventLoop.window.dispatch = spy  # type: ignore[method-assign]
    try:
        assert handler.on_keyboard(EventLoop.window, BACK_KEY, 0, "", []) is True
    finally:
        del EventLoop.window.dispatch
    assert stopped == []
    assert setup.manager.current == "main"


def test_the_back_key_never_stops_the_app(setup: Setup, monkeypatch: Any) -> None:
    """Whatever the state, no step calls App.stop."""
    from kivy.app import App

    stops: list[int] = []
    monkeypatch.setattr(App, "stop", lambda self, *a: stops.append(1))
    setup.back()
    setup.manager.current = "add_event"
    setup.back()
    setup.back()
    assert stops == []


def test_desktop_has_no_background_hook() -> None:
    """Only the Android build can move the app to the background."""
    from kivy_calendar.app import background_hook

    assert background_hook() is None
