"""Calendar values and the error type shared by every calendar service.

The screens work with these types only, so they do not depend on where the
events come from: the HTTP backend on desktop, or the phone's own calendar on
Android.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ServiceError(Exception):
    """A calendar service failure the screens show to the user.

    ``code`` is a short machine-readable reason (``network_error``,
    ``not_found``, ...); ``message`` is the text the screens display.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the error."""
        super().__init__(message)
        self.code = code
        self.message = message


class EditScope(StrEnum):
    """Which occurrences of a repeating event a change or delete applies to."""

    THIS = "this"
    FOLLOWING = "following"
    ALL = "all"


ONLY_THIS = (EditScope.THIS,)


@dataclass(frozen=True)
class CalendarEvent:
    """A calendar event as the screens see it."""

    id: str
    summary: str
    start: datetime
    end: datetime
    start_timezone: str
    end_timezone: str
    calendar_id: str = ""
    recurring_event_id: str | None = None
    all_day: bool = False
    description: str | None = None
    recurrence: list[str] | None = None
    extended_properties: dict[str, str] | None = None
    # True when the change was accepted but is still waiting to sync.
    queued: bool = False


@dataclass(frozen=True)
class CalendarSummary:
    """A calendar the service can write events to."""

    id: str
    summary: str
    primary: bool = False


@dataclass(frozen=True)
class TimeZoneOption:
    """A selectable IANA time zone with its display label."""

    name: str
    label: str


@dataclass(frozen=True)
class FreeSlot:
    """A free time window the service suggests."""

    start: datetime
    end: datetime
