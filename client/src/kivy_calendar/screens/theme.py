"""Light-blue theme: colors, fonts and the styled widgets the screens share."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kivy.core.text import LabelBase
from kivy.graphics import Color, InstructionGroup, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex

RGBA = tuple[float, float, float, float]


def _hex(value: str, alpha: float = 1.0) -> RGBA:
    """Return the Kivy color for a ``#RRGGBB`` hex value."""
    red, green, blue, _ = get_color_from_hex(value)
    return (red, green, blue, alpha)


BACKGROUND = _hex("#F4F9FD")
SURFACE = _hex("#FFFFFF")
SKY_TINT = _hex("#E3F1FB")
SKY_SOFT = _hex("#CFE8F8")
SKY = _hex("#8ECDF4")
SKY_DOT = _hex("#3BA0E0")
DEEP_SKY = _hex("#1F72AE")
LINK = _hex("#1F5F8F")
NOW_TINT = _hex("#DDF0FC")
INK = _hex("#0E2F4A")
MUTED = _hex("#4A6478")
HINT = _hex("#6A8296")
STATUS_TEXT = _hex("#2F5D80")
BORDER = _hex("#DCE9F3")
DIVIDER = _hex("#E6F0F8")
CORAL = _hex("#FF9B7A")
CORAL_TINT = _hex("#FFE3D9")
CORAL_TEXT = _hex("#B8432A")
CORAL_DEEP_TEXT = _hex("#9A3A22")
ERROR_TINT = _hex("#FFF1EC")
OVERLAY = _hex("#0E2F4A", 0.32)
CLEAR: RGBA = (0, 0, 0, 0)

# Dots that tell calendars apart in the event list, primary first.
CALENDAR_DOTS = (SKY_DOT, CORAL, DEEP_SKY, _hex("#E2673F"))

FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
FONT = "Inter"
FONT_SEMIBOLD = "InterSemiBold"
FONT_BOLD = "InterBold"


def register_fonts() -> None:
    """Register the bundled Inter fonts, falling back to Kivy's Roboto."""
    regular = FONT_DIR / "Inter-Regular.ttf"
    semibold = FONT_DIR / "Inter-SemiBold.ttf"
    bold = FONT_DIR / "Inter-Bold.ttf"
    if not all(path.is_file() for path in (regular, semibold, bold)):
        LabelBase.register(FONT, "Roboto-Regular.ttf", fn_bold="Roboto-Bold.ttf")
        LabelBase.register(FONT_SEMIBOLD, "Roboto-Bold.ttf")
        LabelBase.register(FONT_BOLD, "Roboto-Bold.ttf")
        return
    LabelBase.register(FONT, str(regular), fn_bold=str(bold))
    LabelBase.register(FONT_SEMIBOLD, str(semibold))
    LabelBase.register(FONT_BOLD, str(bold))


register_fonts()


Radius = float | Sequence[float] | None


class Paint:
    """A rounded fill and optional outline drawn behind a widget.

    ``radius=None`` makes a pill whose corners follow the widget height.
    """

    def __init__(
        self,
        widget: Widget,
        fill: RGBA,
        *,
        radius: Radius = 12,
        border: RGBA | None = None,
        border_width: float = 1,
    ) -> None:
        """Draw the shape in ``widget.canvas.before`` and follow its size."""
        self.widget = widget
        # Radii and the border width are in dp, like every size in the theme.
        self.radius = radius
        self.border_width = dp(border_width)
        with widget.canvas.before:
            self.fill_color = Color(*fill)
            self.shape = RoundedRectangle()
            self.border_color = Color(*(border or CLEAR))
            self.outline = Line(width=self.border_width)
        widget.bind(pos=self.update, size=self.update)
        # Kivy keeps only weak references to bound methods, so the widget
        # holds on to its paint to keep it following the widget.
        paints = widget.__dict__.setdefault("_paints", [])
        paints.append(self)
        self.update()

    def corners(self) -> list[float]:
        """Return the corner radii, top-left first, clockwise."""
        if self.radius is None:
            return [self.widget.height / 2] * 4
        if isinstance(self.radius, int | float):
            return [dp(self.radius)] * 4
        return [dp(value) for value in self.radius]

    def update(self, *_: Any) -> None:
        """Move the shape to the widget's current position and size."""
        x, y = self.widget.pos
        width, height = self.widget.size
        corners = self.corners()
        self.shape.pos = (x, y)
        self.shape.size = (width, height)
        self.shape.radius = corners
        inset = self.border_width / 2
        self.outline.rounded_rectangle = (
            x + inset,
            y + inset,
            max(0.0, width - 2 * inset),
            max(0.0, height - 2 * inset),
            max(corners[0] - inset, 0.0),
        )

    def set_fill(self, fill: RGBA) -> None:
        """Change the fill color."""
        self.fill_color.rgba = fill

    def set_border(self, border: RGBA | None) -> None:
        """Change the outline color, or hide it with ``None``."""
        self.border_color.rgba = border or CLEAR


