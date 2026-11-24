"""The shared :class:`~calendar_provider.CalendarProvider` over the phone's calendar.

Reads come from Android's calendar store, which Android keeps in sync with
each account on the phone (Google, Exchange, local). Writing arrives in 0.3.0;
until then every write returns an ``INVALID_STATE`` result.
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
    CalendarStore,
    Row,
)

logger = logging.getLogger(__name__)

# Default list window, matching the Android plan (FR-3).
DEFAULT_PAST = timedelta(days=30)
DEFAULT_FUTURE = timedelta(days=180)
# Android allows zero-length events; the shared model needs end > start.
MIN_DURATION = timedelta(minutes=1)
READ_ONLY_MESSAGE = (
    "saving to the phone calendar is not available yet; it arrives in 0.3.0"
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
        """Not available yet (0.3.0)."""
        return Result.fail(ErrorCode.INVALID_STATE, READ_ONLY_MESSAGE)

    def update_event(self, event: Event) -> Result[Event]:
        """Not available yet (0.3.0)."""
        return Result.fail(ErrorCode.INVALID_STATE, READ_ONLY_MESSAGE)

    def move_event(
        self,
        calendar_id: str,
        event_id: str,
        destination_calendar_id: str,
    ) -> Result[Event]:
        """Not available yet (0.3.0)."""
        return Result.fail(ErrorCode.INVALID_STATE, READ_ONLY_MESSAGE)

    def delete_event(self, calendar_id: str, event_id: str) -> Result[None]:
        """Not available yet (0.3.0)."""
        return Result.fail(ErrorCode.INVALID_STATE, READ_ONLY_MESSAGE)

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
