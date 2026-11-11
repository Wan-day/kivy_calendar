"""Tests for the Kivy backend API client."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from datetime import datetime
from email.message import Message
from typing import Literal, Self

import pytest

from kivy_calendar.api import (
    BackendClient,
    BackendError,
    CalendarEvent,
    CalendarSummary,
    FreeSlot,
)

BASE_URL = "http://backend.test"


class _FakeResponse:
    """Minimal context-manager response double for ``urlopen``."""

    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        """Return the stored payload bytes."""
        return self._raw

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        return False


def _client() -> BackendClient:
    return BackendClient(BASE_URL, "test-token")


def test_list_events_returns_backend_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client maps backend event payloads into client events."""

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        return _FakeResponse(
            [
                {
                    "id": "event-1",
                    "summary": "Team standup",
                    "start": "2026-11-06T09:00:00+01:00",
                    "end": "2026-11-06T09:30:00+01:00",
                    "start_timezone": "Europe/Berlin",
                    "end_timezone": "Europe/Berlin",
                    "calendar_id": "work@example.com",
                },
            ],
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    events = _client().list_events()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, CalendarEvent)
    assert event.id == "event-1"
    assert event.summary == "Team standup"
    assert event.calendar_id == "work@example.com"
    assert event.start == datetime.fromisoformat("2026-11-06T09:00:00+01:00")
    assert event.end == datetime.fromisoformat("2026-11-06T09:30:00+01:00")


def test_list_calendars_returns_backend_calendars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client maps backend calendar payloads into client calendars."""

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        return _FakeResponse(
            [
                {"id": "primary", "summary": "Primary", "primary": True},
                {"id": "work@example.com", "summary": "Work"},
            ]
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    calendars = _client().list_calendars()

    assert calendars == [
        CalendarSummary(id="primary", summary="Primary", primary=True),
        CalendarSummary(id="work@example.com", summary="Work", primary=False),
    ]


def test_list_calendars_rejects_a_payload_without_an_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed calendar entry is reported as an invalid response."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=0: _FakeResponse([{"summary": "Work"}]),
    )

    with pytest.raises(BackendError) as error_info:
        _client().list_calendars()

    assert error_info.value.code == "invalid_response"


def test_create_event_posts_the_backend_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client sends a client-generated event id to the backend."""

    captured: dict[str, object] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        captured["url"] = str(request.full_url)
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode())
        return _FakeResponse(
            {
                "id": "event-1",
                "summary": "Team standup",
                "start": "2026-11-06T09:00:00+01:00",
                "end": "2026-11-06T09:30:00+01:00",
                "start_timezone": "Europe/Berlin",
                "end_timezone": "Europe/Berlin",
                "calendar_id": "work@example.com",
            },
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    event = CalendarEvent(
        id="event-1",
        summary="Team standup",
        start=datetime.fromisoformat("2026-11-06T09:00:00+01:00"),
        end=datetime.fromisoformat("2026-11-06T09:30:00+01:00"),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
        calendar_id="work@example.com",
    )
    created = _client().create_event(event)

    assert created.id == "event-1"
    assert created.calendar_id == "work@example.com"
    assert captured["url"] == f"{BASE_URL}/events"
    assert captured["method"] == "POST"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["calendar_id"] == "work@example.com"


def test_update_event_patches_the_event_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client PATCHes the event URL with the updated payload."""

    captured: dict[str, str] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        captured["url"] = str(request.full_url)
        captured["method"] = request.get_method()
        return _FakeResponse(
            {
                "id": "event-1",
                "summary": "Team standup",
                "start": "2026-11-06T10:00:00+01:00",
                "end": "2026-11-06T10:30:00+01:00",
                "start_timezone": "Europe/Berlin",
                "end_timezone": "Europe/Berlin",
            },
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    event = CalendarEvent(
        id="event-1",
        summary="Team standup",
        start=datetime.fromisoformat("2026-11-06T10:00:00+01:00"),
        end=datetime.fromisoformat("2026-11-06T10:30:00+01:00"),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
    )
    updated = _client().update_event(event)

    assert updated.start == datetime.fromisoformat("2026-11-06T10:00:00+01:00")
    assert captured["url"] == f"{BASE_URL}/events/event-1"
    assert captured["method"] == "PATCH"


def test_delete_event_sends_a_delete_and_quotes_the_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client sends DELETE and accepts the empty 204 response."""

    captured: dict[str, str] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        captured["url"] = str(request.full_url)
        captured["method"] = request.get_method()
        return _FakeResponse(None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    _client().delete_event("event/1")

    assert captured["url"] == f"{BASE_URL}/events/event%2F1"
    assert captured["method"] == "DELETE"


def test_list_events_raises_backend_error_on_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backend HTTP error bodies are turned into client errors."""

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        error = urllib.error.HTTPError(
            url=str(request.full_url),
            code=404,
            msg="Not Found",
            hdrs=Message(),
            fp=io.BytesIO(b'{"error": {"code": "not_found", "message": "not cached"}}'),
        )
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(BackendError) as exc_info:
        _client().list_events()

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "not_found"
    assert exc_info.value.message == "not cached"


def test_sync_posts_and_returns_the_synced_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client asks the backend to sync and returns the event count."""

    captured: dict[str, str] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        captured["url"] = str(request.full_url)
        captured["method"] = request.get_method()
        return _FakeResponse({"synced": 4})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert _client().sync() == 4
    assert captured["url"] == f"{BASE_URL}/sync"
    assert captured["method"] == "POST"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"synced": "4"},
        {"synced": True},
        {"synced": None},
    ],
)
def test_sync_rejects_a_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    """A response without an integer synced count is a backend error."""

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(BackendError) as exc_info:
        _client().sync()

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "invalid_response"


