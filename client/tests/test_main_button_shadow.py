"""The New event button's shadow keeps the theme colour in every view.

Kivy is optional in CI, so these tests are skipped when it is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("kivy")


def test_shadow_sets_its_own_colour_right_before_it_is_drawn() -> None:
    """A BoxShadow has no colour property; it uses the last Color drawn.

    Without its own Color, the shadow took the coral of the week grid's
    current-time line, which is drawn earlier in the same frame.
    """
    from kivy.graphics import BoxShadow, Color

    from kivy_calendar.screens.main import SHADOW_COLOUR, MainScreen
    from kivy_calendar.screens.theme import CORAL, DEEP_SKY

    main_screen = MainScreen(name="main", client=None)
    main_screen.show_view("week")

    first, second = main_screen.add_button.canvas.before.children[:2]
    assert isinstance(first, Color)
    assert isinstance(second, BoxShadow)
    assert tuple(first.rgba) == pytest.approx(SHADOW_COLOUR)
    assert tuple(first.rgba)[:3] == pytest.approx(tuple(DEEP_SKY[:3]))
    assert tuple(first.rgba)[:3] != pytest.approx(tuple(CORAL[:3]))


def test_week_time_line_colour_stays_inside_the_grid_canvas() -> None:
    """The coral Color is in the grid's own canvas, not the button's."""
    from kivy.graphics import Color

    from kivy_calendar.screens.main import MainScreen
    from kivy_calendar.screens.theme import CORAL

    main_screen = MainScreen(name="main", client=None)
    grid = main_screen.week_view.grid

    assert grid._now_colour in grid.canvas.after.children
    coral = [
        item
        for item in main_screen.add_button.canvas.before.children
        if isinstance(item, Color) and tuple(item.rgba)[:3] == tuple(CORAL[:3])
    ]
    assert coral == []
