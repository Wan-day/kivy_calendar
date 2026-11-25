"""Keep a focused text field visible above the on-screen keyboard.

The window is not resized or panned. Instead the form gives up the bottom part
of its own area to the keyboard and scrolls the focused field into the part
that is left, so the header (back arrow, title, Save) never moves.
"""

from __future__ import annotations

from typing import Any

from kivy.core.window import Window
from kivy.metrics import dp

from kivy_calendar.screens.scroll_effect import SteadyScrollEffect

# Kivy's SDL2 window on Android reports a keyboard height of 0 (it has no way
# to read it), so on a phone this share of the window height is assumed.
ASSUMED_KEYBOARD_SHARE = 0.4
# Room kept between the field and the edges of the visible area.
FIELD_MARGIN = dp(12)


def reported_keyboard_height() -> float:
    """The keyboard height Kivy reports now (0 when hidden or unknown)."""
    return float(Window.keyboard_height)


def keyboard_inset(
    reported: float, window_height: float, *, mobile: bool, focused: bool
) -> float:
    """Height the form must leave free at its bottom for the keyboard.

    ``reported`` is Kivy's keyboard height. Without a text field in focus there
    is no keyboard and no inset. On a phone where the height is not reported,
    a share of the window is assumed.
    """
    if not focused:
        return 0.0
    if reported > 0:
        return float(reported)
    return window_height * ASSUMED_KEYBOARD_SHARE if mobile else 0.0


def scroll_into_view(scroll: Any, widget: Any, margin: float = FIELD_MARGIN) -> None:
    """Scroll ``scroll`` the least needed so ``widget`` is fully visible.

    Works through the scroll effect, which owns the position (see
    :class:`SteadyScrollEffect`), so the move is not overwritten a frame later.
    """
    content = scroll.viewport_size[1]
    hidden = content - scroll.height
    if hidden <= 0 or scroll.height <= 0:
        return
    view_bottom = scroll.to_window(0, scroll.y)[1]
    view_top = view_bottom + scroll.height
    field_bottom = widget.to_window(0, widget.y)[1]
    field_top = field_bottom + widget.height
    if field_top > view_top - margin:
        shift = field_top - (view_top - margin)  # content moves down
    elif field_bottom < view_bottom + margin:
        shift = field_bottom - (view_bottom + margin)  # content moves up
    else:
        return
    # scroll_y is 1 at the top and 0 at the bottom of ``hidden`` pixels.
    target = min(1.0, max(0.0, scroll.scroll_y + shift / hidden))
    effect = scroll.effect_y
    if isinstance(effect, SteadyScrollEffect):
        effect.halt(-hidden * target)
    scroll.scroll_y = target
