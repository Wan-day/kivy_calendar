"""Switching between List, Week and Month slides the view body.

Kivy is optional in CI, so these tests are skipped when it is not installed.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("kivy")


def _main() -> Any:
    """Return a main screen without a calendar client."""
    from kivy_calendar.screens.main import MainScreen

    main_screen = MainScreen(name="main", client=None)
    main_screen.view_body.size = (400, 600)
    return main_screen


def test_slide_is_about_0_3_seconds_and_eases_out() -> None:
    """The view slide matches the screen slide: 0.3 s, ``out_cubic``."""
    from kivy.animation import AnimationTransition

    from kivy_calendar.screens.main import VIEW_SLIDE_SECONDS

    main_screen = _main()
    slide = main_screen.view_body.transition

    assert slide.duration == pytest.approx(0.3)
    assert VIEW_SLIDE_SECONDS == pytest.approx(0.3)

    main_screen.show_view("week")
    # Halfway in time is further than halfway in distance for out_cubic.
    slide.on_progress(0.5)
    expected = 400 * (1 - AnimationTransition.out_cubic(0.5))
    assert main_screen.view_body.current_screen.x == pytest.approx(expected)
    assert expected < 200


@pytest.mark.parametrize(
    ("first", "second", "direction"),
    [
        ("week", "month", "left"),
        ("month", "week", "right"),
        ("list", "week", "left"),
        ("month", "list", "right"),
    ],
)
def test_direction_follows_the_switcher_order(
    first: str, second: str, direction: str
) -> None:
    """Going right in the switcher brings the new view in from the right."""
    main_screen = _main()
    main_screen.show_view(first)
    main_screen.view_body.transition.stop()

    main_screen.show_view(second)

    assert main_screen.view_body.transition.direction == direction
    assert main_screen.view_body.current == second


def test_new_view_starts_off_screen_and_the_old_one_leaves() -> None:
    """The incoming screen starts at the right edge, the old one at zero."""
    main_screen = _main()
    body = main_screen.view_body

    main_screen.show_view("week")

    assert body.transition.is_active
    assert body.current_screen.x == pytest.approx(body.x + body.width)
    assert body.get_screen("list").x == pytest.approx(body.x)

    body.transition.on_progress(1.0)
    assert body.current_screen.x == pytest.approx(body.x)
    assert body.get_screen("list").x == pytest.approx(body.x - body.width)


def test_header_and_switcher_do_not_move_while_sliding() -> None:
    """Only the body slides; the switcher state changes at once."""
    main_screen = _main()
    before = (
        main_screen.header.height,
        main_screen.view_switcher.height,
        main_screen.content.padding[:],
    )

    main_screen.show_view("month")

    assert main_screen.view_body.transition.is_active
    assert (
        main_screen.header.height,
        main_screen.view_switcher.height,
        main_screen.content.padding[:],
    ) == before
    assert main_screen.view_body.parent is main_screen.content
    assert main_screen.header.parent is main_screen.content
    from kivy_calendar.screens.theme import INK, MUTED

    buttons = main_screen.view_buttons
    assert tuple(buttons["month"].color) == tuple(INK)
    assert tuple(buttons["list"].color) == tuple(MUTED)
    assert main_screen.current_view == "month"


def test_taps_on_the_switcher_during_the_slide_are_safe() -> None:
    """Switching again mid-slide ends the first slide and starts the next."""
    main_screen = _main()
    body = main_screen.view_body

    main_screen.show_view("week")
    main_screen.show_view("month")
    main_screen.show_view("list")
    main_screen.show_view("list")
    body.transition.stop()

    assert main_screen.current_view == "list"
    assert body.current == "list"
    assert body.current_screen.x == pytest.approx(body.x)
    assert [screen.name for screen in body.children] == ["list"]


def test_hidden_views_leave_the_widget_tree_after_the_slide() -> None:
    """A view that is off show is detached, so its clock timer stops."""
    main_screen = _main()
    week = main_screen.week_view

    main_screen.show_view("week")
    assert week.parent is main_screen._holders["week"]
    main_screen.view_body.transition.stop()
    main_screen.view_body.transition.dispatch("on_complete")
    assert main_screen.views["list"].parent is None
    assert week._tick is not None

    main_screen.show_view("list")
    main_screen.view_body.transition.stop()
    main_screen.view_body.transition.dispatch("on_complete")
    assert week.parent is None
    assert week._tick is None
    assert main_screen.views["list"].parent is main_screen._holders["list"]


def test_filter_panel_stays_in_the_list_page() -> None:
    """The date chips and sort spinner never touch the shared header."""
    main_screen = _main()
    page = main_screen.views["list"]

    for name in ("week", "month", "list"):
        main_screen.show_view(name)
        assert main_screen.filter_panel.parent is page
        assert main_screen.filter_panel not in main_screen.content.children
