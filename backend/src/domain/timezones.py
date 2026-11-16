"""Curated IANA time zones offered to clients, with display labels."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

# (IANA zone, representative city).  Real zones only, so DST follows tzdata.
# Includes half-hour (India, Adelaide, Newfoundland), 45-minute (Kathmandu,
# Chatham) and +13/+14 zones (Auckland in summer, Tongatapu, Kiritimati).
CURATED_TIME_ZONES: tuple[tuple[str, str], ...] = (
    ("Pacific/Pago_Pago", "Pago Pago"),
    ("Pacific/Honolulu", "Honolulu"),
    ("America/Anchorage", "Anchorage"),
    ("America/Los_Angeles", "Los Angeles"),
    ("America/Vancouver", "Vancouver"),
    ("America/Denver", "Denver"),
    ("America/Phoenix", "Phoenix"),
    ("America/Chicago", "Chicago"),
    ("America/Mexico_City", "Mexico City"),
    ("America/New_York", "New York"),
    ("America/Toronto", "Toronto"),
    ("America/Bogota", "Bogota"),
    ("America/Halifax", "Halifax"),
    ("America/Santiago", "Santiago"),
    ("America/St_Johns", "St. John's"),
    ("America/Sao_Paulo", "Sao Paulo"),
    ("America/Argentina/Buenos_Aires", "Buenos Aires"),
    ("Atlantic/South_Georgia", "South Georgia"),
    ("Atlantic/Azores", "Azores"),
    ("UTC", "UTC"),
    ("Europe/London", "London"),
    ("Europe/Dublin", "Dublin"),
    ("Europe/Lisbon", "Lisbon"),
    ("Africa/Lagos", "Lagos"),
    ("Europe/Berlin", "Berlin"),
    ("Europe/Paris", "Paris"),
    ("Europe/Rome", "Rome"),
    ("Europe/Madrid", "Madrid"),
    ("Europe/Athens", "Athens"),
    ("Europe/Helsinki", "Helsinki"),
    ("Africa/Cairo", "Cairo"),
    ("Africa/Johannesburg", "Johannesburg"),
    ("Europe/Moscow", "Moscow"),
    ("Europe/Istanbul", "Istanbul"),
    ("Africa/Nairobi", "Nairobi"),
    ("Asia/Tehran", "Tehran"),
    ("Asia/Dubai", "Dubai"),
    ("Asia/Kabul", "Kabul"),
    ("Asia/Karachi", "Karachi"),
    ("Asia/Kolkata", "Kolkata"),
    ("Asia/Kathmandu", "Kathmandu"),
    ("Asia/Dhaka", "Dhaka"),
    ("Asia/Yangon", "Yangon"),
    ("Asia/Bangkok", "Bangkok"),
    ("Asia/Jakarta", "Jakarta"),
    ("Asia/Shanghai", "Beijing"),
    ("Asia/Singapore", "Singapore"),
    ("Australia/Perth", "Perth"),
    ("Asia/Tokyo", "Tokyo"),
    ("Asia/Seoul", "Seoul"),
    ("Australia/Adelaide", "Adelaide"),
    ("Australia/Darwin", "Darwin"),
    ("Australia/Brisbane", "Brisbane"),
    ("Australia/Sydney", "Sydney"),
    ("Pacific/Noumea", "Noumea"),
    ("Pacific/Auckland", "Auckland"),
    ("Pacific/Chatham", "Chatham Islands"),
    ("Pacific/Tongatapu", "Tongatapu"),
    ("Pacific/Apia", "Apia"),
    ("Pacific/Kiritimati", "Kiritimati"),
)


class TimeZoneOption(BaseModel):
    """One selectable IANA time zone."""

    name: str
    label: str
    utc_offset_minutes: int


def format_utc_offset(minutes: int) -> str:
    """Return ``UTC+05:30`` style text for an offset in minutes."""
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{rest:02d}"


def list_time_zones(now: datetime | None = None) -> list[TimeZoneOption]:
    """Return the curated zones with their UTC offset at ``now``.

    Options are sorted by current offset, then city, so the list reads west to
    east.  Offsets honour daylight saving time at ``now``.
    """
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("now must include time zone information")
    options: list[TimeZoneOption] = []
    for name, city in CURATED_TIME_ZONES:
        offset = moment.astimezone(ZoneInfo(name)).utcoffset()
        minutes = int(offset.total_seconds() // 60) if offset is not None else 0
        label = f"{city} ({format_utc_offset(minutes)})"
        options.append(
            TimeZoneOption(name=name, label=label, utc_offset_minutes=minutes)
        )
    options.sort(key=lambda option: (option.utc_offset_minutes, option.label))
    return options
