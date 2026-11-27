"""The event form's Repeat row and its custom repeat dialog.

The rules themselves (parsing, writing, words) live in ``domain.recurrence``
in ``shared/``. Only builds whose service sets repeat rules (Android) bundle
it, so the form imports this module only for such a service.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from domain.recurrence import (
    LAST_WEEK,
    MAX_COUNT,
    MAX_INTERVAL,
    UNIT_NAMES,
    WEEKDAY_NAMES,
    Frequency,
    RepeatRule,
    describe,
    format_rule,
    is_last_weekday_of_month,
    nth_weekday_name,
    parse_rule,
    preset_rules,
    rule_problem,
    rule_text,
    week_of_month,
)
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

from kivy_calendar.screens.keyboard import keyboard_inset, reported_keyboard_height
from kivy_calendar.screens.theme import (
    BACKGROUND,
    BORDER,
    CLEAR,
    DIVIDER,
    FONT_SEMIBOLD,
    INK,
    MUTED,
    OVERLAY,
    SKY,
    SURFACE,
    FlatButton,
    FlatSpinner,
    Paint,
)
from kivy_calendar.screens.time_picker import DateTimeField
from kivy_calendar.screens.ui import StatusBanner, input_box, plain_input, wrapped_label

NO_REPEAT = "Does not repeat"
CUSTOM = "Custom…"
FOREIGN = "Custom rule (kept as set)"
ENDS_NEVER = "Never"
ENDS_ON = "On a date"
ENDS_AFTER = "After a number of times"
# Room kept between the lifted dialog and the keyboard or the window top.
DIALOG_MARGIN = dp(8)

# What the Repeat row holds: a rule the form can edit, the text of a rule set
# in another app (kept as it is), or None for "does not repeat".
Choice = RepeatRule | str | None


class RepeatField(FlatSpinner):
    """A dropdown with "Does not repeat", everyday rules and "Custom…".

    It keeps the event's own rule text while the choice is unchanged, so an
    untouched rule is saved exactly as it was.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Create the dropdown; ``open_for`` fills it."""
        super().__init__(**kwargs)
        self.choice: Choice = None
        self._original: Choice = None
        self._original_text: str | None = None
        self._start = date.today()
        self._labels: dict[str, Choice] = {}
        self._updating = False
        self.dialog: RepeatDialog | None = None
        self.bind(text=self._on_text)
        self.show(None)

    def open_for(self, recurrence: list[str] | None, start: datetime) -> None:
        """Show the rule of ``recurrence`` for an event starting at ``start``."""
        text = rule_text(recurrence)
        self._original_text = text
        self._start = start.date()
        if text is None:
            self._original = None
        else:
            self._original = parse_rule(text, start.tzinfo or UTC) or text
        self.show(self._original)

    def set_start(self, start: date) -> None:
        """Offer the everyday rules for a new start date."""
        if start != self._start:
            self._start = start
            self.show(self.choice)

    @property
    def changed(self) -> bool:
        """Whether the user picked another rule than the event had."""
        return self.choice != self._original

    def recurrence(self, start: datetime, *, all_day: bool) -> list[str] | None:
        """The event's recurrence lines for the current choice."""
        choice = self.choice
        if choice is None:
            return None
        if not self.changed and self._original_text is not None:
            return [f"RRULE:{self._original_text}"]
        if isinstance(choice, str):
            return [f"RRULE:{choice}"]
        return [f"RRULE:{format_rule(choice, start, all_day=all_day)}"]

    def problem(self, start: date) -> str | None:
        """Why the chosen rule cannot be saved for ``start``, if it cannot."""
        choice = self.choice
        if not isinstance(choice, RepeatRule) or not self.changed:
            return None
        if choice.until is not None and choice.until < start:
            return "The repeat end date must be on or after the start date."
        return rule_problem(choice)

    def show(self, choice: Choice) -> None:
        """Select ``choice`` and rebuild the list around it."""
        self.choice = choice
        labels: dict[str, Choice] = {NO_REPEAT: None}
        for preset in preset_rules(self._start):
            labels[describe(preset, self._start)] = preset
        current = self._choice_label(choice)
        if current not in labels:
            labels[current] = choice
        labels[CUSTOM] = None
        self._labels = labels
        spinner: Any = self
        self._updating = True
        try:
            values = list(labels)
            if list(spinner.values) != values:
                spinner.values = values
            spinner.text = current
        finally:
            self._updating = False

    def open_dialog(self) -> None:
        """Open the custom repeat dialog with the current rule."""
        choice = self.choice
        if not isinstance(choice, RepeatRule):
            choice = RepeatRule(Frequency.WEEKLY, weekdays=(self._start.weekday(),))
        self.dialog = RepeatDialog(choice, self._start, self._on_custom_rule)
        if self.get_parent_window() is not None:
            self.dialog.open()

    def _on_custom_rule(self, rule: RepeatRule | None) -> None:
        """Apply the dialog's rule; ``None`` means it was cancelled."""
        self.dialog = None
        if rule is not None:
            self.show(rule)

    def _choice_label(self, choice: Choice) -> str:
        if choice is None:
            return NO_REPEAT
        if isinstance(choice, str):
            return FOREIGN
        return describe(choice, self._start)

    def _on_text(self, _: Any, text: str) -> None:
        """Follow a pick from the list; "Custom…" opens the dialog."""
        if self._updating:
            return
        if text == CUSTOM:
            self.show(self.choice)
            self.open_dialog()
            return
        if text in self._labels:
            self.choice = self._labels[text]


