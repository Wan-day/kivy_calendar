"""A scroll effect that stays in range however slow the frames are."""

from __future__ import annotations

import math
from typing import Any

from kivy.effects.scroll import ScrollEffect
from kivy.metrics import dp

# A frame longer than this counts as this long while the view coasts, so one
# stalled frame on a slow phone cannot throw the content across its height.
MAX_COAST_FRAME = 0.1
# The fastest fling a release may start, in pixels per second (a very hard
# swipe on a phone is under 8000 dp/s; this only stops a corrupt sample).
MAX_FLING = dp(10000)


class SteadyScrollEffect(ScrollEffect):
    """Scroll without bounce, follow the finger, and coast without jumping.

    Kivy's own effects misbehave in ways that show on a slow phone:

    * ``ScrollEffect.reset`` (called when the value hits an end) replaces the
      touch history by one sample stamped "now", so the release speed is
      measured over a few microseconds and comes out near 10**7 px/s;
    * ``KineticEffect.update_velocity`` slows the speed by
      ``friction * dt / 0.017`` a frame, which is more than the whole speed
      once a frame lasts over 0.34 s, so the speed flips sign and the content
      is flung to the opposite end;
    * ``KineticEffect.cancel`` leaves the speed alone, and a programmatic
      ``scroll_y`` leaves the effect with its old value and speed, which then
      overwrite the new position.  Use :meth:`halt` to move the content.
    """

    def reset(self, pos: float) -> None:
        """Pin the value at an end and stop, keeping the real touch history."""
        self.value = pos
        self.velocity = 0

    def on_value(self, *args: Any) -> None:
        """Clamp to the range; a NaN value falls back to the lower bound."""
        if math.isnan(self.value):
            self.value = min(self.min, self.max)
            self.velocity = 0
            return
        super().on_value(*args)

    def stop(self, val: float, t: float | None = None) -> Any:
        """Release the touch, with a sane fling speed."""
        result = super().stop(val, t)
        speed = self.velocity
        if math.isnan(speed):
            speed = 0
        self.velocity = max(-MAX_FLING, min(MAX_FLING, speed))
        return result

    def cancel(self) -> None:
        """Cancel the touch and stop at once (Kivy would keep coasting)."""
        self.velocity = 0
        super().cancel()

    def update_velocity(self, dt: float) -> None:
        """Coast one frame, never counting more than ``MAX_COAST_FRAME``."""
        super().update_velocity(min(dt, MAX_COAST_FRAME))

    def halt(self, value: float | None = None) -> None:
        """Stop coasting at once, and optionally jump to ``value``."""
        self.velocity = 0
        self.is_manual = False
        if value is not None and not math.isnan(value):
            self.value = value
