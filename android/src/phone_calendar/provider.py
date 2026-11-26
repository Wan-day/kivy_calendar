"""The shared :class:`~calendar_provider.CalendarProvider` over the phone's calendar.

Reads and writes go to Android's calendar store, which Android keeps in sync
with each account on the phone (Google, Exchange, local). Single events can be
created, changed, moved and deleted. A repeating series is changed or
deleted for one occurrence, for an occurrence and the ones after it, or as a
whole.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from core.errors import ErrorCode, Result
from domain.calendar import CalendarInfo
from domain.event import Event
from domain.recurrence import rule_ending_before, rule_text
from phone_calendar.store import (
    ACCESS_CONTRIBUTOR,
    AVAILABILITY_FREE,
    SERIES_COLUMNS,
    STATUS_CANCELED,
    UID_COLUMN,
    CalendarStore,
    Row,
)

logger = logging.getLogger(__name__)

# Default list window: one year each way, so the week and month views reach
# back and ahead a year.
DEFAULT_PAST = timedelta(days=365)
DEFAULT_FUTURE = timedelta(days=365)
# Android allows zero-length events; the shared model needs end > start.
MIN_DURATION = timedelta(minutes=1)
REPEATING_MESSAGE = (
    "this is one occurrence of a repeating event; choose which occurrences "
    "to change"
)
SERIES_NOT_FOUND = "the repeating event this occurrence belongs to is gone"


@dataclass(frozen=True)
class _Occurrence:
    """Where one listed occurrence of a series lives in the Events table.

    ``row`` is the occurrence's own exception row, or ``None`` when the
    occurrence comes straight from the series' rule. ``instance`` is the
    occurrence's original start (Android's ``originalInstanceTime``) and
    ``begin`` its current start, both in milliseconds.
    """

    series: Row
    row: Row | None
    instance: int
    begin: int

    @property
    def series_id(self) -> int:
        """Android's id of the series."""
        return int(self.series["_id"])

    @property
    def first(self) -> bool:
        """Whether this is the series' first occurrence."""
        return self.instance == int(self.series["dtstart"])


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
        rules = {
            str(row.get("event_id")): row["rrule"] for row in rows if row.get("rrule")
        }
        events: list[Event] = []
        for row in rows:
            calendar = calendars.get(str(row.get("calendar_id")))
            if calendar is not None and not _truthy(calendar.get("visible")):
                continue
            if row.get("eventStatus") == STATUS_CANCELED:
                continue
            if row.get("original_id") is not None and not row.get("rrule"):
                row = {**row, "rrule": self._series_rule(row["original_id"], rules)}
            event = self._event(row, calendar)
            if event is not None:
                events.append(event)
        events.sort(key=lambda event: (event.start, event.id))
        return Result.ok(events)

    def _series_rule(self, series_id: object, rules: dict[str, str]) -> str | None:
        """The rule of the series a changed occurrence belongs to.

        The form shows it, so "this and following" and "all events" start
        from the series' rule. Series outside the window are read once.
        """
        key = str(series_id)
        if key not in rules:
            try:
                row = self._store.event(int(key))
            except Exception:  # noqa: BLE001 - JNI raises JavaException
                logger.warning("could not read series %s", key, exc_info=True)
                row = None
            rules[key] = str(row.get("rrule") or "") if row is not None else ""
        return rules[key] or None

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
        values = _values_for(event)
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
            _saved(event.model_copy(update={"calendar_id": calendar.value}), android_id)
        )

    def update_event(self, event: Event) -> Result[Event]:
        """Change a single event in place; its calendar stays the same.

        A repeat rule in ``event.recurrence`` turns it into a series. Moving
        to another calendar is :meth:`move_event`; occurrences of a series
        are changed with :meth:`update_occurrence`, :meth:`update_following`
        and :meth:`update_series`.
        """
        android_id = _android_id(event.id)
        if android_id is None or event.recurring_event_id:
            return Result.fail(ErrorCode.INVALID_STATE, REPEATING_MESSAGE)
        try:
            changed = self._store.update_event(android_id, _values_for(event))
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        if changed == 0:
            return Result.fail(ErrorCode.NOT_FOUND, f"event {event.id} not found")
        return Result.ok(_saved(event, android_id))

    def update_occurrence(self, event: Event) -> Result[Event]:
        """Change only this occurrence of a series ("this event").

        A synced series gets an exception. A series that has not synced yet
        cannot hold exceptions (Android would drop its other occurrences), so
        the occurrence is left out with ``exdate`` and saved as its own event.
        """
        found = self._occurrence(event.id)
        if found.error is not None or found.value is None:
            return Result.fail(*_error(found))
        occurrence = found.value
        try:
            if occurrence.row is not None:
                row_id = int(occurrence.row["_id"])
                self._store.update_event(row_id, _event_values(event))
                return Result.ok(_saved(event, row_id, series=occurrence.series_id))
            if occurrence.series.get("_sync_id"):
                values = _exception_values(event)
                values["originalInstanceTime"] = occurrence.instance
                row_id = self._store.insert_exception(occurrence.series_id, values)
                return Result.ok(_saved(event, row_id, series=occurrence.series_id))
            return self._split_off(event, occurrence)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)

    def _split_off(self, event: Event, occurrence: _Occurrence) -> Result[Event]:
        """Save an occurrence of an unsynced series as its own event.

        The new event is written first and removed again if the series cannot
        leave the occurrence out. Its uid ties it to the occurrence, so a
        repeated save finds it instead of adding a second copy.
        """
        uid = f"{_series_uid(occurrence.series)}_{occurrence.instance}"
        values = _event_values(event)
        values["calendar_id"] = occurrence.series.get("calendar_id")
        existing = self._store.find_event_by_uid(uid)
        if existing is not None:
            new_id = int(existing["_id"])
            self._store.update_event(new_id, values)
        else:
            values[UID_COLUMN] = uid
            new_id = self._store.insert_event(values)
        if not self._exclude(occurrence):
            self._store.delete_event(new_id)
            return Result.fail(ErrorCode.NOT_FOUND, SERIES_NOT_FOUND)
        single = event.model_copy(
            update={"recurring_event_id": None, "recurrence": None}
        )
        return Result.ok(_saved(single, new_id))

    def update_following(self, event: Event, calendar_id: str = "") -> Result[Event]:
        """Change this occurrence and the ones after it.

        The series ends before this occurrence and a new series with the
        form's values starts here, in ``calendar_id`` (default: the series'
        calendar). Changes to later occurrences of the old series are dropped.
        From the first occurrence this is :meth:`update_series`.
        """
        found = self._occurrence(event.id)
        if found.error is not None or found.value is None:
            return Result.fail(*_error(found))
        occurrence = found.value
        if occurrence.first:
            return self.update_series(event)
        series = occurrence.series
        if calendar_id:
            destination = self._writable_calendar(calendar_id)
            if destination.error is not None or destination.value is None:
                return Result.fail(*_error(destination))
            target = int(destination.value)
        else:
            target = int(series["calendar_id"])
        new_event = event.model_copy(
            update={"recurrence": _following_rule(event, series)}
        )
        values = _values_for(new_event)
        values["calendar_id"] = target
        uid = f"{_series_uid(series)}_{occurrence.instance}"
        try:
            existing = self._store.find_event_by_uid(uid)
            if existing is not None:
                new_id = int(existing["_id"])
                self._store.update_event(new_id, values)
            else:
                values[UID_COLUMN] = uid
                new_id = self._store.insert_event(values)
            if not self._end_before(occurrence):
                self._store.delete_event(new_id)
                return Result.fail(ErrorCode.NOT_FOUND, SERIES_NOT_FOUND)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        if new_event.recurrence is None:
            single = new_event.model_copy(update={"recurring_event_id": None})
            return Result.ok(_saved(single, new_id, calendar=str(target)))
        return Result.ok(_saved(new_event, new_id, calendar=str(target)))

    def update_series(self, event: Event) -> Result[Event]:
        """Change every occurrence of the series ("all events").

        The series' first start moves by as much as this occurrence moved, and
        every occurrence gets this one's length. When the start moves, the
        changed and left-out occurrences no longer line up and are dropped.
        Without a repeat rule the series becomes this single event.
        """
        found = self._occurrence(event.id)
        if found.error is not None or found.value is None:
            return Result.fail(*_error(found))
        occurrence = found.value
        series = occurrence.series
        series_id = occurrence.series_id
        try:
            if rule_text(event.recurrence) is None:
                values = {**_cleared_series(), **_event_values(event)}
                self._store.update_event(series_id, values)
                self._drop_exceptions(series_id)
                single = event.model_copy(update={"recurring_event_id": None})
                return Result.ok(_saved(single, series_id))
            start = _shifted_start(series, occurrence.begin, event)
            moved = event.model_copy(
                update={"start": start, "end": start + (event.end - event.start)}
            )
            values = {**_series_columns(series), **_values_for(moved)}
            shifted = values["dtstart"] != series.get("dtstart")
            if shifted:
                values["exdate"] = None
            self._store.update_event(series_id, values)
            if shifted:
                self._drop_exceptions(series_id)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        begin = occurrence.begin + int(values["dtstart"]) - int(series["dtstart"])
        return Result.ok(
            event.model_copy(
                update={
                    "id": f"{series_id}_{begin}",
                    "recurring_event_id": str(series_id),
                }
            )
        )

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
        if row.get("original_id") is not None:
            return Result.fail(ErrorCode.INVALID_STATE, REPEATING_MESSAGE)
        if row.get("rrule"):
            return self._move_series(row, destination.value)
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

    def move_series(self, event_id: str, destination_calendar_id: str) -> Result[Event]:
        """Move the series an occurrence belongs to into another calendar."""
        found = self._occurrence(event_id)
        if found.error is not None or found.value is None:
            return Result.fail(*_error(found))
        destination = self._writable_calendar(destination_calendar_id)
        if destination.error is not None or destination.value is None:
            return Result.fail(*_error(destination))
        return self._move_series(found.value.series, destination.value)

    def _move_series(self, series: Row, destination: str) -> Result[Event]:
        """Copy a series into ``destination``, then delete the original.

        The copy has not synced, so it cannot hold exceptions: cancelled
        occurrences become ``exdate`` entries and changed ones their own
        events. Everything is removed again if the original stays.
        """
        series_id = int(series["_id"])
        current = self._event(_instance_like(series), None)
        if current is None:
            return Result.fail(ErrorCode.UPSTREAM_ERROR, "event cannot be read")
        if str(series.get("calendar_id")) == destination:
            return Result.ok(current)
        created: list[int] = []
        try:
            exceptions = self._store.exceptions(series_id)
            exdate = series.get("exdate")
            all_day = _truthy(series.get("allDay"))
            for row in exceptions:
                instance = row.get("originalInstanceTime")
                if instance is not None:
                    exdate = _with_exdate(exdate, int(instance), all_day)
            values = {
                **_series_columns(series),
                "title": series.get("title"),
                "description": series.get("description"),
                "eventEndTimezone": series.get("eventEndTimezone"),
                "availability": series.get("availability"),
                "exdate": exdate,
                "calendar_id": int(destination),
                UID_COLUMN: series.get(UID_COLUMN),
            }
            new_id = self._store.insert_event(values)
            created.append(new_id)
            for row in exceptions:
                if row.get("eventStatus") == STATUS_CANCELED:
                    continue
                single = {
                    key: row.get(key)
                    for key in (
                        "title",
                        "description",
                        "dtstart",
                        "dtend",
                        "allDay",
                        "eventTimezone",
                        "eventEndTimezone",
                        "availability",
                    )
                }
                single["calendar_id"] = int(destination)
                created.append(self._store.insert_event(single))
            if self._store.delete_event(series_id) == 0:
                for row_id in created:
                    self._store.delete_event(row_id)
                return Result.fail(
                    ErrorCode.UPSTREAM_ERROR,
                    "the original event could not be removed; nothing was moved",
                )
            self._drop_exceptions(series_id)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        return Result.ok(
            current.model_copy(
                update={
                    "id": f"{new_id}_{series['dtstart']}",
                    "recurring_event_id": str(new_id),
                    "calendar_id": destination,
                }
            )
        )

    def delete_occurrence(self, event_id: str) -> Result[None]:
        """Delete only this occurrence of a series ("this event")."""
        found = self._occurrence(event_id)
        if found.error is not None or found.value is None:
            return Result.fail(*_error(found))
        occurrence = found.value
        try:
            if occurrence.row is not None:
                self._store.update_event(
                    int(occurrence.row["_id"]), {"eventStatus": STATUS_CANCELED}
                )
            elif occurrence.series.get("_sync_id"):
                self._store.insert_exception(
                    occurrence.series_id,
                    {
                        "originalInstanceTime": occurrence.instance,
                        "eventStatus": STATUS_CANCELED,
                    },
                )
            elif not self._exclude(occurrence):
                return Result.fail(ErrorCode.NOT_FOUND, SERIES_NOT_FOUND)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        return Result.ok(None)

    def delete_following(self, event_id: str) -> Result[None]:
        """Delete this occurrence and the ones after it.

        From the first occurrence this deletes the whole series.
        """
        found = self._occurrence(event_id)
        if found.error is not None or found.value is None:
            return Result.fail(*_error(found))
        occurrence = found.value
        if occurrence.first:
            return self.delete_series(event_id)
        try:
            if not self._end_before(occurrence):
                return Result.fail(ErrorCode.NOT_FOUND, SERIES_NOT_FOUND)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        return Result.ok(None)

    def delete_series(self, event_id: str) -> Result[None]:
        """Delete every occurrence of the series ("all events")."""
        found = self._occurrence(event_id)
        if found.error is not None or found.value is None:
            return Result.fail(*_error(found))
        series_id = found.value.series_id
        try:
            if self._store.delete_event(series_id) == 0:
                return Result.fail(ErrorCode.NOT_FOUND, SERIES_NOT_FOUND)
            self._drop_exceptions(series_id)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        return Result.ok(None)

    def _occurrence(self, event_id: str) -> Result[_Occurrence]:
        """Find the series and rows behind a listed occurrence id."""
        parts = _occurrence_parts(event_id)
        if parts is None:
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT, f"{event_id} is not an occurrence"
            )
        row_id, begin = parts
        try:
            row = self._store.event(row_id)
            if row is None:
                return Result.fail(ErrorCode.NOT_FOUND, f"event {event_id} not found")
            original = row.get("original_id")
            series: Row | None = row
            own: Row | None = None
            instance = begin
            if original is not None:
                series = self._store.event(int(original))
                own = row
                instance = int(row.get("originalInstanceTime") or begin)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            return _store_failure(error)
        if series is None or not series.get("rrule"):
            return Result.fail(ErrorCode.NOT_FOUND, SERIES_NOT_FOUND)
        return Result.ok(_Occurrence(series, own, instance, begin))

    def _exclude(self, occurrence: _Occurrence) -> bool:
        """Leave one occurrence out of its series with ``exdate``."""
        series = occurrence.series
        values = _series_columns(series)
        values["exdate"] = _with_exdate(
            series.get("exdate"), occurrence.instance, _truthy(series.get("allDay"))
        )
        return self._store.update_event(occurrence.series_id, values) > 0

    def _end_before(self, occurrence: _Occurrence) -> bool:
        """End the series before ``occurrence``; drop changes to later ones."""
        series = occurrence.series
        values = _series_columns(series)
        values["rrule"] = rule_ending_before(
            str(series["rrule"]),
            _from_millis(occurrence.instance),
            all_day=_truthy(series.get("allDay")),
        )
        if self._store.update_event(occurrence.series_id, values) == 0:
            return False
        for row in self._store.exceptions(occurrence.series_id):
            instance = row.get("originalInstanceTime")
            if instance is not None and int(instance) >= occurrence.instance:
                self._store.delete_event(int(row["_id"]))
        return True

    def _drop_exceptions(self, series_id: int) -> None:
        """Delete every changed or cancelled occurrence of a series."""
        for row in self._store.exceptions(series_id):
            self._store.delete_event(int(row["_id"]))

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


