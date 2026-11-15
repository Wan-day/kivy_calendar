"""Calendar metadata shared by the provider, API, and client.

A connected Google account can expose several calendars (for example a work
calendar and a personal one).  Events are written to a specific calendar, so the
app needs the list of calendars the account can write to.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class CalendarInfo(BaseModel):
    """One calendar the connected account can read and write."""

    model_config = ConfigDict(extra="forbid")

    id: str
    summary: str
    primary: bool = False

    @field_validator("id", "summary")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("calendar id and summary must not be blank")
        return value
