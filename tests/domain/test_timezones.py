"""Tests for the curated time zone list."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from domain.timezones import CURATED_TIME_ZONES, format_utc_offset, list_time_zones


def _by_name(now: datetime) -> dict[str, tuple[str, int]]:
    return {z.name: (z.label, z.utc_offset_minutes) for z in list_time_zones(now)}


def test_every_curated_name_is_a_valid_unique_zoneinfo_key() -> None:
    """Only real IANA zones are offered, each once."""
    names = [name for name, _ in CURATED_TIME_ZONES]
    assert len(names) == len(set(names))
    for name in names:
        ZoneInfo(name)
    assert not any(name.startswith("Etc/") for name in names)


def test_offsets_follow_daylight_saving_time() -> None:
    """Berlin is +01:00 in January and +02:00 in July."""
    winter = _by_name(datetime(2026, 1, 15, 12, tzinfo=UTC))
    summer = _by_name(datetime(2026, 7, 15, 12, tzinfo=UTC))
    assert winter["Europe/Berlin"] == ("Berlin (UTC+01:00)", 60)
    assert summer["Europe/Berlin"] == ("Berlin (UTC+02:00)", 120)
    assert winter["America/New_York"][1] == -300
    assert summer["America/New_York"][1] == -240


def test_list_includes_fractional_and_extreme_offsets() -> None:
    """Half-hour, 45-minute, +13 and +14 zones are selectable."""
    zones = _by_name(datetime(2026, 1, 15, 12, tzinfo=UTC))
    assert zones["Asia/Kolkata"][1] == 330
    assert zones["Australia/Adelaide"][1] == 630
    assert zones["America/St_Johns"][1] == -210
    assert zones["Asia/Kathmandu"][1] == 345
    assert zones["Pacific/Tongatapu"][1] == 780
    assert zones["Pacific/Kiritimati"][1] == 840
    assert zones["Asia/Kolkata"][0] == "Kolkata (UTC+05:30)"


def test_list_is_sorted_west_to_east() -> None:
    """Options are ordered by current UTC offset."""
    offsets = [z.utc_offset_minutes for z in list_time_zones()]
    assert offsets == sorted(offsets)


def test_naive_now_is_rejected() -> None:
    """A naive reference time is never accepted."""
    with pytest.raises(ValueError):
        list_time_zones(datetime(2026, 1, 1))


def test_format_utc_offset() -> None:
    """Offsets render with sign and minutes."""
    assert format_utc_offset(-210) == "UTC-03:30"
    assert format_utc_offset(0) == "UTC+00:00"
