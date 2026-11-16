"""Tests for the disposable SQLite event cache repository."""

from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from cache.repository import EventRepository
from core.errors import ErrorCode, Result
from core.sqlite import Database
from domain.event import Event

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")


def _event(
    event_id: str = "event-1",
    *,
    summary: str = "Team standup",
    start: datetime | None = None,
    end: datetime | None = None,
    timezone: str = "Europe/Berlin",
    calendar_id: str = "",
    description: str | None = None,
    recurrence: list[str] | None = None,
    extended_properties: dict[str, str] | None = None,
) -> Event:
    zone = ZoneInfo(timezone)
    start_time = start or datetime(2026, 11, 6, 9, 0, tzinfo=zone)
    end_time = end or start_time + timedelta(minutes=30)
    return Event(
        id=event_id,
        calendar_id=calendar_id,
        summary=summary,
        start=start_time,
        end=end_time,
        start_timezone=timezone,
        end_timezone=timezone,
        description=description,
        recurrence=recurrence,
        extended_properties=extended_properties or {},
    )


def _cached(result: Result[Event]) -> Event:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _cached_events(result: Result[list[Event]]) -> list[Event]:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _deleted(result: Result[bool]) -> bool:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _cleared(result: Result[int]) -> int:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


@pytest.fixture
def repository(tmp_path: Path) -> EventRepository:
    """Return a repository backed by a temporary SQLite file."""
    return EventRepository(Database(tmp_path / "data" / "calendar.db"))


def test_create_and_get_round_trip(repository: EventRepository) -> None:
    """Cached events keep all fields, including their IANA time zones."""
    event = _event(
        description="Sync about the backend",
        recurrence=["RRULE:FREQ=WEEKLY;BYDAY=FR"],
        extended_properties={"kivy_calendar_source": "client"},
    )

    created = repository.create(event)

    assert created.is_ok
    loaded = _cached(repository.get(event.id))
    assert loaded == event
    assert loaded.start.tzinfo == BERLIN
    assert loaded.end.tzinfo == BERLIN
    assert loaded.start_timezone == "Europe/Berlin"
    assert loaded.description == "Sync about the backend"
    assert loaded.recurrence == ["RRULE:FREQ=WEEKLY;BYDAY=FR"]
    assert loaded.extended_properties == {"kivy_calendar_source": "client"}
    assert repository.database.path.is_file()


def test_calendar_id_round_trips_through_the_cache(
    repository: EventRepository,
) -> None:
    """The cache keeps the calendar that owns each event."""
    event = _event(calendar_id="work@example.com")

    assert repository.create(event).is_ok

    loaded = _cached(repository.get(event.id))
    assert loaded.calendar_id == "work@example.com"


def test_recurring_event_id_round_trips_through_the_cache(
    repository: EventRepository,
) -> None:
    """The series an occurrence belongs to is cached with the event."""
    event = _event()
    event.recurring_event_id = "series-1"

    assert repository.create(event).is_ok

    loaded = _cached(repository.get(event.id))
    assert loaded.recurring_event_id == "series-1"


def test_all_day_round_trips_through_the_cache(
    repository: EventRepository,
) -> None:
    """An all-day flag is preserved when the cache is read back."""
    event = _event().model_copy(update={"all_day": True})

    assert repository.create(event).is_ok

    loaded = _cached(repository.get(event.id))
    assert loaded.all_day is True


