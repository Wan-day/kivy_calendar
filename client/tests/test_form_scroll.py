"""The event form must never end up scrolled out of its content.

On a slow phone the form's ScrollView went blank (fields far out of view) and
stayed blank.  These tests drive a real ScrollView with real touches on a fake
clock whose frames are slow, and reset the scroll position the way the form
does when it opens and closes.
"""

from __future__ import annotations

import math
import os
import random
from collections.abc import Iterator
from typing import Any

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.clock import Clock  # noqa: E402
from kivy.input.motionevent import MotionEvent  # noqa: E402
from kivy.uix.screenmanager import NoTransition  # noqa: E402
from test_screens import FakeClient, _make_screens  # noqa: E402

from kivy_calendar.screens.scroll_effect import (  # noqa: E402
    MAX_COAST_FRAME,
    MAX_FLING,
    SteadyScrollEffect,
)

WINDOW = 10_000.0
VIEW_HEIGHT = 400.0
EPS = 1e-6


class FakeTime:
    """A clock the test advances by hand, so frames can be as slow as needed."""

    def __init__(self) -> None:
        self.now = Clock.time()

    def __call__(self) -> float:
        return self.now

    def frame(self, dt: float) -> None:
        """Run one Kivy frame that lasted ``dt`` seconds."""
        self.now += dt
        Clock.tick()


@pytest.fixture
def fake_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeTime]:
    """Replace every time source Kivy's scrolling reads with a fake one."""
    import kivy.effects.kinetic as kinetic
    import kivy.effects.scroll as scroll

    fake = FakeTime()
    real_time, real_fps = Clock.time, Clock._max_fps
    Clock.time = fake
    Clock._max_fps = 0
    monkeypatch.setattr(kinetic, "time", fake)
    monkeypatch.setattr(scroll, "time", fake)
    yield fake
    Clock.time = real_time
    Clock._max_fps = real_fps
    Clock._last_tick = Clock.time()


class _Touch(MotionEvent):
    """A real Kivy touch placed at window point (x, y), so grab() works."""

    def depack(self, args: Any) -> None:
        """Take the position from ``args``, scaled like a window touch."""
        self.is_touch = True
        self.profile = ["pos"]
        self.sx, self.sy = args["x"] / WINDOW, args["y"] / WINDOW
        super().depack(args)


class Rig:
    """The real form with a ScrollView of a known size and a fake clock."""

    def __init__(self, fake: FakeTime) -> None:
        self.fake = fake
        manager, _, self.form = _make_screens(FakeClient())
        manager.transition = NoTransition()
        manager.size = (400, 900)
        manager.current = "add_event"
        self.manager = manager
        self.fake.frame(0.016)
        self.fake.frame(0.016)
        self.scroll = self.form.scroll_view
        self.scroll.size_hint = (None, None)
        self.scroll.size = (400, VIEW_HEIGHT)
        self.scroll.pos = (0, 0)
        self.fake.frame(0.016)
        self.fake.frame(0.016)
        assert self.scroll.viewport_size[1] > VIEW_HEIGHT + 100

    @property
    def effect(self) -> Any:
        return self.scroll.effect_y

    def swipe(self, dy: float, dt: float, steps: int = 4) -> None:
        """Drag the finger by ``dy`` px over ``steps`` frames of ``dt`` each."""
        x, y = self.scroll.center
        touch = _Touch("test", 1, {"x": x, "y": y})
        touch.scale_for_screen(WINDOW, WINDOW)
        self.scroll.on_touch_down(touch)
        for _ in range(steps):
            y += dy / steps
            touch.sx, touch.sy = x / WINDOW, y / WINDOW
            touch.scale_for_screen(WINDOW, WINDOW)
            touch.grab_current = self.scroll
            self.scroll.on_touch_move(touch)
            touch.grab_current = None
            self.fake.frame(dt)
        touch.grab_current = self.scroll
        self.scroll.on_touch_up(touch)
        touch.grab_current = None
        self.fake.frame(dt)

    def run(self, frames: int, dt: float) -> list[float]:
        """Run ``frames`` frames and return ``scroll_y`` after each."""
        seen = []
        for _ in range(frames):
            self.fake.frame(dt)
            seen.append(self.scroll.scroll_y)
        return seen


def _in_range(values: list[float]) -> bool:
    return all(-EPS <= v <= 1 + EPS for v in values)


def test_form_scrolls_with_the_steady_effect() -> None:
    """The form's ScrollView uses the no-bounce effect."""
    _, _, form = _make_screens(FakeClient())
    assert isinstance(form.scroll_view.effect_y, SteadyScrollEffect)


def test_a_swipe_scrolls_the_form(fake_time: FakeTime) -> None:
    """The rig really scrolls (the other tests would pass vacuously if not)."""
    rig = Rig(fake_time)
    assert rig.scroll.scroll_y == pytest.approx(1.0)
    rig.swipe(150, 0.016)
    rig.run(5, 0.016)
    assert rig.scroll.scroll_y < 0.9


