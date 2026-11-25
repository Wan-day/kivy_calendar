"""The event form must not leave focus, selection or handles behind."""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.base import EventLoop  # noqa: E402
from test_screens import FakeClient, _make_screens  # noqa: E402


def _select_title(form: Any) -> list[Any]:
    """Focus and select the title, showing its handles; return the handles."""
    window = EventLoop.window
    form.summary.use_handles = True  # the default on a phone, off on desktop
    form.summary.text = "Team standup"
    form.summary.focus = True
    form.summary.select_all()
    form.summary._show_handles(0)
    handles = [form.summary._handle_left, form.summary._handle_right]
    assert all(h is not None and h.parent is window for h in handles)
    return handles


def _assert_clean(form: Any, handles: list[Any]) -> None:
    for field in (form.summary, form.description):
        assert not field.focus
        assert not field.selection_text
        assert field._selection is False
    assert all(h.parent is None for h in handles)
    assert not [w for w in EventLoop.window.children if w in handles]


@pytest.mark.parametrize("how", ["cancel", "leave", "saved", "deleted"])
def test_leaving_the_form_clears_focus_selection_and_handles(how: str) -> None:
    """Every way out unfocuses the fields and removes the Window handles."""
    manager, _, form = _make_screens(FakeClient())
    manager.current = "add_event"
    handles = _select_title(form)
    if how == "cancel":
        form.cancel()
    elif how == "leave":
        manager.current = "main"
    elif how == "saved":
        form._on_saved()
    else:
        form._on_deleted()
    _assert_clean(form, handles)


def test_reopening_starts_at_the_top_with_nothing_selected() -> None:
    """open_for resets focus, selection, handles and the scroll position."""
    _, _, form = _make_screens(FakeClient())
    handles = _select_title(form)
    form.scroll_view.scroll_y = 0.0
    form.open_for(None)
    _assert_clean(form, handles)
    assert form.scroll_view.scroll_y == 1.0
