"""Tests for the free-slot search service."""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
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


# --- Google-expanded occurrences, busy/free, all-day, DST, edges -------------


def _timed(
    event_id: str,
    start: datetime,
    end: datetime,
    **fields: Any,
) -> Event:
    zone = start.tzinfo.key if isinstance(start.tzinfo, ZoneInfo) else "UTC"
    return Event(
        id=event_id,
        start=start,
        end=end,
        start_timezone=zone,
        end_timezone=zone,
        **fields,
    )


def _free(
    events: list[Event],
    *,
    duration: timedelta,
    start: datetime,
    end: datetime,
    zone: str = "UTC",
) -> list[FreeSlot]:
    return _result(
        _service(FakeCalendarProvider(events)).find_free_slots(
            duration=duration,
            window_start=start,
            window_end=end,
            time_zone=zone,
        )
    )


def test_series_started_over_a_year_ago_blocks_current_occurrences() -> None:
    """Occurrences carry their own times, however old the series is."""
    occurrence = _timed(
        "oldseries_20261106T080000Z",
        START,
        START + timedelta(hours=1),
        recurring_event_id="oldseries",
    )

    slots = _free(
        [occurrence],
        duration=timedelta(hours=1),
        start=WINDOW_START,
        end=WINDOW_END,
    )

    assert [slot.start for slot in slots] == [
        WINDOW_START,
        START + timedelta(hours=1),
    ]


def test_byday_occurrences_each_block_their_own_day() -> None:
    """BYDAY=MO,WE,FR instances (expanded by Google) all block time."""
    monday = datetime(2026, 11, 2, 9, 0, tzinfo=BERLIN)
    events = [
        _timed(
            f"series_{day}",
            monday + timedelta(days=offset),
            monday + timedelta(days=offset, hours=1),
            recurring_event_id="series",
        )
        for day, offset in (("mo", 0), ("we", 2), ("fr", 4))
    ]

    slots = _free(
        events,
        duration=timedelta(hours=1),
        start=monday,
        end=datetime(2026, 11, 7, 9, 0, tzinfo=BERLIN),
    )

    starts = {slot.start for slot in slots}
    for offset in (0, 2, 4):
        assert monday + timedelta(days=offset) not in starts
    assert monday + timedelta(hours=1) in starts
    assert monday + timedelta(days=2, hours=1) in starts


def test_moved_instance_blocks_only_its_new_time() -> None:
    """A moved occurrence (one event after expansion) frees its old slot."""
    moved = _timed(
        "series_20261106T080000Z",
        START + timedelta(hours=5),
        START + timedelta(hours=6),
        recurring_event_id="series",
    )

    slots = _free(
        [moved],
        duration=timedelta(hours=5),
        start=START,
        end=START + timedelta(hours=8),
    )

    assert [slot.start for slot in slots] == [START]
    assert slots[0].end == START + timedelta(hours=5)


def test_cancelled_instance_is_absent_so_its_time_stays_free() -> None:
    """Google omits cancelled instances; the slot they held is free."""
    slots = _free(
        [],
        duration=timedelta(hours=1),
        start=WINDOW_START,
        end=WINDOW_END,
    )

    assert [slot.start for slot in slots] == [WINDOW_START]


def test_transparent_events_do_not_block() -> None:
    """Events marked free in Google do not remove availability."""
    free_event = _timed("free1", START, START + timedelta(hours=1), transparent=True)

    slots = _free(
        [free_event],
        duration=timedelta(hours=10),
        start=WINDOW_START,
        end=WINDOW_END,
    )

    assert [slot.start for slot in slots] == [WINDOW_START]


def _all_day(event_id: str, **fields: Any) -> Event:
    day = datetime(2026, 11, 6, tzinfo=BERLIN)
    return _timed(
        event_id,
        day,
        day + timedelta(days=1),
        all_day=True,
        **fields,
    )


def test_all_day_event_on_a_read_only_calendar_does_not_block() -> None:
    """Holidays on subscribed (read-only) calendars are informational."""
    slots = _free(
        [_all_day("holiday", calendar_read_only=True)],
        duration=timedelta(hours=10),
        start=WINDOW_START,
        end=WINDOW_END,
    )

    assert [slot.start for slot in slots] == [WINDOW_START]


def test_transparent_all_day_event_does_not_block() -> None:
    """An all-day event shown as free (birthday, reminder) does not block."""
    slots = _free(
        [_all_day("birthday", transparent=True)],
        duration=timedelta(hours=10),
        start=WINDOW_START,
        end=WINDOW_END,
    )

    assert [slot.start for slot in slots] == [WINDOW_START]


def test_opaque_all_day_event_on_a_writable_calendar_blocks() -> None:
    """An all-day event marked busy on the user's own calendar blocks the day."""
    slots = _free(
        [_all_day("trip")],
        duration=timedelta(minutes=30),
        start=WINDOW_START,
        end=WINDOW_END,
    )

    assert slots == []


def test_adjacent_events_leave_no_gap_between_them() -> None:
    """Back-to-back events do not create a phantom slot."""
    first = _timed("a", START, START + timedelta(hours=1))
    second = _timed("b", START + timedelta(hours=1), START + timedelta(hours=2))

    slots = _free(
        [first, second],
        duration=timedelta(minutes=1),
        start=START,
        end=START + timedelta(hours=3),
    )

    assert [slot.start for slot in slots] == [START + timedelta(hours=2)]


