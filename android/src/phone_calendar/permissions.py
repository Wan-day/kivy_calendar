"""Calendar permission on Android (``READ_CALENDAR`` and ``WRITE_CALENDAR``).

Only importable on Android: it uses python-for-android's ``android`` module and
pyjnius. Tests use a fake with the same three methods.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class CalendarPermissions(Protocol):
    """Check, request and manage the calendar permission."""

    def granted(self) -> bool:
        """Whether the app may read the calendar."""
        ...

    def request(self, on_result: Callable[[bool], None]) -> None:
        """Show Android's permission dialog; report whether it was granted.

        ``on_result`` may run on a Java thread; callers hand it to the UI
        thread themselves.
        """
        ...

    def open_settings(self) -> None:
        """Open this app's Android settings page, where access can be granted."""
        ...


class AndroidCalendarPermissions:
    """:class:`CalendarPermissions` through python-for-android."""

    def __init__(self) -> None:
        """Import the Android helpers."""
        from android.permissions import (  # type: ignore[import-not-found]
            Permission,
            check_permission,
            request_permissions,
        )

        self._check: Callable[[str], bool] = check_permission
        self._request: Callable[..., None] = request_permissions
        self._permissions = [Permission.READ_CALENDAR, Permission.WRITE_CALENDAR]

    def granted(self) -> bool:
        """Whether READ_CALENDAR is granted."""
        return bool(self._check(self._permissions[0]))

    def request(self, on_result: Callable[[bool], None]) -> None:
        """Ask for read and write access; report whether read was granted."""

        def callback(permissions: list[str], grants: list[bool]) -> None:
            on_result(bool(grants) and bool(grants[0]))

        self._request(self._permissions, callback)

    def open_settings(self) -> None:
        """Open the app-details page in Android's settings."""
        from jnius import autoclass  # type: ignore[import-not-found]

        activity: Any = autoclass("org.kivy.android.PythonActivity").mActivity
        intent_class = autoclass("android.content.Intent")
        settings = autoclass("android.provider.Settings")
        uri = autoclass("android.net.Uri")
        intent = intent_class(settings.ACTION_APPLICATION_DETAILS_SETTINGS)
        intent.setData(uri.fromParts("package", activity.getPackageName(), None))
        activity.startActivity(intent)
