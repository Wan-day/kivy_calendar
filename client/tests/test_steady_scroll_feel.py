"""SteadyScrollEffect flings like Kivy's ScrollEffect on a normal phone."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.effects.scroll import ScrollEffect  # noqa: E402

from kivy_calendar.screens.scroll_effect import (  # noqa: E402
    MAX_COAST_FRAME,
    SteadyScrollEffect,
)


def _fling(effect_cls: type[ScrollEffect], speed: float, hz: float) -> float:
    """Release a drag at ``speed`` px/s, coast, and return the distance."""
    effect = effect_cls(min=-1_000_000, max=0)
    effect.value = 0
    step = 0.01
    effect.start(0, 100.0)
    t = 100.0
    for i in range(1, 7):
        t += step
        effect.update(-speed * step * i, t)
    effect.stop(-speed * step * 6, t)
    effect.trigger_velocity_update.cancel()
    start = effect.value
    dt = 1 / hz
    for _ in range(int(20 * hz)):
        effect.update_velocity(dt)
        effect.trigger_velocity_update.cancel()
        if effect.velocity == 0:
            break
    return abs(effect.value - start)


@pytest.mark.parametrize("hz", [60, 90, 120])
@pytest.mark.parametrize("speed", [600, 1200, 3000, 6000])
def test_a_fling_goes_as_far_as_kivys_default(speed: float, hz: float) -> None:
    """Same friction as ScrollEffect: the distance matches within 10 percent."""
    default = _fling(ScrollEffect, speed, hz)
    steady = _fling(SteadyScrollEffect, speed, hz)
    assert default > 100
    assert steady == pytest.approx(default, rel=0.10)


def test_a_busy_frame_of_80_ms_is_not_slowed() -> None:
    """Frames up to 100 ms count in full, so a busy frame does not stutter."""
    assert MAX_COAST_FRAME >= 0.1
    effect = SteadyScrollEffect(min=-1_000_000, max=0)
    effect.velocity = -1000
    effect.update_velocity(0.08)
    effect.trigger_velocity_update.cancel()
    reference = ScrollEffect(min=-1_000_000, max=0)
    reference.velocity = -1000
    reference.update_velocity(0.08)
    reference.trigger_velocity_update.cancel()
    assert effect.value == pytest.approx(reference.value)
    assert effect.velocity == pytest.approx(reference.velocity)


def test_a_stalled_frame_keeps_the_speed_sign() -> None:
    """A half-second stall neither flips the speed nor throws the content."""
    effect = SteadyScrollEffect(min=-1_000_000, max=0)
    effect.velocity = -1000
    effect.update_velocity(0.5)
    effect.trigger_velocity_update.cancel()
    assert effect.velocity < 0
    assert effect.value >= -1000 * MAX_COAST_FRAME - 1
