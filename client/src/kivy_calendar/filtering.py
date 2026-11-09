"""Pure filtering and sorting helpers for the displayed event list."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from kivy_calendar.api import CalendarEvent

SORT_START = "start"
SORT_START_DESC = "start_desc"
SORT_NAME = "name"
DEFAULT_SORT = SORT_START
SORT_ORDERS: tuple[str, ...] = (SORT_START, SORT_START_DESC, SORT_NAME)

SortOrder = Literal["start", "start_desc", "name"]

SORT_LABELS: tuple[str, ...] = (
    "Start: oldest first",
    "Start: newest first",
    "Name: A-Z",
)
SORT_BY_LABEL: dict[str, str] = {
    SORT_LABELS[0]: SORT_START,
    SORT_LABELS[1]: SORT_START_DESC,
    SORT_LABELS[2]: SORT_NAME,
}
DEFAULT_SORT_LABEL = SORT_LABELS[0]


def event_date(event: CalendarEvent) -> date:
    """Return the event's local calendar date in its declared time zone."""
    zone = ZoneInfo(event.start_timezone) if event.start_timezone else ZoneInfo("UTC")
    return event.start.astimezone(zone).date()


def _date_in_range(
    day: date,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    """Return whether ``day`` falls inside the optional date bounds."""
    if date_from is not None and day < date_from:
        return False
    if date_to is not None and day > date_to:
        return False
    return True


def filter_events(
    events: Sequence[CalendarEvent],
    *,
    name: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[CalendarEvent]:
    """Return the events whose name matches and whose date falls in range."""
    needle = name.strip().casefold()
    return [
        event
        for event in events
        if (not needle or needle in (event.summary or "").casefold())
        and _date_in_range(event_date(event), date_from, date_to)
    ]


def sort_events(
    events: Sequence[CalendarEvent],
    order: SortOrder = DEFAULT_SORT,
) -> list[CalendarEvent]:
    """Order events for display: start, start descending, or by name."""
    if order == SORT_START:
        return sorted(events, key=lambda event: (event.start, event.id))
    if order == SORT_START_DESC:
        return sorted(
            events,
            key=lambda event: (event.start, event.id),
            reverse=True,
        )
    return sorted(events, key=lambda event: (event.summary or "").casefold())


def parse_date_input(value: str) -> date | None:
    """Return the date from a ``YYYY-MM-DD`` input, or ``None`` when invalid."""
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
