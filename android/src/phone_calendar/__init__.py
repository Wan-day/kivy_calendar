"""The phone's own calendar as the app's calendar service (Android only)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from phone_calendar.service import PhoneCalendarService

__all__ = [
    "PhoneCalendarService",
    "create_service",
    "device_time_zone",
    "hide_focus_highlight",
    "move_task_to_background",
]

# Keeps the focus listener alive; Android only holds a weak link to Python.
_focus_listener: object | None = None


def create_service() -> PhoneCalendarService:
    """Build the service on a device: JNI calendar store and real permissions."""
    from phone_calendar.account_sync import JniAccountSync
    from phone_calendar.permissions import AndroidCalendarPermissions
    from phone_calendar.provider import AndroidCalendarProvider
    from phone_calendar.store import JniCalendarStore

    return PhoneCalendarService(
        AndroidCalendarProvider(JniCalendarStore(), time_zone=device_time_zone()),
        AndroidCalendarPermissions(),
        account_sync=JniAccountSync(),
    )


def device_time_zone(fallback: str = "UTC") -> str:
    """The device's IANA time zone (``java.util.TimeZone``), or ``fallback``."""
    try:
        from jnius import autoclass  # type: ignore[import-not-found]

        return str(autoclass("java.util.TimeZone").getDefault().getID())
    except Exception:  # noqa: BLE001 - any JNI failure falls back
        return fallback


def move_task_to_background() -> bool:
    """Send the app to the background the Android way; ``False`` if it failed.

    This is what Back does on the main screen: the app stays alive (like
    pressing Home) instead of being closed.
    """
    try:
        from android import mActivity  # type: ignore[import-not-found]

        return bool(mActivity.moveTaskToBack(True))
    except Exception:  # noqa: BLE001 - any JNI failure just means "stay open"
        return False


def hide_focus_highlight() -> bool:
    """Stop Android from greying out the app after the keyboard closes.

    Since Android 8 a focused view without its own focus style is covered with
    a 12% black "default focus highlight" while the phone is not in touch
    mode. SDL gives focus to its full-screen surface when the keyboard closes,
    and typed keys (Enter, a hardware keyboard) leave touch mode, so the whole
    app turned grey. This turns the highlight off on every view now and on
    each view that gets focus later (SDL adds its text view on first use).
    ``False`` off a device or when the views cannot be reached.
    """
    try:
        from android.runnable import (  # type: ignore[import-not-found]
            run_on_ui_thread,
        )
        from jnius import (  # type: ignore[import-not-found]
            PythonJavaClass,
            autoclass,
            cast,
            java_method,
        )
    except Exception:  # noqa: BLE001 - not on a device
        return False

    view_group = autoclass("java.lang.Class").forName("android.view.ViewGroup")

    def children(view: Any) -> list[Any]:
        if not view_group.isInstance(view):
            return []
        group = cast("android.view.ViewGroup", view)
        return [group.getChildAt(index) for index in range(group.getChildCount())]

    class FocusListener(PythonJavaClass):  # type: ignore[misc]
        __javainterfaces__ = [
            "android/view/ViewTreeObserver$OnGlobalFocusChangeListener"
        ]
        __javacontext__ = "app"

        @java_method("(Landroid/view/View;Landroid/view/View;)V")  # type: ignore[misc]
        def onGlobalFocusChanged(self, old: Any, new: Any) -> None:  # noqa: N802
            if new is not None:
                new.setDefaultFocusHighlightEnabled(False)

    @run_on_ui_thread  # type: ignore[misc]
    def apply() -> None:
        global _focus_listener
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        decor = activity.getWindow().getDecorView()
        disable_focus_highlight(decor, children)
        _focus_listener = FocusListener()
        decor.getViewTreeObserver().addOnGlobalFocusChangeListener(_focus_listener)

    try:
        apply()
    except Exception:  # noqa: BLE001 - any JNI failure leaves the app as it was
        return False
    return True


def disable_focus_highlight(view: Any, children: Callable[[Any], list[Any]]) -> int:
    """Turn the default focus highlight off on ``view`` and every view in it.

    ``children`` lists a view's child views (none for a plain view). Returns
    how many views were changed.
    """
    view.setDefaultFocusHighlightEnabled(False)
    return 1 + sum(disable_focus_highlight(child, children) for child in children(view))
