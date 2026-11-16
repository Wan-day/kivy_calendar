"""Kivy-free formatting helpers shared by the calendar screens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
