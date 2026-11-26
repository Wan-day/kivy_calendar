"""Desktop stand-ins for Android's calendar store and permissions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from phone_calendar.store import SERIES_COLUMNS, Row, syncing_calendar_ids

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
    account_type: str = GOOGLE,
) -> Row:
    """A ``CalendarContract.Calendars`` row (700 = owner access)."""
    return {
        "_id": calendar_id,
        "calendar_displayName": name,
        "account_name": account,
        "account_type": account_type,
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
        "originalInstanceTime": None,
        "availability": 0,
        "eventStatus": 1,
    }
    row.update(extra)
    return row


class SeriesCollapsed(AssertionError):
    """An update Android would apply by turning a series into one event."""


class FakeCalendarStore:
    """Rows as Android's calendar provider returns them.

    ``instances`` filters by the window like Android does (overlap with
    ``[begin_ms, end_ms)``) and records the windows it was asked for.
    Repeating events rows are expanded like on a phone (Android 16): ``exdate``
    leaves occurrences out, exceptions replace theirs, and a series without a
    sync id that has exceptions loses all its own occurrences. Daily and
    weekly rules only.
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
        rows = list(self.instance_rows)
        for row in self.event_rows.values():
            if row.get("rrule"):
                rows.extend(self._expand(row))
            else:
                rows.append(_as_instance(row))
        return [row for row in rows if row["begin"] < end_ms and row["end"] > begin_ms]

    def _expand(self, series: Row) -> list[Row]:
        """The series' own occurrences, as Android lists them."""
        exceptions = self._exceptions_of(series["_id"])
        if exceptions and not series.get("_sync_id"):
            return []
        replaced = {row["originalInstanceTime"] for row in exceptions}
        rows = []
        for begin in occurrence_starts(series):
            if begin in replaced:
                continue
            rows.append(
                _as_instance(
                    {**series, "dtstart": begin, "dtend": begin + _length(series)}
                )
            )
        return rows

    def _exceptions_of(self, series_id: int) -> list[Row]:
        return [
            row
            for row in self.event_rows.values()
            if row.get("original_id") == series_id
        ]

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

    def dirty_event_ids(self) -> set[int]:
        """Return ids of dirty events in calendars that sync."""
        self._raise()
        syncing = syncing_calendar_ids(self.calendar_rows)
        return {
            event_id
            for event_id, row in self.event_rows.items()
            if row.get("dirty") == 1 and str(row.get("calendar_id")) in syncing
        }

    def insert_event(self, values: Row) -> int:
        """Insert an event and return its new id."""
        self._raise()
        event_id = self.next_id
        self.next_id += 1
        self.event_rows[event_id] = {"_id": event_id, **values}
        self._set_last_date(event_id)
        return event_id

    def update_event(self, event_id: int, values: Row) -> int:
        """Change columns of one event.

        Changing how a series repeats without sending ``rrule`` raises
        :class:`SeriesCollapsed`: Android would keep one occurrence.
        """
        self._raise()
        row = self.event_rows.get(event_id)
        if row is None:
            return 0
        touched = set(values) & set(SERIES_COLUMNS)
        if row.get("rrule") and touched and "rrule" not in values:
            raise SeriesCollapsed(f"update of {sorted(touched)} without rrule")
        row.update(values)
        self._set_last_date(event_id)
        return 1

    def insert_exception(self, series_id: int, values: Row) -> int:
        """Insert an exception the way ``Events.CONTENT_EXCEPTION_URI`` does."""
        self._raise()
        if "dtend" in values:
            raise ValueError("Exceptions can't overwrite dtend")
        series = self.event_rows[series_id]
        instance = int(values["originalInstanceTime"])
        row: Row = {
            key: series.get(key)
            for key in (
                "calendar_id",
                "title",
                "description",
                "allDay",
                "eventTimezone",
                "eventEndTimezone",
                "availability",
            )
        }
        row.update(
            {
                "dtstart": instance,
                "original_id": series_id,
                "original_sync_id": series.get("_sync_id"),
                "originalInstanceTime": instance,
                "eventStatus": 1,
            }
        )
        duration = values.get("duration", series.get("duration"))
        row.update({key: value for key, value in values.items() if key != "duration"})
        row["dtend"] = int(row["dtstart"]) + duration_millis(duration)
        return self.insert_event(row)

    def exceptions(self, series_id: int) -> list[Row]:
        """Return the exception rows of a series."""
        self._raise()
        return [dict(row) for row in self._exceptions_of(series_id)]

    def _set_last_date(self, event_id: int) -> None:
        """Keep ``lastDate`` (end of the last occurrence) like Android does."""
        row = self.event_rows[event_id]
        if row.get("rrule") and _ends(str(row["rrule"])):
            starts = occurrence_starts(row)
            row["lastDate"] = starts[-1] + _length(row) if starts else None

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


