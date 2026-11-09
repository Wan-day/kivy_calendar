"""An in-memory failing calendar provider used when Google is unconfigured."""

from __future__ import annotations

from api.errors import ErrorCode, Result
from domain.event import Event


class UnavailableCalendarProvider:
    """A :class:`CalendarProvider` fake that fails every operation."""

    def __init__(self, reason: str | None = None) -> None:
        """Store the configuration failure reported to API callers."""
        message = "Google Calendar is not configured"
        if reason:
            message = f"{message}: {reason}"
        self._message = message

    def create_event(self, event: Event) -> Result[Event]:
        """Fail creates with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, self._message)

    def update_event(self, event: Event) -> Result[Event]:
        """Fail updates with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, self._message)

    def delete_event(self, event_id: str) -> Result[None]:
        """Fail deletes with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, self._message)

    def get_event(self, event_id: str) -> Result[Event | None]:
        """Fail gets with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, self._message)

    def list_events(self) -> Result[list[Event]]:
        """Fail listings with an authentication error."""
        return Result.fail(ErrorCode.AUTH_ERROR, self._message)