def test_overlapping_events_are_merged() -> None:
    """Overlapping events block their union exactly once."""
    first = _timed("a", START, START + timedelta(hours=2))
    second = _timed("b", START + timedelta(hours=1), START + timedelta(hours=3))
    inside = _timed("c", START + timedelta(minutes=30), START + timedelta(hours=1))

    slots = _free(
        [first, second, inside],
        duration=timedelta(hours=1),
        start=START,
        end=START + timedelta(hours=5),
    )

    assert [slot.start for slot in slots] == [START + timedelta(hours=3)]


def test_events_straddling_the_window_edges_are_clipped() -> None:
    """Events starting before or ending after the window still block its edges."""
    before = _timed("a", START - timedelta(hours=2), START + timedelta(hours=1))
    after = _timed("b", START + timedelta(hours=4), START + timedelta(hours=9))

    slots = _free(
        [before, after],
        duration=timedelta(hours=1),
        start=START,
        end=START + timedelta(hours=6),
    )

    assert [slot.start for slot in slots] == [START + timedelta(hours=1)]


def test_events_touching_the_window_bounds_are_ignored() -> None:
    """Events that end at or start at the window bounds do not block."""
    before = _timed("a", START - timedelta(hours=2), START)
    after = _timed("b", START + timedelta(hours=2), START + timedelta(hours=3))

    slots = _free(
        [before, after],
        duration=timedelta(hours=2),
        start=START,
        end=START + timedelta(hours=2),
    )

    assert [slot.start for slot in slots] == [START]


@pytest.mark.parametrize(
    ("zone", "day", "hours"),
    [
        ("Europe/Berlin", (2026, 3, 29), 23),
        ("Europe/Berlin", (2026, 10, 25), 25),
        ("America/New_York", (2026, 3, 8), 23),
        ("America/New_York", (2026, 11, 1), 25),
    ],
)
def test_a_dst_day_is_exactly_23_or_25_hours_long(
    zone: str,
    day: tuple[int, int, int],
    hours: int,
) -> None:
    """A whole-day slot fits on a transition day and nothing longer does."""
    tz = ZoneInfo(zone)
    start = datetime(*day, tzinfo=tz)
    end = datetime(day[0], day[1], day[2] + 1, tzinfo=tz)
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=hours)

    fits = _free([], duration=timedelta(hours=hours), start=start, end=end, zone=zone)
    too_long = _free(
        [], duration=timedelta(hours=hours + 1), start=start, end=end, zone=zone
    )

    assert len(fits) == 1
    assert fits[0].start == start
    assert fits[0].end == end
    assert too_long == []


@pytest.mark.parametrize(
    ("zone", "day", "busy_until", "expected_end"),
    [
        # Spring forward 02:00 -> 03:00: 01:30 plus one real hour is 03:30.
        ("Europe/Berlin", (2026, 3, 29), (1, 30), (3, 30, 0)),
        ("America/New_York", (2026, 3, 8), (1, 30), (3, 30, 0)),
        # Fall back: 01:30 EDT plus one real hour is 01:30 EST (fold=1).
        ("America/New_York", (2026, 11, 1), (1, 30), (1, 30, 1)),
        ("Europe/Berlin", (2026, 10, 25), (2, 30), (2, 30, 1)),
    ],
)
def test_slot_duration_is_elapsed_time_across_a_dst_transition(
    zone: str,
    day: tuple[int, int, int],
    busy_until: tuple[int, int],
    expected_end: tuple[int, int, int],
) -> None:
    """A one-hour slot spanning a transition lasts one real hour."""
    tz = ZoneInfo(zone)
    day_start = datetime(*day, tzinfo=tz)
    busy_end = datetime(*day, *busy_until, tzinfo=tz)
    window_end = datetime(day[0], day[1], day[2] + 1, tzinfo=tz)
    busy = _timed("busy", day_start, busy_end)

    slots = _free(
        [busy],
        duration=timedelta(hours=1),
        start=day_start,
        end=window_end,
        zone=zone,
    )

    slot = slots[0]
    assert slot.start == busy_end
    hour, minute, fold = expected_end
    assert slot.end == datetime(*day, hour, minute, fold=fold, tzinfo=tz)
    assert slot.end.utcoffset() == datetime(
        *day, hour, minute, fold=fold, tzinfo=tz
    ).utcoffset()
    assert slot.end.astimezone(UTC) - slot.start.astimezone(UTC) == timedelta(hours=1)


def test_find_free_slots_asks_the_provider_for_the_window_only() -> None:
    """Slot search passes the search window to the provider listing."""
    provider = FakeCalendarProvider()
    seen: list[tuple[datetime | None, datetime | None]] = []
    original = provider.list_events

    def spy(
        time_min: datetime | None = None,
        time_max: datetime | None = None,
    ) -> Result[list[Event]]:
        seen.append((time_min, time_max))
        return original(time_min, time_max)

    provider.list_events = spy  # type: ignore[method-assign]

    _service(provider).find_free_slots(
        duration=timedelta(minutes=30),
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    assert seen == [(WINDOW_START, WINDOW_END)]
