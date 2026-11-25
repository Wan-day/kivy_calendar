"""The main screen's header is the same in the list, week and month views.

Kivy is optional in CI, so these tests are skipped when it is not installed.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("kivy")


def _main() -> Any:
    """Return a main screen without a calendar client."""
    from kivy_calendar.screens.main import MainScreen

    return MainScreen(name="main", client=None)


def _header_geometry(main_screen: Any) -> tuple[Any, ...]:
    """Return every size and padding that makes up the header."""
    content = main_screen.content
    return (
        tuple(content.padding[:3]),
        content.spacing,
        main_screen.header.height,
        main_screen.view_switcher.height,
        main_screen.search_row.height,
        main_screen.status_label.collapse,
    )


def test_header_geometry_is_the_same_in_every_view() -> None:
    """Switching views never changes the header's padding or sizes."""
    main_screen = _main()
    shapes = []
    for name in ("list", "week", "month", "list"):
        main_screen.show_view(name)
        shapes.append(_header_geometry(main_screen))

    assert all(shape == shapes[0] for shape in shapes)


def test_only_the_bottom_room_for_the_button_differs_in_grid_views() -> None:
    """Grid views stop above the New event button; the list scrolls under it."""
    main_screen = _main()
    assert main_screen.content.padding[3] == 0

    main_screen.show_view("week")
    assert main_screen.content.padding[3] > 0

    main_screen.show_view("list")
    assert main_screen.content.padding[3] == 0


def test_errors_and_notices_still_show_in_every_view() -> None:
    """Only the plain event count folds away; messages always show."""
    main_screen = _main()
    for name in ("list", "week", "month"):
        main_screen.show_view(name)
        main_screen._set_status("Could not load events: offline", error=True)
        assert main_screen.status_label.height > 0
        main_screen._set_status("")
        assert main_screen.status_label.height == 0
