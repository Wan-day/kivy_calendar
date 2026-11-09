"""Free-slot search against the calendar provider.

The source of truth for busy time is Google Calendar, so slot finding reads the
provider the same way a full sync does.  Only events with a finite duration are
considered; recurring rules that could not be expanded keep their series shape
and are skipped here rather than guessed at.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from core.errors import ErrorCode, Result
from google_calendar.provider import CalendarProvider


class FreeSlot(BaseModel):
    """A contiguous window that is free for at least the requested duration."""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _datetimes_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("free slot times must include time zone information")
        return value

    @model_validator(mode="after")
    def _end_must_be_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("free slot end must be after start")
        return self


class SlotService:
    """Find windows in the calendar that are free for a new event."""

    def __init__(self, provider: CalendarProvider) -> None:
        self._provider = provider

    def find_free_slots(
        self,
        *,
        duration: timedelta,
        window_start: datetime,
        window_end: datetime,
        time_zone: str = "UTC",
    ) -> Result[list[FreeSlot]]:
        """Return free windows of at least ``duration`` in the window.

        The window bounds must be timezone-aware and the end must follow the
        start.  Results are returned as aware datetimes in ``time_zone``.
        """
        if duration <= timedelta(0):
            return Result.fail(ErrorCode.INVALID_ARGUMENT, "duration must be positive")
        if window_start.tzinfo is None or window_start.utcoffset() is None:
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT,
                "window start must include time zone information",
            )
        if window_end.tzinfo is None or window_end.utcoffset() is None:
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT,
                "window end must include time zone information",
            )
        if window_end <= window_start:
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT,
                "window end must be after window start",
            )
        try:
            zone = ZoneInfo(time_zone)
        except (ValueError, ZoneInfoNotFoundError):
            return Result.fail(
                ErrorCode.INVALID_ARGUMENT,
                f"unknown IANA time zone: {time_zone!r}",
            )

        listed = self._provider.list_events()
        if listed.error is not None:
            return Result.fail(listed.error.code, listed.error.message)

        events = listed.value
        if events is None:
            return Result.fail(
                ErrorCode.UPSTREAM_ERROR,
                "calendar provider reported success without an event list",
            )

        window_start_utc = window_start.astimezone(UTC)
        window_end_utc = window_end.astimezone(UTC)
        busy: list[tuple[datetime, datetime]] = []
        for event in events:
            if event.recurrence is not None:
                continue
            event_start = event.start.astimezone(UTC)
            event_end = event.end.astimezone(UTC)
            if event_end <= window_start_utc or event_start >= window_end_utc:
                continue
            busy.append(
                (max(event_start, window_start_utc), min(event_end, window_end_utc)),
            )
        busy.sort(key=lambda interval: (interval[0], interval[1]))

        slots: list[FreeSlot] = []
        cursor = window_start_utc
        for busy_start, busy_end in busy:
            if busy_start > cursor and busy_start - cursor >= duration:
                slots.append(self._build_slot(cursor, duration, zone))
            cursor = max(cursor, busy_end)
        if window_end_utc - cursor >= duration:
            slots.append(self._build_slot(cursor, duration, zone))
        return Result.ok(slots)

    def _build_slot(
        self,
        start: datetime,
        duration: timedelta,
        zone: ZoneInfo,
    ) -> FreeSlot:
        """Return a free slot starting at ``start`` with the requested duration."""
        slot_start = start.astimezone(zone)
        return FreeSlot(start=slot_start, end=slot_start + duration)
