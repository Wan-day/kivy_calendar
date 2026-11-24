"""Read rows from Android's calendar store (``CalendarContract``).

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
    "_id",
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
    "availability",
    "eventStatus",
)

# Values from CalendarContract.
ACCESS_CONTRIBUTOR = 500  # Calendars.CAL_ACCESS_CONTRIBUTOR: can write events
AVAILABILITY_FREE = 1  # Events.AVAILABILITY_FREE: shown as "free"
STATUS_CANCELED = 2  # Events.STATUS_CANCELED


class CalendarStore(Protocol):
    """Read access to the phone's calendars and event occurrences."""

    def calendars(self) -> list[Row]:
        """Return every calendar row (``CALENDAR_COLUMNS``)."""
        ...

    def instances(self, begin_ms: int, end_ms: int) -> list[Row]:
        """Return occurrence rows (``INSTANCE_COLUMNS``) overlapping the window.

        ``begin_ms`` and ``end_ms`` are milliseconds since the Unix epoch.
        """
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
        self._content_uris = autoclass("android.content.ContentUris")

    def calendars(self) -> list[Row]:
        """Return every calendar row."""
        return self._query(self._calendars_uri, CALENDAR_COLUMNS)

    def instances(self, begin_ms: int, end_ms: int) -> list[Row]:
        """Return occurrence rows overlapping ``[begin_ms, end_ms)``."""
        builder = self._instances_uri.buildUpon()
        self._content_uris.appendId(builder, begin_ms)
        self._content_uris.appendId(builder, end_ms)
        return self._query(builder.build(), INSTANCE_COLUMNS, order="begin ASC")

    def _query(
        self,
        uri: Any,
        columns: tuple[str, ...],
        order: str | None = None,
    ) -> list[Row]:
        """Run a query and read every row into a dict."""
        cursor = self._resolver.query(uri, list(columns), None, None, order)
        if cursor is None:
            return []
        rows: list[Row] = []
        try:
            indexes = {name: cursor.getColumnIndex(name) for name in columns}
            while cursor.moveToNext():
                rows.append(
                    {name: _read(cursor, index) for name, index in indexes.items()}
                )
        finally:
            cursor.close()
        return rows


# android.database.Cursor field types.
_FIELD_TYPE_NULL = 0
_FIELD_TYPE_INTEGER = 1
_FIELD_TYPE_FLOAT = 2


def _read(cursor: Any, index: int) -> Any:
    """Read one cell as a Python value; missing columns read as ``None``."""
    if index < 0:
        return None
    kind = cursor.getType(index)
    if kind == _FIELD_TYPE_NULL:
        return None
    if kind == _FIELD_TYPE_INTEGER:
        return int(cursor.getLong(index))
    if kind == _FIELD_TYPE_FLOAT:
        return float(cursor.getDouble(index))
    return str(cursor.getString(index))
