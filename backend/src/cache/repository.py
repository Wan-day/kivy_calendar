"""SQLite-backed cache of calendar events.

The cache is disposable: Google Calendar is the source of truth, so this module
only stores a copy that can be rebuilt by deleting the database and syncing
again.  It never stores credentials or the only copy of an event.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from core.errors import ErrorCode, Result
from core.sqlite import Database, run_in_transaction
from domain.event import Event

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY NOT NULL,
    summary TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    start_timezone TEXT NOT NULL,
    end_utc TEXT NOT NULL,
    end_timezone TEXT NOT NULL,
    description TEXT,
    recurrence TEXT,
    extended_properties TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_start_utc ON events (start_utc);
"""

_COLUMNS = (
    "id",
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
SET summary = ?,
    start_utc = ?,
    start_timezone = ?,
    end_utc = ?,
    end_timezone = ?,
    description = ?,
    recurrence = ?,
    extended_properties = ?,
    cached_at = ?
WHERE id = ?
"""


class EventRepository:
    """Create, read, update, and delete events in the disposable cache."""

    def __init__(self, database: Database | None = None) -> None:
        self._database = database if database is not None else Database()

    @property
    def database(self) -> Database:
        """The database this repository writes to."""
        return self._database

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

        return run_in_transaction(self._database, _SCHEMA, operation)

    def get(self, event_id: str) -> Result[Event]:
        """Return the cached event with ``event_id``."""

        def operation(connection: sqlite3.Connection) -> Result[Event]:
            row = connection.execute(
                f"SELECT {_COLUMN_LIST} FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                return Result.fail(
                    ErrorCode.NOT_FOUND,
                    f"event {event_id!r} is not cached",
                )
            return Result.ok(_row_to_event(row))

        return run_in_transaction(self._database, _SCHEMA, operation)

    def list(self) -> Result[list[Event]]:
        """Return every cached event ordered by start time."""

        def operation(connection: sqlite3.Connection) -> Result[list[Event]]:
            rows = connection.execute(
                f"SELECT {_COLUMN_LIST} FROM events ORDER BY start_utc, id"
            ).fetchall()
            return Result.ok([_row_to_event(row) for row in rows])

        return run_in_transaction(self._database, _SCHEMA, operation)

    def update(self, event: Event) -> Result[Event]:
        """Replace the cached event that has the same id."""

        def operation(connection: sqlite3.Connection) -> Result[Event]:
            cursor = connection.execute(
                _UPDATE,
                (*_event_values(event)[1:], event.id),
            )
            if cursor.rowcount == 0:
                return Result.fail(
                    ErrorCode.NOT_FOUND,
                    f"event {event.id!r} is not cached",
                )
            return Result.ok(event)

        return run_in_transaction(self._database, _SCHEMA, operation)

    def delete(self, event_id: str) -> Result[bool]:
        """Delete one cached event."""

        def operation(connection: sqlite3.Connection) -> Result[bool]:
            cursor = connection.execute(
                "DELETE FROM events WHERE id = ?",
                (event_id,),
            )
            if cursor.rowcount == 0:
                return Result.fail(
                    ErrorCode.NOT_FOUND,
                    f"event {event_id!r} is not cached",
                )
            return Result.ok(True)

        return run_in_transaction(self._database, _SCHEMA, operation)

    def clear(self) -> Result[int]:
        """Delete every cached event and return how many were removed."""

        def operation(connection: sqlite3.Connection) -> Result[int]:
            cursor = connection.execute("DELETE FROM events")
            return Result.ok(cursor.rowcount)

        return run_in_transaction(self._database, _SCHEMA, operation)

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

        return run_in_transaction(self._database, _SCHEMA, operation)


def _event_values(event: Event) -> tuple[object, ...]:
    """Flatten an event into the cache column order."""
    return (
        event.id,
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
    return Event(
        id=row["id"],
        summary=row["summary"],
        start=start,
        end=end,
        start_timezone=start_timezone,
        end_timezone=end_timezone,
        description=row["description"],
        recurrence=json.loads(row["recurrence"]) if row["recurrence"] else None,
        extended_properties=json.loads(row["extended_properties"]),
    )
