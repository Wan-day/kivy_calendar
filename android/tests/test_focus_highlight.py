"""Android's grey focus highlight is turned off on the app's views."""

from __future__ import annotations

from typing import Any

from phone_calendar import disable_focus_highlight, hide_focus_highlight


class View:
    """A view (or a container of views) that records the highlight setting."""

    def __init__(self, *children: View) -> None:
        self.children = list(children)
        self.highlight: bool | None = None

    def setDefaultFocusHighlightEnabled(self, enabled: bool) -> None:  # noqa: N802
        self.highlight = enabled


def _children(view: Any) -> list[Any]:
    return list(view.children)


def test_without_android_it_reports_failure() -> None:
    """Off a device there are no views; the call fails quietly."""
    assert hide_focus_highlight() is False


def test_every_view_in_the_tree_loses_the_highlight() -> None:
    """The SDL surface sits a few containers below the window's root view."""
    surface = View()
    text_view = View()
    root = View(View(View(surface), text_view), View())

    changed = disable_focus_highlight(root, _children)

    assert changed == 6
    assert surface.highlight is False
    assert text_view.highlight is False
    assert root.highlight is False
