"""Kivy-free formatting helpers shared by the calendar screens."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kivy_calendar.api import CalendarEvent

DEFAULT_TIME_ZONE = "Europe/Berlin"

def default_event_times(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the next full hour and one hour after it.

    When ``now`` is omitted the current local time is used, so the returned
    datetimes carry the local time zone.  A passed-in aware datetime keeps its
    own time zone, which makes the helper easy to test.
    """
    current = now if now is not None else datetime.now().astimezone()
    start = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return start, start + timedelta(hours=1)


def format_event_when(event: CalendarEvent) -> str:
    """Return a short human-readable span for an event."""
    start = event.start
    end = event.end
    if event.all_day:
        # All-day events cover whole calendar days; the end is exclusive, so
        # the last covered day is the day before the end.
        end_day = end.date() - timedelta(days=1)
        if end_day < start.date():
            end_day = start.date()
        if start.date() == end_day:
            return f"{start:%a %d %b %Y}"
        return f"{start:%d %b %Y} \u2013 {end_day:%d %b %Y}"
    if start.date() == end.date():
        span = f"{start:%H:%M}\u2013{end:%H:%M}"
    else:
        span = f"{start:%d %b %H:%M} \u2013 {end:%d %b %H:%M}"
    return f"{start:%a %d %b %Y} \u00b7 {span}"


def to_input_value(value: datetime) -> str:
    """Format a datetime for an ISO datetime text field."""
    return value.isoformat(timespec="minutes")


def to_wall_clock_value(value: datetime, zone: str) -> str:
    """Format ``value`` as wall-clock time in IANA ``zone`` without an offset."""
    local = value.astimezone(ZoneInfo(zone))
    return local.replace(tzinfo=None).isoformat(timespec="minutes")


def localize_wall_clock(text: str, zone: str) -> datetime:
    """Return the aware datetime for wall-clock ``text`` in IANA ``zone``.

    The chosen zone alone decides the instant, so DST is applied correctly:
    15:00 in Europe/Berlin is +01:00 in January and +02:00 in July.  Any UTC
    offset typed into ``text`` is ignored.  Raises ``ValueError`` for text
    that is not an ISO datetime, an unknown zone, or a wall-clock time that
    does not exist in the zone (a DST gap).  Ambiguous times use the first
    occurrence.
    """
    try:
        parsed = datetime.fromisoformat(text.strip())
        tz = ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError(str(error)) from error
    naive = parsed.replace(tzinfo=None)
    aware = naive.replace(tzinfo=tz)
    if aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive:
        shown = naive.isoformat(timespec="minutes")
        raise ValueError(f"{shown} does not exist in {zone}")
    return aware


def short_date(day: date, today: date | None = None) -> str:
    """Return ``Tue 24 Nov``, adding the year when it is not this year."""
    current = today if today is not None else date.today()
    if day.year != current.year:
        return f"{day:%a} {day.day} {day:%b %Y}"
    return f"{day:%a} {day.day} {day:%b}"


def day_heading(day: date, today: date | None = None) -> str:
    """Return the event-list heading for ``day``, e.g. ``Today · Tue 24 Nov``."""
    current = today if today is not None else date.today()
    names = {
        current: "Today",
        current + timedelta(days=1): "Tomorrow",
        current - timedelta(days=1): "Yesterday",
    }
    label = short_date(day, current)
    name = names.get(day)
    return f"{name} · {label}" if name else label


def _in_zone(value: datetime, zone: str) -> datetime:
    """Return ``value`` in IANA ``zone``, unchanged when the zone is unknown."""
    try:
        return value.astimezone(ZoneInfo(zone)) if zone else value
    except (ValueError, ZoneInfoNotFoundError):
        return value


def event_clock(event: CalendarEvent) -> tuple[str, str]:
    """Return the start and end shown beside an event in the list.

    Times are wall-clock in the event's own zones.  An end on a later day
    shows that day instead of a time; all-day events return blanks.
    """
    if event.all_day:
        return "", ""
    start = _in_zone(event.start, event.start_timezone)
    end = _in_zone(event.end, event.end_timezone)
    if end.date() != start.date():
        return f"{start:%H:%M}", f"{end.day} {end:%b}"
    return f"{start:%H:%M}", f"{end:%H:%M}"


def all_day_last_day(event: CalendarEvent) -> date:
    """Return the last day an all-day event covers (its end is exclusive)."""
    last = event.end.date() - timedelta(days=1)
    return max(last, event.start.date())


def is_happening(event: CalendarEvent, now: datetime | None = None) -> bool:
    """Return whether a timed event is in progress at ``now``."""
    if event.all_day:
        return False
    current = now if now is not None else datetime.now(UTC)
    return event.start <= current < event.end
