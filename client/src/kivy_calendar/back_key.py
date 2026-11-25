"""What the Back key (Android) and Escape (desktop) do, in order.

Kivy delivers both as key 27 through ``Window.on_keyboard``. Returning ``True``
from the handler consumes the key, so Kivy's own reaction (closing the app on
Escape) never happens. Each press does the first thing that applies:

1. close an open popup (date picker, time sheet, confirm dialog, any
   ``ModalView``);
2. close an open dropdown list;
3. unfocus the text field being edited (this hides the keyboard);
4. on the event form, go back to the main screen without saving;
5. on the main (or permission) screen, move the app to the background the way
   Android's Home does. On desktop there is nothing to do, and the app stays.

Week and Month are tabs of the main screen, not screens, so Back does not
step through them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kivy.core.window import Window
from kivy.uix.dropdown import DropDown
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import ScreenManager
from kivy.uix.textinput import TextInput

BACK_KEY = 27  # Android Back and desktop Escape


class BackKeyHandler:
    """Dispatch the Back key to the first thing that can take it."""

    def __init__(
        self,
        screen_manager: ScreenManager,
        move_to_background: Callable[[], object] | None = None,
        window: Any = Window,
    ) -> None:
        """Create the handler.

        ``move_to_background`` is the platform's way to leave the app without
        closing it (``None`` on desktop, where Escape then does nothing).
        """
        self.screen_manager = screen_manager
        self.move_to_background = move_to_background
        self.window = window

    def on_keyboard(self, window: Any, key: int, *args: Any) -> bool:
        """``Window.on_keyboard`` callback; consume Back, ignore other keys."""
        if key != BACK_KEY:
            return False
        return self.handle()

    def handle(self) -> bool:
        """Do what Back means now. Always consumes the key (returns ``True``)."""
        for step in (
            self._close_popup,
            self._close_dropdown,
            self._unfocus_text,
            self._leave_form,
            self._leave_app,
        ):
            if step():
                break
        return True

    def _open_children(self, kind: type) -> list[Any]:
        """Open widgets of ``kind`` in the window, topmost first."""
        return [w for w in self.window.children if isinstance(w, kind)]

    def _close_popup(self) -> bool:
        popups = [p for p in self._open_children(ModalView) if p._is_open]
        if not popups:
            return False
        popups[0].dismiss()
        return True

    def _close_dropdown(self) -> bool:
        lists = self._open_children(DropDown)
        if not lists:
            return False
        lists[0].dismiss()
        return True

    def _unfocus_text(self) -> bool:
        for child in self.window.children:
            for widget in child.walk():
                if isinstance(widget, TextInput) and widget.focus:
                    widget.focus = False
                    return True
        return False

    def _leave_form(self) -> bool:
        if self.screen_manager.current != "add_event":
            return False
        self.screen_manager.current_screen.cancel()
        return True

    def _leave_app(self) -> bool:
        if self.move_to_background is not None:
            self.move_to_background()
        return True
