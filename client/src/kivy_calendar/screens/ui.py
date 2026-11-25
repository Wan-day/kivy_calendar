"""Small shared widget helpers for the Kivy screens."""

from __future__ import annotations

from typing import Any

from kivy.animation import AnimationTransition
from kivy.graphics import Color, Line
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import SlideTransition
from kivy.uix.textinput import TextInput

from kivy_calendar.screens.theme import (
    BORDER,
    CLEAR,
    CORAL_DEEP_TEXT,
    DEEP_SKY,
    DIVIDER,
    ERROR_TINT,
    FONT,
    FONT_SEMIBOLD,
    HINT,
    INK,
    MUTED,
    SKY_TINT,
    STATUS_TEXT,
    SURFACE,
    Paint,
)


def wrapped_label(text: str = "", **kwargs: Any) -> Label:
    """Create a left-aligned label whose text wraps to its width."""
    kwargs.setdefault("font_name", FONT)
    kwargs.setdefault("color", INK)
    label = Label(text=text, halign="left", valign="middle", **kwargs)

    def update_text_size(instance: Label, *_: Any) -> None:
        width = instance.width if instance.width > 8 else 8
        instance.text_size = (width - dp(8), None)

    label.bind(size=update_text_size)
    update_text_size(label)
    return label


def caption(text: str, **kwargs: Any) -> Label:
    """Return a small muted label for section and field names."""
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(20))
    return wrapped_label(
        text=text,
        font_name=FONT_SEMIBOLD,
        font_size="12sp",
        color=MUTED,
        **kwargs,
    )


def plain_input(hint: str = "", **kwargs: Any) -> TextInput:
    """Return a borderless text input meant to sit inside ``input_box``."""
    kwargs.setdefault("font_size", "15sp")
    kwargs.setdefault("multiline", False)
    kwargs.setdefault("font_name", FONT)
    return TextInput(
        hint_text=hint,
        background_normal="",
        background_active="",
        background_color=CLEAR,
        foreground_color=INK,
        hint_text_color=HINT,
        cursor_color=DEEP_SKY,
        selection_color=(*SKY_TINT[:3], 0.9),
        **kwargs,
    )


def input_box(*widgets: Any, height: float = dp(44), **kwargs: Any) -> BoxLayout:
    """Wrap inputs (and an optional icon) in a white rounded field."""
    kwargs.setdefault("padding", (dp(12), 0))
    box = BoxLayout(
        orientation="horizontal",
        size_hint_y=None,
        height=height,
        spacing=dp(8),
        **kwargs,
    )
    Paint(box, SURFACE, radius=12, border=BORDER)
    for widget in widgets:
        box.add_widget(widget)
    return box


class Card(BoxLayout):
    """A white rounded panel whose rows are split by thin lines."""

    def __init__(self, **kwargs: Any) -> None:
        """Create the card; it grows with its rows."""
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))
        Paint(self, SURFACE, radius=16, border=DIVIDER)

    def add_row(
        self, caption_text: str, widget: Any, height: float = dp(52)
    ) -> BoxLayout:
        """Add a row with ``caption_text`` on the left and ``widget`` right."""
        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=height,
            padding=(dp(16), 0, dp(12), 0),
            spacing=dp(8),
        )
        label = wrapped_label(text=caption_text, font_size="15sp")
        row.add_widget(label)
        row.add_widget(widget)
        if self.children:
            # A thin line above every row but the first.
            with row.canvas.before:
                Color(*DIVIDER)
                line = Line(width=dp(1))

            def place_line(*_: Any) -> None:
                # x + width, not ``right``, which can lag in a size callback.
                top = row.y + row.height
                line.points = [row.x + dp(16), top, row.x + row.width, top]

            row.bind(pos=place_line, size=place_line)
            place_line()
        self.add_widget(row)
        row.caption = label
        return row


class StatusBanner(Label):
    """A tinted message strip; coral for errors, light blue otherwise.

    With ``collapse=True`` it takes no space while it has no text.
    """

    def __init__(self, *, collapse: bool = False, **kwargs: Any) -> None:
        """Create the banner."""
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", "13sp")
        super().__init__(
            size_hint_y=None,
            halign="left",
            valign="middle",
            padding=(dp(14), dp(8)),
            color=STATUS_TEXT,
            **kwargs,
        )
        self.collapse = collapse
        self.error = False
        self.paint = Paint(self, SKY_TINT, radius=12)
        self.bind(width=self._fit, texture_size=self._fit, text=self._fit)
        self._fit()

    def show(self, text: str, *, error: bool = False) -> None:
        """Show ``text`` as a normal or an error message."""
        self.error = error
        self.text = text
        self.color = CORAL_DEEP_TEXT if error else STATUS_TEXT
        self.paint.set_fill(ERROR_TINT if error else SKY_TINT)

    def _fit(self, *_: Any) -> None:
        """Wrap to the banner width and grow with the text."""
        self.text_size = (max(self.width, dp(40)), None)
        if self.collapse and not self.text:
            self.height = 0
            self.opacity = 0
            return
        self.opacity = 1
        self.height = max(self.texture_size[1], dp(34))


class EaseOutSlide(SlideTransition):
    """A horizontal slide that decelerates smoothly (``out_cubic``).

    Kivy's own ``SlideTransition`` always uses ``out_quad``; the screens of
    this app share this curve and a duration of about 0.3 s (set ``duration``).
    """

    def on_progress(self, progression: float) -> None:
        """Move the incoming and outgoing screens along the eased curve."""
        incoming, outgoing = self.screen_in, self.screen_out
        x, y = self.manager.pos
        width = self.manager.width
        eased = AnimationTransition.out_cubic(progression)
        incoming.y = outgoing.y = y
        if self.direction == "right":
            outgoing.x = x + width * eased
            incoming.x = x - width * (1 - eased)
        else:
            incoming.x = x + width * (1 - eased)
            outgoing.x = x - width * eased
