"""FastAPI router for the Kivy calendar backend."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from api.auth import verify_api_key
from api.deps import get_repository, get_sync_service
from api.errors import ApiError, error_status
from api.schemas import SyncResponse
from cache.repository import EventRepository
from core.errors import ErrorCode
from domain.event import Event
from sync.service import SyncService

api_router = APIRouter()


@api_router.get("/health")
def health() -> dict[str, str]:
    """Return the health status of the backend."""
    return {"status": "ok"}


@api_router.get(
    "/events",
    response_model=list[Event],
    dependencies=[Depends(verify_api_key)],
)
def list_events(
    repository: EventRepository = Depends(get_repository),
) -> list[Event]:
    """List cached events."""
    result = repository.list()
    if result.is_error:
        error = result.error
        if error is None:
            raise RuntimeError("list events failed without an error")
        raise ApiError(error_status(error), error.code, error.message)
    return list(result.value or [])


@api_router.get(
    "/events/{event_id}",
    response_model=Event,
    dependencies=[Depends(verify_api_key)],
)
def get_event(
    event_id: str,
    repository: EventRepository = Depends(get_repository),
) -> Event:
    """Get one cached event by id."""
    result = repository.get(event_id)
    if result.is_error:
        error = result.error
        if error is None:
            raise RuntimeError("get event failed without an error")
        raise ApiError(error_status(error), error.code, error.message)
    value = result.value
    if value is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"event {event_id!r} was not found")
    return value


@api_router.post(
    "/events",
    response_model=Event,
    status_code=201,
    dependencies=[Depends(verify_api_key)],
)
def create_event(
    event: Event,
    service: SyncService = Depends(get_sync_service),
) -> Event:
    """Create an event in Google first, then cache it."""
    result = service.create_event(event)
    if result.is_error:
        error = result.error
        if error is None:
            raise RuntimeError("create event failed without an error")
        raise ApiError(error_status(error), error.code, error.message)
    value = result.value
    if value is None:
        raise ApiError(500, ErrorCode.STORAGE_ERROR, "create event returned no event")
    return value


@api_router.patch(
    "/events/{event_id}",
    response_model=Event,
    dependencies=[Depends(verify_api_key)],
)
def update_event(
    event_id: str,
    event: Event,
    service: SyncService = Depends(get_sync_service),
) -> Event:
    """Patch an upstream event and refresh the cached copy."""
    updated = Event(
        id=event_id,
        start=event.start,
        end=event.end,
        start_timezone=event.start_timezone,
        end_timezone=event.end_timezone,
        summary=event.summary,
        description=event.description,
        recurrence=event.recurrence,
        extended_properties=event.extended_properties,
    )
    result = service.update_event(updated)
    if result.is_error:
        error = result.error
        if error is None:
            raise RuntimeError("update event failed without an error")
        raise ApiError(error_status(error), error.code, error.message)
    value = result.value
    if value is None:
        raise ApiError(500, ErrorCode.STORAGE_ERROR, "update event returned no event")
    return value


@api_router.delete(
    "/events/{event_id}",
    status_code=204,
    dependencies=[Depends(verify_api_key)],
)
def delete_event(
    event_id: str,
    service: SyncService = Depends(get_sync_service),
) -> Response:
    """Delete an event in Google and drop the cached copy."""
    result = service.delete_event(event_id)
    if result.is_error:
        error = result.error
        if error is None:
            raise RuntimeError("delete event failed without an error")
        raise ApiError(error_status(error), error.code, error.message)
    return Response(status_code=204)


@api_router.post(
    "/sync",
    response_model=SyncResponse,
    dependencies=[Depends(verify_api_key)],
)
def sync(service: SyncService = Depends(get_sync_service)) -> SyncResponse:
    """Rebuild the local cache from Google."""
    result = service.sync_from_google()
    if result.is_error:
        error = result.error
        if error is None:
            raise RuntimeError("sync failed without an error")
        raise ApiError(error_status(error), error.code, error.message)
    count = result.value if result.value is not None else 0
    return SyncResponse(synced=count)
