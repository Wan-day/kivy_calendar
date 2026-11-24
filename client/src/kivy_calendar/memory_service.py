"""A calendar service that keeps its events in memory.

It needs no backend, network or permissions. The Android build uses it until
the phone-calendar service exists, and on desktop it lets the screens run with
sample data (``KIVY_CALENDAR_SERVICE=memory``). Nothing is saved: events are
gone when the app closes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kivy_calendar.formatting import DEFAULT_TIME_ZONE
from kivy_calendar.models import (
    CalendarEvent,
    CalendarSummary,
    FreeSlot,
    ServiceError,
    TimeZoneOption,
)

PERSONAL_CALENDAR = CalendarSummary(id="personal", summary="Personal", primary=True)
WORK_CALENDAR = CalendarSummary(id="work", summary="Work")
DEFAULT_CALENDARS = (PERSONAL_CALENDAR, WORK_CALENDAR)
DEFAULT_TIME_ZONES = (
    TimeZoneOption(name="Europe/Berlin", label="Berlin"),
    TimeZoneOption(name="Europe/London", label="London"),
    TimeZoneOption(name="America/New_York", label="New York"),
    TimeZoneOption(name="Asia/Kolkata", label="Kolkata"),
    TimeZoneOption(name="UTC", label="UTC"),
)
# Free-slot candidates start on these minute boundaries.
SLOT_STEP = timedelta(minutes=15)
MAX_FREE_SLOTS = 5


class InMemoryCalendarService:
    """A :class:`~kivy_calendar.service.CalendarService` backed by a dict."""

    def __init__(
        self,
        events: Iterable[CalendarEvent] = (),
        *,
        calendars: Iterable[CalendarSummary] = DEFAULT_CALENDARS,
        time_zones: Iterable[TimeZoneOption] = DEFAULT_TIME_ZONES,
    ) -> None:
        """Create the service with optional starting events."""
        self._calendars = list(calendars)
        self._time_zones = list(time_zones)
        self._events: dict[str, CalendarEvent] = {}
        for event in events:
            self._events[event.id] = self._with_calendar(event)

    def list_events(self) -> list[CalendarEvent]:
        """Return every event, earliest first."""
        return sorted(self._events.values(), key=lambda event: event.start)

    def list_calendars(self) -> list[CalendarSummary]:
        """Return the configured calendars."""
        return list(self._calendars)

    def list_time_zones(self) -> list[TimeZoneOption]:
        """Return the configured time zones."""
        return list(self._time_zones)

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        """Store a new event; saving the same id twice is not a duplicate."""
        saved = self._with_calendar(event)
        existing = self._events.get(event.id)
        if existing is not None and existing != saved:
            raise ServiceError("already_exists", f"event {event.id} already exists")
        self._events[event.id] = saved
        return saved

    def update_event(
        self,
        event: CalendarEvent,
        source_calendar_id: str = "",
    ) -> CalendarEvent:
        """Replace a stored event, which may move it to another calendar."""
        if event.id not in self._events:
            raise ServiceError("not_found", f"event {event.id} does not exist")
        saved = self._with_calendar(event)
        self._events[event.id] = saved
        return saved

    def delete_event(self, event_id: str, calendar_id: str = "") -> bool:
        """Delete an event; deletes are never queued here."""
        if self._events.pop(event_id, None) is None:
            raise ServiceError("not_found", f"event {event_id} does not exist")
        return False

    def sync(self) -> int:
        """Nothing to sync with; return the event count."""
        return len(self._events)

    def find_free_slots(
        self,
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        time_zone: str,
    ) -> list[FreeSlot]:
        """Return up to five free windows on 15-minute boundaries."""
        if window_start.tzinfo is None or window_end.tzinfo is None:
            raise ServiceError(
                "invalid_event",
                "free-slot window times must include time zone information",
            )
        if duration_minutes <= 0:
            raise ServiceError("invalid_argument", "duration must be positive")
        try:
            zone = ZoneInfo(time_zone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ServiceError(
                "invalid_argument", f"unknown time zone: {time_zone}"
            ) from error
        duration = timedelta(minutes=duration_minutes)
        busy = sorted(
            (event.start, event.end)
            for event in self._events.values()
            if event.end > window_start and event.start < window_end
        )
        slots: list[FreeSlot] = []
        start = _next_step(window_start)
        while start + duration <= window_end and len(slots) < MAX_FREE_SLOTS:
            end = start + duration
            clash = next(
                (busy_end for busy_start, busy_end in busy
                 if busy_start < end and busy_end > start),
                None,
            )
            if clash is not None:
                start = _next_step(clash)
                continue
            slots.append(
                FreeSlot(start=start.astimezone(zone), end=end.astimezone(zone))
            )
            start = end
        return slots

    def _with_calendar(self, event: CalendarEvent) -> CalendarEvent:
        """Put events without a calendar into the primary calendar."""
        if event.calendar_id or not self._calendars:
            return replace(event, queued=False)
        primary = next(
            (calendar for calendar in self._calendars if calendar.primary),
            self._calendars[0],
        )
        return replace(event, calendar_id=primary.id, queued=False)


def _next_step(value: datetime) -> datetime:
    """Round ``value`` up to the next 15-minute boundary."""
    floored = value.replace(
        minute=value.minute - value.minute % 15, second=0, microsecond=0
    )
    return floored if floored == value else floored + SLOT_STEP


def sample_events(
    now: datetime | None = None,
    time_zone: str = DEFAULT_TIME_ZONE,
) -> list[CalendarEvent]:
    """Return a few example events around ``now`` for demos and screenshots."""
    zone = ZoneInfo(time_zone)
    current = now.astimezone(zone) if now is not None else datetime.now(zone)
    today = current.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(days: int, hour: int, minute: int = 0) -> datetime:
        day = (today + timedelta(days=days)).date()
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)

    def event(
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        calendar: CalendarSummary,
        *,
        all_day: bool = False,
    ) -> CalendarEvent:
        return CalendarEvent(
            id=event_id,
            summary=summary,
            start=start,
            end=end,
            start_timezone=time_zone,
            end_timezone=time_zone,
            calendar_id=calendar.id,
            all_day=all_day,
        )

    return [
        event("sample-standup", "Team standup", at(0, 9, 30), at(0, 10),
              WORK_CALENDAR),
        event("sample-lunch", "Lunch with Mira", at(0, 12, 30), at(0, 13, 30),
              PERSONAL_CALENDAR),
        event("sample-dentist", "Dentist", at(0, 16), at(0, 17),
              PERSONAL_CALENDAR),
        event("sample-birthday", "Lena's birthday", at(1, 0), at(2, 0),
              PERSONAL_CALENDAR, all_day=True),
        event("sample-review", "Design review", at(1, 10), at(1, 11, 30),
              WORK_CALENDAR),
        event("sample-gym", "Gym", at(2, 8), at(2, 9), PERSONAL_CALENDAR),
    ]