# Icons are line drawings on a 24x24 grid with y pointing down, like SVG.
# Each part is ("line", [x, y, ...]), ("circle", cx, cy, r) or
# ("arc", cx, cy, r, start_degrees, end_degrees), 0 degrees at 12 o'clock.
ICONS: dict[str, list[tuple[Any, ...]]] = {
    "plus": [("line", [12, 5, 12, 19]), ("line", [5, 12, 19, 12])],
    "close": [("line", [6, 6, 18, 18]), ("line", [18, 6, 6, 18])],
    "back": [("line", [15, 6, 9, 12, 15, 18])],
    "chevron_left": [("line", [15, 6, 9, 12, 15, 18])],
    "chevron_right": [("line", [9, 6, 15, 12, 9, 18])],
    "chevron_down": [("line", [7, 10, 12, 15, 17, 10])],
    "search": [("circle", 11, 11, 7), ("line", [20, 20, 16.5, 16.5])],
    "refresh": [("arc", 12, 12, 8, 60, 360), ("line", [9, 1, 12, 4, 9, 7])],
    "sync": [
        ("line", [12, 4, 12, 15]),
        ("line", [7, 10, 12, 15, 17, 10]),
        ("line", [5, 19, 19, 19]),
    ],
    "clock": [("circle", 12, 12, 9), ("line", [12, 7, 12, 12, 15, 14])],
    "calendar": [
        ("line", [4, 6, 20, 6, 20, 20, 4, 20, 4, 6]),
        ("line", [4, 10, 20, 10]),
        ("line", [8, 3, 8, 7]),
        ("line", [16, 3, 16, 7]),
    ],
    "trash": [
        ("line", [4, 7, 20, 7]),
        ("line", [10, 11, 10, 17]),
        ("line", [14, 11, 14, 17]),
        ("line", [6, 7, 7, 20, 17, 20, 18, 7]),
        ("line", [9, 7, 9, 4, 15, 4, 15, 7]),
    ],
}


def draw_icon(
    group: InstructionGroup,
    name: str,
    x: float,
    y: float,
    size: float,
    color: RGBA,
    width: float = 1.6,
) -> None:
    """Add icon ``name`` to ``group`` with its bottom-left corner at x, y.

    ``size`` is in pixels; ``width`` is the stroke width in dp.
    """
    scale = size / 24
    width = dp(width)

    def point(px: float, py: float) -> tuple[float, float]:
        return x + px * scale, y + (24 - py) * scale

    group.add(Color(*color))
    for part in ICONS.get(name, []):
        kind = part[0]
        if kind == "line":
            coords = part[1]
            points: list[float] = []
            for index in range(0, len(coords), 2):
                points.extend(point(coords[index], coords[index + 1]))
            group.add(Line(points=points, width=width, cap="round", joint="round"))
        elif kind == "circle":
            cx, cy = point(part[1], part[2])
            group.add(Line(circle=(cx, cy, part[3] * scale), width=width))
        elif kind == "arc":
            cx, cy = point(part[1], part[2])
            group.add(
                Line(
                    circle=(cx, cy, part[3] * scale, part[4], part[5]),
                    width=width,
                    cap="round",
                )
            )


