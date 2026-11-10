"""Kivy-free formatting helpers shared by the calendar screens."""

from __future__ import annotations

from datetime import datetime, timedelta

from kivy_calendar.api import CalendarEvent

DEFAULT_TIME_ZONE = "Europe/Berlin"

# The event form offers one fixed UTC offset per hour.  UTC-11 through UTC+12
# covers every inhabited offset in 24 entries.
UTC_OFFSET_HOURS: tuple[int, ...] = tuple(range(-11, 13))

# Two or three representative cities per offset, so a dropdown entry is easy to
# recognize without knowing the numeric offset by heart.
UTC_OFFSET_CITIES: dict[int, tuple[str, ...]] = {
    -11: ("Pago Pago", "Alofi", "Midway"),
    -10: ("Honolulu", "Papeete", "Rarotonga"),
    -9: ("Anchorage", "Juneau", "Nome"),
    -8: ("Los Angeles", "Vancouver", "Tijuana"),
    -7: ("Denver", "Calgary", "Phoenix"),
    -6: ("Chicago", "Mexico City", "Winnipeg"),
    -5: ("New York", "Toronto", "Bogotá"),
    -4: ("Santiago", "Halifax", "Caracas"),
    -3: ("São Paulo", "Buenos Aires", "Rio de Janeiro"),
    -2: ("Fernando de Noronha", "South Georgia"),
    -1: ("Azores", "Praia", "Ittoqqortoormiit"),
    0: ("London", "Dublin", "Lisbon"),
    1: ("Berlin", "Paris", "Rome"),
    2: ("Athens", "Helsinki", "Johannesburg"),
    3: ("Moscow", "Istanbul", "Nairobi"),
    4: ("Dubai", "Baku", "Muscat"),
    5: ("Karachi", "Tashkent", "Yekaterinburg"),
    6: ("Dhaka", "Almaty", "Omsk"),
    7: ("Bangkok", "Jakarta", "Hanoi"),
    8: ("Beijing", "Singapore", "Perth"),
    9: ("Tokyo", "Seoul", "Yakutsk"),
    10: ("Brisbane", "Vladivostok", "Port Moresby"),
    11: ("Nouméa", "Honiara", "Magadan"),
    12: ("Suva", "Majuro", "Kamchatka"),
}


def utc_offset_label(hours: int) -> str:
    """Return the dropdown label for a whole-hour UTC offset."""
    label = f"UTC{hours:+d}"
    cities = UTC_OFFSET_CITIES.get(hours)
    if not cities:
        return label
    return f"{label} ({', '.join(cities)})"


UTC_OFFSET_LABELS: tuple[str, ...] = tuple(
    utc_offset_label(hours) for hours in UTC_OFFSET_HOURS
)


def time_zone_for_offset(hours: int) -> str:
    """Return the IANA fixed-offset zone ``hours`` east of UTC."""
    if hours == 0:
        return "UTC"
    # POSIX-style Etc zones invert the sign: Etc/GMT-1 means UTC+1.
    return f"Etc/GMT{-hours:+d}"


def offset_hours_for_zone(zone: str) -> int | None:
    """Return the whole-hour offset of a fixed-offset zone, or ``None``."""
    zero_zones = {
        "UTC",
        "Etc/UTC",
        "Etc/GMT",
        "Etc/GMT0",
        "Etc/GMT+0",
        "Etc/GMT-0",
    }
    if zone in zero_zones:
        return 0
    if zone.startswith("Etc/GMT"):
        try:
            return -int(zone[len("Etc/GMT") :])
        except ValueError:
            return None
    return None


def time_zone_label(zone: str) -> str:
    """Return the dropdown label for ``zone``, keeping unknown zones as-is."""
    hours = offset_hours_for_zone(zone)
    return utc_offset_label(hours) if hours is not None else zone


def time_zone_from_label(label: str) -> str | None:
    """Return the IANA zone for a ``UTC+N`` label, or ``None`` when unknown."""
    text = label.strip()
    # Labels may carry example cities in parentheses: "UTC+1 (Berlin, ...)".
    prefix = text.split("(", 1)[0].strip()
    if not prefix.upper().startswith("UTC"):
        return None
    suffix = prefix[3:].strip()
    if not suffix:
        return "UTC"
    if suffix[0] not in "+-" or not suffix[1:].isdigit():
        return None
    hours = int(suffix[1:])
    offset = hours if suffix[0] == "+" else -hours
    if offset not in UTC_OFFSET_HOURS:
        return None
    return time_zone_for_offset(offset)


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
