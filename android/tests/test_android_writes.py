"""Tests for saving, moving and deleting events in the phone's calendar."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import FakeCalendarStore, calendar_row, instance_row, millis, utc_midnight

from core.errors import ErrorCode
from domain.event import Event
from phone_calendar.provider import REPEATING_MESSAGE, AndroidCalendarProvider

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
START = datetime(2026, 11, 26, 9, 30, tzinfo=BERLIN)


def _store() -> FakeCalendarStore:
    return FakeCalendarStore(
        calendars=[
            calendar_row(1, "me@example.com", primary=1),
            calendar_row(2, "Work"),
            calendar_row(3, "Holidays", access=200),
        ]
    )


def _provider(store: FakeCalendarStore) -> AndroidCalendarProvider:
    return AndroidCalendarProvider(store, time_zone="Europe/Berlin")


def _event(**changes: object) -> Event:
    values: dict[str, object] = {
        "id": "app-id-1",
        "calendar_id": "1",
        "start": START,
        "end": START + timedelta(hours=1),
        "start_timezone": "Europe/Berlin",
        "end_timezone": "Europe/Berlin",
        "summary": "Dentist",
        "description": "Bring the card",
    }
    values.update(changes)
    return Event(**values)  # type: ignore[arg-type]


def _listed(store: FakeCalendarStore) -> list[Event]:
    result = _provider(store).list_events(
        datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 31, tzinfo=UTC)
    )
    assert result.value is not None
    return result.value


def test_create_writes_an_event_row_and_returns_androids_id() -> None:
    """A new event lands in the Events table with the app's id as uid2445."""
    store = _store()

    result = _provider(store).create_event(_event())

    assert result.error is None and result.value is not None
    saved = result.value
    row = store.event_rows[int(saved.id)]
    assert row["calendar_id"] == 1
    assert row["title"] == "Dentist"
    assert row["description"] == "Bring the card"
    assert row["dtstart"] == millis(START)
    assert row["dtend"] == millis(START + timedelta(hours=1))
    assert row["eventTimezone"] == "Europe/Berlin"
    assert row["allDay"] == 0
    assert row["uid2445"] == "app-id-1"
    assert [event.summary for event in _listed(store)] == ["Dentist"]


def test_saving_the_same_new_event_twice_keeps_one_copy() -> None:
    """W4: the second save finds the first through uid2445 and updates it."""
    store = _store()
    provider = _provider(store)

    first = provider.create_event(_event())
    second = provider.create_event(_event(summary="Dentist, room 4"))

    assert first.value is not None and second.value is not None
    assert first.value.id == second.value.id
    assert len(store.event_rows) == 1
    assert store.event_rows[int(first.value.id)]["title"] == "Dentist, room 4"


def test_a_blank_calendar_means_the_primary_one() -> None:
    """New events without a calendar go to the primary writable calendar."""
    store = _store()

    result = _provider(store).create_event(_event(calendar_id=""))

    assert result.value is not None and result.value.calendar_id == "1"


def test_read_only_and_unknown_calendars_are_refused() -> None:
    """Saving to a calendar without write access is an error, not a crash."""
    store = _store()
    provider = _provider(store)

    read_only = provider.create_event(_event(calendar_id="3"))
    unknown = provider.create_event(_event(calendar_id="99"))

    assert read_only.error is not None
    assert read_only.error.code == ErrorCode.INVALID_ARGUMENT
    assert unknown.error is not None
    assert store.event_rows == {}


def test_all_day_events_are_stored_as_utc_midnights() -> None:
    """W2: Android wants all-day events in UTC with an exclusive end date."""
    store = _store()
    start = datetime(2026, 11, 27, tzinfo=BERLIN)

    result = _provider(store).create_event(
        _event(all_day=True, start=start, end=start + timedelta(days=2))
    )

    assert result.value is not None
    row = store.event_rows[int(result.value.id)]
    assert row["allDay"] == 1
    assert row["eventTimezone"] == "UTC"
    assert row["dtstart"] == utc_midnight(date(2026, 11, 27))
    assert row["dtend"] == utc_midnight(date(2026, 11, 29))
    (listed,) = _listed(store)
    assert listed.all_day
    assert listed.start.date() == date(2026, 11, 27)
    assert listed.end.date() == date(2026, 11, 29)