def _values_for(event: Event) -> Row:
    """``Events`` columns for ``event``: a series when it has a repeat rule.

    Android expands a series from ``dtstart`` and ``duration``; ``dtend``
    must be empty. A single event clears any rule it had.
    """
    values = _event_values(event)
    rule = rule_text(event.recurrence)
    if rule is None:
        return {**values, "rrule": None, "duration": None}
    values["duration"] = _duration(event)
    values["dtend"] = None
    values["rrule"] = rule
    return values


def _exception_values(event: Event) -> Row:
    """Columns for an exception: Android refuses ``dtend`` there."""
    values = _event_values(event)
    values.pop("dtend")
    values["duration"] = _duration(event)
    return values


def _duration(event: Event) -> str:
    """RFC 5545 duration as Android stores it: ``P3600S`` or ``P2D``."""
    if event.all_day:
        first = event.start.date()
        days = max((event.end.date() - first).days, 1)
        return f"P{days}D"
    seconds = max(int((event.end - event.start).total_seconds()), 60)
    return f"P{seconds}S"


def _series_columns(series: Row) -> Row:
    """The series' current expansion columns, to send with any change to them."""
    return {column: series.get(column) for column in SERIES_COLUMNS}


def _cleared_series() -> Row:
    """Columns that make a series a single event again."""
    return {
        "rrule": None,
        "rdate": None,
        "exrule": None,
        "exdate": None,
        "duration": None,
    }


