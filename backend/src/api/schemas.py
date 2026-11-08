"""Pydantic schemas for the backend API."""

from pydantic import BaseModel


class SyncResponse(BaseModel):
    """Response returned after a successful full calendar sync."""

    synced: int