def test_old_cache_is_rebuilt_with_the_calendar_key(tmp_path: Path) -> None:
    """An old id-only table is rebuilt empty; a re-sync refills the cache."""
    database = Database(tmp_path / "old" / "calendar.db")
    with closing(database.connect()) as connection:
        connection.executescript(
            """
            CREATE TABLE events (
                id TEXT PRIMARY KEY NOT NULL,
                summary TEXT NOT NULL,
                start_utc TEXT NOT NULL,
                start_timezone TEXT NOT NULL,
                end_utc TEXT NOT NULL,
                end_timezone TEXT NOT NULL,
                description TEXT,
                recurrence TEXT,
                extended_properties TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO events (
                id, summary, start_utc, start_timezone, end_utc,
                end_timezone, description, recurrence, extended_properties,
                cached_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "old-event",
                "Old standup",
                "2026-11-06T08:00:00+00:00",
                "Europe/Berlin",
                "2026-11-06T08:30:00+00:00",
                "Europe/Berlin",
                None,
                None,
                "{}",
                "2026-11-06T08:00:00+00:00",
            ),
        )
        connection.commit()

    repository = EventRepository(database)
    missing = repository.get("old-event")

    assert missing.error is not None
    assert missing.error.code is ErrorCode.NOT_FOUND
    assert repository.create(_event("new", calendar_id="work")).is_ok
    with closing(database.connect()) as connection:
        key = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(events)")
            if row["pk"]
        }
    assert key == {"calendar_id", "id"}


def test_create_rejects_a_duplicate_id(repository: EventRepository) -> None:
    """A client-generated id cannot be cached twice."""
    assert repository.create(_event()).is_ok

    duplicate = repository.create(_event(summary="Duplicate"))

    assert duplicate.error is not None
    assert duplicate.error.code is ErrorCode.ALREADY_EXISTS
    assert len(_cached_events(repository.list())) == 1


def test_get_returns_not_found_for_a_missing_event(
    repository: EventRepository,
) -> None:
    """Missing rows produce an error result rather than an exception."""
    result = repository.get("missing-event")

    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_list_is_ordered_by_start_time(repository: EventRepository) -> None:
    """The cache returns events in calendar order."""
    later = _event("later", start=datetime(2026, 11, 6, 12, 0, tzinfo=BERLIN))
    earlier = _event("earlier", start=datetime(2026, 11, 6, 8, 0, tzinfo=BERLIN))
    assert repository.create(later).is_ok
    assert repository.create(earlier).is_ok

    events = _cached_events(repository.list())

    assert [event.id for event in events] == ["earlier", "later"]


def _corrupt_stored_timezone(
    repository: EventRepository,
    event_id: str,
) -> None:
    """Store an unknown IANA zone in a row, simulating an outdated cache."""
    with closing(repository.database.connect()) as connection:
        connection.execute(
            "UPDATE events SET start_timezone = ? WHERE id = ?",
            ("Not/AZone", event_id),
        )
        connection.commit()


def test_get_returns_storage_error_for_an_invalid_stored_timezone(
    repository: EventRepository,
) -> None:
    """A corrupt cache row fails with a storage error instead of raising."""
    assert repository.create(_event()).is_ok
    _corrupt_stored_timezone(repository, "event-1")

    result = repository.get("event-1")

    assert result.error is not None
    assert result.error.code is ErrorCode.STORAGE_ERROR


def test_list_returns_storage_error_for_an_invalid_stored_timezone(
    repository: EventRepository,
) -> None:
    """Listing a corrupt cache row fails with a storage error instead of raising."""
    assert repository.create(_event()).is_ok
    _corrupt_stored_timezone(repository, "event-1")

    result = repository.list()

    assert result.error is not None
    assert result.error.code is ErrorCode.STORAGE_ERROR


def test_update_replaces_the_cached_event(repository: EventRepository) -> None:
    """Updating an event refreshes its values and time zone."""
    assert repository.create(_event()).is_ok
    updated = _event(
        summary="Updated standup",
        start=datetime(2026, 11, 6, 10, 0, tzinfo=NEW_YORK),
        timezone="America/New_York",
    )

    result = repository.update(updated)

    assert _cached(result) == updated
    loaded = _cached(repository.get(updated.id))
    assert loaded.summary == "Updated standup"
    assert loaded.start_timezone == "America/New_York"
    assert loaded.start.tzinfo == NEW_YORK


def test_update_returns_not_found_for_a_missing_event(
    repository: EventRepository,
) -> None:
    """Only existing events can be updated."""
    result = repository.update(_event("missing-event"))

    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND


def test_delete_removes_the_cached_event(repository: EventRepository) -> None:
    """Deleting an event removes it from the cache."""
    assert repository.create(_event()).is_ok

    assert _deleted(repository.delete("event-1")) is True
    assert repository.get("event-1").error is not None
    again = repository.delete("event-1")
    assert again.error is not None
    assert again.error.code is ErrorCode.NOT_FOUND


def test_clear_makes_the_cache_rebuildable(repository: EventRepository) -> None:
    """Clearing the cache empties it and new events can be cached afterwards."""
    assert repository.create(_event("first")).is_ok
    assert repository.create(_event("second")).is_ok

    assert _cleared(repository.clear()) == 2
    assert _cached_events(repository.list()) == []

    rebuilt = _event("rebuilt")
    assert repository.create(rebuilt).is_ok
    assert _cached_events(repository.list()) == [rebuilt]


def test_replace_all_swaps_the_whole_cache(repository: EventRepository) -> None:
    """A full re-sync can replace every row in one call."""
    assert repository.create(_event("old")).is_ok

    result = repository.replace_all([_event("new-1"), _event("new-2")])

    assert result.is_ok
    assert result.value == 2
    assert [event.id for event in _cached_events(repository.list())] == [
        "new-1",
        "new-2",
    ]


def test_replace_all_keeps_the_old_cache_on_failure(
    repository: EventRepository,
) -> None:
    """A failed replacement is rolled back instead of leaving a partial cache."""
    assert repository.create(_event("old")).is_ok

    result = repository.replace_all([_event("duplicate"), _event("duplicate")])

    assert result.error is not None
    assert result.error.code is ErrorCode.ALREADY_EXISTS
    assert [event.id for event in _cached_events(repository.list())] == ["old"]


def test_same_id_can_be_cached_in_two_calendars(
    repository: EventRepository,
) -> None:
    """The cache keys events by calendar and id."""
    assert repository.create(_event("shared", calendar_id="a")).is_ok
    assert repository.create(_event("shared", calendar_id="b")).is_ok

    duplicate = repository.create(_event("shared", calendar_id="a"))

    assert duplicate.error is not None
    assert duplicate.error.code is ErrorCode.ALREADY_EXISTS
    assert [e.calendar_id for e in _cached_events(repository.list())] == ["a", "b"]


def test_get_and_delete_target_one_calendar_copy(
    repository: EventRepository,
) -> None:
    """A calendar id picks one copy; a bare shared id is ambiguous."""
    assert repository.create(_event("shared", calendar_id="a")).is_ok
    assert repository.create(_event("shared", calendar_id="b", summary="B")).is_ok

    assert _cached(repository.get("shared", "b")).summary == "B"
    ambiguous = repository.get("shared")
    assert ambiguous.error is not None
    assert ambiguous.error.code is ErrorCode.INVALID_ARGUMENT
    refused = repository.delete("shared")
    assert refused.error is not None
    assert refused.error.code is ErrorCode.INVALID_ARGUMENT

    assert _deleted(repository.delete("shared", "a")) is True
    assert _cached(repository.get("shared")).calendar_id == "b"


def test_update_only_touches_its_own_calendar_copy(
    repository: EventRepository,
) -> None:
    """Updating one calendar's copy leaves the other copy alone."""
    assert repository.create(_event("shared", calendar_id="a")).is_ok
    assert repository.create(_event("shared", calendar_id="b")).is_ok

    assert repository.update(_event("shared", calendar_id="a", summary="New")).is_ok

    assert _cached(repository.get("shared", "a")).summary == "New"
    assert _cached(repository.get("shared", "b")).summary == "Team standup"


def test_move_points_the_cached_event_at_the_new_calendar(
    repository: EventRepository,
) -> None:
    """Moving a cached event changes only its calendar."""
    assert repository.create(_event("e", calendar_id="a", summary="Kept")).is_ok

    assert _deleted(repository.move("e", "a", "b")) is True

    moved = _cached(repository.get("e"))
    assert (moved.calendar_id, moved.summary) == ("b", "Kept")
    missing = repository.move("e", "a", "c")
    assert missing.error is not None
    assert missing.error.code is ErrorCode.NOT_FOUND


def test_move_into_a_calendar_that_has_the_id_drops_the_source_copy(
    repository: EventRepository,
) -> None:
    """A destination that already caches the id keeps the key unique."""
    assert repository.create(_event("e", calendar_id="a")).is_ok
    assert repository.create(_event("e", calendar_id="b")).is_ok

    assert _deleted(repository.move("e", "a", "b")) is True

    assert [e.calendar_id for e in _cached_events(repository.list())] == ["b"]