def test_find_free_slots_posts_the_window_and_parses_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client sends the request body and maps slots into values."""

    captured: dict[str, object] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        captured["url"] = str(request.full_url)
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode())
        return _FakeResponse(
            {
                "slots": [
                    {
                        "start": "2026-11-09T09:00:00+01:00",
                        "end": "2026-11-09T09:30:00+01:00",
                    },
                    {
                        "start": "2026-11-10T14:00:00+01:00",
                        "end": "2026-11-10T14:30:00+01:00",
                    },
                ],
            },
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    window_start = datetime.fromisoformat("2026-11-09T08:00:00+01:00")
    window_end = datetime.fromisoformat("2026-11-16T08:00:00+01:00")

    slots = _client().find_free_slots(
        30,
        window_start,
        window_end,
        "Europe/Berlin",
    )

    assert slots == [
        FreeSlot(
            start=datetime.fromisoformat("2026-11-09T09:00:00+01:00"),
            end=datetime.fromisoformat("2026-11-09T09:30:00+01:00"),
        ),
        FreeSlot(
            start=datetime.fromisoformat("2026-11-10T14:00:00+01:00"),
            end=datetime.fromisoformat("2026-11-10T14:30:00+01:00"),
        ),
    ]
    assert captured["url"] == f"{BASE_URL}/slots/free"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "duration_minutes": 30,
        "window_start": "2026-11-09T08:00:00+01:00",
        "window_end": "2026-11-16T08:00:00+01:00",
        "time_zone": "Europe/Berlin",
    }


def test_find_free_slots_rejects_naive_window_times() -> None:
    """A window without a time zone never reaches the backend."""
    with pytest.raises(BackendError) as exc_info:
        _client().find_free_slots(
            30,
            datetime(2026, 11, 9, 8, 0),
            datetime(2026, 11, 16, 8, 0),
            "Europe/Berlin",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "invalid_event"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"slots": "nope"},
        {"slots": ["nope"]},
        {"slots": [{"start": "not-a-date", "end": "not-a-date"}]},
        {
            "slots": [
                {
                    "start": "2026-11-09T09:00:00",
                    "end": "2026-11-09T09:30:00",
                },
            ],
        },
    ],
)
def test_find_free_slots_rejects_a_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    """A non-list or malformed slot list is a backend error."""

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(BackendError) as exc_info:
        _client().find_free_slots(
            30,
            datetime.fromisoformat("2026-11-09T08:00:00+01:00"),
            datetime.fromisoformat("2026-11-16T08:00:00+01:00"),
            "Europe/Berlin",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "invalid_response"

