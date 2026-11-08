"""Thin HTTP client for the Kivy calendar backend.

The client talks to the backend API only; calendar rules live in the backend.
This module turns backend JSON responses into :class:`CalendarEvent` values and
raises :class:`BackendError` when the backend reports a failure.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

BASE_URL_ENV = "KIVY_CALENDAR_API_BASE_URL"
TOKEN_ENV = "BACKEND_API_TOKEN"
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 10.0


class BackendError(Exception):
    """A backend API failure surfaced to the client."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        """Create the error."""
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CalendarEvent:
    """A calendar event as returned by the backend."""

    id: str
    summary: str
    start: datetime
    end: datetime
    start_timezone: str
    end_timezone: str
    description: str | None = None
    recurrence: list[str] | None = None
    extended_properties: dict[str, str] | None = None


class BackendClient:
    """Small HTTP client for the backend calendar API."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Create the client, defaulting the connection details to the environment."""
        if base_url is None:
            base_url = os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
        if token is None:
            token = os.environ.get(TOKEN_ENV) or ""
        if not base_url:
            raise ValueError("base_url must not be blank")
        if not token:
            raise ValueError("token must not be blank")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def list_events(self) -> list[CalendarEvent]:
        """Return every event the backend has cached."""
        payload = self._request("/events", method="GET")
        if not isinstance(payload, list):
            raise BackendError(
                500,
                "invalid_response",
                "backend returned an unexpected event list",
            )
        events: list[CalendarEvent] = []
        for item in payload:
            events.append(self._event_from_payload(item))
        return events

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        """Create an event in the backend calendar."""
        payload = self._request(
            "/events",
            method="POST",
            body=self._event_payload(event),
        )
        return self._event_from_payload(payload)

    def _request(self, path: str, *, method: str, body: object | None = None) -> Any:
        """Perform a JSON request against the backend and decode the response."""
        data = json.dumps(body).encode() if body is not None else None
        headers: dict[str, str] = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={**headers, "Authorization": f"Bearer {self.token}"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as error:
            raise self._backend_error_from_http(error) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise BackendError(
                0,
                "network_error",
                f"backend request failed: {error}",
            ) from error
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise BackendError(
                500,
                "invalid_response",
                f"backend returned invalid JSON: {error}",
            ) from error

    def _backend_error_from_http(self, error: urllib.error.HTTPError) -> BackendError:
        """Translate a backend HTTP error into a client error."""
        code = "unknown_error"
        message = f"backend request failed with status {error.code}"
        try:
            parsed: Any = json.loads(error.read().decode() or "{}")
            error_body = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error_body, dict):
                code = str(error_body.get("code") or "unknown_error")
                message = str(error_body.get("message") or message)
        except (json.JSONDecodeError, OSError):
            pass
        return BackendError(error.code, code, message)

    def _event_from_payload(self, payload: object) -> CalendarEvent:
        """Turn a backend event payload into a client event."""
        if not isinstance(payload, dict):
            raise BackendError(
                500,
                "invalid_response",
                "backend returned an unexpected event",
            )
        start = self._parse_datetime(str(payload.get("start") or ""), "start")
        end = self._parse_datetime(str(payload.get("end") or ""), "end")
        if start.tzinfo is None or end.tzinfo is None:
            raise BackendError(
                422,
                "invalid_event",
                "backend event times must include time zone information",
            )
        recurrence = payload.get("recurrence")
        extended_properties = payload.get("extended_properties")
        return CalendarEvent(
            id=str(payload.get("id") or ""),
            summary=str(payload.get("summary") or ""),
            start=start,
            end=end,
            start_timezone=str(payload.get("start_timezone") or "UTC"),
            end_timezone=str(payload.get("end_timezone") or "UTC"),
            description=(
                str(payload["description"])
                if payload.get("description") is not None
                else None
            ),
            recurrence=list(recurrence) if isinstance(recurrence, list) else None,
            extended_properties=(
                dict(extended_properties)
                if isinstance(extended_properties, dict)
                else None
            ),
        )

    @staticmethod
    def _parse_datetime(value: str, field: str) -> datetime:
        """Parse a backend ISO datetime, reporting failures as backend errors."""
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise BackendError(
                422,
                "invalid_event",
                f"backend event {field} is not a valid datetime: {value}",
            ) from error

    @staticmethod
    def _event_payload(event: CalendarEvent) -> dict[str, object]:
        """Turn a client event into a backend create payload."""
        return {
            "id": event.id,
            "summary": event.summary,
            "start": event.start.isoformat(),
            "end": event.end.isoformat(),
            "start_timezone": event.start_timezone,
            "end_timezone": event.end_timezone,
            "description": event.description,
            "recurrence": event.recurrence,
            "extended_properties": event.extended_properties or {},
        }
