"""Tests for the FastAPI backend API surface."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from api.app import _build_default_provider, create_app
from api.unavailable_provider import UnavailableCalendarProvider
from cache.repository import EventRepository
from core.config import Settings
from core.errors import ErrorCode, Result
from core.sqlite import Database
from domain.event import Event
from fastapi.testclient import TestClient
from google_calendar.auth import CALENDAR_SCOPES
from google_calendar.fake import FakeCalendarProvider
from google_calendar.provider import ProviderOperation
from httpx import Response
from retry.queue import RetryQueue
from slots.service import SlotService
from sync.service import SyncService

BERLIN = ZoneInfo("Europe/Berlin")
TOKEN = "test-token"


def _event(
    event_id: str = "event-1",
    *,
    summary: str = "Team standup",
) -> Event:
    start = datetime(2026, 11, 6, 9, 0, tzinfo=BERLIN)
    return Event(
        id=event_id,
        summary=summary,
        start=start,
        end=start + timedelta(minutes=30),
        start_timezone="Europe/Berlin",
        end_timezone="Europe/Berlin",
    )


def _event_payload(
    event_id: str = "event-1",
    *,
    summary: str = "Team standup",
) -> dict[str, object]:
    return {
        "id": event_id,
        "summary": summary,
        "start": _event(event_id).start.isoformat(),
        "end": _event(event_id).end.isoformat(),
        "start_timezone": "Europe/Berlin",
        "end_timezone": "Europe/Berlin",
    }


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _error_code(response: Response) -> str:
    body = response.json()
    assert "error" in body, body
    error = body["error"]
    assert "code" in error, error
    return error["code"]


def test_default_provider_requests_the_full_calendar_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The app wires a scope sequence, not a string split into characters."""
    import api.app as app_module

    captured: dict[str, object] = {}

    def fake_build_credentials(environ: object, *, scopes: object) -> object:
        captured["scopes"] = scopes
        return Result.fail(ErrorCode.INVALID_ARGUMENT, "stop before Google")

    monkeypatch.setattr(app_module, "build_credentials", fake_build_credentials)
    settings = Settings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        google_refresh_token="refresh-token",
    )

    provider = _build_default_provider(settings)

    assert captured["scopes"] == CALENDAR_SCOPES
    assert isinstance(provider, UnavailableCalendarProvider)


@pytest.fixture
def provider() -> FakeCalendarProvider:
    return FakeCalendarProvider()


@pytest.fixture
def repository(tmp_path: Path) -> EventRepository:
    return EventRepository(Database(tmp_path / "calendar.db"))


@pytest.fixture
def retry_queue(tmp_path: Path) -> RetryQueue:
    return RetryQueue(Database(tmp_path / "retry.db"))


