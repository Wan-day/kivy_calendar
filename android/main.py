"""Android entry point for Kivy Calendar.

python-for-android starts the app from this file. The app code is copied next
to it by ``android/build.sh``: the Kivy client (``kivy_calendar``) and the
shared calendar logic (``core``, ``domain``, ``slots``, ``calendar_provider``).
"""

from __future__ import annotations

from kivy.logger import Logger


def check_shared_code() -> bool:
    """Import the shared calendar logic once and log whether it works.

    The client does not use it yet; this proves that pydantic and the shared
    models load on the device before the Android provider depends on them.
    """
    try:
        import calendar_provider  # noqa: F401
        import slots.service  # noqa: F401
        from domain.event import Event
    except Exception as error:  # noqa: BLE001 - report any import failure
        Logger.error("KivyCalendar: shared code failed to import: %s", error)
        return False
    Logger.info(
        "KivyCalendar: shared code imported (Event model has %d fields)",
        len(Event.model_fields),
    )
    return True


if __name__ == "__main__":
    check_shared_code()

    from kivy_calendar.__main__ import main

    main()
