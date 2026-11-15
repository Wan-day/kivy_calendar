"""Tests for the calendar metadata model."""

from __future__ import annotations

import pytest
from domain.calendar import CalendarInfo


def test_calendar_defaults_to_not_primary() -> None:
    """Only the account's primary calendar is flagged as primary."""
    assert CalendarInfo(id="work@example.com", summary="Work").primary is False


@pytest.mark.parametrize(
    ("calendar_id", "summary"),
    [
        ("", "Work"),
        ("   ", "Work"),
        ("work@example.com", ""),
        ("work@example.com", "   "),
    ],
)
def test_calendar_rejects_blank_fields(calendar_id: str, summary: str) -> None:
    """A calendar without an id or display name cannot be offered."""
    with pytest.raises(ValueError):
        CalendarInfo(id=calendar_id, summary=summary)