def test_each_end_of_an_event_keeps_its_own_zone() -> None:
    """W2: a flight from Berlin to New York keeps both zones."""
    store = _store()
    arrival = datetime(2026, 11, 26, 14, 0, tzinfo=NEW_YORK)

    result = _provider(store).create_event(
        _event(end=arrival, end_timezone="America/New_York")
    )

    assert result.value is not None
    row = store.event_rows[int(result.value.id)]
    assert row["eventEndTimezone"] == "America/New_York"
    assert row["dtend"] == millis(arrival)
    (listed,) = _listed(store)
    assert listed.end == arrival
    assert listed.end_timezone == "America/New_York"


def test_update_changes_a_single_event_in_place() -> None:
    """W1: an edit rewrites the row; the calendar stays the same."""
    store = _store()
    provider = _provider(store)
    saved = provider.create_event(_event()).value
    assert saved is not None

    later = START + timedelta(hours=2)
    result = provider.update_event(
        saved.model_copy(
            update={
                "summary": "Dentist (moved)",
                "start": later,
                "end": later + timedelta(hours=1),
            }
        )
    )

    assert result.error is None
    row = store.event_rows[int(saved.id)]
    assert row["title"] == "Dentist (moved)"
    assert row["dtstart"] == millis(later)
    assert row["calendar_id"] == 1


def test_updating_or_deleting_a_missing_event_is_not_found() -> None:
    """Stale ids report NOT_FOUND."""
    provider = _provider(_store())

    update = provider.update_event(_event(id="555"))
    delete = provider.delete_event("1", "555")

    assert update.error is not None and update.error.code == ErrorCode.NOT_FOUND
    assert delete.error is not None and delete.error.code == ErrorCode.NOT_FOUND


def test_move_copies_to_the_new_calendar_and_removes_the_original() -> None:
    """W3: the event ends up once, in the destination calendar."""
    store = _store()
    provider = _provider(store)
    saved = provider.create_event(_event()).value
    assert saved is not None

    moved = provider.move_event("1", saved.id, "2")

    assert moved.error is None and moved.value is not None
    assert moved.value.calendar_id == "2"
    assert moved.value.summary == "Dentist"
    assert list(store.event_rows) == [int(moved.value.id)]
    assert store.event_rows[int(moved.value.id)]["calendar_id"] == 2
    assert store.event_rows[int(moved.value.id)]["uid2445"] == "app-id-1"


def test_a_failed_move_leaves_only_the_original() -> None:
    """If the original cannot be removed, the copy is removed again."""
    store = _store()
    provider = _provider(store)
    saved = provider.create_event(_event()).value
    assert saved is not None
    store.fail_next_delete = True

    moved = provider.move_event("1", saved.id, "2")

    assert moved.error is not None
    assert list(store.event_rows) == [int(saved.id)]
    assert store.event_rows[int(saved.id)]["calendar_id"] == 1


def test_delete_removes_the_event() -> None:
    """W1: delete removes the row and the event leaves the list."""
    store = _store()
    provider = _provider(store)
    saved = provider.create_event(_event()).value
    assert saved is not None

    result = provider.delete_event("1", saved.id)

    assert result.error is None
    assert store.event_rows == {}
    assert _listed(store) == []


def test_repeating_occurrences_are_read_only() -> None:
    """W5: occurrences of a series cannot be changed, moved or deleted yet."""
    first = datetime(2026, 11, 2, 8, 0, tzinfo=BERLIN)
    store = _store()
    store.instance_rows = [
        instance_row(
            9,
            1,
            millis(first),
            millis(first + timedelta(hours=1)),
            "Gym",
            rrule="FREQ=WEEKLY",
        )
    ]
    provider = _provider(store)
    (occurrence,) = _listed(store)

    update = provider.update_event(occurrence.model_copy(update={"summary": "x"}))
    move = provider.move_event("1", occurrence.id, "2")
    delete = provider.delete_event("1", occurrence.id)
    create = provider.create_event(occurrence)

    for result in (update, move, delete, create):
        assert result.error is not None
        assert result.error.code == ErrorCode.INVALID_STATE
        assert result.error.message == REPEATING_MESSAGE
    assert store.event_rows == {}


def test_write_failures_are_reported_not_raised() -> None:
    """A SecurityException while writing is PERMISSION_DENIED."""
    store = _store()
    provider = _provider(store)
    saved = provider.create_event(_event()).value
    assert saved is not None
    store.error = RuntimeError("java.lang.SecurityException: no WRITE_CALENDAR")

    result = provider.delete_event("1", saved.id)

    assert result.error is not None
    assert result.error.code == ErrorCode.PERMISSION_DENIED
