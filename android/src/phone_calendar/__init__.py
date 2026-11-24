"""The phone's own calendar as the app's calendar service (Android only)."""

from __future__ import annotations

from phone_calendar.service import PhoneCalendarService

__all__ = ["PhoneCalendarService", "create_service", "device_time_zone"]


def create_service() -> PhoneCalendarService:
    """Build the service on a device: JNI calendar store and real permissions."""
    from phone_calendar.permissions import AndroidCalendarPermissions
    from phone_calendar.provider import AndroidCalendarProvider
    from phone_calendar.store import JniCalendarStore

    return PhoneCalendarService(
        AndroidCalendarProvider(JniCalendarStore(), time_zone=device_time_zone()),
        AndroidCalendarPermissions(),
    )


def device_time_zone(fallback: str = "UTC") -> str:
    """The device's IANA time zone (``java.util.TimeZone``), or ``fallback``."""
    try:
        from jnius import autoclass  # type: ignore[import-not-found]

        return str(autoclass("java.util.TimeZone").getDefault().getID())
    except Exception:  # noqa: BLE001 - any JNI failure falls back
        return fallback
