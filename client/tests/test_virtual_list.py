"""The event list builds only the cards near the screen."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("kivy")

from kivy.uix.scrollview import ScrollView  # noqa: E402
from kivy.uix.widget import Widget  # noqa: E402

from kivy_calendar.models import CalendarEvent  # noqa: E402
from kivy_calendar.screens.event_list import ListItem, VirtualList  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")


def _list(count: int, height: float = 50) -> tuple[ScrollView, VirtualList, list[int]]:
    """Return a scroll view with a list of ``count`` items and its build log."""
    scroll = ScrollView(size=(300, 400), size_hint=(None, None))
    items = VirtualList(scroll, spacing=10, padding_bottom=100)
    scroll.add_widget(items)
    log: list[int] = []

    def make(index: int) -> Widget:
        log.append(index)
        return Widget()

    items.set_items(
        [ListItem(height, lambda index=index: make(index)) for index in range(count)]
    )
    return scroll, items, log


def test_the_list_is_as_tall_as_all_items_but_builds_few() -> None:
    """Height covers every item and padding; only the near ones are built."""
    _, items, log = _list(1000)

    assert items.height == 1000 * 50 + 999 * 10 + 100
    assert 0 < len(log) < 60
    assert log == sorted(set(log))
    assert log[0] == 0


def test_scrolling_builds_the_items_that_come_near_and_drops_the_rest() -> None:
    """Items far above the view are removed again, new ones are placed."""
    scroll, items, log = _list(1000)

    scroll.scroll_y = 0.5
    built = items.built()

    assert len(built) < 60
    assert 0 not in [i for i in items._built]
    assert all(index > 100 for index in items._built)
    # Every built widget sits where its item is in the stack.
    for index, widget in items._built.items():
        assert widget.y == items.height - index * 60 - 50
        assert widget.width == items.width
    assert max(log) > 100


def test_a_short_list_is_built_whole() -> None:
    """A few items are all built, in order from top to bottom."""
    _, items, log = _list(5)

    assert log == [0, 1, 2, 3, 4]
    assert [w.y for w in items.built()] == sorted(
        (w.y for w in items.built()), reverse=True
    )


def test_replacing_the_items_drops_the_old_widgets() -> None:
    """New items start from the top with fresh widgets."""
    _, items, _ = _list(100)

    items.set_items([])

    assert items.children == []
    assert items.built() == []
    assert items.height == 100


def test_a_thousand_events_make_few_cards() -> None:
    """The main screen builds a screenful of cards for 1,000 events."""
    from kivy_calendar.screens.main import MainScreen

    start = datetime.now(BERLIN).replace(hour=9, minute=0, second=0, microsecond=0)
    events = [
        CalendarEvent(
            id=f"event-{index}",
            summary=f"Event {index}",
            start=start + timedelta(hours=index),
            end=start + timedelta(hours=index, minutes=30),
            start_timezone="Europe/Berlin",
            end_timezone="Europe/Berlin",
        )
        for index in range(1000)
    ]
    screen = MainScreen(name="main", client=None)

    screen._show_events(events)

    assert 0 < len(screen.rows) < 50
    assert screen.rows[0].event.id == "event-0"
    assert screen.event_list.height > 1000 * 68