@pytest.mark.parametrize("dt", [0.1, 0.35, 0.6, 1.0])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_slow_frame_swipes_keep_scroll_in_range(
    fake_time: FakeTime, dt: float, seed: int
) -> None:
    """Swipes on slow frames, quick or slow, never leave the content."""
    rig = Rig(fake_time)
    rng = random.Random(seed)
    seen: list[float] = []
    for _ in range(25):
        rig.swipe(rng.choice([-250, -120, 120, 250]), rng.choice([0.016, dt]))
        seen.append(rig.scroll.scroll_y)
        seen += rig.run(10, dt)
    assert _in_range(seen), (min(seen), max(seen))


@pytest.mark.parametrize("dt", [0.016, 0.1, 0.35, 0.6])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_reopening_during_motion_ends_at_the_top_and_stays(
    fake_time: FakeTime, dt: float, seed: int
) -> None:
    """Opening the form after a fling leaves it on top, however long we wait.

    This is the stuck-blank state: the effect kept its old value and speed
    after ``scroll_y`` was reset, and kept overwriting the reset.
    """
    rig = Rig(fake_time)
    rng = random.Random(seed)
    for _ in range(25):
        rig.swipe(rng.choice([-250, -120, 120, 250]), 0.016)
        if rng.random() < 0.7:
            rig.form.open_for(None)
            assert rig.scroll.scroll_y == pytest.approx(1.0)
            seen = rig.run(15, dt)
            assert seen == [pytest.approx(1.0)] * len(seen)
            assert rig.effect.velocity == 0
        else:
            rig.run(8, dt)
    rig.form.open_for(None)
    assert rig.run(60, dt) == [pytest.approx(1.0)] * 60


def test_leaving_during_a_fling_stops_the_scrolling(fake_time: FakeTime) -> None:
    """Closing the form while it coasts halts the effect at the top."""
    rig = Rig(fake_time)
    rig.swipe(250, 0.016)
    assert rig.effect.velocity != 0
    rig.form.cancel()
    assert rig.effect.velocity == 0
    assert rig.run(30, 0.35) == [pytest.approx(1.0)] * 30


def test_opening_reapplies_the_top_after_layout(fake_time: FakeTime) -> None:
    """The top is applied again once Kivy has laid the new fields out."""
    rig = Rig(fake_time)
    rig.swipe(-250, 0.016)
    rig.form.open_for(None)
    # Something moves the form after open_for returned (content height changed
    # during layout); the scheduled re-apply puts it back on top.
    rig.scroll.scroll_y = 0.3
    rig.fake.frame(0.016)
    assert rig.scroll.scroll_y == pytest.approx(1.0)


def test_effect_release_speed_is_capped() -> None:
    """A release over a few microseconds cannot start a huge fling."""
    effect = SteadyScrollEffect(min=-1000, max=0)
    effect.start(0, 100.0)
    effect.update(-5, 100.00001)
    effect.stop(-500, 100.00002)
    assert abs(effect.velocity) <= MAX_FLING


def test_effect_reset_keeps_the_touch_history() -> None:
    """Hitting an end pins the value but keeps the real samples."""
    effect = SteadyScrollEffect(min=-100, max=0)
    effect.start(0, 1.0)
    effect.update(50, 1.01)
    assert effect.value == 0
    assert effect.history == [(1.0, 0), (1.01, 50)]
    assert effect.velocity == 0


def test_effect_coast_frame_is_capped() -> None:
    """A stalled frame coasts like a normal one and never flips the speed."""
    effect = SteadyScrollEffect(min=-100000, max=0)
    effect.velocity = -1000
    effect.update_velocity(5.0)
    assert effect.velocity < 0
    assert effect.value >= -1000 * MAX_COAST_FRAME - 1


def test_effect_halt_stops_and_moves() -> None:
    """halt() zeroes the speed, ends a touch and sets the value."""
    effect = SteadyScrollEffect(min=-100, max=0)
    effect.velocity = -500
    effect.is_manual = True
    effect.halt(-40)
    assert effect.velocity == 0
    assert not effect.is_manual
    assert effect.value == -40


def test_effect_cancel_zeroes_the_speed() -> None:
    """cancel() does not leave Kivy's speed running."""
    effect = SteadyScrollEffect(min=-100, max=0)
    effect.velocity = 300
    effect.cancel()
    assert effect.velocity == 0


def test_effect_survives_nan() -> None:
    """A NaN value or speed falls back to a safe number."""
    effect = SteadyScrollEffect(min=-100, max=0)
    effect.value = math.nan
    assert not math.isnan(effect.value)
    assert effect.velocity == 0
    effect.halt(math.nan)
    assert not math.isnan(effect.value)
