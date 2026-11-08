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
) -> Event:
    start = datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN)
    return Event(
        id=event_id,
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

    assert _event_result(result) == event
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

    assert _event_result(result) == event
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


def test_delete_calls_google_and_returns_unit(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Delete uses the event id and treats an empty response as success."""
    delete = service.events.return_value.delete
    delete.return_value.execute.return_value = None

    result = provider.delete_event("event1")

    assert result.is_ok
    assert result.value is None
    assert delete.call_args.kwargs == {
        "calendarId": "primary",
        "eventId": "event1",
    }


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

    result = provider.get_event("event1")

    event = _loaded_event(result)
    assert event.extended_properties == {"color": "blue"}


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

    result = _loaded_event(provider.get_event("event1"))

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

    result = provider.get_event("missing")

    assert result.is_ok
    assert result.value is None


def test_get_rejects_an_all_day_event_with_a_clear_error(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """All-day events are unsupported and reported, never crashed on."""
    service.events.return_value.get.return_value.execute.return_value = (
        _all_day_resource()
    )

    result = provider.get_event("all-day")

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_EVENT
    assert "all-day" in result.error.message


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

    event = _loaded_event(provider.get_event("offset1"))

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

    result = provider.get_event("offset1")

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_EVENT
    assert "IANA" in result.error.message


def test_list_skips_an_offset_only_non_utc_event(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """One unmappable event does not abort the rest of the sync."""
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            _offset_only_resource("offset1"),
            _resource("valid1"),
        ]
    }

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == ["valid1"]


def test_list_follows_pagination_and_skips_all_day_events(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """Every page is fetched and all-day entries are omitted."""
    list_request = service.events.return_value.list
    list_request.return_value.execute.side_effect = [
        {
            "items": [_all_day_resource(), _resource("first")],
            "nextPageToken": "next-page",
        },
        {"items": [_resource("second", summary="Second")]},
    ]

    result = provider.list_events()

    assert result.is_ok
    assert result.value is not None
    assert [event.id for event in result.value] == ["first", "second"]
    first_call, second_call = list_request.call_args_list
    assert first_call.kwargs == {
        "calendarId": "primary",
        "maxResults": 2500,
        "singleEvents": False,
        "showDeleted": False,
    }
    assert second_call.kwargs["pageToken"] == "next-page"


def test_list_stops_when_google_returns_no_items(
    provider: GoogleCalendarProvider,
    service: Mock,
) -> None:
    """An empty response is an empty calendar."""
    service.events.return_value.list.return_value.execute.return_value = {}

    result = provider.list_events()

    assert result.is_ok
    assert result.value == []


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
    service.events.return_value.list.return_value.execute.side_effect = (
        ConnectionError("offline")
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

    result = provider.get_event("event1")

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
