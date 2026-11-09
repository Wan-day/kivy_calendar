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

from kivy_calendar.api import BackendClient, BackendError, CalendarEvent

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
    assert event.start == datetime.fromisoformat("2026-11-06T09:00:00+01:00")
    assert event.end == datetime.fromisoformat("2026-11-06T09:30:00+01:00")


def test_create_event_posts_the_backend_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client sends a client-generated event id to the backend."""

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
                "start": "2026-11-06T09:00:00+01:00",
                "end": "2026-11-06T09:30:00+01:00",
                "start_timezone": "Europe/Berlin",
                "end_timezone": "Europe/Berlin",
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
    )
    created = _client().create_event(event)

    assert created.id == "event-1"
    assert captured["url"] == f"{BASE_URL}/events"
    assert captured["method"] == "POST"


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