def duration_millis(value: object) -> int:
    """Milliseconds of ``P3600S`` or ``P1D``."""
    text = str(value).upper()
    if text.endswith("S"):
        return int(text[1:-1]) * 1000
    if text.endswith("D"):
        return int(text[1:-1]) * 86_400_000
    raise ValueError(f"unsupported duration {value!r}")


def _length(series: Row) -> int:
    return duration_millis(series["duration"])


def _ends(rule: str) -> bool:
    return any(part.startswith(("COUNT=", "UNTIL=")) for part in rule.split(";"))


def occurrence_starts(series: Row, limit: int = 1000) -> list[int]:
    """Starts (ms) of a daily or weekly series, without left-out ones.

    Occurrences repeat at the first start's wall-clock time in its zone.
    """
    parts = dict(part.split("=", 1) for part in str(series["rrule"]).split(";"))
    zone = ZoneInfo(str(series.get("eventTimezone") or "UTC"))
    first = datetime.fromtimestamp(int(series["dtstart"]) / 1000, UTC).astimezone(zone)
    interval = int(parts.get("INTERVAL", "1"))
    count = int(parts["COUNT"]) if "COUNT" in parts else None
    until = parts.get("UNTIL")
    codes = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
    weekdays = {codes.index(code) for code in parts.get("BYDAY", "").split(",") if code}
    excluded = set(str(series.get("exdate") or "").split(","))
    starts: list[int] = []
    produced = 0
    for offset in range(limit):
        day = first.date() + timedelta(days=offset)
        if parts["FREQ"] == "DAILY":
            matches = offset % interval == 0
        elif parts["FREQ"] == "WEEKLY":
            week = (offset + first.weekday()) // 7
            matches = week % interval == 0 and day.weekday() in (
                weekdays or {first.weekday()}
            )
        else:
            raise NotImplementedError(parts["FREQ"])
        if not matches:
            continue
        local = datetime.combine(day, first.timetz().replace(tzinfo=None), tzinfo=zone)
        moment = local.astimezone(UTC)
        if until is not None and _after_until(moment, until):
            break
        produced += 1
        if count is not None and produced > count:
            break
        stamp = (
            f"{moment:%Y%m%d}" if series.get("allDay") else f"{moment:%Y%m%dT%H%M%SZ}"
        )
        if stamp not in excluded:
            starts.append(int(moment.timestamp() * 1000))
    return starts


def _after_until(moment: datetime, until: str) -> bool:
    if len(until) == 8:
        return moment.date() > datetime.strptime(until, "%Y%m%d").date()
    return moment > datetime.strptime(until, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _as_instance(row: Row) -> Row:
    """An occurrence row for an event row (or one expanded occurrence)."""
    return {
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
        "originalInstanceTime": row.get("originalInstanceTime"),
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


class FakeAccountSync:
    """Account sync that stays busy for a set number of polls."""

    def __init__(
        self,
        busy_polls: int = 0,
        error: Exception | None = None,
        forever: bool = False,
    ) -> None:
        """``busy_polls`` polls report busy; ``forever`` never finishes."""
        self.requests: list[list[tuple[str, str]]] = []
        self.polls = 0
        self.busy_polls = busy_polls
        self.forever = forever
        self.error = error

    def request(self, accounts: list[tuple[str, str]]) -> None:
        """Record the request, or raise the configured error."""
        if self.error is not None:
            raise self.error
        self.requests.append(list(accounts))

    def busy(self, accounts: list[tuple[str, str]]) -> bool:
        """Busy until ``busy_polls`` polls have passed."""
        self.polls += 1
        return self.forever or self.polls <= self.busy_polls
