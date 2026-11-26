"""Read and write rows in Android's calendar store (``CalendarContract``).

:class:`CalendarStore` is the narrow seam between the provider and Android:
it returns plain rows (dicts keyed by the ``CalendarContract`` column names),
so the provider's mapping is tested on desktop with a fake store, and only
:class:`JniCalendarStore` talks to Android through pyjnius.
"""

from __future__ import annotations

from typing import Any, Protocol

Row = dict[str, Any]

# CalendarContract.Calendars columns (public constants, stable since API 14).
CALENDAR_COLUMNS = (
    "_id",
    "calendar_displayName",
    "account_name",
    "account_type",
    "calendar_access_level",
    "visible",
    "isPrimary",
    "calendar_color",
)

# CalendarContract.Instances columns: one row per occurrence, recurring
# series already expanded by Android.
INSTANCE_COLUMNS = (
    "event_id",
    "begin",
    "end",
    "title",
    "description",
    "allDay",
    "eventTimezone",
    "eventEndTimezone",
    "calendar_id",
    "rrule",
    "original_id",
    "originalInstanceTime",
    "availability",
    "eventStatus",
)

# CalendarContract.Events columns the app reads back after a write, and the
# column that keeps the app's own event id (RFC 5545 UID) for duplicate checks.
EVENT_COLUMNS = (
    "_id",
    "calendar_id",
    "title",
    "description",
    "dtstart",
    "dtend",
    "allDay",
    "eventTimezone",
    "eventEndTimezone",
    "duration",
    "rrule",
    "rdate",
    "exrule",
    "exdate",
    "lastDate",
    "original_id",
    "originalInstanceTime",
    "_sync_id",
    "availability",
    "eventStatus",
    "uid2445",
)
UID_COLUMN = "uid2445"
# The columns Android reads to expand a repeating event. An update that sets
# any of them must set all of them: without ``rrule`` in the same update,
# Android re-expands the series as a single event (seen on Android 16).
SERIES_COLUMNS = (
    "dtstart",
    "duration",
    "allDay",
    "eventTimezone",
    "rrule",
    "rdate",
    "exrule",
    "exdate",
)

# Events columns read to find changes the account has not received yet.
DIRTY_COLUMNS = ("_id", "calendar_id", "dirty")

# Values from CalendarContract.
ACCESS_CONTRIBUTOR = 500  # Calendars.CAL_ACCESS_CONTRIBUTOR: can write events
AVAILABILITY_FREE = 1  # Events.AVAILABILITY_FREE: shown as "free"
STATUS_CANCELED = 2  # Events.STATUS_CANCELED
ACCOUNT_TYPE_LOCAL = "LOCAL"  # CalendarContract.ACCOUNT_TYPE_LOCAL: never synced


def syncing_calendar_ids(calendar_rows: list[Row]) -> set[str]:
    """Ids (as text) of the calendars an account syncs, i.e. not ``LOCAL`` ones."""
    return {
        str(row.get("_id"))
        for row in calendar_rows
        if row.get("account_type") != ACCOUNT_TYPE_LOCAL
    }


class CalendarStore(Protocol):
    """Access to the phone's calendars, event occurrences and events."""

    def calendars(self) -> list[Row]:
        """Return every calendar row (``CALENDAR_COLUMNS``)."""
        ...

    def instances(self, begin_ms: int, end_ms: int) -> list[Row]:
        """Return occurrence rows (``INSTANCE_COLUMNS``) overlapping the window.

        ``begin_ms`` and ``end_ms`` are milliseconds since the Unix epoch.
        """
        ...

    def event(self, event_id: int) -> Row | None:
        """Return one ``Events`` row (``EVENT_COLUMNS``), or ``None``."""
        ...

    def find_event_by_uid(self, uid: str) -> Row | None:
        """Return the ``Events`` row whose ``uid2445`` is ``uid``, or ``None``."""
        ...

    def dirty_event_ids(self) -> set[int]:
        """Return ids of events changed on the phone and not yet synced.

        These are ``Events`` rows with ``dirty = 1`` in calendars whose account
        syncs; ``LOCAL`` calendars never sync, so their events are left out.
        """
        ...

    def insert_event(self, values: Row) -> int:
        """Insert an ``Events`` row and return its new ``_id``."""
        ...

    def update_event(self, event_id: int, values: Row) -> int:
        """Change columns of one event; return the number of rows changed."""
        ...

    def insert_exception(self, series_id: int, values: Row) -> int:
        """Change or cancel one occurrence of a series; return the new row's id.

        ``values`` needs ``originalInstanceTime``. Android copies the rest from
        the series and refuses ``dtend`` (give ``duration``). It matches the
        exception to its series by sync id, so a series that has not synced
        yet loses all its occurrences; callers use ``exdate`` there instead.
        """
        ...

    def exceptions(self, series_id: int) -> list[Row]:
        """Return the changed and cancelled occurrences of a series."""
        ...

    def delete_event(self, event_id: int) -> int:
        """Delete one event; return the number of rows deleted."""
        ...