def _following_rule(event: Event, series: Row) -> list[str] | None:
    """The repeat rule for the part of a series that starts at ``event``.

    An unchanged rule that ends after a number of occurrences would start
    counting again; the new part ends on the day the series ended instead
    (the whole day, as the new part may start later in the day).
    """
    rule = rule_text(event.recurrence)
    if rule is None:
        return None
    last = series.get("lastDate")
    counted = any(
        part.strip().upper().startswith("COUNT=") for part in rule.split(";")
    )
    if counted and rule == series.get("rrule") and last is not None:
        # lastDate is the end of the last occurrence; step back into it.
        end = _from_millis(int(last) - 1)
        if event.all_day:
            next_day = _midnight(end.date() + timedelta(days=1), "UTC")
        else:
            zone = event.start_timezone
            day = end.astimezone(ZoneInfo(zone)).date()
            next_day = _midnight(day + timedelta(days=1), zone)
        rule = rule_ending_before(rule, next_day, all_day=event.all_day)
    return [f"RRULE:{rule}"]


def _shifted_start(series: Row, begin: int, event: Event) -> datetime:
    """The series' new first start when one occurrence moved to ``event.start``.

    All-day series move by whole days; timed ones by the same wall-clock
    change, so 10:00 to 11:00 in summer is 10:00 to 11:00 in winter too.
    """
    first = int(series["dtstart"])
    if event.all_day:
        days = (event.start.date() - _utc_date(begin)).days
        return _midnight(_utc_date(first) + timedelta(days=days), event.start_timezone)
    zone = ZoneInfo(event.start_timezone)
    old_wall = _from_millis(begin).astimezone(zone).replace(tzinfo=None)
    new_wall = event.start.astimezone(zone).replace(tzinfo=None)
    first_wall = _from_millis(first).astimezone(zone).replace(tzinfo=None)
    return (first_wall + (new_wall - old_wall)).replace(tzinfo=zone)


