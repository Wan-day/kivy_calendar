"""The window is phone-sized on desktop and never forced on a phone."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy_calendar.app import DESKTOP_WINDOW_SIZE, apply_window_size  # noqa: E402


@pytest.mark.parametrize("name", ["linux", "win", "macosx"])
def test_desktop_gets_a_phone_like_window(name: str) -> None:
    """On desktop the window is set to the phone-like default size."""
    window = SimpleNamespace(size=(800, 600))
    assert apply_window_size(window, name) is True
    assert window.size == DESKTOP_WINDOW_SIZE


@pytest.mark.parametrize("name", ["android", "ios"])
def test_phone_keeps_the_device_size(name: str) -> None:
    """On a phone the window size is left alone."""
    window = SimpleNamespace(size=(1080, 2340))
    assert apply_window_size(window, name) is False
    assert window.size == (1080, 2340)
