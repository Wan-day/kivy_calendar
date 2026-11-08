"""An in-memory calendar provider for tests and local development.

The fake keeps events in a dictionary keyed by the client-generated event id.  It
never performs network calls, and it mirrors the provider contract closely
enough that the sync service can be exercised offline.  Failures are injected
explicitly with :meth:`FakeCalendarProvider.fail_next`; an injected failure is
consumed before the operation changes any state, just like an offline or
rate-limited upstream call.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from core.errors import Error, ErrorCode, Result
from domain.event import Event
from google_calendar.provider import ProviderOperation


class FakeCalendarProvider:
    """An in-memory :class:`~google_calendar.provider.CalendarProvider` fake."""

    def __init__(self, events: Iterable[Event] = ()) -> None:
        self._events: dict[str, Event] = {
            event.id: event.model_copy(deep=True) for event in events
        }
        self._failures: dict[ProviderOperation, deque[Error]] = {
            operation: deque() for operation in ProviderOperation
        }
        self.calls: list[tuple[ProviderOperation, str | None]] = []

    @property
    def events(self) -> list[Event]:
        """Return deep copies of the stored events ordered by start time."""
        return sorted(
            (event.model_copy(deep=True) for event in self._events.values()),
            key=lambda event: (event.start, event.id),
        )

    def fail_next(
        self,
        operation: ProviderOperation | str,
        *,
        code: ErrorCode = ErrorCode.UPSTREAM_ERROR,
        message: str = "fake calendar provider failure",
        times: int = 1,
    ) -> None:
        """Make the next ``times`` calls to ``operation`` fail.

        The call leaves the stored events untouched, so callers see the same
        behaviour as a network or rate-limit failure.  ``times`` lets a test
        keep the provider offline across several attempts.
        """
        try:
            normalized = ProviderOperation(operation)
        except ValueError:
            raise ValueError(f"unknown provider operation: {operation!r}") from None
        if times < 1:
            raise ValueError("times must be at least 1")
        for _ in range(times):
            self._failures[normalized].append(Error(code=code, message=message))

    def create_event(self, event: Event) -> Result[Event]:
        """Store a new event, rejecting an id the fake already holds."""
        self.calls.append((ProviderOperation.CREATE, event.id))
        failure = self._take_failure(ProviderOperation.CREATE)
        if failure is not None:
            return Result.fail(failure.code, failure.message)
        if event.id in self._events:
            return Result.fail(
                ErrorCode.ALREADY_EXISTS,
                f"event {event.id!r} already exists in the fake calendar",
            )
        self._events[event.id] = event.model_copy(deep=True)
        return Result.ok(event.model_copy(deep=True))

    def update_event(self, event: Event) -> Result[Event]:
        """Replace a stored event, failing when its id is unknown."""
        self.calls.append((ProviderOperation.UPDATE, event.id))
        failure = self._take_failure(ProviderOperation.UPDATE)
        if failure is not None:
            return Result.fail(failure.code, failure.message)
        if event.id not in self._events:
            return Result.fail(
                ErrorCode.NOT_FOUND,
                f"event {event.id!r} does not exist in the fake calendar",
            )
        self._events[event.id] = event.model_copy(deep=True)
        return Result.ok(event.model_copy(deep=True))

    def delete_event(self, event_id: str) -> Result[None]:
        """Remove a stored event, failing when its id is unknown."""
        self.calls.append((ProviderOperation.DELETE, event_id))
        failure = self._take_failure(ProviderOperation.DELETE)
        if failure is not None:
            return Result.fail(failure.code, failure.message)
        if event_id not in self._events:
            return Result.fail(
                ErrorCode.NOT_FOUND,
                f"event {event_id!r} does not exist in the fake calendar",
            )
        del self._events[event_id]
        return Result.ok(None)

    def get_event(self, event_id: str) -> Result[Event | None]:
        """Return a stored event, or ``None`` when it does not exist."""
        self.calls.append((ProviderOperation.GET, event_id))
        failure = self._take_failure(ProviderOperation.GET)
        if failure is not None:
            return Result.fail(failure.code, failure.message)
        event = self._events.get(event_id)
        return Result.ok(event.model_copy(deep=True) if event is not None else None)

    def list_events(self) -> Result[list[Event]]:
        """Return every stored event ordered by start time."""
        self.calls.append((ProviderOperation.LIST, None))
        failure = self._take_failure(ProviderOperation.LIST)
        if failure is not None:
            return Result.fail(failure.code, failure.message)
        return Result.ok(self.events)

    def _take_failure(self, operation: ProviderOperation) -> Error | None:
        failures = self._failures[operation]
        return failures.popleft() if failures else None