class RepeatDialog(ModalView):
    """Set any rule the app models: every N units, weekdays, ends."""

    def __init__(
        self,
        rule: RepeatRule,
        start: date,
        on_done: Callable[[RepeatRule | None], None],
    ) -> None:
        """Open on ``rule`` for an event starting on ``start``."""
        super().__init__(
            size_hint=(None, None),
            width=dp(340),
            auto_dismiss=False,
            background="",
            background_color=CLEAR,
            overlay_color=OVERLAY,
        )
        self.start = start
        self._on_done = on_done
        self._weekdays = set(rule.weekdays) or {start.weekday()}

        content = BoxLayout(
            orientation="vertical", spacing=dp(12), padding=dp(20), size_hint_y=None
        )
        content.bind(minimum_height=content.setter("height"))
        content.bind(height=lambda _, height: setattr(self, "height", height))
        Paint(content, SURFACE, radius=20)
        content.add_widget(
            wrapped_label(
                text="Custom repeat",
                font_name=FONT_SEMIBOLD,
                font_size="17sp",
                size_hint_y=None,
                height=dp(28),
            )
        )

        self.interval = _number_input("1")
        self.interval.text = str(rule.interval)
        self.unit = _spinner(
            [UNIT_NAMES[frequency][1] for frequency in Frequency],
            UNIT_NAMES[rule.frequency][1],
        )
        every = _line()
        every.add_widget(wrapped_label(text="Every", size_hint_x=None, width=dp(56)))
        every.add_widget(
            input_box(self.interval, size_hint_x=None, width=dp(64), padding=(dp(8), 0))
        )
        every.add_widget(self.unit)
        content.add_widget(every)

        self.weekday_buttons: list[FlatButton] = []
        self.weekday_row = _line(spacing=dp(4))
        for day, name in enumerate(WEEKDAY_NAMES):
            button = FlatButton(text=name[:2], font_size="13sp", radius=None)
            button.bind(on_release=lambda _, day=day: self.toggle_weekday(day))
            self.weekday_buttons.append(button)
            self.weekday_row.add_widget(button)
        self._paint_weekdays()

        self._monthly_rules = self._monthly_choices(rule)
        monthly_text = next(
            (text for text, choice in self._monthly_rules.items() if choice == rule),
            next(iter(self._monthly_rules)),
        )
        self.monthly = _spinner(list(self._monthly_rules), monthly_text)
        self.monthly_row = _line()
        self.monthly_row.add_widget(self.monthly)

        self.ends = _spinner(
            [ENDS_NEVER, ENDS_ON, ENDS_AFTER],
            ENDS_AFTER if rule.count else ENDS_ON if rule.until else ENDS_NEVER,
        )
        ends = _line()
        ends.add_widget(wrapped_label(text="Ends", size_hint_x=None, width=dp(56)))
        ends.add_widget(self.ends)
        content.add_widget(ends)

        self.until = DateTimeField(title="Ends")
        self.until.show_time = False
        self.until.text = (rule.until or start).isoformat()
        self.until_row = _line()
        self.until_row.add_widget(Widget(size_hint_x=None, width=dp(64)))
        self.until_row.add_widget(self.until)

        self.count = _number_input("10")
        self.count.text = str(rule.count or 10)
        self.count_row = _line()
        self.count_row.add_widget(Widget(size_hint_x=None, width=dp(64)))
        self.count_row.add_widget(
            input_box(self.count, size_hint_x=None, width=dp(64), padding=(dp(8), 0))
        )
        self.count_row.add_widget(wrapped_label(text="times", color=MUTED))

        self.status = StatusBanner(collapse=True)
        buttons = _line()
        cancel = FlatButton(
            text="Cancel", fill=BACKGROUND, text_color=INK, border=DIVIDER
        )
        done = FlatButton(text="Done", fill=SKY, text_color=INK)
        cancel.bind(on_release=lambda *_: self.cancel())
        done.bind(on_release=lambda *_: self.done())
        buttons.add_widget(cancel)
        buttons.add_widget(done)

        self._content = content
        # Rows that come and go with the unit and the end choice sit
        # between "Every" and "Ends", or between "Ends" and the buttons.
        self._optional = (self.weekday_row, self.monthly_row)
        self._end_rows = (self.until_row, self.count_row)
        self._status = self.status
        self._buttons = buttons
        content.add_widget(self.status)
        content.add_widget(buttons)
        self.unit.bind(text=lambda *_: self._arrange())
        self.ends.bind(text=lambda *_: self._arrange())
        self._arrange()
        self.add_widget(content)
        # Lift the dialog above the keyboard while a number is typed in.
        for field in (self.interval, self.count):
            field.bind(focus=self._align_center)
        Window.bind(keyboard_height=self._align_center)
        self.bind(
            on_dismiss=lambda *_: Window.unbind(keyboard_height=self._align_center)
        )

    def keyboard_inset(self) -> float:
        """Height the keyboard takes at the bottom while a field is focused."""
        return keyboard_inset(
            reported_keyboard_height(),
            Window.height,
            mobile=platform in ("android", "ios"),
            focused=self.interval.focus or self.count.focus,
        )

    def _align_center(self, *_args: Any) -> None:
        """Center the dialog, or keep it above the keyboard while typing.

        Overrides ``ModalView``'s own centering, which runs on every size and
        window change. Without a keyboard it centers as usual.
        """
        inset = self.keyboard_inset()
        window = self._window
        if not inset or window is None:
            super()._align_center()
            return
        self.center_x = window.center[0]
        self.y = min(inset + DIALOG_MARGIN, window.height - self.height - DIALOG_MARGIN)

    @property
    def frequency(self) -> Frequency:
        """The chosen unit."""
        for frequency, names in UNIT_NAMES.items():
            if self.unit.text == names[1]:
                return frequency
        return Frequency.WEEKLY

    def toggle_weekday(self, day: int) -> None:
        """Add or remove a weekday; at least one stays chosen."""
        if day in self._weekdays and len(self._weekdays) > 1:
            self._weekdays.remove(day)
        else:
            self._weekdays.add(day)
        self._paint_weekdays()

    def rule(self) -> RepeatRule | str:
        """The rule the dialog shows, or why it cannot be used."""
        try:
            interval = int(self.interval.text.strip() or "0")
        except ValueError:
            interval = 0
        if not 1 <= interval <= MAX_INTERVAL:
            return f"Repeat every 1 to {MAX_INTERVAL} {self.unit.text}."
        frequency = self.frequency
        rule = RepeatRule(frequency, interval=interval)
        if frequency == Frequency.WEEKLY:
            rule = replace(rule, weekdays=tuple(sorted(self._weekdays)))
        elif frequency == Frequency.MONTHLY:
            monthly = self._monthly_rules.get(self.monthly.text)
            if monthly is not None:
                rule = replace(
                    rule,
                    month_day=monthly.month_day,
                    week_of_month=monthly.week_of_month,
                    weekdays=monthly.weekdays,
                )
        if self.ends.text == ENDS_AFTER:
            try:
                count = int(self.count.text.strip() or "0")
            except ValueError:
                count = 0
            if not 1 <= count <= MAX_COUNT:
                return f"End after 1 to {MAX_COUNT} times."
            rule = replace(rule, count=count)
        elif self.ends.text == ENDS_ON:
            try:
                until = date.fromisoformat(self.until.text)
            except ValueError:
                return "Choose the last date."
            if until < self.start:
                return "The end date must be on or after the start date."
            rule = replace(rule, until=until)
        return rule_problem(rule) or rule

    def done(self) -> None:
        """Hand the rule back, or show what is wrong with it."""
        rule = self.rule()
        if isinstance(rule, str):
            self.status.show(rule, error=True)
            return
        self.dismiss()
        self._on_done(rule)

    def cancel(self) -> None:
        """Close without changing the rule."""
        self.dismiss()
        self._on_done(None)

    def _monthly_choices(self, rule: RepeatRule) -> dict[str, RepeatRule]:
        """ "On day 26", "On the 4th Thursday" and, if so, "On the last …"."""
        start = self.start
        weekday = start.weekday()
        choices = {
            f"On day {start.day}": RepeatRule(Frequency.MONTHLY, month_day=start.day)
        }
        week = week_of_month(start)
        if week != LAST_WEEK:
            nth = RepeatRule(Frequency.MONTHLY, week_of_month=week, weekdays=(weekday,))
            choices[f"On the {nth_weekday_name(week, weekday)}"] = nth
        if is_last_weekday_of_month(start):
            last = RepeatRule(
                Frequency.MONTHLY, week_of_month=LAST_WEEK, weekdays=(weekday,)
            )
            choices[f"On the {nth_weekday_name(LAST_WEEK, weekday)}"] = last
        # Keep a monthly rule set elsewhere selectable, e.g. day 15 on the 26th.
        if rule.frequency == Frequency.MONTHLY:
            own = RepeatRule(
                Frequency.MONTHLY,
                month_day=rule.month_day,
                week_of_month=rule.week_of_month,
                weekdays=rule.weekdays,
            )
            if own not in choices.values() and (rule.month_day or rule.week_of_month):
                words = describe(own, start).removeprefix("Every month on ")
                choices[f"On {words}"] = own
        return choices

    def _arrange(self) -> None:
        """Show the rows that belong to the chosen unit and end."""
        content = self._content
        for row in (*self._optional, *self._end_rows):
            if row.parent is not None:
                content.remove_widget(row)
        # Kivy lists children last-first; index counts from the bottom.
        if self.frequency == Frequency.WEEKLY:
            content.add_widget(self.weekday_row, index=len(content.children) - 2)
        elif self.frequency == Frequency.MONTHLY:
            content.add_widget(self.monthly_row, index=len(content.children) - 2)
        if self.ends.text == ENDS_ON:
            content.add_widget(self.until_row, index=2)
        elif self.ends.text == ENDS_AFTER:
            content.add_widget(self.count_row, index=2)

    def _paint_weekdays(self) -> None:
        for day, button in enumerate(self.weekday_buttons):
            if day in self._weekdays:
                button.set_colors(fill=SKY, border=None, text=INK)
            else:
                button.set_colors(fill=SURFACE, border=BORDER, text=MUTED)


def _number_input(hint: str) -> TextInput:
    """A whole-number field with its text centered in the box both ways."""
    field = plain_input(hint, input_filter="int", input_type="number", halign="center")

    def center(*_: Any) -> None:
        # TextInput has no vertical alignment; equal top and bottom padding
        # around one line puts the text in the middle of the box.
        room = max((field.height - field.line_height) / 2, 0)
        field.padding = (0, room, 0, room)

    field.bind(height=center, line_height=center)
    center()
    return field


def _line(**kwargs: Any) -> BoxLayout:
    kwargs.setdefault("spacing", dp(8))
    return BoxLayout(
        orientation="horizontal", size_hint_y=None, height=dp(44), **kwargs
    )


def _spinner(values: list[str], text: str) -> FlatSpinner:
    return FlatSpinner(text=text, values=values, size_hint_y=None, height=dp(44))
