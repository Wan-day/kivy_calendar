"""FastAPI dependencies that inject backend services into routes."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from cache.repository import EventRepository
from core.config import Settings
from google_calendar.provider import CalendarProvider
from retry.queue import RetryQueue
from slots.service import SlotService
from sync.service import SyncService


def get_settings_dep(request: Request) -> Settings:
    """Return the application settings from the application state."""
    return cast(Settings, request.app.state.settings)


def get_provider(request: Request) -> CalendarProvider:
    """Return the calendar provider from the application state."""
    provider = getattr(request.app.state, "provider")
    return cast(CalendarProvider, provider)


def get_repository(request: Request) -> EventRepository:
    """Return the SQLite event repository from the application state."""
    repository = getattr(request.app.state, "repository")
    return cast(EventRepository, repository)


def get_retry_queue(request: Request) -> RetryQueue:
    """Return the retry queue from the application state."""
    queue = getattr(request.app.state, "retry_queue")
    return cast(RetryQueue, queue)


def get_slot_service(request: Request) -> SlotService:
    """Return the slot service from the application state."""
    service = getattr(request.app.state, "slot_service")
    return cast(SlotService, service)


def get_sync_service(request: Request) -> SyncService:
    """Return the sync service from the application state."""
    service = getattr(request.app.state, "sync_service")
    return cast(SyncService, service)
