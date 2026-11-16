"""SQLite-backed cache of calendar events.

The cache is disposable: Google Calendar is the source of truth, so this module
only stores a copy that can be rebuilt by replacing its rows from a full sync.
Clearing or replacing cached events never touches the retry queue.  This module
never stores credentials or the only copy of an event.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from core.errors import ErrorCode, Result
from core.sqlite import Database, run_in_transaction
from domain.event import Event

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT NOT NULL,
    calendar_id TEXT NOT NULL DEFAULT '',
    recurring_event_id TEXT NOT NULL DEFAULT '',
    all_day TEXT NOT NULL DEFAULT '0',
    summary TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    start_timezone TEXT NOT NULL,
    end_utc TEXT NOT NULL,
    end_timezone TEXT NOT NULL,
    description TEXT,
    recurrence TEXT,
    extended_properties TEXT NOT NULL,
    cached_at TEXT NOT NULL,
    PRIMARY KEY (calendar_id, id)
);

CREATE INDEX IF NOT EXISTS idx_events_start_utc ON events (start_utc);
CREATE INDEX IF NOT EXISTS idx_events_id ON events (id);
"""

_COLUMNS = (
    "id",
    "calendar_id",
    "recurring_event_id",
    "all_day",
    "summary",
    "start_utc",
    "start_timezone",
    "end_utc",
    "end_timezone",
    "description",
    "recurrence",
    "extended_properties",
    "cached_at",
)
_COLUMN_LIST = ", ".join(_COLUMNS)
_PLACEHOLDERS = ", ".join("?" for _ in _COLUMNS)
_INSERT = f"INSERT INTO events ({_COLUMN_LIST}) VALUES ({_PLACEHOLDERS})"
_UPDATE = """
UPDATE events
SET calendar_id = ?,
    recurring_event_id = ?,
    all_day = ?,
    summary = ?,
    start_utc = ?,
    start_timezone = ?,
    end_utc = ?,
    end_timezone = ?,
    description = ?,
    recurrence = ?,
    extended_properties = ?,
    cached_at = ?
WHERE calendar_id = ? AND id = ?
"""

AMBIGUOUS_MESSAGE = (
    "event {event_id!r} is cached in several calendars; specify calendar_id"
)


class EventRepository:
    """Create, read, update, and delete events in the disposable cache."""

    def __init__(self, database: Database | None = None) -> None:
        self._database = database if database is not None else Database()

    @property
    def database(self) -> Database:
        """The database this repository writes to."""
        return self._database

    def _run[T](
        self,
        operation: Callable[[sqlite3.Connection], Result[T]],
    ) -> Result[T]:
        """Run ``operation`` after bringing an old cache schema up to date."""

        def migrated(connection: sqlite3.Connection) -> Result[T]:
            _migrate(connection)
            return operation(connection)

        return run_in_transaction(self._database, _SCHEMA, migrated)

    def create(self, event: Event) -> Result[Event]:
        """Cache a new event, failing if its id is already cached."""

        def operation(connection: sqlite3.Connection) -> Result[Event]:
            try:
                connection.execute(_INSERT, _event_values(event))
            except sqlite3.IntegrityError:
                return Result.fail(
                    ErrorCode.ALREADY_EXISTS,
                    f"event {event.id!r} is already cached",
                )
            return Result.ok(event)

        return self._run(operation)

    def get(self, event_id: str, calendar_id: str | None = None) -> Result[Event]:
        """Return the cached event with ``event_id``.

        Events are keyed by calendar and id.  Without ``calendar_id`` the id
        must match exactly one cached event; an id shared by several calendars
        is rejected as ambiguous instead of guessing.
        """

        def operation(connection: sqlite3.Connection) -> Result[Event]:
            rows = _select_rows(connection, event_id, calendar_id)
            if not rows:
                return Result.fail(
                    ErrorCode.NOT_FOUND,
                    f"event {event_id!r} is not cached",
                )
            if len(rows) > 1:
                return Result.fail(
                    ErrorCode.INVALID_ARGUMENT,
                    AMBIGUOUS_MESSAGE.format(event_id=event_id),
                )
            return Result.ok(_row_to_event(rows[0]))

        return self._run(operation)

    def list(self) -> Result[list[Event]]:
        """Return every cached event ordered by start time."""

        def operation(connection: sqlite3.Connection) -> Result[list[Event]]:
            rows = connection.execute(
                f"SELECT {_COLUMN_LIST} FROM events ORDER BY start_utc, calendar_id, id"
            ).fetchall()
            return Result.ok([_row_to_event(row) for row in rows])

        return self._run(operation)

    def update(self, event: Event) -> Result[Event]:
        """Replace the cached event with the same calendar and id."""

        def operation(connection: sqlite3.Connection) -> Result[Event]:
            cursor = connection.execute(
                _UPDATE,
                (*_event_values(event)[1:], event.calendar_id, event.id),
            )
            if cursor.rowcount == 0:
                return Result.fail(
                    ErrorCode.NOT_FOUND,
                    f"event {event.id!r} is not cached",
                )
            return Result.ok(event)

        return self._run(operation)

    def delete(self, event_id: str, calendar_id: str | None = None) -> Result[bool]:
        """Delete one cached event, rejecting an ambiguous bare id."""

        def operation(connection: sqlite3.Connection) -> Result[bool]:
            rows = _select_rows(connection, event_id, calendar_id)
            if not rows:
                return Result.fail(
                    ErrorCode.NOT_FOUND,
                    f"event {event_id!r} is not cached",
                )
            if len(rows) > 1:
                return Result.fail(
                    ErrorCode.INVALID_ARGUMENT,
                    AMBIGUOUS_MESSAGE.format(event_id=event_id),
                )
            connection.execute(
                "DELETE FROM events WHERE calendar_id = ? AND id = ?",
                (rows[0]["calendar_id"], event_id),
            )
            return Result.ok(True)

        return self._run(operation)

    def move(
        self,
        event_id: str,
        from_calendar_id: str,
        to_calendar_id: str,
    ) -> Result[bool]:
        """Point a cached event at the calendar Google moved it to.

        If the destination calendar already caches the same id, the source copy
        is dropped instead so the key stays unique.
        """

        def operation(connection: sqlite3.Connection) -> Result[bool]:
            try:
                cursor = connection.execute(
                    "UPDATE events SET calendar_id = ? "
                    "WHERE calendar_id = ? AND id = ?",
                    (to_calendar_id, from_calendar_id, event_id),
                )
            except sqlite3.IntegrityError:
                cursor = connection.execute(
                    "DELETE FROM events WHERE calendar_id = ? AND id = ?",
                    (from_calendar_id, event_id),
                )
            if cursor.rowcount == 0:
                return Result.fail(
                    ErrorCode.NOT_FOUND,
                    f"event {event_id!r} is not cached in {from_calendar_id!r}",
                )
            return Result.ok(True)

        return self._run(operation)

    def clear(self) -> Result[int]:
        """Delete every cached event and return how many were removed."""

        def operation(connection: sqlite3.Connection) -> Result[int]:
            cursor = connection.execute("DELETE FROM events")
            return Result.ok(cursor.rowcount)

        return self._run(operation)

    def replace_all(self, events: Iterable[Event]) -> Result[int]:
        """Replace the whole cache with ``events`` in one transaction.

        This is the entry point a full re-sync uses: the cache is disposable, so
        replacing it wholesale is safe and avoids trying to merge partial data.
        """
        cached_events = list(events)

        def operation(connection: sqlite3.Connection) -> Result[int]:
            connection.execute("DELETE FROM events")
            try:
                connection.executemany(
                    _INSERT,
                    [_event_values(event) for event in cached_events],
                )
            except sqlite3.IntegrityError:
                return Result.fail(
                    ErrorCode.ALREADY_EXISTS,
                    "events to cache contain duplicate ids",
                )
            return Result.ok(len(cached_events))

        return self._run(operation)


