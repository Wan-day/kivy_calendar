"""Tests for the Event domain model."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from domain.event import Event
from pydantic import ValidationError

BERLIN = ZoneInfo("Europe/Berlin")


def _event(
    *,
    id: str = "client-generated-id",
    summary: str = "Team standup",
    start: datetime | None = None,
    end: datetime | None = None,
    start_timezone: str = "Europe/Berlin",
    end_timezone: str = "Europe/Berlin",
    calendar_id: str = "",
    description: str | None = None,
    recurrence: list[str] | None = None,
    extended_properties: dict[str, str] | None = None,
) -> Event:
    return Event(
        id=id,
        calendar_id=calendar_id,
        summary=summary,
        start=start or datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN),
        end=end or datetime(2026, 11, 6, 9, 30, tzinfo=BERLIN),
        start_timezone=start_timezone,
        end_timezone=end_timezone,
        description=description,
        recurrence=recurrence,
        extended_properties=extended_properties or {},
    )


def test_event_keeps_iana_timezone_information() -> None:
    """Valid events keep the declared time zone and its offset."""
    event = _event()

    assert event.start.tzinfo == BERLIN
    assert event.end.tzinfo == BERLIN
    assert event.start_timezone == "Europe/Berlin"
    assert event.end_timezone == "Europe/Berlin"
    assert event.start.utcoffset() == timedelta(hours=1)


def test_naive_start_is_rejected() -> None:
    """A start time without timezone information is not allowed."""
    with pytest.raises(ValidationError, match="time zone information"):
        _event(start=datetime(2026, 11, 6, 9, 0))


def test_naive_end_is_rejected() -> None:
    """An end time without timezone information is not allowed."""
    with pytest.raises(ValidationError, match="time zone information"):
        _event(end=datetime(2026, 11, 6, 9, 30))


def test_unknown_iana_timezone_is_rejected() -> None:
    """Timezone names must resolve through the IANA database."""
    with pytest.raises(ValidationError, match="unknown IANA time zone"):
        _event(start_timezone="Mars/Olympus_Mons")


def test_times_are_normalised_to_the_declared_zone() -> None:
    """The declared IANA zone wins over the offset on the input datetime."""
    event = _event(
        start=datetime(2026, 11, 6, 8, 0, tzinfo=UTC),
        end=datetime(2026, 11, 6, 8, 30, tzinfo=UTC),
    )

    assert event.start.hour == 9
    assert event.start.tzinfo == BERLIN
    assert event.end.hour == 9
    assert event.end.minute == 30


def test_end_must_be_after_start() -> None:
    """An event cannot end before or at its start time."""
    with pytest.raises(ValidationError, match="end must be after start"):
        _event(end=datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN))


def test_blank_event_id_is_rejected() -> None:
    """The client-generated id must contain more than whitespace."""
    with pytest.raises(ValidationError, match="event id must not be blank"):
        _event(id="   ")


def test_optional_fields_round_trip() -> None:
    """Optional event data is kept as provided."""
    event = _event(
        description="Sync about the backend",
        recurrence=["RRULE:FREQ=WEEKLY;BYDAY=FR"],
        extended_properties={"kivy_calendar_source": "client"},
    )

    assert event.description == "Sync about the backend"
    assert event.recurrence == ["RRULE:FREQ=WEEKLY;BYDAY=FR"]
    assert event.extended_properties == {"kivy_calendar_source": "client"}


def test_optional_fields_have_safe_defaults() -> None:
    """Events without optional data use empty defaults."""
    event = _event()

    assert event.summary == "Team standup"
    assert event.calendar_id == ""
    assert event.description is None
    assert event.recurrence is None
    assert event.extended_properties == {}


def test_calendar_id_round_trips_through_serialisation() -> None:
    """The owning calendar survives a JSON round-trip."""
    event = _event(calendar_id="work@example.com")

    restored = Event.model_validate(event.model_dump(mode="json"))

    assert restored.calendar_id == "work@example.com"


def test_blank_calendar_id_is_allowed() -> None:
    """A blank calendar id means the provider's configured default calendar."""
    event = _event(calendar_id="")

    assert event.calendar_id == ""
