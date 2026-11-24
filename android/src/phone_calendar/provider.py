"""The shared :class:`~calendar_provider.CalendarProvider` over the phone's calendar.

Reads and writes go to Android's calendar store, which Android keeps in sync
with each account on the phone (Google, Exchange, local). Single events can be
created, changed, moved and deleted; occurrences of a repeating series are
read-only for now.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from core.errors import ErrorCode, Result
from domain.calendar import CalendarInfo
from domain.event import Event
from phone_calendar.store import (
    ACCESS_CONTRIBUTOR,
    AVAILABILITY_FREE,
    STATUS_CANCELED,
    UID_COLUMN,
    CalendarStore,
    Row,
)

logger = logging.getLogger(__name__)

# Default list window, matching the Android plan (FR-3).
DEFAULT_PAST = timedelta(days=30)
DEFAULT_FUTURE = timedelta(days=180)
# Android allows zero-length events; the shared model needs end > start.
MIN_DURATION = timedelta(minutes=1)
REPEATING_MESSAGE = (
    "repeating events can't be changed in Kivy Calendar yet; "
    "edit them in your phone's calendar app"
)


class AndroidCalendarProvider:
    """Read the phone's calendars and event occurrences.

    Occurrences of a recurring series get the id ``<event id>_<begin ms>`` and
    the series id in ``recurring_event_id``; single events keep their Android
    event id.
    """

    def __init__(self, store: CalendarStore, time_zone: str = "UTC") -> None:
        """Create the provider; ``time_zone`` is used for events without one."""
        self._store = store
        self._time_zone = time_zone if _is_zone(time_zone) else "UTC"

    def list_calendars(self) -> Result[list[CalendarInfo]]:
        """Return the visible calendars events can be written to."""
        rows = self._calendar_rows()
        if rows.error is not None or rows.value is None:
            return Result.fail(*_error(rows))
        calendars: list[CalendarInfo] = []
        for row in rows.value:
            info = _calendar_info(row)
            if info is not None and info.writable and _truthy(row.get("visible")):
                calendars.append(info)
        calendars.sort(key=lambda calendar: (not calendar.primary, calendar.summary))
        return Result.ok(calendars)

    def accounts(self) -> Result[list[tuple[str, str]]]:
        """Return the distinct ``(name, type)`` accounts that sync calendars.

        Local calendars (type ``LOCAL``) never sync and are left out.
        """
        rows = self._calendar_rows()
        if rows.error is not None or rows.value is None:
            return Result.fail(*_error(rows))
        found: dict[tuple[str, str], None] = {}
        for row in rows.value:
            name = row.get("account_name")
            kind = row.get("account_type")
            if isinstance(name, str) and isinstance(kind, str) and kind != "LOCAL":
                found[(name, kind)] = None
        return Result.ok(list(found))

    def list_events(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
    ) -> Result[list[Event]]:
        """Return occurrences in visible calendars overlapping the window."""
        now = datetime.now(UTC)
        start = time_min or now - DEFAULT_PAST
        end = time_max or now + DEFAULT_FUTURE
        if start.tzinfo is None or end.tzinfo is None:
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT, "window bounds must be timezone-aware"
            )
        calendar_rows = self._calendar_rows()
        if calendar_rows.error is not None or calendar_rows.value is None:
            return Result.fail(*_error(calendar_rows))
        calendars = {str(row.get("_id")): row for row in calendar_rows.value}
        try:
            rows = self._store.instances(_millis(start), _millis(end))
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        events: list[Event] = []
        for row in rows:
            calendar = calendars.get(str(row.get("calendar_id")))
            if calendar is not None and not _truthy(calendar.get("visible")):
                continue
            if row.get("eventStatus") == STATUS_CANCELED:
                continue
            event = self._event(row, calendar)
            if event is not None:
                events.append(event)
        events.sort(key=lambda event: (event.start, event.id))
        return Result.ok(events)

    def unsynced_event_ids(self) -> Result[set[str]]:
        """Return ids of events changed on the phone that no account has yet.

        The ids are Android event ids, which is ``Event.id`` of a single event
        and ``Event.recurring_event_id`` of an occurrence of a series.
        """
        try:
            return Result.ok(
                {str(event_id) for event_id in self._store.dirty_event_ids()}
            )
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)

    def get_event(self, calendar_id: str, event_id: str) -> Result[Event | None]:
        """Return a listed occurrence by id, or ``None`` when it is not listed."""
        listed = self.list_events()
        if listed.error is not None or listed.value is None:
            return Result.fail(*_error(listed))
        for event in listed.value:
            if event.id == event_id and (
                not calendar_id or event.calendar_id == calendar_id
            ):
                return Result.ok(event)
        return Result.ok(None)

    def create_event(self, event: Event) -> Result[Event]:
        """Save a new event; the returned copy carries Android's event id.

        ``event.id`` is the app's own id. It is stored in ``uid2445``, so
        saving the same new event again updates it instead of adding a second
        copy. A blank ``calendar_id`` means the primary writable calendar.
        """
        if event.recurring_event_id:
            return Result.fail(ErrorCode.INVALID_STATE, REPEATING_MESSAGE)
        calendar = self._writable_calendar(event.calendar_id)
        if calendar.error is not None or calendar.value is None:
            return Result.fail(*_error(calendar))
        values = _event_values(event)
        values["calendar_id"] = int(calendar.value)
        try:
            existing = self._store.find_event_by_uid(event.id)
            if existing is not None:
                android_id = int(existing["_id"])
                self._store.update_event(android_id, values)
            else:
                values[UID_COLUMN] = event.id
                android_id = self._store.insert_event(values)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        return Result.ok(
            event.model_copy(
                update={"id": str(android_id), "calendar_id": calendar.value}
            )
        )

    def update_event(self, event: Event) -> Result[Event]:
        """Change a single event in place; its calendar stays the same.

        Moving to another calendar is :meth:`move_event`.
        """
        android_id = _android_id(event.id)
        if android_id is None or event.recurring_event_id:
            return Result.fail(ErrorCode.INVALID_STATE, REPEATING_MESSAGE)
        try:
            changed = self._store.update_event(android_id, _event_values(event))
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        if changed == 0:
            return Result.fail(ErrorCode.NOT_FOUND, f"event {event.id} not found")
        return Result.ok(event)

    def move_event(
        self,
        calendar_id: str,
        event_id: str,
        destination_calendar_id: str,
    ) -> Result[Event]:
        """Copy the event into another calendar, then delete the original.

        Android ties an event to its calendar's account, so moving is a copy
        and a delete. If the delete fails the copy is removed again.
        """
        android_id = _android_id(event_id)
        if android_id is None:
            return Result.fail(ErrorCode.INVALID_STATE, REPEATING_MESSAGE)
        destination = self._writable_calendar(destination_calendar_id)
        if destination.error is not None or destination.value is None:
            return Result.fail(*_error(destination))
        try:
            row = self._store.event(android_id)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        if row is None:
            return Result.fail(ErrorCode.NOT_FOUND, f"event {event_id} not found")
        if row.get("rrule") or row.get("original_id") is not None:
            return Result.fail(ErrorCode.INVALID_STATE, REPEATING_MESSAGE)
        if str(row.get("calendar_id")) == destination.value:
            current = self._event(_instance_like(row), None)
            if current is None:
                return Result.fail(ErrorCode.UPSTREAM_ERROR, "event cannot be read")
            return Result.ok(current)
        original = self._event(_instance_like(row), None)
        if original is None:
            return Result.fail(ErrorCode.UPSTREAM_ERROR, "event cannot be read")
        values = _event_values(original)
        values["calendar_id"] = int(destination.value)
        values[UID_COLUMN] = row.get(UID_COLUMN)
        try:
            new_id = self._store.insert_event(values)
            if self._store.delete_event(android_id) == 0:
                self._store.delete_event(new_id)
                return Result.fail(
                    ErrorCode.UPSTREAM_ERROR,
                    "the original event could not be removed; nothing was moved",
                )
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        return Result.ok(
            original.model_copy(
                update={"id": str(new_id), "calendar_id": destination.value}
            )
        )

    def delete_event(self, calendar_id: str, event_id: str) -> Result[None]:
        """Delete a single event."""
        android_id = _android_id(event_id)
        if android_id is None:
            return Result.fail(ErrorCode.INVALID_STATE, REPEATING_MESSAGE)
        try:
            deleted = self._store.delete_event(android_id)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        if deleted == 0:
            return Result.fail(ErrorCode.NOT_FOUND, f"event {event_id} not found")
        return Result.ok(None)

    def _writable_calendar(self, calendar_id: str) -> Result[str]:
        """Return ``calendar_id`` if events can be saved there.

        A blank id picks the primary writable calendar (or the first one).
        """
        calendars = self.list_calendars()
        if calendars.error is not None or calendars.value is None:
            return Result.fail(*_error(calendars))
        if not calendar_id:
            if not calendars.value:
                return Result.fail(
                    ErrorCode.INVALID_STATE,
                    "this phone has no calendar that accepts new events",
                )
            return Result.ok(calendars.value[0].id)
        if any(calendar.id == calendar_id for calendar in calendars.value):
            return Result.ok(calendar_id)
        return Result.fail(
            ErrorCode.INVALID_ARGUMENT,
            "events can't be saved to that calendar; choose another one",
        )

    def _calendar_rows(self) -> Result[list[Row]]:
        """Read the calendar table, turning store failures into results."""
        try:
            return Result.ok(self._store.calendars())
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)

    def _event(self, row: Row, calendar: Row | None) -> Event | None:
        """Map one occurrence row to an event; skip rows that cannot map."""
        try:
            begin = int(row["begin"])
            finish = int(row["end"])
        except KeyError, TypeError, ValueError:
            logger.warning("skipping occurrence without begin/end: %r", row)
            return None
        all_day = _truthy(row.get("allDay"))
        start_zone = _zone_name(row.get("eventTimezone"), self._time_zone)
        end_zone = _zone_name(row.get("eventEndTimezone"), start_zone)
        if all_day:
            start = _midnight(_utc_date(begin), start_zone)
            end = _midnight(_utc_date(finish), end_zone)
            if end <= start:
                end = start + timedelta(days=1)
        else:
            start = _from_millis(begin).astimezone(ZoneInfo(start_zone))
            end = _from_millis(finish).astimezone(ZoneInfo(end_zone))
            if end <= start:
                end = start + MIN_DURATION
        event_id = str(row.get("event_id") or "")
        if not event_id:
            return None
        rrule = row.get("rrule")
        original_id = row.get("original_id")
        recurring = bool(rrule) or original_id is not None
        series_id = str(original_id) if original_id is not None else event_id
        try:
            return Event(
                id=f"{event_id}_{begin}" if recurring else event_id,
                calendar_id=str(row.get("calendar_id") or ""),
                recurring_event_id=series_id if recurring else None,
                all_day=all_day,
                start=start,
                end=end,
                start_timezone=start_zone,
                end_timezone=end_zone,
                summary=str(row.get("title") or ""),
                description=str(row["description"]) if row.get("description") else None,
                recurrence=[f"RRULE:{rrule}"] if rrule else None,
                transparent=row.get("availability") == AVAILABILITY_FREE,
                calendar_read_only=calendar is not None and not _writable(calendar),
            )
        except ValidationError as error:
            logger.warning("skipping occurrence %s: %s", event_id, error)
            return None


def _event_values(event: Event) -> Row:
    """``Events`` columns for a single event (without calendar and uid).

    Android stores all-day events as UTC midnights in the ``UTC`` zone, with
    an exclusive end date.
    """
    if event.all_day:
        first = event.start.date()
        after = max(event.end.date(), first + timedelta(days=1))
        start_ms = _millis(_midnight(first, "UTC"))
        end_ms = _millis(_midnight(after, "UTC"))
        start_zone = end_zone = "UTC"
    else:
        start_ms = _millis(event.start)
        end_ms = _millis(event.end)
        start_zone = event.start_timezone
        end_zone = event.end_timezone
    return {
        "title": event.summary,
        "description": event.description,
        "dtstart": start_ms,
        "dtend": end_ms,
        "allDay": 1 if event.all_day else 0,
        "eventTimezone": start_zone,
        "eventEndTimezone": end_zone,
    }


def _instance_like(row: Row) -> Row:
    """Shape an ``Events`` row like an ``Instances`` row for mapping."""
    return {
        **row,
        "event_id": row.get("_id"),
        "begin": row.get("dtstart"),
        "end": row.get("dtend"),
    }


def _android_id(event_id: str) -> int | None:
    """Android's numeric id of a single event; ``None`` for occurrences."""
    return int(event_id) if event_id.isdigit() else None


