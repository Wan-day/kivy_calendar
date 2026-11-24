"""The calendar service the screens talk to.

Each build provides one implementation: :class:`~kivy_calendar.api.BackendClient`
talks to the HTTP backend on desktop, and an in-process service will read the
phone's calendar on Android. Implementations raise
:class:`~kivy_calendar.models.ServiceError` for failures the user should see.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from kivy_calendar.models import (
    CalendarEvent,
    CalendarSummary,
    FreeSlot,
    TimeZoneOption,
)


class CalendarService(Protocol):
    """Everything the screens need from a calendar."""

    def list_events(self) -> list[CalendarEvent]:
        """Return the events to show in the list."""
        ...

    def list_calendars(self) -> list[CalendarSummary]:
        """Return the calendars events can be written to."""
        ...

    def list_time_zones(self) -> list[TimeZoneOption]:
        """Return the time zones offered in the event form."""
        ...

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        """Create ``event`` and return it as saved."""
        ...

    def update_event(
        self,
        event: CalendarEvent,
        source_calendar_id: str = "",
    ) -> CalendarEvent:
        """Update ``event``; ``source_calendar_id`` is the calendar it is in now."""
        ...

    def delete_event(self, event_id: str, calendar_id: str = "") -> bool:
        """Delete an event; return ``True`` when the delete is only queued."""
        ...

    def sync(self) -> int:
        """Refresh from the calendar's source and return the event count."""
        ...

    def find_free_slots(
        self,
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        time_zone: str,
    ) -> list[FreeSlot]:
        """Return free windows of ``duration_minutes`` between the two times."""
        ...


SERVICE_ENV = "KIVY_CALENDAR_SERVICE"
MEMORY_SERVICE = "memory"


def choose_service(
    environ: Mapping[str, str] | None = None,
    platform: str = "",
) -> tuple[CalendarService | None, str | None]:
    """Return the service for this build and a configuration error, if any.

    Android uses the in-memory service until the phone-calendar service
    exists; ``KIVY_CALENDAR_SERVICE=memory`` does the same on desktop. Other
    desktop runs use the HTTP backend. Without a backend token the app still
    starts, so the window can say what is missing instead of crashing.
    """
    # Imported here so the interface module stays free of implementations.
    from kivy_calendar.api import (
        BASE_URL_ENV,
        DEFAULT_BASE_URL,
        TOKEN_ENV,
        BackendClient,
    )
    from kivy_calendar.memory_service import InMemoryCalendarService, sample_events

    environment = os.environ if environ is None else environ
    if platform == "android" or environment.get(SERVICE_ENV) == MEMORY_SERVICE:
        return InMemoryCalendarService(sample_events()), None
    try:
        client = BackendClient(
            base_url=environment.get(BASE_URL_ENV) or DEFAULT_BASE_URL,
            token=environment.get(TOKEN_ENV) or "",
        )
        return client, None
    except ValueError as error:
        message = (
            f"Backend client is not configured: {error}. "
            f"Set {TOKEN_ENV} and restart the app, or set "
            f"{SERVICE_ENV}={MEMORY_SERVICE} to try it with sample events."
        )
        return None, message
