"""Tests for creating, changing and deleting repeating events on the phone.

The fake store expands series like Android 16 does, including its quirks:
exceptions to a series without a sync id hide the whole series, and an
update that touches a series' times without its rule collapses the series.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import (
    FakeCalendarStore,
    calendar_row,
    millis,
    utc_midnight,
)

from core.errors import ErrorCode
from domain.event import Event
from phone_calendar.provider import AndroidCalendarProvider
from phone_calendar.store import STATUS_CANCELED

PRAGUE = ZoneInfo("Europe/Prague")
# Tuesdays at 10:00 in Prague: 1, 8, 15, 22 and 29 December 2026.
FIRST = datetime(2026, 12, 1, 10, 0, tzinfo=PRAGUE)
WEEK = timedelta(weeks=1)
WEEKLY = "FREQ=WEEKLY;COUNT=5;BYDAY=TU"


def _store() -> FakeCalendarStore:
    return FakeCalendarStore(
        calendars=[
            calendar_row(1, "me@example.com", primary=1),
            calendar_row(2, "Work"),
        ]
    )


def _provider(store: FakeCalendarStore) -> AndroidCalendarProvider:
    return AndroidCalendarProvider(store, time_zone="Europe/Prague")


def _event(**changes: object) -> Event:
    values: dict[str, object] = {
        "id": "app-id-1",
        "calendar_id": "1",
        "start": FIRST,
        "end": FIRST + timedelta(hours=1),
        "start_timezone": "Europe/Prague",
        "end_timezone": "Europe/Prague",
        "summary": "Yoga",
        "recurrence": [f"RRULE:{WEEKLY}"],
    }
    values.update(changes)
    return Event(**values)  # type: ignore[arg-type]


def _listed(store: FakeCalendarStore) -> list[Event]:
    result = _provider(store).list_events(
        datetime(2026, 11, 1, tzinfo=UTC), datetime(2027, 3, 1, tzinfo=UTC)
    )
    assert result.error is None and result.value is not None
    return result.value


def _series(store: FakeCalendarStore, *, synced: bool = True) -> int:
    """Save the weekly series; ``synced`` gives it a sync id like Google does."""
    saved = _provider(store).create_event(_event()).value
    assert saved is not None and saved.recurring_event_id is not None
    series_id = int(saved.recurring_event_id)
    if synced:
        store.event_rows[series_id]["_sync_id"] = "google-sync-id"
    return series_id


def _occurrence(store: FakeCalendarStore, week: int) -> Event:
    """The listed occurrence ``week`` weeks after the first."""
    start = FIRST + week * WEEK
    return next(event for event in _listed(store) if event.start == start)


def _starts(store: FakeCalendarStore, title: str = "Yoga") -> list[datetime]:
    return [event.start for event in _listed(store) if event.summary == title]


def _weeks(*weeks: int) -> list[datetime]:
    return [FIRST + week * WEEK for week in weeks]


def test_a_new_repeating_event_is_one_series_row() -> None:
    """Android expands series from dtstart and duration; dtend stays empty."""
    store = _store()

    saved = _provider(store).create_event(_event()).value

    assert saved is not None
    (row,) = store.event_rows.values()
    assert row["rrule"] == WEEKLY
    assert row["duration"] == "P3600S"
    assert row["dtend"] is None
    assert row["uid2445"] == "app-id-1"
    assert saved.id == f"{row['_id']}_{millis(FIRST)}"
    assert saved.recurring_event_id == str(row["_id"])
    listed = _listed(store)
    assert [event.start for event in listed] == _weeks(0, 1, 2, 3, 4)
    assert {event.recurring_event_id for event in listed} == {str(row["_id"])}
    assert listed[2].recurrence == [f"RRULE:{WEEKLY}"]


def test_all_day_series_use_whole_days() -> None:
    """An all-day series is stored at UTC midnight with a P1D duration."""
    store = _store()
    day = datetime(2026, 12, 1, tzinfo=PRAGUE)

    _provider(store).create_event(
        _event(
            all_day=True,
            start=day,
            end=day + timedelta(days=1),
            recurrence=["RRULE:FREQ=DAILY;COUNT=3"],
        )
    )

    (row,) = store.event_rows.values()
    assert row["dtstart"] == utc_midnight(date(2026, 12, 1))
    assert row["duration"] == "P1D"
    assert [event.start.date() for event in _listed(store)] == [
        date(2026, 12, 1),
        date(2026, 12, 2),
        date(2026, 12, 3),
    ]


def test_a_single_event_can_start_repeating() -> None:
    """Saving a rule on a single event turns its row into a series."""
    store = _store()
    provider = _provider(store)
    single = provider.create_event(_event(recurrence=None)).value
    assert single is not None and single.id.isdigit()

    saved = provider.update_event(
        single.model_copy(update={"recurrence": [f"RRULE:{WEEKLY}"]})
    )

    assert saved.value is not None
    assert saved.value.recurring_event_id == single.id
    assert _starts(store) == _weeks(0, 1, 2, 3, 4)


def test_changing_this_occurrence_of_a_synced_series_adds_an_exception() -> None:
    """Only the 15 Dec occurrence moves to 11:00 and gets a new title."""
    store = _store()
    series_id = _series(store)
    third = _occurrence(store, 2)
    later = third.start + timedelta(hours=1)

    result = _provider(store).update_occurrence(
        third.model_copy(
            update={
                "summary": "Yoga (hall B)",
                "start": later,
                "end": later + timedelta(hours=1),
            }
        )
    )

    assert result.error is None and result.value is not None
    exception = store.event_rows[int(result.value.id.partition("_")[0])]
    assert exception["original_id"] == series_id
    assert exception["originalInstanceTime"] == millis(third.start)
    assert _starts(store) == _weeks(0, 1, 3, 4)
    assert _starts(store, "Yoga (hall B)") == [later]
    moved = next(event for event in _listed(store) if event.start == later)
    assert moved.recurring_event_id == str(series_id)
    assert moved.recurrence == [f"RRULE:{WEEKLY}"]


def test_changing_this_occurrence_of_an_unsynced_series_splits_it_off() -> None:
    """Without a sync id an exception would hide the series; exdate is used."""
    store = _store()
    series_id = _series(store, synced=False)
    third = _occurrence(store, 2)
    changed = third.model_copy(update={"summary": "Yoga (hall B)"})
    provider = _provider(store)

    first = provider.update_occurrence(changed)
    again = provider.update_occurrence(changed)

    assert first.value is not None and again.value is not None
    assert first.value.recurring_event_id is None
    assert store.event_rows[series_id]["exdate"] == "20261215T090000Z"
    assert store.event_rows[series_id]["rrule"] == WEEKLY
    assert _starts(store) == _weeks(0, 1, 3, 4)
    assert _starts(store, "Yoga (hall B)") == _weeks(2)


def test_changing_an_occurrence_that_was_changed_before_updates_it() -> None:
    """A second edit rewrites the exception instead of adding another."""
    store = _store()
    _series(store)
    provider = _provider(store)
    provider.update_occurrence(
        _occurrence(store, 1).model_copy(update={"summary": "Yoga (hall B)"})
    )
    changed = next(
        event for event in _listed(store) if event.summary == "Yoga (hall B)"
    )

    provider.update_occurrence(changed.model_copy(update={"summary": "Yoga (hall C)"}))

    assert _starts(store, "Yoga (hall C)") == _weeks(1)
    assert _starts(store, "Yoga (hall B)") == []
    assert len(store.event_rows) == 2


def test_deleting_this_occurrence_cancels_only_it() -> None:
    """Synced series get a cancelled exception, unsynced ones an exdate."""
    synced = _store()
    _series(synced)
    unsynced = _store()
    unsynced_id = _series(unsynced, synced=False)

    for store in (synced, unsynced):
        assert (
            _provider(store).delete_occurrence(_occurrence(store, 1).id).error is None
        )
        assert _starts(store) == _weeks(0, 2, 3, 4)
    cancelled = [
        row for row in synced.event_rows.values() if row.get("original_id") is not None
    ]
    assert [row["eventStatus"] for row in cancelled] == [STATUS_CANCELED]
    assert unsynced.event_rows[unsynced_id]["exdate"] == "20261208T090000Z"


def test_deleting_a_changed_occurrence_cancels_its_exception() -> None:
    """Deleting the exception row would bring the original occurrence back."""
    store = _store()
    _series(store)
    provider = _provider(store)
    provider.update_occurrence(
        _occurrence(store, 1).model_copy(update={"summary": "Moved"})
    )
    changed = next(event for event in _listed(store) if event.summary == "Moved")

    assert provider.delete_occurrence(changed.id).error is None

    assert _starts(store) == _weeks(0, 2, 3, 4)
    assert _starts(store, "Moved") == []


def test_this_and_following_splits_the_series() -> None:
    """From 15 Dec on the class is at 18:00; the series before stays at 10:00."""
    store = _store()
    series_id = _series(store)
    third = _occurrence(store, 2)
    evening = third.start.replace(hour=18)

    result = _provider(store).update_following(
        third.model_copy(
            update={
                "summary": "Evening yoga",
                "start": evening,
                "end": evening + timedelta(hours=1),
            }
        )
    )

    assert result.error is None and result.value is not None
    assert store.event_rows[series_id]["rrule"] == (
        "FREQ=WEEKLY;BYDAY=TU;UNTIL=20261215T085959Z"
    )
    assert _starts(store) == _weeks(0, 1)
    assert _starts(store, "Evening yoga") == [
        evening,
        evening + WEEK,
        evening + 2 * WEEK,
    ]
    new_id = int(result.value.recurring_event_id or 0)
    assert new_id != series_id
    assert store.event_rows[new_id]["calendar_id"] == 1


def test_this_and_following_keeps_the_series_end_for_counted_rules() -> None:
    """COUNT=5 must not restart at the split: the new part ends on 29 Dec."""
    store = _store()
    _series(store)
    third = _occurrence(store, 2)

    result = _provider(store).update_following(
        third.model_copy(update={"summary": "New"})
    )

    assert result.value is not None
    new_row = store.event_rows[int(result.value.recurring_event_id or 0)]
    assert "COUNT" not in new_row["rrule"]
    assert _starts(store, "New") == _weeks(2, 3, 4)


def test_this_and_following_drops_later_changes_of_the_old_series() -> None:
    """A changed 22 Dec occurrence belongs to the part that is replaced."""
    store = _store()
    _series(store)
    provider = _provider(store)
    provider.update_occurrence(
        _occurrence(store, 3).model_copy(update={"summary": "Moved"})
    )
    provider.update_occurrence(
        _occurrence(store, 0).model_copy(update={"summary": "Kept"})
    )

    provider.update_following(
        _occurrence(store, 2).model_copy(update={"summary": "New"})
    )

    assert _starts(store, "Moved") == []
    assert _starts(store, "Kept") == _weeks(0)
    assert _starts(store, "New") == _weeks(2, 3, 4)


def test_this_and_following_from_the_first_occurrence_changes_the_series() -> None:
    """Splitting before the first occurrence would leave an empty series."""
    store = _store()
    series_id = _series(store)

    result = _provider(store).update_following(
        _occurrence(store, 0).model_copy(update={"summary": "Renamed"})
    )

    assert result.value is not None
    assert list(store.event_rows) == [series_id]
    assert _starts(store, "Renamed") == _weeks(0, 1, 2, 3, 4)


def test_this_and_following_without_a_rule_leaves_one_event() -> None:
    """Choosing "Does not repeat" ends the series with this single event."""
    store = _store()
    _series(store)

    result = _provider(store).update_following(
        _occurrence(store, 2).model_copy(update={"recurrence": None, "summary": "Last"})
    )

    assert result.value is not None and result.value.recurring_event_id is None
    assert _starts(store) == _weeks(0, 1)
    assert _starts(store, "Last") == _weeks(2)


def test_this_and_following_can_start_in_another_calendar() -> None:
    """The new part is created in the chosen calendar."""
    store = _store()
    _series(store)

    result = _provider(store).update_following(_occurrence(store, 2), calendar_id="2")

    assert result.value is not None and result.value.calendar_id == "2"
    rows = [row for row in store.event_rows.values() if row["calendar_id"] == 2]
    assert len(rows) == 1


def test_deleting_this_and_following_ends_the_series() -> None:
    """Deleting from 15 Dec keeps 1 and 8 Dec."""
    store = _store()
    _series(store)

    assert _provider(store).delete_following(_occurrence(store, 2).id).error is None

    assert _starts(store) == _weeks(0, 1)


def test_changing_all_events_keeps_their_changed_occurrences() -> None:
    """A new title for the series leaves a moved occurrence where it is."""
    store = _store()
    series_id = _series(store)
    provider = _provider(store)
    provider.update_occurrence(
        _occurrence(store, 3).model_copy(update={"summary": "Moved"})
    )

    result = provider.update_series(
        _occurrence(store, 1).model_copy(update={"summary": "Pilates"})
    )

    assert result.error is None
    assert store.event_rows[series_id]["title"] == "Pilates"
    assert _starts(store, "Pilates") == _weeks(0, 1, 2, 4)
    assert _starts(store, "Moved") == _weeks(3)


def test_moving_all_events_shifts_the_series_start() -> None:
    """Moving the 8 Dec class to 11:00 moves every class to 11:00."""
    store = _store()
    series_id = _series(store)
    provider = _provider(store)
    provider.update_occurrence(
        _occurrence(store, 3).model_copy(update={"summary": "Moved"})
    )
    second = _occurrence(store, 1)
    later = second.start + timedelta(hours=1)

    result = provider.update_series(
        second.model_copy(update={"start": later, "end": later + timedelta(minutes=90)})
    )

    assert result.value is not None
    assert result.value.start == later
    assert store.event_rows[series_id]["duration"] == "P5400S"
    assert _starts(store) == [
        start + timedelta(hours=1) for start in _weeks(0, 1, 2, 3, 4)
    ]
    assert _starts(store, "Moved") == []


def test_all_events_keep_their_wall_clock_time_across_daylight_saving() -> None:
    """A summer occurrence moved to 11:00 moves a winter series to 11:00."""
    store = _store()
    march = datetime(2027, 3, 2, 10, 0, tzinfo=PRAGUE)
    saved = (
        _provider(store)
        .create_event(
            _event(
                start=march,
                end=march + timedelta(hours=1),
                recurrence=["RRULE:FREQ=WEEKLY;COUNT=6;BYDAY=TU"],
            )
        )
        .value
    )
    assert saved is not None
    summer = next(
        event
        for event in _provider(store)
        .list_events(datetime(2027, 3, 1, tzinfo=UTC), datetime(2027, 5, 1, tzinfo=UTC))
        .value
        or []
        if event.start.date() == date(2027, 4, 6)
    )
    eleven = summer.start.replace(hour=11)

    _provider(store).update_series(
        summer.model_copy(update={"start": eleven, "end": eleven + timedelta(hours=1)})
    )

    row = next(iter(store.event_rows.values()))
    assert datetime.fromtimestamp(row["dtstart"] / 1000, PRAGUE) == march.replace(
        hour=11
    )


def test_all_events_without_a_rule_become_one_event() -> None:
    """Choosing "Does not repeat" for all events keeps this one."""
    store = _store()
    series_id = _series(store)

    result = _provider(store).update_series(
        _occurrence(store, 2).model_copy(update={"recurrence": None})
    )

    assert result.value is not None and result.value.id == str(series_id)
    assert store.event_rows[series_id]["rrule"] is None
    assert _starts(store) == _weeks(2)


def test_deleting_all_events_removes_the_series_and_its_changes() -> None:
    store = _store()
    _series(store)
    provider = _provider(store)
    provider.update_occurrence(
        _occurrence(store, 3).model_copy(update={"summary": "Moved"})
    )

    assert provider.delete_series(_occurrence(store, 1).id).error is None

    assert store.event_rows == {}


def test_moving_a_series_keeps_its_cancelled_and_changed_occurrences() -> None:
    """The copy has no sync id yet: changes become exdates and own events."""
    store = _store()
    _series(store)
    provider = _provider(store)
    provider.delete_occurrence(_occurrence(store, 1).id)
    provider.update_occurrence(
        _occurrence(store, 3).model_copy(update={"summary": "Moved"})
    )

    result = provider.move_series(_occurrence(store, 0).id, "2")

    assert result.error is None and result.value is not None
    assert result.value.calendar_id == "2"
    assert {row["calendar_id"] for row in store.event_rows.values()} == {2}
    assert _starts(store) == _weeks(0, 2, 4)
    assert _starts(store, "Moved") == _weeks(3)


def test_occurrence_operations_need_an_occurrence_id() -> None:
    """A single event's id is not an occurrence; a gone series is NOT_FOUND."""
    store = _store()
    provider = _provider(store)
    single = provider.create_event(_event(recurrence=None)).value
    assert single is not None

    wrong = provider.delete_occurrence(single.id)
    gone = provider.delete_series(f"999_{millis(FIRST)}")

    assert wrong.error is not None and wrong.error.code == ErrorCode.INVALID_ARGUMENT
    assert gone.error is not None and gone.error.code == ErrorCode.NOT_FOUND
