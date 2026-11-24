"""Kivy client for the self-hosted Kivy calendar backend."""

from kivy_calendar.api import BackendClient, BackendError, CalendarEvent

# The app version; tests keep it equal to the repository's VERSION file.
__version__ = "0.5.0"

__all__ = ["BackendClient", "BackendError", "CalendarEvent", "__version__"]
