"""Tests for the real Google Calendar provider adapter.

Every test mocks the Google service object.  No credentials, network calls, or
real calendars are involved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from core.errors import ErrorCode, Result
from domain.event import Event
from google.auth.exceptions import RefreshError
from google_calendar import google_provider
from google_calendar.google_provider import (
    GoogleCalendarProvider,
    generate_event_id,
)
from google_calendar.provider import CalendarProvider
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

BERLIN = ZoneInfo("Europe/Berlin")


def _event(
    event_id: str = "event1",
    *,
    summary: str = "Team standup",
    calendar_id: str = "",
) -> Event:
    start = datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN)
    return Event(
        id=event_id,
        calendar_id=calendar_id,
        summary=summary,
        description="Daily sync",
        start=start,
        end=start + timedelta(minutes=30),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        recurrence=["RRULE:FREQ=WEEKLY"],
        extended_properties={"color": "blue"},
    )


def _resource(
    event_id: str = "event1",
    *,
    summary: str = "Team standup",
    **overrides: Any,
) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "id": event_id,
        "summary": summary,
        "description": "Daily sync",
        "start": {
            "dateTime": "2026-11-06T09:00:00+01:00",
            "timeZone": "Europe/Berlin",
        },
        "end": {
            "dateTime": "2026-11-06T09:30:00+01:00",
            "timeZone": "Europe/Berlin",
        },
        "recurrence": ["RRULE:FREQ=WEEKLY"],
        "extendedProperties": {"private": {"color": "blue"}},
    }
    resource.update(overrides)
    return resource


def _calendar_item(
    calendar_id: str = "primary",
    **overrides: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {"id": calendar_id, "accessRole": "owner"}
    item.update(overrides)
    return item


def _calendar_list(*items: object) -> dict[str, Any]:
    return {"items": list(items)}


def _primary_calendar_list() -> dict[str, Any]:
    return _calendar_list(_calendar_item("primary"))


def _all_day_resource(event_id: str = "all-day") -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": "Holiday",
        "start": {"date": "2026-11-06"},
        "end": {"date": "2026-11-07"},
    }


def _offset_only_resource(
    event_id: str = "offset1",
    *,
    start: str = "2026-11-06T09:00:00+05:00",
    end: str = "2026-11-06T09:30:00+05:00",
) -> dict[str, Any]:
    """Return a timed resource that carries an offset but no ``timeZone``."""
    return {
        "id": event_id,
        "summary": "Offset-only event",
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }


class _Response:
    """The minimal response object ``HttpError`` reads."""

    def __init__(self, status: int, reason: str = "error") -> None:
        self.status = status
        self.reason = reason


def _http_error(status: int) -> HttpError:
    content = json.dumps({"error": {"message": f"HTTP {status}"}}).encode()
    return HttpError(_Response(status), content, uri="https://example.test")


def _event_result(result: Result[Event]) -> Event:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


def _loaded_event(result: Result[Event | None]) -> Event:
    assert result.is_ok, result.error
    assert result.value is not None
    return result.value


@pytest.fixture
def service() -> Mock:
    """Return a mock Google Calendar service object."""
    return Mock()


@pytest.fixture
def provider(service: Mock) -> GoogleCalendarProvider:
    """Return a provider wired to the mock service."""
    return GoogleCalendarProvider(service, "primary")


def test_google_provider_satisfies_the_interface(
    provider: GoogleCalendarProvider,
) -> None:
    """The real provider is usable wherever the protocol is expected."""
    assert isinstance(provider, CalendarProvider)


def test_create_maps_the_event_to_a_google_payload(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Create sends the client id, timed values, recurrence, and private data."""
    event = _event()
    insert = service.events.return_value.insert
    insert.return_value.execute.return_value = _resource()

    result = provider.create_event(event)

    assert _event_result(result) == event.model_copy(
        update={"calendar_id": "primary"}
    )
    insert.assert_called_once()
    call = insert.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["body"] == {
        "id": event.id,
        "summary": "Team standup",
        "description": "Daily sync",
        "start": {
            "dateTime": event.start.isoformat(),
            "timeZone": "Europe/Berlin",
        },
        "end": {
            "dateTime": event.end.isoformat(),
            "timeZone": "Europe/Berlin",
        },
        "recurrence": ["RRULE:FREQ=WEEKLY"],
        "extendedProperties": {"private": {"color": "blue"}},
    }


