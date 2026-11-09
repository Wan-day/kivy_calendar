"""Small shared widget helpers for the Kivy screens."""

from __future__ import annotations

from typing import Any

from kivy.uix.label import Label


def wrapped_label(text: str = "", **kwargs: Any) -> Label:
    """Create a left-aligned label whose text wraps to its width."""
    label = Label(text=text, halign="left", valign="middle", **kwargs)

    def update_text_size(instance: Label, *_: Any) -> None:
        width = instance.width if instance.width > 8 else 8
        instance.text_size = (width - 8, None)

    label.bind(size=update_text_size)
    update_text_size(label)
    return label
