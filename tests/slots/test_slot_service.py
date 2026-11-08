"""Tests for the free-slot search service."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.errors import ErrorCode, Result
from domain.event import Event
from google_calendar.fake import FakeCalendarProvider
from google_calendar.provider import ProviderOperation
from slots.service import FreeSlot, SlotService

BERLIN = ZoneInfo("Europe/Berlin")
START = datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN)
WINDOW_START = datetime(2026, 11, 6, 8, 0, tzinfo=BERLIN)
WINDOW_END = datetime(2026, 11, 6, 18, 0, tzinfo=BERLIN)


def _event(event_id: str = "event-1") -> Event:
    return Event(
        id=event_id,
        summary="Team standup",
        start=START,
        end=START + timedelta(minutes=30),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
    )


def _result(result: Result[list[FreeSlot]]) -> list[FreeSlot]:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _service(provider: FakeCalendarProvider) -> SlotService:
    return SlotService(provider=provider)


def test_find_free_slots_returns_the_whole_window_when_empty() -> None:
    """Without bookings the whole window is free."""
    result = _service(FakeCalendarProvider()).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    slots = _result(result)
    assert len(slots) == 1
    assert slots[0].start == WINDOW_START
    assert slots[0].end == WINDOW_START + timedelta(minutes=30)


def test_find_free_slots_skips_booked_windows() -> None:
    """Booked events carve gaps out of the requested window."""
    result = _service(FakeCalendarProvider([_event()])).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    slots = _result(result)
    assert len(slots) == 2
    assert slots[0].start == WINDOW_START
    assert slots[0].end == WINDOW_START + timedelta(minutes=30)
    assert slots[1].start == START + timedelta(minutes=30)
    assert slots[1].end == START + timedelta(minutes=60)


def test_find_free_slots_returns_no_slot_when_window_is_too_short() -> None:
    """A window shorter than the requested duration holds no slot."""
    result = _service(FakeCalendarProvider()).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=datetime(2026, 11, 6, 8, 0, tzinfo=BERLIN),
        window_end=datetime(2026, 11, 6, 8, 20, tzinfo=BERLIN),
    )

    assert _result(result) == []


def test_find_free_slots_skips_recurring_events() -> None:
    """Recurring events are not expanded yet and are skipped."""
    recurring = _event("recurring")
    recurring.recurrence = ["FREQ=DAILY;COUNT=1"]
    result = _service(FakeCalendarProvider([recurring])).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    assert len(_result(result)) == 1


def test_find_free_slots_returns_provider_error() -> None:
    """A provider failure crosses the module boundary as a failed result."""
    provider = FakeCalendarProvider()
    service = _service(provider)
    provider.fail_next(ProviderOperation.LIST, code=ErrorCode.UPSTREAM_ERROR, message="offline")
    result = service.find_free_slots(
        duration=timedelta(minutes=30),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR


def test_find_free_slots_rejects_a_non_positive_duration() -> None:
    """A non-positive duration is an invalid argument."""
    result = _service(FakeCalendarProvider()).find_free_slots(
        duration=timedelta(0),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT


def test_find_free_slots_rejects_a_naive_window_start() -> None:
    """A window start without time zone information is an invalid argument."""
    result = _service(FakeCalendarProvider()).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=datetime(2026, 11, 6, 8, 0),
        window_end=WINDOW_END,
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT


def test_find_free_slots_rejects_an_inverted_window() -> None:
    """A window whose end precedes its start is an invalid argument."""
    result = _service(FakeCalendarProvider()).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=WINDOW_END,
        window_end=WINDOW_START,
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT


def test_find_free_slots_rejects_an_unknown_time_zone() -> None:
    """An unknown IANA time zone is an invalid argument."""
    result = _service(FakeCalendarProvider()).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        time_zone="Mars/Olympus",
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT
