"""A long vertical list that only builds the widgets near the screen.

Building a card costs several milliseconds on a desktop and several times
that on a phone, so a list of 1,000 events must not make 1,000 cards.  The
list knows every item's height up front, so it can lay the items out without
widgets and create the card of an item only while it is within a screenful of
the visible part.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from kivy.metrics import dp
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

# Items this far above and below the visible part are built too, so a
# fling shows cards instead of blank space.
BUFFER = dp(500)
# The visible height assumed until the list has been laid out.
FALLBACK_VIEWPORT = dp(800)


@dataclass(frozen=True)
class ListItem:
    """One entry of the list: its height and how to build its widget."""

    height: float
    build: Callable[[], Widget]


class VirtualList(RelativeLayout):
    """Items stacked top to bottom inside a scroll view, built when near.

    ``children`` holds only the built widgets, in no particular order; the
    list is as tall as all items together, so the scroll bar and the scroll
    position behave as if every card existed.
    """

    def __init__(
        self,
        scroll: ScrollView,
        *,
        spacing: float = 0,
        padding_bottom: float = 0,
        **kwargs: Any,
    ) -> None:
        """Create the list inside ``scroll``; its height follows the items."""
        super().__init__(size_hint_y=None, height=padding_bottom, **kwargs)
        self.scroll = scroll
        self.spacing = spacing
        self.padding_bottom = padding_bottom
        self._items: list[ListItem] = []
        self._tops: list[float] = []
        self._built: dict[int, Widget] = {}
        self._range = (0, 0)
        scroll.bind(scroll_y=self._refresh, height=self._refresh)
        self.bind(height=self._refresh, width=self._fit_width)

    def set_items(self, items: Sequence[ListItem]) -> None:
        """Replace the items and build the ones that are in view."""
        self.clear_widgets()
        self._built = {}
        self._range = (0, 0)
        self._items = list(items)
        self._tops = []
        top = 0.0
        for item in self._items:
            self._tops.append(top)
            top += item.height + self.spacing
        if self._items:
            top -= self.spacing
        self.height = top + self.padding_bottom
        self._refresh()

    def built(self) -> list[Widget]:
        """Return the built widgets from top to bottom."""
        return [self._built[index] for index in sorted(self._built)]

    def _fit_width(self, *_: Any) -> None:
        """Keep the built widgets as wide as the list."""
        for widget in self._built.values():
            widget.width = self.width

    def _visible_span(self) -> tuple[float, float]:
        """Return the distances from the list's top that are on screen."""
        viewport = self.scroll.height or FALLBACK_VIEWPORT
        hidden = max(0.0, self.height - viewport)
        top = (1 - self.scroll.scroll_y) * hidden
        return top, top + viewport

    def _refresh(self, *_: Any) -> None:
        """Build the widgets that came near and drop the ones that left."""
        if not self._items:
            return
        top, bottom = self._visible_span()
        first = max(0, bisect_right(self._tops, top - BUFFER) - 1)
        last = bisect_right(self._tops, bottom + BUFFER)
        if (first, last) == self._range:
            return
        self._range = (first, last)
        for index in [i for i in self._built if not first <= i < last]:
            self.remove_widget(self._built.pop(index))
        for index in range(first, last):
            if index not in self._built:
                self._build(index)

    def _build(self, index: int) -> None:
        """Build the widget of item ``index`` and put it in place."""
        item = self._items[index]
        widget = item.build()
        widget.size_hint = (None, None)
        widget.size = (self.width, item.height)
        widget.pos = (0, self.height - self._tops[index] - item.height)
        self._built[index] = widget
        self.add_widget(widget)