@pytest.fixture
def service(
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> SyncService:
    return SyncService(provider=provider, repository=repository, retry_queue=retry_queue)


def _make_client(
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> TestClient:
    app = create_app(
        settings=Settings(backend_api_token=TOKEN),
        provider=provider,
        repository=repository,
        retry_queue=retry_queue,
        sync_service=SyncService(provider=provider, repository=repository, retry_queue=retry_queue),
        slot_service=SlotService(provider=provider),
    )
    return TestClient(app)


@pytest.fixture
def client(
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> TestClient:
    return _make_client(provider, repository, retry_queue)


def test_health_returns_ok(client: TestClient) -> None:
    """The health endpoint should return a 200 with status ok."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_endpoints_reject_a_missing_bearer_token(client: TestClient) -> None:
    """Protected endpoints must not answer without a bearer token."""
    response = client.get("/events")

    assert response.status_code == 401
    assert _error_code(response) == "auth_error"


def test_protected_endpoints_reject_an_invalid_bearer_token(client: TestClient) -> None:
    """A wrong bearer token is rejected with an auth error."""
    response = client.get("/events", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert _error_code(response) == "auth_error"


def test_create_event_writes_to_google_then_caches(
    client: TestClient,
    provider: FakeCalendarProvider,
) -> None:
    """A create is stored by Google first and cached only after confirmation."""
    response = client.post("/events", json=_event_payload(), headers=_auth_headers())

    assert response.status_code == 201
    assert response.json()["id"] == "event-1"
    assert provider.calls == [(ProviderOperation.CREATE, "event-1")]


def test_create_event_returns_upstream_error_without_caching(
    client: TestClient,
    provider: FakeCalendarProvider,
    repository: EventRepository,
) -> None:
    """A provider failure maps to a structured upstream error and caches nothing."""
    provider.fail_next(ProviderOperation.CREATE, code=ErrorCode.UPSTREAM_ERROR, message="offline")

    response = client.post("/events", json=_event_payload(), headers=_auth_headers())

    assert response.status_code == 503
    assert _error_code(response) == "upstream_error"
    cached = repository.get("event-1")
    assert cached.error is not None
    assert cached.error.code is ErrorCode.NOT_FOUND


def test_create_event_rejects_naive_datetimes(client: TestClient) -> None:
    """Naive datetimes without a time zone must be rejected."""
    response = client.post(
        "/events",
        json={
            "id": "event-1",
            "start": "2026-11-06T09:00:00",
            "end": "2026-11-06T09:30:00",
            "start_timezone": "Europe/Berlin",
            "end_timezone": "Europe/Berlin",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 422


def test_get_event_returns_404_for_unknown_id(client: TestClient) -> None:
    """Reading an event that was never created returns a not found error."""
    response = client.get("/events/unknown", headers=_auth_headers())

    assert response.status_code == 404
    assert _error_code(response) == "not_found"


def test_list_events_returns_cached_events(client: TestClient) -> None:
    """A create is visible through the list endpoint."""
    created = client.post("/events", json=_event_payload(), headers=_auth_headers())
    assert created.status_code == 201

    response = client.get("/events", headers=_auth_headers())

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == "event-1"


def test_update_event_patches_google_and_the_cache(client: TestClient) -> None:
    """A patch goes to Google and refreshes the cached copy."""
    created = client.post("/events", json=_event_payload(), headers=_auth_headers())
    assert created.status_code == 201

    response = client.patch(
        "/events/event-1",
        json=_event_payload("event-1", summary="Renamed standup"),
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["summary"] == "Renamed standup"


def test_delete_event_removes_google_and_the_cache(client: TestClient) -> None:
    """A delete goes to Google and drops the cached copy."""
    created = client.post("/events", json=_event_payload(), headers=_auth_headers())
    assert created.status_code == 201

    response = client.delete("/events/event-1", headers=_auth_headers())

    assert response.status_code == 204
    cached = client.get("/events/event-1", headers=_auth_headers())
    assert cached.status_code == 404


def test_sync_replaces_the_cache_and_returns_the_count(
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """A full sync replaces the disposable cache and reports how many events."""
    provider = FakeCalendarProvider(
        [
            _event("event-1", summary="Standup"),
            _event("event-2", summary="Release review"),
        ],
    )
    sync_client = _make_client(provider, repository, retry_queue)

    response = sync_client.post("/sync", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"synced": 2}
    listed = repository.list()
    assert listed.is_ok
    assert listed.value is not None
    assert len(listed.value) == 2


def test_sync_returns_upstream_error_when_provider_fails(
    client: TestClient,
    provider: FakeCalendarProvider,
) -> None:
    """A failed full sync maps to a structured upstream error."""
    provider.fail_next(ProviderOperation.LIST, code=ErrorCode.UPSTREAM_ERROR, message="offline")

    response = client.post("/sync", headers=_auth_headers())

    assert response.status_code == 503
    assert _error_code(response) == "upstream_error"


def test_free_slots_returns_free_windows(
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """Free-slot search skips booked events and returns fitting windows."""
    provider = FakeCalendarProvider([_event("event-1")])
    slots_client = _make_client(provider, repository, retry_queue)

    response = slots_client.post(
        "/slots/free",
        json={
            "duration_minutes": 30,
            "window_start": "2026-11-06T08:00:00+01:00",
            "window_end": "2026-11-06T18:00:00+01:00",
            "time_zone": "Europe/Berlin",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    slots = response.json()["slots"]
    assert len(slots) == 2
    assert slots[0]["start"] == "2026-11-06T08:00:00+01:00"
    assert slots[0]["end"] == "2026-11-06T08:30:00+01:00"
    assert slots[1]["start"] == "2026-11-06T09:30:00+01:00"
    assert slots[1]["end"] == "2026-11-06T10:00:00+01:00"


def test_free_slots_returns_upstream_error_when_provider_fails(
    provider: FakeCalendarProvider,
    repository: EventRepository,
    retry_queue: RetryQueue,
) -> None:
    """A failed free-slot search maps to a structured upstream error."""
    provider.fail_next(ProviderOperation.LIST, code=ErrorCode.UPSTREAM_ERROR, message="offline")
    slots_client = _make_client(provider, repository, retry_queue)

    response = slots_client.post(
        "/slots/free",
        json={
            "duration_minutes": 30,
            "window_start": "2026-11-06T08:00:00+01:00",
            "window_end": "2026-11-06T18:00:00+01:00",
            "time_zone": "Europe/Berlin",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 503
    assert _error_code(response) == "upstream_error"