def _with_exdate(exdate: object, instance: int, all_day: bool) -> str:
    """``exdate`` with one more left-out occurrence (UTC, as Android reads it)."""
    moment = _from_millis(instance)
    value = f"{moment:%Y%m%d}" if all_day else f"{moment:%Y%m%dT%H%M%SZ}"
    current = str(exdate or "")
    if value in current.split(","):
        return current
    return f"{current},{value}" if current else value


def _series_uid(series: Row) -> str:
    """The series' uid2445, or its Android id when it has none."""
    return str(series.get(UID_COLUMN) or series["_id"])


def _saved(
    event: Event, row_id: int, *, series: int | None = None, calendar: str = ""
) -> Event:
    """``event`` with the ids Android gave it, as the list will show it.

    Occurrences of a series are listed as ``<row id>_<begin ms>``.
    """
    update: dict[str, object] = {}
    if calendar:
        update["calendar_id"] = calendar
    if series is not None:
        update["id"] = f"{row_id}_{_occurrence_begin(event)}"
        update["recurring_event_id"] = str(series)
    elif rule_text(event.recurrence) is not None:
        update["id"] = f"{row_id}_{_occurrence_begin(event)}"
        update["recurring_event_id"] = str(row_id)
    else:
        update["id"] = str(row_id)
    return event.model_copy(update=update)