class JniCalendarStore:
    """:class:`CalendarStore` backed by Android's ``ContentResolver``.

    Only importable on Android (it needs pyjnius). Queries raise pyjnius'
    ``JavaException`` on failure, e.g. a ``SecurityException`` when calendar
    permission is missing; the provider turns those into error results.
    """

    def __init__(self) -> None:
        """Look up the Android classes once."""
        from jnius import autoclass  # type: ignore[import-not-found]

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        self._resolver = activity.getContentResolver()
        self._calendars_uri = autoclass(
            "android.provider.CalendarContract$Calendars"
        ).CONTENT_URI
        self._instances_uri = autoclass(
            "android.provider.CalendarContract$Instances"
        ).CONTENT_URI
        events = autoclass("android.provider.CalendarContract$Events")
        self._events_uri = events.CONTENT_URI
        self._exception_uri = events.CONTENT_EXCEPTION_URI
        self._content_uris = autoclass("android.content.ContentUris")
        self._content_values = autoclass("android.content.ContentValues")
        self._long = autoclass("java.lang.Long")

    def calendars(self) -> list[Row]:
        """Return every calendar row."""
        return self._query(self._calendars_uri, CALENDAR_COLUMNS)

    def instances(self, begin_ms: int, end_ms: int) -> list[Row]:
        """Return occurrence rows overlapping ``[begin_ms, end_ms)``."""
        builder = self._instances_uri.buildUpon()
        self._content_uris.appendId(builder, begin_ms)
        self._content_uris.appendId(builder, end_ms)
        return self._query(builder.build(), INSTANCE_COLUMNS, order="begin ASC")

    def event(self, event_id: int) -> Row | None:
        """Return one event row by id."""
        rows = self._query(self._event_uri(event_id), EVENT_COLUMNS)
        return rows[0] if rows else None

    def find_event_by_uid(self, uid: str) -> Row | None:
        """Return the event whose uid2445 matches ``uid``."""
        rows = self._query(self._events_uri, EVENT_COLUMNS, f"{UID_COLUMN} = ?", [uid])
        return rows[0] if rows else None

    def dirty_event_ids(self) -> set[int]:
        """Return ids of dirty events in calendars that sync."""
        syncing = syncing_calendar_ids(self.calendars())
        rows = self._query(self._events_uri, DIRTY_COLUMNS, "dirty = 1")
        return {
            int(row["_id"])
            for row in rows
            if row.get("_id") is not None and str(row.get("calendar_id")) in syncing
        }

    def insert_event(self, values: Row) -> int:
        """Insert an event and return its id."""
        uri = self._resolver.insert(self._events_uri, self._values(values))
        if uri is None:
            raise RuntimeError("the calendar provider did not insert the event")
        return int(self._content_uris.parseId(uri))

    def update_event(self, event_id: int, values: Row) -> int:
        """Change columns of one event."""
        return int(
            self._resolver.update(
                self._event_uri(event_id), self._values(values), None, None
            )
        )

    def delete_event(self, event_id: int) -> int:
        """Delete one event."""
        return int(self._resolver.delete(self._event_uri(event_id), None, None))

    def insert_exception(self, series_id: int, values: Row) -> int:
        """Insert an exception to one occurrence of a series."""
        uri = self._resolver.insert(
            self._content_uris.withAppendedId(self._exception_uri, series_id),
            self._values(values),
        )
        if uri is None:
            raise RuntimeError("the calendar provider did not change the occurrence")
        return int(self._content_uris.parseId(uri))

    def exceptions(self, series_id: int) -> list[Row]:
        """Return the exception rows of a series."""
        return self._query(
            self._events_uri, EVENT_COLUMNS, "original_id = ?", [str(series_id)]
        )

    def _event_uri(self, event_id: int) -> Any:
        """The content URI of one event."""
        return self._content_uris.withAppendedId(self._events_uri, event_id)

    def _values(self, values: Row) -> Any:
        """Build ``ContentValues``; ints are boxed as Long, None is NULL."""
        content = self._content_values()
        for key, value in values.items():
            if value is None:
                content.putNull(key)
            elif isinstance(value, bool):
                content.put(key, self._long(int(value)))
            elif isinstance(value, int):
                content.put(key, self._long(value))
            else:
                content.put(key, str(value))
        return content

    def _query(
        self,
        uri: Any,
        columns: tuple[str, ...],
        selection: str | None = None,
        args: list[str] | None = None,
        order: str | None = None,
    ) -> list[Row]:
        """Run a query and read every row into a dict."""
        cursor = self._resolver.query(uri, list(columns), selection, args, order)
        if cursor is None:
            return []
        try:
            return read_rows(cursor, columns)
        finally:
            cursor.close()


# Columns that hold integers. Every other column is read as text.
INTEGER_COLUMNS = frozenset(
    {
        "_id",
        "event_id",
        "calendar_id",
        "original_id",
        "originalInstanceTime",
        "lastDate",
        "begin",
        "end",
        "dtstart",
        "dtend",
        "allDay",
        "availability",
        "eventStatus",
        "dirty",
        "calendar_access_level",
        "visible",
        "isPrimary",
        "calendar_color",
    }
)


def read_rows(cursor: Any, columns: tuple[str, ...]) -> list[Row]:
    """Read every remaining row of ``cursor`` into dicts keyed by column name.

    Each pyjnius call is a slow round trip (about 0.1 ms on a phone), and a
    1,000-event list has 14,000 cells. So every cell is read with one
    ``getString`` call: ``None`` for NULL, and integer columns
    (``INTEGER_COLUMNS``) are converted in Python. Asking ``getType`` first
    would double the calls. Columns the cursor does not have read as ``None``.
    """
    get_string = cursor.getString
    move_to_next = cursor.moveToNext
    cells = [
        (name, cursor.getColumnIndex(name), name in INTEGER_COLUMNS) for name in columns
    ]
    rows: list[Row] = []
    while move_to_next():
        row: Row = {}
        for name, index, integer in cells:
            if index < 0:
                row[name] = None
                continue
            text = get_string(index)
            row[name] = _number(text) if integer and text is not None else text
        rows.append(row)
    return rows


def _number(text: str) -> int | float | str:
    """An integer column's text as a number; anything else stays text."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return str(text)
