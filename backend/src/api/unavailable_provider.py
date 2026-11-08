"""An in-memory failing calendar provider used when Google is unconfigured."""

from __future__ import annotations

from api.errors import ErrorCode, Result
from domain.event import Event


class UnavailableCalendarProvider:
    """A :class:`CalendarProvider` fake that fails every operation."""

    def create_event(self, event: Event) -> Result[Event]:
        """Fail creates with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, "Google Calendar is not configured")

    def update_event(self, event: Event) -> Result[Event]:
        """Fail updates with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, "Google Calendar is not configured")

    def delete_event(self, event_id: str) -> Result[None]:
        """Fail deletes with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, "Google Calendar is not configured")

    def get_event(self, event_id: str) -> Result[Event | None]:
        """Fail gets with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, "Google Calendar is not configured")

    def list_events(self) -> Result[list[Event]]:
        """Fail listings with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, "Google Calendar is not configured")
