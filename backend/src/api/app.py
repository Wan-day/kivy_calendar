"""FastAPI application factory for the Kivy calendar backend."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.auth import verify_api_key  # noqa: F401 - registered on routes
from api.deps import (  # noqa: F401 - used by route dependencies
    get_provider,
    get_repository,
    get_retry_queue,
    get_sync_service,
)
from api.errors import ApiError
from api.router import api_router
from api.unavailable_provider import UnavailableCalendarProvider
from cache.repository import EventRepository
from core.config import Settings, get_settings
from google_calendar.auth import CALENDAR_EVENTS_SCOPE, build_credentials
from google_calendar.google_provider import GoogleCalendarProvider
from google_calendar.provider import CalendarProvider
from retry.queue import RetryQueue
from sync.service import SyncService


def _build_default_provider(settings: Settings) -> CalendarProvider:
    """Build a Google provider from settings, or an unavailable fake."""
    environ = {
        "GOOGLE_CLIENT_ID": settings.google_client_id,
        "GOOGLE_CLIENT_SECRET": settings.google_client_secret,
        "GOOGLE_REFRESH_TOKEN": settings.google_refresh_token,
    }
    credentials_result = build_credentials(environ, scopes=CALENDAR_EVENTS_SCOPE)
    if credentials_result.is_ok and credentials_result.value is not None:
        provider_result = GoogleCalendarProvider.from_credentials(
            credentials_result.value,
            settings.google_calendar_id,
        )
        if provider_result.is_ok and provider_result.value is not None:
            return provider_result.value
    return UnavailableCalendarProvider()


def create_app(
    *,
    settings: Settings | None = None,
    provider: CalendarProvider | None = None,
    repository: EventRepository | None = None,
    retry_queue: RetryQueue | None = None,
    sync_service: SyncService | None = None,
) -> FastAPI:
    """Create the FastAPI application.

    Services default to the local SQLite-backed implementations so the
    module-level app can be run directly; tests may inject fakes through the
    explicit arguments.
    """
    resolved_settings = settings or get_settings()
    app = FastAPI(title="Kivy Calendar Backend")

    if provider is None:
        provider = _build_default_provider(resolved_settings)
    if repository is None:
        repository = EventRepository()
    if retry_queue is None:
        retry_queue = RetryQueue()
    if sync_service is None:
        sync_service = SyncService(
            provider=provider,
            repository=repository,
            retry_queue=retry_queue,
        )

    app.state.settings = resolved_settings
    app.state.provider = provider
    app.state.repository = repository
    app.state.retry_queue = retry_queue
    app.state.sync_service = sync_service

    app.include_router(api_router)

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code.value, "message": exc.message}},
        )

    return app