def _migrate(connection: sqlite3.Connection) -> None:
    """Rebuild a cache table that predates the (calendar_id, id) key.

    The cache is disposable and a re-sync refills it, so an old table is
    dropped and recreated instead of being converted in place.
    """
    key = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(events)")
        if row["pk"]
    }
    if key == {"calendar_id", "id"}:
        return
    connection.execute("DROP TABLE events")
    connection.executescript(_SCHEMA)


def _select_rows(
    connection: sqlite3.Connection,
    event_id: str,
    calendar_id: str | None,
) -> list[sqlite3.Row]:
    """Return the cached rows for an id, optionally within one calendar."""
    if calendar_id is None:
        return connection.execute(
            f"SELECT {_COLUMN_LIST} FROM events WHERE id = ?",
            (event_id,),
        ).fetchall()
    return connection.execute(
        f"SELECT {_COLUMN_LIST} FROM events WHERE calendar_id = ? AND id = ?",
        (calendar_id, event_id),
    ).fetchall()


def _event_values(event: Event) -> tuple[object, ...]:
    """Flatten an event into the cache column order."""
    return (
        event.id,
        event.calendar_id,
        event.recurring_event_id or "",
        int(event.all_day),
        event.summary,
        event.start.astimezone(UTC).isoformat(),
        event.start_timezone,
        event.end.astimezone(UTC).isoformat(),
        event.end_timezone,
        event.description,
        json.dumps(event.recurrence) if event.recurrence is not None else None,
        json.dumps(event.extended_properties, sort_keys=True),
        datetime.now(UTC).isoformat(),
    )


def _row_to_event(row: sqlite3.Row) -> Event:
    """Rebuild an event from a cache row, restoring its IANA zones."""
    start_timezone = row["start_timezone"]
    end_timezone = row["end_timezone"]
    start = datetime.fromisoformat(row["start_utc"]).astimezone(
        ZoneInfo(start_timezone)
    )
    end = datetime.fromisoformat(row["end_utc"]).astimezone(ZoneInfo(end_timezone))
    calendar_id = row["calendar_id"] if "calendar_id" in row.keys() else ""
    recurring_event_id = (
        row["recurring_event_id"] if "recurring_event_id" in row.keys() else ""
    )
    all_day = (
        row["all_day"] if "all_day" in row.keys() else "0"
    )
    return Event(
        id=row["id"],
        calendar_id=calendar_id,
        recurring_event_id=recurring_event_id or None,
        all_day=str(all_day).strip().lower() in {"1", "true", "yes"},
        summary=row["summary"],
        start=start,
        end=end,
        start_timezone=start_timezone,
        end_timezone=end_timezone,
        description=row["description"],
        recurrence=json.loads(row["recurrence"]) if row["recurrence"] else None,
        extended_properties=json.loads(row["extended_properties"]),
    )
