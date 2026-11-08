"""Pydantic schemas for the backend API."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SyncResponse(BaseModel):
    """Response returned after a successful full calendar sync."""

    synced: int


class FreeSlot(BaseModel):
    """A suggested free window for a new event."""

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _datetimes_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("free slot times must include time zone information")
        return value


class FreeSlotsResponse(BaseModel):
    """Response listing the free windows that fit a requested duration."""

    slots: list[FreeSlot] = Field(default_factory=list)


class FreeSlotRequest(BaseModel):
    """Request to find free time for a new event."""

    duration_minutes: int = Field(ge=1)
    window_start: datetime
    window_end: datetime
    time_zone: str = "UTC"

    @field_validator("window_start", "window_end")
    @classmethod
    def _window_times_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("window times must include time zone information")
        return value