def test_update_patches_the_event_id_and_new_payload(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Update patches the same client-generated id instead of replacing it."""
    event = _event(summary="Updated standup")
    patch = service.events.return_value.patch
    patch.return_value.execute.return_value = _resource(
        summary="Updated standup",
        location="Room 1",
    )

    result = provider.update_event(event)

    assert _event_result(result) == event.model_copy(
        update={"calendar_id": "primary"}
    )
    service.events.return_value.update.assert_not_called()
    patch.assert_called_once()
    call = patch.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["eventId"] == event.id
    assert call["body"]["summary"] == "Updated standup"
    assert "location" not in call["body"]


@pytest.mark.parametrize(
    "event_id",
    ["abcd", "event-1", "EVENT1", "event_1", "wxyz1"],
)
def test_create_rejects_ids_google_would_reject(
    provider: GoogleCalendarProvider,
    service: Mock,
    event_id: str,
) -> None:
    """Invalid ids never reach Google, which would reject them itself."""
    result = provider.create_event(_event(event_id))

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT
    assert "base32hex" in result.error.message
    service.events.return_value.insert.assert_not_called()


def test_update_rejects_ids_google_would_reject(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Updates validate the id before issuing a patch."""
    result = provider.update_event(_event("event-1"))

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT
    service.events.return_value.patch.assert_not_called()


def test_generate_event_id_satisfies_google_constraints() -> None:
    """The helper returns a base32hex id within Google's length bounds."""
    event_id = generate_event_id()

    assert 5 <= len(event_id) <= 1024
    assert all(
        character in "0123456789abcdefghijklmnopqrstuv" for character in event_id
    )


def test_create_targets_the_event_calendar_when_set(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An event's own calendar overrides the provider default."""
    event = _event(calendar_id="work@example.com")
    insert = service.events.return_value.insert
    insert.return_value.execute.return_value = _resource()

    result = provider.create_event(event)

    assert insert.call_args.kwargs["calendarId"] == "work@example.com"
    assert _event_result(result).calendar_id == "work@example.com"


def test_update_targets_the_event_calendar_when_set(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An edit stays in the calendar the event came from."""
    event = _event(calendar_id="work@example.com")
    patch = service.events.return_value.patch
    patch.return_value.execute.return_value = _resource()

    result = provider.update_event(event)

    assert patch.call_args.kwargs["calendarId"] == "work@example.com"
    assert _event_result(result).calendar_id == "work@example.com"


def test_create_event_targets_a_series_override_when_set(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An event that names a series saves the occurrence slot instead."""
    event = _event()
    event.recurring_event_id = "series-1"
    insert = service.events.return_value.insert
    insert.return_value.execute.return_value = _resource(recurringEventId="series-1")

    result = provider.create_event(event)

    assert result.is_ok
    insert.assert_called_once()
    call = insert.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["body"]["recurringEventId"] == "series-1"
    assert "id" not in call["body"]


def test_update_event_targets_a_series_override_when_set(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An edited occurrence is saved through its series override."""
    event = _event()
    event.recurring_event_id = "series-1"
    insert = service.events.return_value.insert
    insert.return_value.execute.return_value = _resource(recurringEventId="series-1")

    result = provider.update_event(event)

    assert result.is_ok
    service.events.return_value.patch.assert_not_called()
    insert.assert_called_once()
    call = insert.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["body"]["recurringEventId"] == "series-1"
    assert "id" not in call["body"]


def test_get_maps_the_recurring_event_id(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A returned occurrence keeps the id of the series it belongs to."""
    service.events.return_value.get.return_value.execute.return_value = _resource(
        recurringEventId="series-1",
    )

    result = provider.get_event("primary", "event1")

    assert result.is_ok
    assert result.value is not None
    assert result.value.recurring_event_id == "series-1"


def test_delete_calls_google_and_returns_unit(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Delete uses the passed calendar and treats an empty response as success."""
    delete = service.events.return_value.delete
    delete.return_value.execute.return_value = None

    result = provider.delete_event("work@example.com", "event1")

    assert result.is_ok
    assert result.value is None
    assert delete.call_args.kwargs == {
        "calendarId": "work@example.com",
        "eventId": "event1",
    }


def test_delete_falls_back_to_the_default_calendar(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A blank calendar id uses the provider's configured default."""
    delete = service.events.return_value.delete
    delete.return_value.execute.return_value = None

    result = provider.delete_event("", "event1")

    assert result.is_ok
    assert delete.call_args.kwargs["calendarId"] == "primary"


def test_get_maps_private_properties_only(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Shared extended properties are ignored on read."""
    resource = _resource(
        extendedProperties={
            "private": {"color": "blue"},
            "shared": {"visible": "to everyone"},
        }
    )
    service.events.return_value.get.return_value.execute.return_value = resource

    result = provider.get_event("primary", "event1")

    event = _loaded_event(result)
    assert event.extended_properties == {"color": "blue"}


def test_get_uses_the_passed_calendar_and_tags_the_event(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Reads target the requested calendar and keep its id on the event."""
    get = service.events.return_value.get
    get.return_value.execute.return_value = _resource()

    event = _loaded_event(provider.get_event("work@example.com", "event1"))

    assert get.call_args.kwargs == {
        "calendarId": "work@example.com",
        "eventId": "event1",
    }
    assert event.calendar_id == "work@example.com"


def test_get_falls_back_to_the_default_calendar(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A blank calendar id reads from the provider's configured default."""
    get = service.events.return_value.get
    get.return_value.execute.return_value = _resource()

    event = _loaded_event(provider.get_event("", "event1"))

    assert get.call_args.kwargs["calendarId"] == "primary"
    assert event.calendar_id == "primary"


def test_get_maps_a_timed_event_without_a_description_or_recurrence(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Optional fields are not invented when Google omits them."""
    resource = _resource()
    resource.pop("description")
    resource.pop("recurrence")
    resource.pop("extendedProperties")
    service.events.return_value.get.return_value.execute.return_value = resource

    result = _loaded_event(provider.get_event("primary", "event1"))

    assert result.description is None
    assert result.recurrence is None
    assert result.extended_properties == {}


@pytest.mark.parametrize("status", [404, 410])
def test_get_returns_none_for_a_missing_event(
    provider: GoogleCalendarProvider,
    service: Mock,
    status: int,
) -> None:
    """A missing upstream event is a successful empty lookup."""
    service.events.return_value.get.return_value.execute.side_effect = _http_error(
        status
    )

    result = provider.get_event("primary", "missing")

    assert result.is_ok
    assert result.value is None


def test_get_maps_an_all_day_event(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """All-day events are mapped to whole-day timed events."""
    service.events.return_value.get.return_value.execute.return_value = (
        _all_day_resource()
    )

    event = _loaded_event(provider.get_event("primary", "all-day"))

    assert event.id == "all-day"
    assert event.summary == "Holiday"
    assert event.all_day is True
    assert event.start.date().isoformat() == "2026-11-06"
    # Google end dates are exclusive, so a one-day event ends on the next day.
    assert event.end.date().isoformat() == "2026-11-07"
    assert event.start_timezone == "UTC"
    assert event.end_timezone == "UTC"


def test_get_maps_an_offset_only_utc_event_to_utc(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A missing ``timeZone`` with a zero offset is unambiguously UTC."""
    service.events.return_value.get.return_value.execute.return_value = (
        _offset_only_resource(
            start="2026-11-06T09:00:00Z",
            end="2026-11-06T09:30:00Z",
        )
    )

    event = _loaded_event(provider.get_event("primary", "offset1"))

    assert event.start_timezone == "UTC"
    assert event.end_timezone == "UTC"
    assert event.start == datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
    assert event.end == datetime(2026, 11, 6, 9, 30, tzinfo=UTC)


def test_get_rejects_an_offset_only_non_utc_event(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A non-zero offset alone cannot be mapped to an IANA zone."""
    service.events.return_value.get.return_value.execute.return_value = (
        _offset_only_resource()
    )

    result = provider.get_event("primary", "offset1")

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_EVENT
    assert "IANA" in result.error.message


def test_list_skips_an_offset_only_non_utc_event(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """One unmappable event does not abort the rest of the sync."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _primary_calendar_list()
    )
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            _offset_only_resource("offset1"),
            _resource("valid1", recurrence=None),
        ]
    }

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == ["valid1"]


def test_list_calendars_maps_summaries_and_marks_the_primary(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Readable calendars are listed with their names, primary first."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _calendar_list(
            _calendar_item(
                "work@example.com",
                summary="Work",
                accessRole="writer",
            ),
            _calendar_item(
                "reader@example.com",
                summary="Shared",
                accessRole="reader",
            ),
            _calendar_item(
                "primary",
                summary="Personal",
                summaryOverride="Me",
                primary=True,
            ),
            _calendar_item("hidden", summary="Hidden", selected=False),
        )
    )

    result = provider.list_calendars()

    assert result.is_ok
    assert result.value is not None
    assert [(calendar.id, calendar.summary, calendar.primary) for calendar in result.value] == [
        ("primary", "Me", True),
        ("reader@example.com", "Shared", False),
        ("work@example.com", "Work", False),
    ]


def test_list_calendars_includes_the_configured_default(
    service: Mock,
) -> None:
    """The configured calendar is offered even when Google omits it."""
    provider = GoogleCalendarProvider(service, "team@example.com")
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _calendar_list(_calendar_item("work@example.com", summary="Work"))
    )

    result = provider.list_calendars()

    assert result.is_ok
    assert result.value is not None
    assert [(calendar.id, calendar.summary) for calendar in result.value] == [
        ("team@example.com", "team@example.com"),
        ("work@example.com", "Work"),
    ]


def test_move_event_calls_google_move_and_maps_the_result(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Moving an event uses Google's dedicated move operation."""
    move = service.events.return_value.move
    move.return_value.execute.return_value = _resource("event1", summary="Moved")

    result = provider.move_event("primary", "event1", "work@example.com")

    assert result.is_ok
    assert result.value is not None
    assert result.value.calendar_id == "work@example.com"
    assert move.call_args.kwargs == {
        "calendarId": "primary",
        "eventId": "event1",
        "destination": "work@example.com",
    }


def test_move_event_rejects_a_blank_destination(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A move without a destination is an invalid argument."""
    result = provider.move_event("primary", "event1", " ")

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT
    service.events.return_value.move.assert_not_called()


def test_list_follows_pagination_and_maps_all_day_events(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Every page is fetched and all-day entries are included."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _primary_calendar_list()
    )
    list_request = service.events.return_value.list
    list_request.return_value.execute.side_effect = [
        {
            "items": [_all_day_resource(), _resource("first", recurrence=None)],
            "nextPageToken": "next-page",
        },
        {"items": [_resource("second", summary="Second", recurrence=None)]},
    ]

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == ["all-day", "first", "second"]
    assert result.value[0].all_day is True
    first_call, second_call = list_request.call_args_list
    assert first_call.kwargs == {
        "calendarId": "primary",
        "maxResults": 2500,
        "singleEvents": False,
        "showDeleted": False,
    }
    assert second_call.kwargs["pageToken"] == "next-page"


def test_list_expands_a_recurring_event_into_occurrences(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A recurring series becomes one event per occurrence."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _primary_calendar_list()
    )
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [_resource("weekly", recurrence=["RRULE:FREQ=WEEKLY;COUNT=3"])],
    }

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == [
        "weekly:2026-11-06T08:00:00+00:00",
        "weekly:2026-11-13T08:00:00+00:00",
        "weekly:2026-11-20T08:00:00+00:00",
    ]
    assert all(event.recurrence is None for event in result.value)
    assert result.value[0].summary == "Team standup"
    assert result.value[0].start_timezone == "Europe/Berlin"


def test_list_keeps_the_series_when_the_rule_is_unsupported(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An unexpandable rule keeps the series event instead of failing the sync."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _primary_calendar_list()
    )
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [_resource("hourly", recurrence=["RRULE:FREQ=HOURLY"])],
    }

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == ["hourly"]
    assert result.value[0].recurrence == ["RRULE:FREQ=HOURLY"]


def test_list_stops_when_google_returns_no_items(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An empty response is an empty calendar."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _primary_calendar_list()
    )
    service.events.return_value.list.return_value.execute.return_value = {}

    result = provider.list_events()

    assert result.is_ok
    assert result.value == []


def test_list_reads_every_discovered_calendar_and_tags_events(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Events from all readable calendars are concatenated with their owner."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _calendar_list(
            _calendar_item("primary"),
            _calendar_item("work@example.com", accessRole="writer"),
        )
    )
    list_request = service.events.return_value.list
    list_request.return_value.execute.side_effect = [
        {"items": [_resource("primary-event", recurrence=None)]},
        {"items": [_resource("work-event", summary="Work standup", recurrence=None)]},
    ]

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == [
        "primary-event",
        "work-event",
    ]
    assert result.value[0].calendar_id == "primary"
    assert result.value[1].calendar_id == "work@example.com"
    assert [
        call.kwargs["calendarId"] for call in list_request.call_args_list
    ] == ["primary", "work@example.com"]


def test_calendar_list_follows_pagination(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """The calendar list is paginated like the event list."""
    calendar_list = service.calendarList.return_value.list
    calendar_list.return_value.execute.side_effect = [
        {
            "items": [_calendar_item("work@example.com")],
            "nextPageToken": "next-calendar",
        },
        {"items": [_calendar_item("shared@example.com", accessRole="reader")]},
    ]
    list_request = service.events.return_value.list
    list_request.return_value.execute.return_value = {}

    result = provider.list_events()

    assert result.is_ok
    first_call, second_call = calendar_list.call_args_list
    assert first_call.kwargs == {"maxResults": 2500}
    assert second_call.kwargs == {
        "maxResults": 2500,
        "pageToken": "next-calendar",
    }
    assert [
        call.kwargs["calendarId"] for call in list_request.call_args_list
    ] == ["primary", "work@example.com", "shared@example.com"]


def test_calendar_list_skips_unusable_entries(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Unselected, deleted, read-only-free, and malformed entries are skipped."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _calendar_list(
            _calendar_item("hidden", selected=False),
            _calendar_item("deleted", deleted=True),
            _calendar_item("busy-only", accessRole="freeBusyReader"),
            {"id": "missing-role"},
            {"id": "", "accessRole": "owner"},
            {"accessRole": "owner"},
            "not-an-object",
            _calendar_item("work@example.com"),
        )
    )
    list_request = service.events.return_value.list
    list_request.return_value.execute.return_value = {}

    result = provider.list_events()

    assert result.is_ok
    assert [
        call.kwargs["calendarId"] for call in list_request.call_args_list
    ] == ["primary", "work@example.com"]


def test_calendar_list_includes_the_configured_default_first(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An empty discovery result still reads the configured default calendar."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _calendar_list(_calendar_item("work@example.com"))
    )
    list_request = service.events.return_value.list
    list_request.return_value.execute.return_value = {}

    provider.list_events()

    assert [
        call.kwargs["calendarId"] for call in list_request.call_args_list
    ] == ["primary", "work@example.com"]


def test_calendar_list_failure_with_a_missing_scope_is_actionable(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An auth failure explains how to grant the calendar-list scope."""
    service.calendarList.return_value.list.return_value.execute.side_effect = (
        _http_error(403)
    )

    result = provider.list_events()

    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_ERROR
    assert "python -m google_calendar.auth" in result.error.message
    assert "calendar.calendarlist.readonly" in result.error.message


def test_calendar_list_refresh_failure_is_actionable(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A refresh failure before calendar discovery points at the helper."""
    service.calendarList.return_value.list.return_value.execute.side_effect = (
        RefreshError("invalid_scope")
    )

    result = provider.list_events()

    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_ERROR
    assert "python -m google_calendar.auth" in result.error.message


def test_list_deduplicates_the_same_event_across_calendars(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An event visible through two calendars is returned only once."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _calendar_list(
            _calendar_item("primary"),
            _calendar_item("work@example.com"),
        )
    )
    list_request = service.events.return_value.list
    list_request.return_value.execute.side_effect = [
        {"items": [_resource("shared-event", recurrence=None)]},
        {
            "items": [
                _resource("shared-event", summary="Same event elsewhere", recurrence=None),
                _resource("other-event", recurrence=None),
            ]
        },
    ]

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == [
        "shared-event",
        "other-event",
    ]
    assert result.value[0].calendar_id == "primary"
    assert result.value[0].summary == "Team standup"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, ErrorCode.INVALID_ARGUMENT),
        (401, ErrorCode.AUTH_ERROR),
        (404, ErrorCode.NOT_FOUND),
        (410, ErrorCode.NOT_FOUND),
        (409, ErrorCode.ALREADY_EXISTS),
        (429, ErrorCode.UPSTREAM_ERROR),
        (500, ErrorCode.UPSTREAM_ERROR),
        (503, ErrorCode.UPSTREAM_ERROR),
        (418, ErrorCode.UPSTREAM_ERROR),
    ],
)
def test_http_statuses_map_to_error_codes(
    provider: GoogleCalendarProvider,
    service: Mock,
    status: int,
    expected: ErrorCode,
) -> None:
    """Google HTTP failures become stable result codes."""
    service.events.return_value.insert.return_value.execute.side_effect = (
        _http_error(status)
    )

    result = provider.create_event(_event())

    assert result.error is not None
    assert result.error.code is expected


def test_refresh_failures_map_to_auth_errors(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A revoked or invalid refresh token is a permanent authentication error."""
    service.events.return_value.insert.return_value.execute.side_effect = (
        RefreshError("invalid_grant: token has been revoked")
    )

    result = provider.create_event(_event())

    assert result.error is not None
    assert result.error.code is ErrorCode.AUTH_ERROR
    assert "authentication" in result.error.message


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("timed out"),
        ConnectionError("connection reset"),
        OSError("network unreachable"),
        RuntimeError("unexpected client failure"),
    ],
)
def test_network_and_unknown_failures_are_upstream_errors(
    provider: GoogleCalendarProvider,
    service: Mock,
    failure: Exception,
) -> None:
    """No operational exception escapes the provider."""
    service.events.return_value.insert.return_value.execute.side_effect = failure

    result = provider.create_event(_event())

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR


def test_list_failures_do_not_escape(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A network failure while listing is returned, not raised."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _primary_calendar_list()
    )
    service.events.return_value.list.return_value.execute.side_effect = (
        ConnectionError("offline")
    )

    result = provider.list_events()

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR


def test_calendar_list_non_auth_failures_keep_their_mapping(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A server failure during discovery is still an upstream error."""
    service.calendarList.return_value.list.return_value.execute.side_effect = (
        _http_error(500)
    )

    result = provider.list_events()

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR


def test_request_construction_failures_do_not_escape(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A broken discovery client is reported instead of raised."""
    service.events.side_effect = RuntimeError("client is broken")

    result = provider.create_event(_event())

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert "client is broken" in result.error.message


def test_invalid_timed_payload_is_reported(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Malformed Google resources become INVALID_EVENT results."""
    resource = _resource(start={"dateTime": "not-a-time", "timeZone": "UTC"})
    service.events.return_value.get.return_value.execute.return_value = resource

    result = provider.get_event("primary", "event1")

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_EVENT


def test_from_credentials_builds_the_calendar_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory constructs a v3 calendar client from credentials."""
    service = Mock()
    build = Mock(return_value=service)
    monkeypatch.setattr(google_provider, "build", build)
    credentials = Mock()

    result = GoogleCalendarProvider.from_credentials(
        credentials,
        calendar_id="calendar-id",
    )

    assert result.is_ok
    assert result.value is not None
    build.assert_called_once_with(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def test_from_credentials_maps_service_construction_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken credential setup is an upstream error, not a crash."""
    monkeypatch.setattr(
        google_provider,
        "build",
        Mock(side_effect=RuntimeError("bad credentials")),
    )

    result = GoogleCalendarProvider.from_credentials(Mock())

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR


def test_from_credentials_rejects_a_blank_calendar_id() -> None:
    """The factory validates its calendar id before building a service."""
    result = GoogleCalendarProvider.from_credentials(Mock(), calendar_id=" ")

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT


def test_create_maps_an_all_day_event_to_date_fields(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """All-day events are written with Google date-only fields."""
    event = Event(
        id="event1",
        summary="Holiday",
        all_day=True,
        start=datetime(2026, 11, 6, 0, 0, tzinfo=ZoneInfo("UTC")),
        end=datetime(2026, 11, 7, 0, 0, tzinfo=ZoneInfo("UTC")),
        start_timezone="UTC",
        end_timezone="UTC",
    )
    insert = service.events.return_value.insert
    insert.return_value.execute.return_value = _all_day_resource("allday1")

    result = provider.create_event(event)

    assert result.is_ok
    body = insert.call_args.kwargs["body"]
    assert body["start"] == {"date": "2026-11-06"}
    assert body["end"] == {"date": "2026-11-07"}
    assert "dateTime" not in body["start"]
    assert "dateTime" not in body["end"]


def test_update_maps_an_all_day_event_to_date_fields(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """All-day event edits use date-only fields in the patch payload."""
    event = Event(
        id="event1",
        summary="Holiday",
        all_day=True,
        start=datetime(2026, 11, 6, 0, 0, tzinfo=ZoneInfo("UTC")),
        end=datetime(2026, 11, 8, 0, 0, tzinfo=ZoneInfo("UTC")),
        start_timezone="UTC",
        end_timezone="UTC",
    )
    patch = service.events.return_value.patch
    patch.return_value.execute.return_value = {
        "id": "event1",
        "summary": "Holiday",
        "start": {"date": "2026-11-06"},
        "end": {"date": "2026-11-08"},
    }

    result = provider.update_event(event)

    assert result.is_ok
    body = patch.call_args.kwargs["body"]
    assert body["start"] == {"date": "2026-11-06"}
    assert body["end"] == {"date": "2026-11-08"}


def test_list_maps_multi_day_all_day_event(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """A multi-day all-day event keeps its full exclusive span."""
    service.calendarList.return_value.list.return_value.execute.return_value = (
        _primary_calendar_list()
    )
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "trip",
                "summary": "Trip",
                "start": {"date": "2026-11-06"},
                "end": {"date": "2026-11-10"},
            }
        ]
    }

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    event = result.value[0]
    assert event.all_day is True
    assert event.start.date().isoformat() == "2026-11-06"
    assert event.end.date().isoformat() == "2026-11-10"
