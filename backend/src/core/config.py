"""Application settings sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_RETRY_INTERVAL_SECONDS = 30.0


def _positive_or_zero(raw: str, default: float) -> float:
    """Parse a seconds value; blank or invalid falls back to ``default``."""
    try:
        return max(float(raw), 0.0) if raw.strip() else default
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    """Backend application settings."""

    db_path: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_calendar_id: str = "primary"
    google_calendar_time_zone: str = "UTC"
    backend_api_token: str = ""
    retry_interval_seconds: float = DEFAULT_RETRY_INTERVAL_SECONDS

    @classmethod
    def from_env(cls) -> Settings:
        """Load the settings from the process environment."""

        def value(name: str) -> str:
            return os.environ.get(name, "")

        return cls(
            db_path=value("KIVY_CALENDAR_DB_PATH"),
            google_client_id=value("GOOGLE_CLIENT_ID"),
            google_client_secret=value("GOOGLE_CLIENT_SECRET"),
            google_refresh_token=value("GOOGLE_REFRESH_TOKEN"),
            google_calendar_id=value("GOOGLE_CALENDAR_ID") or "primary",
            google_calendar_time_zone=value("GOOGLE_CALENDAR_TIME_ZONE") or "UTC",
            backend_api_token=value("BACKEND_API_TOKEN"),
            retry_interval_seconds=_positive_or_zero(
                value("RETRY_WORKER_INTERVAL_SECONDS"),
                DEFAULT_RETRY_INTERVAL_SECONDS,
            ),
        )


def get_settings() -> Settings:
    """Return the process-wide application settings."""
    return Settings.from_env()