class StyledMixin:
    """Rounded background, press feedback and an optional drawn icon.

    Mixed into Kivy buttons, which keep their own text and events.
    """

    def _style(
        self,
        *,
        fill: RGBA,
        border: RGBA | None,
        radius: Radius,
        icon: str,
        icon_side: str,
        icon_color: RGBA | None,
        icon_size: float,
    ) -> None:
        """Replace the default button images with the theme's shapes."""
        widget: Any = self
        self._shape_fill = fill
        self._shape_border = border
        self.paint = Paint(widget, fill, radius=radius, border=border)
        self.icon = icon
        self.icon_side = icon_side
        self.icon_color = icon_color
        self.icon_size = dp(icon_size)
        self._icon_group = InstructionGroup()
        widget.canvas.after.add(self._icon_group)
        widget.bind(
            pos=self._draw_icon,
            size=self._draw_icon,
            texture_size=self._draw_icon,
            state=self._on_state,
            disabled=self._on_state,
        )
        self._draw_icon()

    def set_colors(
        self,
        *,
        fill: RGBA | None = None,
        border: RGBA | None = None,
        text: RGBA | None = None,
    ) -> None:
        """Change the fill, outline or text color."""
        widget: Any = self
        if fill is not None:
            self._shape_fill = fill
        self._shape_border = border
        if text is not None:
            widget.color = text
        self._on_state()

    def _on_state(self, *_: Any) -> None:
        """Darken the fill while pressed and fade it while disabled."""
        widget: Any = self
        red, green, blue, alpha = self._shape_fill
        if widget.state == "down" and alpha > 0:
            red, green, blue = red * 0.9, green * 0.9, blue * 0.9
        elif widget.state == "down":
            red, green, blue, alpha = (*SKY_TINT[:3], 1.0)
        self.paint.set_fill((red, green, blue, alpha))
        self.paint.set_border(self._shape_border)
        widget.opacity = 0.45 if widget.disabled else 1.0
        self._draw_icon()

    def _draw_icon(self, *_: Any) -> None:
        """Draw the icon left of the text, right of it, or centered alone."""
        widget: Any = self
        self._icon_group.clear()
        if not self.icon:
            return
        size = self.icon_size
        # Read x and width directly: inside a size callback the derived
        # ``right`` and ``center_x`` can still hold their previous values.
        center_x = widget.x + widget.width / 2
        if self.icon_side == "right":
            x = widget.x + widget.width - size - dp(8)
        elif widget.text:
            # The left padding reserves the icon's room in the texture.
            x = center_x - widget.texture_size[0] / 2
        else:
            x = center_x - size / 2
        y = widget.y + (widget.height - size) / 2
        color = self.icon_color or widget.color
        draw_icon(self._icon_group, self.icon, x, y, size, color)


class FlatButton(StyledMixin, Button):
    """A rounded button with theme colors and an optional icon."""

    def __init__(
        self,
        *,
        fill: RGBA = SKY,
        text_color: RGBA = INK,
        border: RGBA | None = None,
        radius: Radius = 12,
        icon: str = "",
        icon_side: str = "left",
        icon_color: RGBA | None = None,
        icon_size: float = 20,
        **kwargs: Any,
    ) -> None:
        """Create the button; keyword arguments go to ``Button``."""
        kwargs.setdefault("font_name", FONT_SEMIBOLD)
        kwargs.setdefault("font_size", "15sp")
        super().__init__(
            background_normal="",
            background_down="",
            background_disabled_normal="",
            background_disabled_down="",
            background_color=CLEAR,
            color=text_color,
            disabled_color=text_color,
            **kwargs,
        )
        if icon and icon_side == "left" and self.text:
            self.padding = (dp(icon_size + 8), 0, 0, 0)
        self._style(
            fill=fill,
            border=border,
            radius=radius,
            icon=icon,
            icon_side=icon_side,
            icon_color=icon_color,
            icon_size=icon_size,
        )


def primary_button(text: str, **kwargs: Any) -> FlatButton:
    """Return the light-blue pill used for the main action."""
    kwargs.setdefault("radius", None)
    return FlatButton(text=text, fill=SKY, text_color=INK, **kwargs)


def outline_button(text: str, **kwargs: Any) -> FlatButton:
    """Return a white button with a light-blue outline."""
    return FlatButton(
        text=text,
        fill=SURFACE,
        border=SKY,
        text_color=LINK,
        **kwargs,
    )


def ghost_button(text: str, color: RGBA = LINK, **kwargs: Any) -> FlatButton:
    """Return a borderless button that only shows its text and icon."""
    return FlatButton(text=text, fill=CLEAR, text_color=color, **kwargs)


def icon_button(icon: str, **kwargs: Any) -> FlatButton:
    """Return a round 44 px button with only an icon."""
    kwargs.setdefault("fill", SURFACE)
    kwargs.setdefault("border", BORDER)
    kwargs.setdefault("text_color", LINK)
    kwargs.setdefault("radius", None)
    return FlatButton(
        text="",
        icon=icon,
        size_hint=(None, None),
        size=(dp(44), dp(44)),
        **kwargs,
    )