def _calendar_info(row: Row) -> CalendarInfo | None:
    """Map one calendar row, or ``None`` when it has no id or name."""
    calendar_id = str(row.get("_id") or "").strip()
    name = str(row.get("calendar_displayName") or row.get("account_name") or "")
    if not calendar_id or not name.strip():
        return None
    return CalendarInfo(
        id=calendar_id,
        summary=name,
        primary=_truthy(row.get("isPrimary")),
        writable=_writable(row),
    )


def _writable(row: Row) -> bool:
    """Whether the calendar's access level allows writing events."""
    try:
        return int(row.get("calendar_access_level") or 0) >= ACCESS_CONTRIBUTOR
    except TypeError, ValueError:
        return False


def _truthy(value: object) -> bool:
    """Android stores booleans as 0/1 integers (sometimes as strings)."""
    if isinstance(value, str):
        return value.strip() not in ("", "0")
    return bool(value)


def _is_zone(name: object) -> bool:
    """Whether ``name`` is a known IANA zone."""
    if not isinstance(name, str) or not name.strip():
        return False
    try:
        ZoneInfo(name)
    except ValueError, ZoneInfoNotFoundError:
        return False
    return True


def _zone_name(value: object, fallback: str) -> str:
    """Return ``value`` when it is an IANA zone, else ``fallback``."""
    return str(value) if _is_zone(value) else fallback


def _millis(value: datetime) -> int:
    """Milliseconds since the epoch for an aware datetime."""
    return int(value.timestamp() * 1000)


def _from_millis(value: int) -> datetime:
    """Aware UTC datetime for milliseconds since the epoch."""
    return datetime.fromtimestamp(value / 1000, UTC)


def _utc_date(value: int) -> date:
    """All-day events are stored as UTC midnights; return that date."""
    return _from_millis(value).date()


def _midnight(day: date, zone: str) -> datetime:
    """Midnight of ``day`` in ``zone``."""
    return datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(zone))


def _store_failure[T](error: Exception) -> Result[T]:
    """Turn a store exception into a result; missing permission is its own code."""
    message = str(error)
    if "SecurityException" in message or "Permission" in message:
        return Result.fail(
            ErrorCode.PERMISSION_DENIED, "calendar permission is not granted"
        )
    return Result.fail(
        ErrorCode.UPSTREAM_ERROR, f"reading the phone calendar failed: {message}"
    )


def _error[T](result: Result[T]) -> tuple[ErrorCode, str]:
    """The code and message of a failed result."""
    if result.error is None:
        return ErrorCode.UPSTREAM_ERROR, "unknown error"
    return result.error.code, result.error.message
