"""Entry point for running the Kivy calendar client."""

from __future__ import annotations

from kivy_calendar.app import KivyCalendarApp


def main() -> None:
    """Launch the Kivy calendar application."""
    KivyCalendarApp().run()


if __name__ == "__main__":
    main()
