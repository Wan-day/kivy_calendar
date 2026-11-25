"""A single tap on a form text field focuses it and leaves the form alone.

The form's ScrollView holds a touch back until it knows whether it is a tap or
a drag, then replays it to the field.  These tests press and release a real
touch like a finger does (small movements while it is down) and run the clock
for a second afterwards.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.uix.behaviors.focus import FocusBehavior  # noqa: E402
from test_form_scroll import (  # noqa: E402, F401
    WINDOW,
    FakeTime,
    Rig,
    _Touch,
    fake_time,
)


def _tap(rig: Rig, field: Any, hold: float, jitter: float = 0.0) -> None:
    """Press ``field`` and release it ``hold`` seconds later, like a finger."""
    x, y = field.to_window(*field.center)
    touch = _Touch("test", 7, {"x": x, "y": y})
    touch.scale_for_screen(WINDOW, WINDOW)
    rig.scroll.on_touch_down(touch)
    elapsed = 0.0
    while elapsed < hold:
        rig.fake.frame(0.016)
        elapsed += 0.016
        touch.move({"x": x + jitter, "y": y + jitter})
        touch.scale_for_screen(WINDOW, WINDOW)
        touch.grab_current = rig.scroll
        rig.scroll.on_touch_move(touch)
        touch.grab_current = None
        jitter = -jitter
    touch.grab_current = rig.scroll
    rig.scroll.on_touch_up(touch)
    touch.grab_current = None
    # The Window does this after every touch up.
    FocusBehavior._handle_post_on_touch_up(touch)


def _rig_with_both_fields_visible(fake: FakeTime) -> Rig:
    rig = Rig(fake)
    rig.scroll.height = rig.scroll.viewport_size[1]
    for _ in range(3):
        fake.frame(0.016)
    assert rig.form.description.to_window(*rig.form.description.center)[1] > 0
    return rig


@pytest.mark.parametrize("name", ["summary", "description"])
@pytest.mark.parametrize("hold", [0.03, 0.06, 0.12])
@pytest.mark.parametrize("jitter", [0.0, 1.0, 8.0])
def test_one_tap_focuses_the_field_and_it_stays_focused(
    fake_time: FakeTime,  # noqa: F811
    name: str,
    hold: float,
    jitter: float,
) -> None:
    """The ScrollView replays the tap to the field; nothing unfocuses it."""
    rig = _rig_with_both_fields_visible(fake_time)
    field = getattr(rig.form, name)
    _tap(rig, field, hold, jitter)
    for _ in range(70):  # about a second of frames
        rig.fake.frame(0.016)
    assert field.focus


@pytest.mark.parametrize("hold", [0.03, 0.06, 0.1, 0.12, 0.2])
@pytest.mark.parametrize("jitter", [1.0, 4.0, 8.0])
def test_a_tap_does_not_move_the_form(
    fake_time: FakeTime,  # noqa: F811
    hold: float,
    jitter: float,
) -> None:
    """A finger that wobbles while tapping must not fling the form away.

    The effect once treated any movement as a drag, so the wobble of a tap
    became a fling that scrolled the field out from under the finger.
    """
    rig = Rig(fake_time)
    _tap(rig, rig.form.summary, hold, jitter)
    for _ in range(70):
        rig.fake.frame(0.016)
    assert rig.scroll.scroll_y == pytest.approx(1.0)
    assert rig.form.summary.focus
