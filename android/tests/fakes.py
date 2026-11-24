"""Desktop stand-ins for Android's calendar store and permissions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from phone_calendar.store import Row

GOOGLE = "com.google"
LOCAL = "LOCAL"


def millis(value: datetime) -> int:
    """Milliseconds since the epoch, as Android stores times."""
    return int(value.timestamp() * 1000)


def utc_midnight(day: date) -> int:
    """All-day events are stored as UTC midnights."""
    return millis(datetime(day.year, day.month, day.day, tzinfo=UTC))


def calendar_row(
    calendar_id: int,
    name: str,
    *,
    access: int = 700,
    visible: int = 1,
    primary: int = 0,
    account: str = "test@example.com",
) -> Row:
    """A ``CalendarContract.Calendars`` row (700 = owner access)."""
    return {
        "_id": calendar_id,
        "calendar_displayName": name,
        "account_name": account,
        "account_type": GOOGLE,
        "calendar_access_level": access,
        "visible": visible,
        "isPrimary": primary,
        "calendar_color": -16776961,
    }


def instance_row(
    event_id: int,
    calendar_id: int,
    begin: int,
    end: int,
    title: str = "Event",
    **extra: object,
) -> Row:
    """A ``CalendarContract.Instances`` row with sensible defaults."""
    row: Row = {
        "_id": event_id * 1000,
        "event_id": event_id,
        "begin": begin,
        "end": end,
        "title": title,
        "description": None,
        "allDay": 0,
        "eventTimezone": "Europe/Berlin",
        "eventEndTimezone": None,
        "calendar_id": calendar_id,
        "rrule": None,
        "original_id": None,
        "availability": 0,
        "eventStatus": 1,
    }
    row.update(extra)
    return row


class FakeCalendarStore:
    """Rows as Android's calendar provider returns them.

    ``instances`` filters by the window like Android does (overlap with
    ``[begin_ms, end_ms)``) and records the windows it was asked for.
    """

    def __init__(
        self,
        calendars: list[Row] | None = None,
        instances: list[Row] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Create the store with optional rows and an error to raise."""
        self.calendar_rows = calendars or []
        self.instance_rows = instances or []
        self.error = error
        self.windows: list[tuple[int, int]] = []
        # Events table for writes; single events here also appear as
        # occurrences, as on a phone.
        self.event_rows: dict[int, Row] = {}
        self.next_id = 100
        # Make the next delete report 0 rows (to test rollbacks).
        self.fail_next_delete = False

    def calendars(self) -> list[Row]:
        """Return the calendar rows, or raise the configured error."""
        if self.error is not None:
            raise self.error
        return list(self.calendar_rows)

    def instances(self, begin_ms: int, end_ms: int) -> list[Row]:
        """Return the rows overlapping the window."""
        if self.error is not None:
            raise self.error
        self.windows.append((begin_ms, end_ms))
        rows = self.instance_rows + [
            _as_instance(row) for row in self.event_rows.values()
        ]
        return [row for row in rows if row["begin"] < end_ms and row["end"] > begin_ms]

    def event(self, event_id: int) -> Row | None:
        """Return one event row."""
        self._raise()
        row = self.event_rows.get(event_id)
        return dict(row) if row is not None else None

    def find_event_by_uid(self, uid: str) -> Row | None:
        """Return the event whose uid2445 is ``uid``."""
        self._raise()
        for row in self.event_rows.values():
            if row.get("uid2445") == uid:
                return dict(row)
        return None

    def insert_event(self, values: Row) -> int:
        """Insert an event and return its new id."""
        self._raise()
        event_id = self.next_id
        self.next_id += 1
        self.event_rows[event_id] = {"_id": event_id, **values}
        return event_id

    def update_event(self, event_id: int, values: Row) -> int:
        """Change columns of one event."""
        self._raise()
        row = self.event_rows.get(event_id)
        if row is None:
            return 0
        row.update(values)
        return 1

    def delete_event(self, event_id: int) -> int:
        """Delete one event."""
        self._raise()
        if self.fail_next_delete:
            self.fail_next_delete = False
            return 0
        return 1 if self.event_rows.pop(event_id, None) is not None else 0

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error


def _as_instance(row: Row) -> Row:
    """An occurrence row for a single (non-repeating) event row."""
    return {
        "_id": row["_id"] * 1000,
        "event_id": row["_id"],
        "begin": row["dtstart"],
        "end": row["dtend"],
        "title": row.get("title"),
        "description": row.get("description"),
        "allDay": row.get("allDay", 0),
        "eventTimezone": row.get("eventTimezone"),
        "eventEndTimezone": row.get("eventEndTimezone"),
        "calendar_id": row.get("calendar_id"),
        "rrule": row.get("rrule"),
        "original_id": row.get("original_id"),
        "availability": row.get("availability", 0),
        "eventStatus": row.get("eventStatus", 1),
    }


class FakePermissions:
    """Calendar permission that the test decides."""

    def __init__(self, granted: bool = True, answer: bool = True) -> None:
        """``granted`` is the current state; ``answer`` the dialog's result."""
        self.is_granted = granted
        self.answer = answer
        self.requests = 0
        self.settings_opened = 0

    def granted(self) -> bool:
        """Whether access is granted now."""
        return self.is_granted

    def request(self, on_result: Callable[[bool], None]) -> None:
        """Answer the request at once with ``answer``."""
        self.requests += 1
        self.is_granted = self.answer
        on_result(self.answer)

    def open_settings(self) -> None:
        """Record that the settings page was opened."""
        self.settings_opened += 1