def chip_button(text: str = "", **kwargs: Any) -> FlatButton:
    """Return a small pill that sizes itself to its text."""
    kwargs.setdefault("fill", SURFACE)
    kwargs.setdefault("border", BORDER)
    kwargs.setdefault("text_color", MUTED)
    kwargs.setdefault("radius", None)
    kwargs.setdefault("font_name", FONT)
    kwargs.setdefault("font_size", "13sp")
    chip = FlatButton(text=text, size_hint=(None, None), height=dp(34), **kwargs)
    fit_width(chip, 28)
    return chip


def fit_width(widget: Any, extra: float) -> None:
    """Keep ``widget`` as wide as its text plus ``extra`` dp."""

    def update(*_: Any) -> None:
        widget.width = widget.texture_size[0] + dp(extra)

    widget.bind(texture_size=update)
    update()


class ThemedOption(SpinnerOption):
    """A white dropdown row for the themed spinners."""

    def __init__(self, **kwargs: Any) -> None:
        """Create the row with theme colors."""
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = SURFACE
        self.color = INK
        self.font_name = FONT
        self.font_size = "14sp"
        self.height = dp(44)


class FlatSpinner(StyledMixin, Spinner):
    """A dropdown drawn with theme colors and an optional chevron."""

    def __init__(
        self,
        *,
        fill: RGBA = SURFACE,
        text_color: RGBA = INK,
        border: RGBA | None = BORDER,
        radius: Radius = 12,
        icon: str = "chevron_down",
        icon_size: float = 16,
        halign: str = "center",
        **kwargs: Any,
    ) -> None:
        """Create the spinner; keyword arguments go to ``Spinner``."""
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", "14sp")
        super().__init__(
            option_cls=ThemedOption,
            background_normal="",
            background_down="",
            background_disabled_normal="",
            background_disabled_down="",
            background_color=CLEAR,
            color=text_color,
            disabled_color=text_color,
            halign=halign,
            padding=(dp(12), 0, dp(36) if icon else dp(12), 0),
            shorten=True,
            shorten_from="right",
            **kwargs,
        )

        def wrap_text(*_: Any) -> None:
            # Keep long names on one line and clear of the chevron.
            self.text_size = (max(self.width, dp(10)), None)

        self.bind(width=wrap_text)
        wrap_text()
        self._style(
            fill=fill,
            border=border,
            radius=radius,
            icon=icon,
            icon_side="right",
            icon_color=MUTED,
            icon_size=icon_size,
        )


class IconView(Widget):
    """A non-interactive drawn icon."""

    def __init__(
        self,
        icon: str,
        *,
        color: RGBA = MUTED,
        icon_size: float = 18,
        **kwargs: Any,
    ) -> None:
        """Create the icon at a fixed size."""
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(icon_size), dp(icon_size)))
        super().__init__(**kwargs)
        self.icon = icon
        self.color = color
        self._group = InstructionGroup()
        self.canvas.add(self._group)
        self.bind(pos=self._draw, size=self._draw)
        self._draw()

    def _draw(self, *_: Any) -> None:
        self._group.clear()
        draw_icon(self._group, self.icon, self.x, self.y, self.width, self.color)


class ToggleSwitch(Widget):
    """An on/off switch; ``active`` works like ``CheckBox.active``."""

    active = BooleanProperty(False)

    def __init__(self, **kwargs: Any) -> None:
        """Create the switch at its fixed 48x28 size."""
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(48), dp(28)))
        super().__init__(**kwargs)
        with self.canvas:
            self._track_color = Color(*BORDER)
            self._track = RoundedRectangle(radius=[14])
            Color(*SURFACE)
            self._knob = RoundedRectangle(radius=[11])
        self.bind(pos=self._draw, size=self._draw, active=self._draw)
        # Fade while disabled, like the theme's buttons.
        self.bind(
            disabled=lambda _, disabled: setattr(
                self, "opacity", 0.45 if disabled else 1.0
            )
        )
        self._draw()

    def _draw(self, *_: Any) -> None:
        self._track.pos = self.pos
        self._track.size = self.size
        self._track.radius = [self.height / 2]
        self._track_color.rgba = DEEP_SKY if self.active else BORDER
        inset = dp(3)
        knob = self.height - 2 * inset
        x = self.x + self.width - knob - inset if self.active else self.x + inset
        self._knob.pos = (x, self.y + inset)
        self._knob.radius = [knob / 2]
        self._knob.size = (knob, knob)

    def on_touch_down(self, touch: Any) -> bool:
        """Flip the switch when it is tapped."""
        if self.disabled or not self.collide_point(*touch.pos):
            return bool(super().on_touch_down(touch))
        self.active = not self.active
        return True