def _occurrence_begin(event: Event) -> int:
    """An occurrence's ``begin`` as Instances lists it."""
    if event.all_day:
        return _millis(_midnight(event.start.date(), "UTC"))
    return _millis(event.start)


def _occurrence_parts(event_id: str) -> tuple[int, int] | None:
    """``(event row id, begin ms)`` of an occurrence id ``<id>_<begin>``."""
    row_id, sep, begin = event_id.partition("_")
    if not sep or not row_id.isdigit() or not begin.lstrip("-").isdigit():
        return None
    return int(row_id), int(begin)


def _instance_like(row: Row) -> Row:
    """Shape an ``Events`` row like an ``Instances`` row for mapping."""
    begin = row.get("dtstart")
    end = row.get("dtend")
    if end is None and begin is not None:
        end = int(begin) + _duration_millis(row.get("duration"))
    return {**row, "event_id": row.get("_id"), "begin": begin, "end": end}


def _duration_millis(value: object) -> int:
    """Milliseconds of an Android duration such as ``P3600S`` or ``P1D``."""
    text = str(value or "").upper().lstrip("P")
    try:
        if text.endswith("S"):
            return int(text[:-1]) * 1000
        if text.endswith("D"):
            return int(text[:-1]) * 86_400_000
        if text.endswith("W"):
            return int(text[:-1]) * 7 * 86_400_000
    except ValueError:
        pass
    return 3_600_000


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
