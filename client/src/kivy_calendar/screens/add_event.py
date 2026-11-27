"""Create and edit events in the backend calendar."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.utils import platform

from kivy_calendar.formatting import (
    DEFAULT_TIME_ZONE,
    default_event_times,
    localize_wall_clock,
    to_wall_clock_value,
)
from kivy_calendar.models import (
    ONLY_THIS,
    CalendarEvent,
    CalendarSummary,
    EditScope,
    FreeSlot,
    ServiceError,
    TimeZoneOption,
)
from kivy_calendar.screens.keyboard import (
    keyboard_inset,
    reported_keyboard_height,
    scroll_into_view,
)
from kivy_calendar.screens.scroll_effect import SteadyScrollEffect
from kivy_calendar.screens.theme import (
    BACKGROUND,
    CLEAR,
    CORAL,
    CORAL_TEXT,
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
    ToggleSwitch,
    ghost_button,
    icon_button,
    outline_button,
    primary_button,
)
from kivy_calendar.screens.time_picker import DateTimeField
from kivy_calendar.screens.ui import (
    Card,
    StatusBanner,
    caption,
    input_box,
    plain_input,
    wrapped_label,
)
from kivy_calendar.service import CalendarService

if TYPE_CHECKING:
    from kivy_calendar.screens.repeat_field import RepeatField

QUEUED_NOTICE = "Saved. Google is unreachable, so it will sync automatically."
REPEATING_NOTE = (
    "This is one occurrence of a repeating event. Repeating events can't be "
    "changed here yet; edit them in your phone's calendar app."
)
SPINNER_WIDTH = dp(190)
# Row padding, spacing and the "Repeat" caption, left of the Repeat dropdown.
REPEAT_CAPTION = dp(100)
SCOPE_LABELS = {
    EditScope.THIS: "This event",
    EditScope.FOLLOWING: "This and following events",
    EditScope.ALL: "All events",
}


def _row_spinner(text: str = "", values: list[str] | None = None) -> FlatSpinner:
    """Return a borderless dropdown that sits on the right of a form row."""
    return FlatSpinner(
        text=text,
        values=values or [],
        fill=CLEAR,
        border=None,
        text_color=MUTED,
        icon="chevron_right",
        halign="right",
        size_hint=(None, None),
        size=(SPINNER_WIDTH, dp(44)),
    )


def _set_values(spinner: Any, values: list[str]) -> None:
    """Set a spinner's values unless they are unchanged.

    Kivy rebuilds every option widget on each assignment, even of equal values,
    which is slow for the long time zone list.
    """
    if list(spinner.values) != values:
        spinner.values = values


def _right(widget: Any, height: float = 56) -> BoxLayout:
    """Right-align a fixed-size widget inside a form row."""
    box = BoxLayout(orientation="horizontal", size_hint_x=None, padding=(0, 0))
    box.add_widget(Widget())
    holder = BoxLayout(orientation="vertical", size_hint_x=None)
    holder.add_widget(Widget())
    holder.add_widget(widget)
    holder.add_widget(Widget())
    box.add_widget(holder)

    def fit(*_: Any) -> None:
        holder.width = widget.width
        box.width = widget.width

    widget.bind(width=fit)
    fit()
    return box


class AddEventScreen(Screen):
    """Create a new event or edit an existing one in the backend."""

    def __init__(
        self,
        client: CalendarService | None,
        refresh: Callable[[], None],
        time_zone: str = DEFAULT_TIME_ZONE,
        event: CalendarEvent | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the screen with event fields, save, delete and cancel."""
        super().__init__(**kwargs)
        self.client = client
        self.refresh = refresh
        self.time_zone = time_zone
        self.event: CalendarEvent | None = None
        # Id for a new event, fixed when the form opens so every Save press
        # (e.g. after a timeout) sends the same id and cannot duplicate it.
        self._new_event_id = ""
        self._calendars: list[CalendarSummary] = []
        self._calendar_labels: dict[str, str] = {}
        self._labels_by_calendar: dict[str, str] = {}
        self._time_zone_names: dict[str, str] = {}
        self._time_zone_labels: dict[str, str] = {}
        self._curated_zones: list[TimeZoneOption] = []

        self.summary = plain_input(
            "Team standup",
            font_name=FONT_SEMIBOLD,
            font_size="22sp",
            size_hint_y=None,
            height=dp(48),
            padding=(0, dp(8)),
        )
        self.calendar = _row_spinner()
        self.start = DateTimeField(title="Start")
        self.end = DateTimeField(title="End")
        self.start.on_user_change = self._on_start_changed
        self.start_timezone = _row_spinner(self.time_zone, [self.time_zone])
        self.end_timezone = _row_spinner(self.time_zone, [self.time_zone])
        self.description = plain_input(
            "Optional notes",
            multiline=True,
            padding=(0, dp(12)),
        )
        self.all_day = ToggleSwitch()

        form = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(16),
            padding=(dp(20), dp(8), dp(20), dp(24)),
        )
        form.bind(minimum_height=form.setter("height"))

        title_field = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(72))
        title_field.add_widget(caption("Title"))
        title_field.add_widget(self.summary)
        underline = Widget(size_hint_y=None, height=dp(2))
        Paint(underline, SKY, radius=0)
        title_field.add_widget(underline)
        form.add_widget(title_field)

        when = Card()
        when.add_row("Calendar", _right(self.calendar))
        when.add_row("All day", _right(self.all_day))
        self._start_field = when.add_row("Starts", _right(self.start), height=dp(56))
        self._end_field = when.add_row("Ends", _right(self.end), height=dp(56))
        self._start_label = self._start_field.caption
        self._end_label = self._end_field.caption
        # The Repeat row only for services that set repeat rules (Android);
        # its rules come from shared/, which only those builds bundle.
        self.repeat: RepeatField | None = None
        if getattr(client, "edits_repeat_rules", False):
            from kivy_calendar.screens.repeat_field import RepeatField

            self.repeat = RepeatField(
                fill=CLEAR,
                border=None,
                text_color=MUTED,
                icon="chevron_right",
                halign="right",
                size_hint=(None, None),
                size=(SPINNER_WIDTH, dp(44)),
            )
            repeat_row = when.add_row("Repeat", _right(self.repeat))
            repeat = self.repeat

            def widen(*_: Any) -> None:
                # Rules read longer than calendar names: give the dropdown
                # all the room the short "Repeat" caption leaves.
                repeat.width = max(SPINNER_WIDTH, repeat_row.width - REPEAT_CAPTION)

            repeat_row.bind(width=widen)
        # The open "which occurrences?" question, if any.
        self.scope_popup: ModalView | None = None
        self.scope_buttons: dict[EditScope, Any] = {}
        form.add_widget(when)

        zones = Card()
        zones.add_row("Start time zone", _right(self.start_timezone))
        zones.add_row("End time zone", _right(self.end_timezone))
        form.add_widget(zones)

        self.all_day.bind(active=self._on_all_day_changed)

        self.suggest_button = outline_button(
            "Suggest a free time",
            icon="clock",
            icon_size=18,
            radius=14,
            size_hint_y=None,
            height=dp(48),
        )
        self.suggest_button.bind(on_press=self.suggest_free_time)
        form.add_widget(self.suggest_button)

        notes = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(116))
        notes.add_widget(caption("Notes"))
        notes.add_widget(
            input_box(self.description, height=dp(96), padding=(dp(14), 0))
        )
        form.add_widget(notes)

        self.delete_button = ghost_button(
            "Delete event",
            color=CORAL_TEXT,
            icon="trash",
            icon_size=18,
            size_hint_y=None,
            height=dp(44),
        )
        self.delete_button.bind(on_press=self.confirm_delete)
        # Holds the delete button only while an existing event is open.
        self._delete_slot = BoxLayout(size_hint_y=None, height=dp(44))
        form.add_widget(self._delete_slot)

        self.scroll_view = ScrollView(
            bar_width=dp(4), effect_cls=SteadyScrollEffect
        )
        self._top_trigger = Clock.create_trigger(self._scroll_to_top_when_idle, 0)
        # Work that would change the form's widgets while it slides in or out
        # waits here until the slide is over.
        self._after_slide: list[Callable[[], None]] = []
        self.scroll_view.add_widget(form)

        self.cancel_button = icon_button("back", fill=CLEAR, border=None)
        self.cancel_button.bind(on_press=self.cancel)
        self.save_button = primary_button(
            "Save", size_hint=(None, None), size=(dp(84), dp(40))
        )
        self.save_button.bind(on_press=self.save_event)
        self.title_label = wrapped_label(
            text="New event",
            font_name=FONT_SEMIBOLD,
            font_size="17sp",
        )
        self.title_label.halign = "center"
        save_box = BoxLayout(
            orientation="vertical", size_hint_x=None, width=dp(84), padding=(0, dp(2))
        )
        save_box.add_widget(self.save_button)
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            padding=(dp(12), 0, dp(16), 0),
            spacing=dp(8),
        )
        header.add_widget(self.cancel_button)
        header.add_widget(self.title_label)
        # Balance the save button so the title stays centered.
        header.add_widget(Widget(size_hint_x=None, width=dp(84) - 44))
        header.add_widget(save_box)

        self.status_label = StatusBanner(collapse=True)
        status_box = BoxLayout(size_hint_y=None, height=0, padding=(dp(20), 0))
        status_box.add_widget(self.status_label)
        self.status_label.bind(
            height=lambda _, height: setattr(status_box, "height", height)
        )

        layout = BoxLayout(
            orientation="vertical", padding=(0, dp(20), 0, 0), spacing=dp(8)
        )
        layout.add_widget(header)
        layout.add_widget(status_box)
        layout.add_widget(self.scroll_view)
        self.add_widget(layout)
        # The form leaves room for the on-screen keyboard at its bottom while a
        # text field is focused, and scrolls that field into the room left.
        self._layout = layout
        self._keyboard_inset = 0.0
        self._watching_keyboard = False
        for field in (self.summary, self.description):
            field.bind(focus=self._on_field_focus)
        self.scroll_view.bind(height=self._show_focused_field)

        self.open_for(event)

    def open_for(
        self,
        event: CalendarEvent | None,
        *,
        start: datetime | None = None,
        all_day: bool = False,
    ) -> None:
        """Fill the form for creating a new event or editing ``event``.

        For a new event, ``start`` (an aware datetime) prefills the start in
        the form's time zone with the usual one-hour length, and ``all_day``
        makes it an all-day event on that date.  Both are ignored when
        editing.
        """
        self._run_after_slide()
        self._release_text_inputs()
        self.event = event
        self._new_event_id = uuid4().hex if event is None else ""
        # Services that cannot edit repeating occurrences (the phone calendar)
        # open them read-only.
        self.read_only = (
            event is not None
            and event.recurring_event_id is not None
            and not getattr(self.client, "edits_repeating_events", True)
        )
        self.calendar.text = ""
        if event is None:
            self.title_label.text = "New event"
            self._reset_form()
            if start is not None:
                self._prefill_start(start, all_day)
        else:
            self.title_label.text = "Edit event"
            self.all_day.active = event.all_day
            self.summary.text = event.summary
            if event.all_day:
                self.start.text = event.start.date().isoformat()
                # The end is exclusive for all-day events.
                end_day = event.end.date() - timedelta(days=1)
                if end_day < event.start.date():
                    end_day = event.start.date()
                self.end.text = end_day.isoformat()
            else:
                self.start.text = self._wall_clock(event.start, event.start_timezone)
                self.end.text = self._wall_clock(event.end, event.end_timezone)
            self._refresh_time_zone_choices(
                event.start_timezone, event.end_timezone
            )
            self.description.text = event.description or ""
            self._apply_all_day_mode(event.all_day)
        if self.repeat is not None:
            self.repeat.open_for(
                event.recurrence if event is not None else None,
                event.start if event is not None else self._form_start(),
            )
        if self.read_only:
            self.title_label.text = "Repeating event"
        self._set_fields_editable(not self.read_only)
        self._set_buttons_enabled(True)
        self._show_default_status()
        self._load_calendars()
        self._load_time_zones()
        # The fields above change the content height; scroll to the top again
        # once Kivy has laid them out.
        self._top_trigger()

    def on_enter(self, *args: Any) -> None:
        """Clear any message left over from a previous visit."""
        self._show_default_status()
        self._run_after_slide()

    def on_pre_leave(self, *args: Any) -> None:
        """Drop focus and handles as soon as the form starts to close."""
        self._release_text_inputs()

    def on_leave(self, *args: Any) -> None:
        """Drop focus, selection and selection handles when the form closes."""
        self._release_text_inputs()
        self._run_after_slide()

    def _sliding(self) -> bool:
        """Whether the form is part of a running screen transition."""
        manager = self.manager
        if manager is None:
            return False
        transition = manager.transition
        return bool(transition.is_active) and self in (
            transition.screen_in,
            transition.screen_out,
        )

    def _when_slide_ends(self, action: Callable[[], None]) -> None:
        """Run ``action`` now, or after the form has finished sliding.

        Rebuilding dropdowns or clearing fields while the form moves makes the
        slide stall, so those changes wait for ``on_enter`` / ``on_leave``.
        """
        if self._sliding():
            self._after_slide.append(action)
        else:
            action()

    def _run_after_slide(self) -> None:
        """Run the changes that were held back during a slide."""
        pending, self._after_slide = self._after_slide, []
        for action in pending:
            action()

    def _release_text_inputs(self) -> None:
        """Unfocus every text field and remove its selection handles.

        On a phone the handles and the cut/copy/paste bubble live on the
        Window, not in the form, so they stay on screen over every other view
        unless they are removed explicitly.
        """
        for field in (self.summary, self.description):
            field.cancel_long_touch_event()
            field._trigger_show_handles.cancel()
            field.focus = False
            field.cancel_selection()
            field._hide_cut_copy_paste()
            field._hide_handles()
        self._scroll_to_top()

    def _focused_field(self) -> Any:
        """The text field being edited, or ``None``."""
        for field in (self.summary, self.description):
            if field.focus:
                return field
        return None

    def _on_field_focus(self, *_: Any) -> None:
        """Follow the keyboard while a field is focused; make room for it."""
        focused = self._focused_field() is not None
        if focused and not self._watching_keyboard:
            Window.bind(keyboard_height=self._update_keyboard_inset)
            self._watching_keyboard = True
        elif not focused and self._watching_keyboard:
            Window.unbind(keyboard_height=self._update_keyboard_inset)
            self._watching_keyboard = False
        self._update_keyboard_inset()

    def _update_keyboard_inset(self, *_: Any) -> None:
        """Reserve the keyboard's height at the form's bottom; show the field."""
        field = self._focused_field()
        inset = keyboard_inset(
            reported_keyboard_height(),
            Window.height,
            mobile=platform in ("android", "ios"),
            focused=field is not None,
        )
        if inset != self._keyboard_inset:
            self._keyboard_inset = inset
            self._layout.padding = (0, dp(20), 0, inset)
        if field is not None:
            Clock.schedule_once(self._show_focused_field, 0)

    def _show_focused_field(self, *_: Any) -> None:
        """Scroll the focused field into the part of the form above the keyboard."""
        field = self._focused_field()
        if field is None:
            return
        effect = self.scroll_view.effect_y
        if effect is not None and effect.is_manual:
            return  # a finger is scrolling; do not fight it
        scroll_into_view(self.scroll_view, field)

    def _scroll_to_top(self) -> None:
        """Show the top of the form and stop any scrolling in progress.

        The scroll effect owns the position: setting ``scroll_y`` alone leaves
        its old value and speed running, and they overwrite it a frame later.
        """
        scroll = self.scroll_view
        effect = scroll.effect_y
        if isinstance(effect, SteadyScrollEffect):
            effect.halt(scroll.height - scroll.viewport_size[1])
        scroll.scroll_y = 1.0

    def _scroll_to_top_when_idle(self, *_: Any) -> None:
        """Re-apply the top position after layout, unless a finger is down."""
        effect = self.scroll_view.effect_y
        if effect is not None and effect.is_manual:
            return
        self._scroll_to_top()

    def _show_default_status(self) -> None:
        """Show the read-only note, or nothing."""
        self._set_status(REPEATING_NOTE if self.read_only else "")

    def _set_fields_editable(self, editable: bool) -> None:
        """Lock or unlock every input of the form.

        On a phone Kivy makes a read-only text field unfocusable for good: it
        never makes it focusable again when ``readonly`` goes back to False.
        Without ``is_focusable`` below, opening one repeating event would
        leave every later Title and Notes field dead (no keyboard).
        """
        for field in (self.summary, self.description):
            field.readonly = not editable
            field.is_focusable = editable
        for widget in (
            self.calendar,
            self.all_day,
            self.start,
            self.end,
            self.start_timezone,
            self.end_timezone,
            self.repeat,
        ):
            if widget is not None:
                widget.disabled = not editable

    def save_event(self, *args: Any) -> None:
        """Validate the form and save the event in the background."""
        client = self.client
        if client is None:
            self._set_status("Backend client is not configured.", error=True)
            return
        event = self._build_event()
        if event is None:
            return
        scopes = self._save_scopes(event)
        if len(scopes) > 1:
            self.ask_scope(
                "Save repeating event",
                "Which occurrences should change?",
                scopes,
                lambda scope: self._start_save(client, event, scope),
            )
            return
        self._start_save(client, event, scopes[0])

    def _start_save(
        self, client: CalendarService, event: CalendarEvent, scope: EditScope
    ) -> None:
        """Save the event in the background with the chosen scope."""
        editing = self.event is not None
        self._set_buttons_enabled(False)
        self._set_status("Saving event…")
        thread = threading.Thread(
            target=self._persist_event,
            args=(client, event, editing, scope),
            daemon=True,
        )
        thread.start()

    def _offered_scopes(self) -> tuple[EditScope, ...]:
        """The scopes the service accepts for an occurrence of a series."""
        scopes = getattr(self.client, "repeat_scopes", ONLY_THIS)
        return tuple(scopes) or ONLY_THIS

    def _save_scopes(self, event: CalendarEvent) -> tuple[EditScope, ...]:
        """The scopes to offer for saving ``event``.

        Only occurrences of a series get a choice. A new repeat rule or
        another calendar cannot apply to one occurrence alone.
        """
        existing = self.event
        if existing is None or existing.recurring_event_id is None:
            return ONLY_THIS
        offered = self._offered_scopes()
        rule_changed = self.repeat is not None and self.repeat.changed
        if rule_changed or event.calendar_id != existing.calendar_id:
            wider = tuple(scope for scope in offered if scope != EditScope.THIS)
            return wider or offered
        return offered

    def ask_scope(
        self,
        title: str,
        message: str,
        scopes: tuple[EditScope, ...],
        on_choice: Callable[[EditScope], None],
        *,
        destructive: bool = False,
    ) -> None:
        """Ask which occurrences of a repeating event to change or delete."""
        popup = ModalView(
            size_hint=(None, None),
            size=(dp(320), dp(120) + dp(52) * (len(scopes) + 1)),
            auto_dismiss=False,
            background="",
            background_color=CLEAR,
            overlay_color=OVERLAY,
        )
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=20)
        Paint(content, SURFACE, radius=20)
        content.add_widget(
            wrapped_label(
                text=title,
                font_name=FONT_SEMIBOLD,
                font_size="17sp",
                size_hint_y=None,
                height=dp(28),
            )
        )
        content.add_widget(wrapped_label(text=message, font_size="14sp", color=MUTED))
        self.scope_popup = popup
        self.scope_buttons = {}

        def close() -> None:
            popup.dismiss()
            self.scope_popup = None
            self.scope_buttons = {}

        for scope in scopes:
            button = FlatButton(
                text=SCOPE_LABELS[scope],
                fill=CORAL if destructive else SKY,
                text_color=INK,
                size_hint_y=None,
                height=dp(44),
            )

            def chosen(*_: Any, scope: EditScope = scope) -> None:
                close()
                on_choice(scope)

            button.bind(on_release=chosen)
            self.scope_buttons[scope] = button
            content.add_widget(button)
        cancel = FlatButton(
            text="Keep" if destructive else "Cancel",
            fill=BACKGROUND,
            text_color=INK,
            border=DIVIDER,
            size_hint_y=None,
            height=dp(44),
        )
        cancel.bind(on_release=lambda *_: close())
        content.add_widget(cancel)
        popup.add_widget(content)
        popup.open()

    def _persist_event(
        self,
        client: CalendarService,
        event: CalendarEvent,
        editing: bool,
        scope: EditScope = EditScope.THIS,
    ) -> None:
        """Create or update the event off the UI thread."""
        try:
            if editing:
                current = self.event
                saved = client.update_event(
                    event,
                    source_calendar_id=current.calendar_id if current else "",
                    scope=scope,
                )
            else:
                saved = client.create_event(event)
        except ServiceError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_save_failed(message))
            return
        queued = saved.queued
        Clock.schedule_once(lambda *_: self._on_saved(queued))

    def _on_save_failed(self, message: str) -> None:
        """Re-enable the form and show the backend error."""
        self._set_buttons_enabled(True)
        self._set_status(f"Could not save event: {message}", error=True)

    def _on_saved(self, queued: bool = False) -> None:
        """Return to the main screen and refresh the event list."""
        self._return_to_main(self._notice("saved_notice", queued))

    def _load_time_zones(self) -> None:
        """Fetch the curated time zones for the dropdowns off the UI thread."""
        client = self.client
        if client is None:
            return
        thread = threading.Thread(
            target=self._fetch_time_zones,
            args=(client,),
            daemon=True,
        )
        thread.start()

    def _fetch_time_zones(self, client: CalendarService) -> None:
        """Load time zones in the background and apply them on the UI thread."""
        try:
            zones = client.list_time_zones()
        except ServiceError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_time_zones_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_time_zones_loaded(zones))

    def _on_time_zones_loaded(self, zones: list[TimeZoneOption]) -> None:
        """Offer the backend's zones, keeping the current selection."""
        self._curated_zones = list(zones)
        self._when_slide_ends(
            lambda: self._refresh_time_zone_choices(
                self._resolved_time_zone(self.start_timezone.text),
                self._resolved_time_zone(self.end_timezone.text),
            )
        )

    def _on_time_zones_failed(self, message: str) -> None:
        """Report that time zones could not be loaded; the current zone stays."""
        self._set_status(f"Could not load time zones: {message}", error=True)

    def _refresh_time_zone_choices(self, start_zone: str, end_zone: str) -> None:
        """Rebuild the dropdowns and select ``start_zone`` and ``end_zone``.

        The two zones are always selectable, even when the backend's curated
        list does not contain them.
        """
        options = list(self._curated_zones)
        known = {option.name for option in options}
        for zone in (start_zone, end_zone):
            if zone and zone not in known:
                options.insert(0, TimeZoneOption(name=zone, label=zone))
                known.add(zone)
        self._time_zone_names = {option.label: option.name for option in options}
        self._time_zone_labels = {option.name: option.label for option in options}
        values = [option.label for option in options]
        _set_values(self.start_timezone, values)
        _set_values(self.end_timezone, values)
        self.start_timezone.text = self._time_zone_labels.get(start_zone, start_zone)
        self.end_timezone.text = self._time_zone_labels.get(end_zone, end_zone)

    def _load_calendars(self) -> None:
        """Fetch the writable calendars for the dropdown off the UI thread."""
        client = self.client
        if client is None:
            return
        self.calendar.disabled = True
        thread = threading.Thread(
            target=self._fetch_calendars,
            args=(client,),
            daemon=True,
        )
        thread.start()

    def _fetch_calendars(self, client: CalendarService) -> None:
        """Load calendars in the background and apply them on the UI thread."""
        try:
            calendars = client.list_calendars()
        except ServiceError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_calendars_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_calendars_loaded(calendars))

    def _on_calendars_loaded(self, calendars: list[CalendarSummary]) -> None:
        """Fill the dropdown and select the event's calendar."""
        self._when_slide_ends(lambda: self._apply_calendars(calendars))

    def _apply_calendars(self, calendars: list[CalendarSummary]) -> None:
        """Fill the calendar dropdown now."""
        self._calendars = list(calendars)
        self._calendar_labels = {}
        self._labels_by_calendar = {}
        labels: list[str] = []
        for calendar in self._calendars:
            label = calendar.summary
            if label in self._calendar_labels:
                label = f"{calendar.summary} ({calendar.id})"
            self._calendar_labels[label] = calendar.id
            self._labels_by_calendar[calendar.id] = label
            labels.append(label)
        _set_values(self.calendar, labels)
        self.calendar.disabled = not labels or self.read_only
        self._select_current_calendar()

    def _on_calendars_failed(self, message: str) -> None:
        """Report that calendars could not be loaded and keep saving usable."""
        self.calendar.disabled = True
        self._set_status(f"Could not load calendars: {message}", error=True)

    def _select_current_calendar(self) -> None:
        """Select the edited event's calendar, or the primary calendar."""
        event = self.event
        if event is not None and event.calendar_id:
            label = self._labels_by_calendar.get(event.calendar_id)
            self.calendar.text = label if label is not None else event.calendar_id
            return
        for calendar in self._calendars:
            if calendar.primary:
                self.calendar.text = self._labels_by_calendar[calendar.id]
                return
        if self._calendars:
            self.calendar.text = self._labels_by_calendar[self._calendars[0].id]

    def _selected_calendar_id(self) -> str:
        """Return the calendar id behind the dropdown selection, or blank."""
        return self._calendar_labels.get(self.calendar.text.strip(), "")

    def suggest_free_time(self, *args: Any) -> None:
        """Ask the backend for a free window and fill the form with it."""
        if self.all_day.active:
            self._set_status(
                "Free-time suggestions are not available for all-day events."
            )
            return
        client = self.client
        if client is None:
            self._set_status("Backend client is not configured.", error=True)
            return
        time_zone = self._resolved_time_zone(self.start_timezone.text)
        if not self._is_known_time_zone(time_zone):
            self._set_status(f"Unknown time zone: {time_zone}", error=True)
            return
        duration_minutes = self._duration_minutes()
        zone = ZoneInfo(time_zone)
        window_start = datetime.now(zone)
        window_end = window_start + timedelta(days=7)
        self.suggest_button.disabled = True
        self._set_status("Looking for a free time…")
        thread = threading.Thread(
            target=self._find_free_slots,
            args=(
                client,
                duration_minutes,
                window_start,
                window_end,
                time_zone,
            ),
            daemon=True,
        )
        thread.start()

    def _duration_minutes(self) -> int:
        """Return the form duration, or an hour when the times are unusable."""
        if self.all_day.active:
            return 24 * 60
        try:
            start = localize_wall_clock(
                self.start.text, self._resolved_time_zone(self.start_timezone.text)
            )
            end = localize_wall_clock(
                self.end.text, self._resolved_time_zone(self.end_timezone.text)
            )
            difference = end - start
        except (TypeError, ValueError):
            return 60
        if difference <= timedelta(0):
            return 60
        return max(1, int(difference.total_seconds() // 60))

    def _on_start_changed(self, previous_start: str) -> None:
        """Keep the duration and offer repeat rules for the new date."""
        self._keep_duration_after_start_change(previous_start)
        self._follow_start_in_repeat()

    def _follow_start_in_repeat(self) -> None:
        """Let the Repeat row offer rules for the form's start date."""
        if self.repeat is not None:
            self.repeat.set_start(self._form_start().date())

    def _form_start(self) -> datetime:
        """Midnight of the form's start date in its start zone."""
        try:
            zone = ZoneInfo(self._resolved_time_zone(self.start_timezone.text))
        except (ValueError, ZoneInfoNotFoundError):
            zone = ZoneInfo("UTC")
        try:
            day = date.fromisoformat(self.start.text.partition("T")[0])
        except ValueError:
            day = datetime.now(zone).date()
        return datetime.combine(day, time(), tzinfo=zone)

    def _keep_duration_after_start_change(self, previous_start: str) -> None:
        """Move the end with a changed start so the duration stays put."""
        if self.all_day.active:
            self._keep_day_span_after_start_change(previous_start)
            return
        start_zone = self._resolved_time_zone(self.start_timezone.text)
        end_zone = self._resolved_time_zone(self.end_timezone.text)
        try:
            new_start = localize_wall_clock(self.start.text, start_zone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            return
        try:
            duration = localize_wall_clock(
                self.end.text, end_zone
            ) - localize_wall_clock(previous_start, start_zone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            duration = timedelta(hours=1)
        if duration <= timedelta(0):
            duration = timedelta(hours=1)
        self.end.text = self._wall_clock(new_start + duration, end_zone)

    def _keep_day_span_after_start_change(self, previous_start: str) -> None:
        """Move an all-day end date by as many days as the start moved."""
        try:
            new_start = date.fromisoformat(self.start.text)
        except ValueError:
            return
        try:
            span = date.fromisoformat(self.end.text) - date.fromisoformat(
                previous_start
            )
        except ValueError:
            span = timedelta(0)
        if span < timedelta(0):
            span = timedelta(0)
        self.end.text = (new_start + span).isoformat()

    def _find_free_slots(
        self,
        client: CalendarService,
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        time_zone: str,
    ) -> None:
        """Find free slots off the UI thread and hand them back to the UI."""
        try:
            slots = client.find_free_slots(
                duration_minutes,
                window_start,
                window_end,
                time_zone,
            )
        except ServiceError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_suggest_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_slots_found(slots))

    def _on_suggest_failed(self, message: str) -> None:
        """Re-enable the suggest button and show the backend error."""
        self.suggest_button.disabled = False
        self._set_status(message, error=True)

    def _on_slots_found(self, slots: list[FreeSlot]) -> None:
        """Fill the form with the first free slot, or report that none exist."""
        self.suggest_button.disabled = False
        if not slots:
            self._set_status("No free slot found in the next 7 days.")
            return
        slot = slots[0]
        start_zone = self._resolved_time_zone(self.start_timezone.text)
        end_zone = self._resolved_time_zone(self.end_timezone.text)
        self.start.text = self._wall_clock(slot.start, start_zone)
        self.end.text = self._wall_clock(slot.end, end_zone)
        self._follow_start_in_repeat()
        self._set_status("Suggested a free time.")

    def _on_all_day_changed(self, instance: ToggleSwitch, value: bool) -> None:
        """Switch the form between timed and all-day input."""
        self._apply_all_day_mode(value)
        if value:
            # Convert the current values to whole-day bounds when possible.
            try:
                text = self.start.text.strip()
                if "T" in text:
                    start_day = datetime.fromisoformat(text).date()
                else:
                    start_day = date.fromisoformat(text)
            except ValueError:
                start_day = datetime.now().astimezone().date()
            self.start.text = start_day.isoformat()
            self.end.text = start_day.isoformat()
        else:
            self._fill_default_times()

    def _apply_all_day_mode(self, all_day: bool) -> None:
        """Hide the times for all-day events and show them otherwise."""
        self.start.show_time = not all_day
        self.end.show_time = not all_day
        self.suggest_button.disabled = all_day or self.save_button.disabled

    def confirm_delete(self, *args: Any) -> None:
        """Ask for confirmation before deleting the current event.

        For an occurrence of a series the question is which occurrences go.
        """
        event = self.event
        if event is None:
            return
        scopes = self._offered_scopes()
        if event.recurring_event_id is not None and len(scopes) > 1:
            self.ask_scope(
                "Delete repeating event?",
                f"\u201c{event.summary or 'Untitled event'}\u201d repeats. "
                "Which occurrences should be deleted?",
                scopes,
                self._delete_current_event,
                destructive=True,
            )
            return
        summary = event.summary or "Untitled event"
        popup = ModalView(
            size_hint=(None, None),
            size=(dp(320), dp(200)),
            auto_dismiss=False,
            background="",
            background_color=CLEAR,
            overlay_color=OVERLAY,
        )
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=20)
        Paint(content, SURFACE, radius=20)
        content.add_widget(
            wrapped_label(
                text="Delete event?",
                font_name=FONT_SEMIBOLD,
                font_size="17sp",
                size_hint_y=None,
                height=dp(28),
            )
        )
        content.add_widget(
            wrapped_label(
                text=f"\u201c{summary}\u201d will be deleted from your calendar.",
                font_size="14sp",
                color=MUTED,
            )
        )
        buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )
        keep_button = FlatButton(
            text="Keep", fill=BACKGROUND, text_color=INK, border=DIVIDER
        )
        delete_button = FlatButton(text="Delete", fill=CORAL, text_color=INK)
        buttons.add_widget(keep_button)
        buttons.add_widget(delete_button)
        content.add_widget(buttons)
        popup.add_widget(content)

        def keep(*_: Any) -> None:
            popup.dismiss()

        def confirmed(*_: Any) -> None:
            popup.dismiss()
            self._delete_current_event()

        keep_button.bind(on_release=keep)
        delete_button.bind(on_release=confirmed)
        popup.open()

    def _delete_current_event(self, scope: EditScope = EditScope.THIS) -> None:
        """Delete the current event (or ``scope`` of its series) in the background."""
        client = self.client
        event = self.event
        if client is None or event is None:
            return
        self._set_buttons_enabled(False)
        self._set_status("Deleting event…")
        thread = threading.Thread(
            target=self._delete_event,
            args=(client, event.id, event.calendar_id, scope),
            daemon=True,
        )
        thread.start()

    def _delete_event(
        self,
        client: CalendarService,
        event_id: str,
        calendar_id: str = "",
        scope: EditScope = EditScope.THIS,
    ) -> None:
        """Delete the event off the UI thread and hand the result back."""
        try:
            queued = client.delete_event(event_id, calendar_id, scope)
        except ServiceError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_delete_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_deleted(queued))

    def _on_delete_failed(self, message: str) -> None:
        """Re-enable the form and show the backend error."""
        self._set_buttons_enabled(True)
        self._set_status(f"Could not delete event: {message}", error=True)

    def _on_deleted(self, queued: bool = False) -> None:
        """Return to the main screen and refresh the event list."""
        self._return_to_main(self._notice("deleted_notice", queued))

    def _notice(self, name: str, queued: bool) -> str:
        """The note to show on the main screen after a save or delete.

        A service may offer its own (``saved_notice``/``deleted_notice``),
        e.g. the phone calendar; otherwise a queued change gets the queue note.
        """
        text = getattr(self.client, name, "")
        if isinstance(text, str) and text:
            return text
        return QUEUED_NOTICE if queued else ""

    def _return_to_main(self, notice: str = "") -> None:
        """Reset the form and show the refreshed event list.

        ``notice`` is shown on the main screen, e.g. when the backend queued
        the change instead of saving it to Google right away.
        """
        self._set_buttons_enabled(True)
        self._set_status("")
        self.event = None
        self._new_event_id = ""
        self._release_text_inputs()
        manager = self.manager
        if manager is not None:
            manager.current = "main"
            if notice:
                manager.get_screen("main").set_notice(notice)
        # Clearing the fields now would blank the form while it slides away.
        self._when_slide_ends(self._reset_form)
        self.refresh()

    def _build_event(self) -> CalendarEvent | None:
        """Turn the form values into an event, reporting invalid input."""
        existing = self.event
        description = self.description.text.strip()
        start_timezone = self._resolved_time_zone(self.start_timezone.text)
        end_timezone = self._resolved_time_zone(self.end_timezone.text)
        if self.all_day.active:
            try:
                start_day = date.fromisoformat(self.start.text.strip())
                end_day = date.fromisoformat(self.end.text.strip())
            except ValueError:
                self._set_status(
                    "Use dates like 2026-11-09 for all-day events.",
                    error=True,
                )
                return None
            if end_day < start_day:
                self._set_status("End date must be on or after start date.", error=True)
                return None
            for time_zone in (start_timezone, end_timezone):
                if not self._is_known_time_zone(time_zone):
                    self._set_status(f"Unknown time zone: {time_zone}", error=True)
                    return None
            start_zone = ZoneInfo(start_timezone)
            end_zone = ZoneInfo(end_timezone)
            start = datetime(
                start_day.year, start_day.month, start_day.day, tzinfo=start_zone
            )
            # The end date in the form is inclusive; the event end is exclusive.
            end_inclusive = datetime(
                end_day.year, end_day.month, end_day.day, tzinfo=end_zone
            )
            end = end_inclusive + timedelta(days=1)
            all_day = True
        else:
            for time_zone in (start_timezone, end_timezone):
                if not self._is_known_time_zone(time_zone):
                    self._set_status(f"Unknown time zone: {time_zone}", error=True)
                    return None
            try:
                start = localize_wall_clock(self.start.text, start_timezone)
                end = localize_wall_clock(self.end.text, end_timezone)
            except ValueError as error:
                self._set_status(
                    "Use local times: a date such as 2026-11-09 and a time "
                    f"from the list ({error}).",
                    error=True,
                )
                return None
            if end <= start:
                self._set_status("End must be after start.", error=True)
                return None
            all_day = False
        if self.repeat is not None:
            problem = self.repeat.problem(start.date())
            if problem is not None:
                self._set_status(problem, error=True)
                return None
            recurrence = self.repeat.recurrence(start, all_day=all_day)
        else:
            recurrence = existing.recurrence if existing is not None else None
        calendar_id = self._selected_calendar_id()
        if not calendar_id and existing is not None:
            calendar_id = existing.calendar_id
        if existing is not None:
            event_id = existing.id
        else:
            if not self._new_event_id:
                self._new_event_id = uuid4().hex
            event_id = self._new_event_id
        return CalendarEvent(
            id=event_id,
            summary=self.summary.text.strip() or "Untitled event",
            start=start,
            end=end,
            start_timezone=start_timezone,
            end_timezone=end_timezone,
            calendar_id=calendar_id,
            recurring_event_id=(
                existing.recurring_event_id if existing is not None else None
            ),
            all_day=all_day,
            description=description or None,
            recurrence=recurrence,
            extended_properties=(
                dict(existing.extended_properties or {})
                if existing is not None
                else {}
            ),
        )

    def _fill_default_times(self) -> None:
        """Prefill the next full hour as wall-clock time in the default zone."""
        try:
            now = datetime.now(ZoneInfo(self.time_zone))
        except (ValueError, ZoneInfoNotFoundError):
            now = None
        start, end = default_event_times(now)
        self.start.text = self._wall_clock(start, self.time_zone)
        self.end.text = self._wall_clock(end, self.time_zone)

    def _prefill_start(self, start: datetime, all_day: bool) -> None:
        """Prefill a new event that begins at ``start`` and lasts one hour."""
        try:
            # Go through UTC: same-zone astimezone() would keep a gap time as is.
            local = start.astimezone(UTC).astimezone(ZoneInfo(self.time_zone))
        except (ValueError, ZoneInfoNotFoundError):
            local = start
        # Add the hour in UTC: wall-clock arithmetic can land in a DST gap.
        hour = timedelta(hours=1)
        end = (local.astimezone(UTC) + hour).astimezone(local.tzinfo)
        # The form stores wall-clock text; keep end after start on round trip.
        while end.replace(fold=0).replace(tzinfo=None) <= local.replace(
            tzinfo=None
        ):
            end = (end.astimezone(UTC) + hour).astimezone(local.tzinfo)
        self.start.text = self._wall_clock(local, self.time_zone)
        self.end.text = self._wall_clock(end, self.time_zone)
        if all_day:
            # The all-day switch keeps the date of the start text.
            self.all_day.active = True

    @staticmethod
    def _wall_clock(value: datetime, zone: str) -> str:
        """Return ``value`` as wall-clock text in ``zone``."""
        try:
            return to_wall_clock_value(value, zone)
        except (ValueError, ZoneInfoNotFoundError):
            return value.replace(tzinfo=None).isoformat(timespec="minutes")

    def _resolved_time_zone(self, raw: str) -> str:
        """Return the IANA zone for a dropdown label or a zone name."""
        text = raw.strip()
        return self._time_zone_names.get(text) or text or self.time_zone

    @staticmethod
    def _is_known_time_zone(name: str) -> bool:
        """Return whether ``name`` is an IANA time zone."""
        try:
            ZoneInfo(name)
        except (ValueError, ZoneInfoNotFoundError):
            return False
        return True

    def _reset_form(self) -> None:
        """Clear the form and prefill a fresh time window and time zone."""
        self.all_day.active = False
        self.summary.text = ""
        self.description.text = ""
        self._fill_default_times()
        self._refresh_time_zone_choices(self.time_zone, self.time_zone)
        self._apply_all_day_mode(False)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable the form actions."""
        locked = getattr(self, "read_only", False)
        self.save_button.disabled = not enabled or locked
        self.cancel_button.disabled = not enabled
        self.delete_button.disabled = not enabled or self.event is None or locked
        if self.event is None:
            self._delete_slot.clear_widgets()
        elif self.delete_button.parent is None:
            self._delete_slot.add_widget(self.delete_button)
        self.suggest_button.disabled = not enabled or self.all_day.active or locked

    def _set_status(self, text: str, *, error: bool = False) -> None:
        """Show a status or error message below the form."""
        self.status_label.show(text, error=error)

    def cancel(self, *args: Any) -> None:
        """Close the event form."""
        self._release_text_inputs()
        manager = self.manager
        if manager is not None:
            manager.current = "main"
