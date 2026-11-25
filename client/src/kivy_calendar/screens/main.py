"""Main screen listing the calendar events."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from kivy.clock import Clock
from kivy.graphics import BoxShadow, Color
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.widget import Widget

from kivy_calendar import __version__
from kivy_calendar.filtering import (
    DEFAULT_SORT,
    DEFAULT_SORT_LABEL,
    SORT_BY_LABEL,
    SORT_LABELS,
    SORT_NAME,
    SortOrder,
    event_date,
    filter_events,
    parse_date_input,
    sort_events,
)
from kivy_calendar.formatting import (
    all_day_last_day,
    day_heading,
    event_clock,
    is_happening,
    short_date,
)
from kivy_calendar.models import (
    CalendarEvent,
    CalendarSummary,
    ServiceError,
)
from kivy_calendar.screens.date_picker import DatePicker
from kivy_calendar.screens.month import MonthView
from kivy_calendar.screens.scroll_effect import SteadyScrollEffect
from kivy_calendar.screens.theme import (
    BORDER,
    CALENDAR_DOTS,
    CLEAR,
    CORAL_DEEP_TEXT,
    CORAL_TINT,
    DEEP_SKY,
    DIVIDER,
    FONT,
    FONT_BOLD,
    FONT_SEMIBOLD,
    INK,
    MUTED,
    NOW_TINT,
    SKY,
    SKY_SOFT,
    SKY_TINT,
    SURFACE,
    FlatButton,
    FlatSpinner,
    IconView,
    Paint,
    fit_width,
    icon_button,
    primary_button,
)
from kivy_calendar.screens.ui import StatusBanner, input_box, plain_input
from kivy_calendar.screens.week import WeekView
from kivy_calendar.service import CalendarService

CARD_HEIGHT = dp(68)
SORT_CHIP_WIDTH = dp(170)
FILTER_PANEL_HEIGHT = dp(34)
ADD_BUTTON_SIZE = (dp(164), dp(56))
ADD_BUTTON_MARGIN = dp(24)
SHADOW_COLOUR = (*DEEP_SKY[:3], 0.25)
# Grid views end above the floating New event button, plus a small gap.
GRID_BOTTOM_ROOM = ADD_BUTTON_SIZE[1] + ADD_BUTTON_MARGIN + dp(8)
# Header sizes, the same in every view so switching views never moves them.
HEADER_HEIGHT = dp(48)
SWITCHER_HEIGHT = dp(36)
SEARCH_HEIGHT = dp(38)
CONTENT_TOP = dp(10)
CONTENT_SPACING = dp(6)
# The views the switcher offers, in order; a view is enabled by register_view.
VIEW_LABELS = {"list": "List", "week": "Week", "month": "Month"}


def _text(text: str, **kwargs: Any) -> Label:
    """Return a one-line label that is as wide as its text."""
    kwargs.setdefault("font_name", FONT)
    kwargs.setdefault("color", INK)
    label = Label(text=text, size_hint=(None, None), **kwargs)
    label.bind(texture_size=label.setter("size"))
    label.texture_update()
    label.size = label.texture_size
    return label


def _dot(color: Any) -> Widget:
    """Return a small round color marker."""
    dot = Widget(size_hint=(None, None), size=(dp(8), dp(8)))
    Paint(dot, color, radius=4)
    return dot


class EventRow(ButtonBehavior, BoxLayout):
    """A tappable event card: times on the left, name and calendar right."""

    def __init__(
        self,
        event: CalendarEvent,
        open_event: Callable[[CalendarEvent], None],
        *,
        calendar_name: str = "",
        dot_color: Any = CALENDAR_DOTS[0],
        show_date: bool = False,
        now: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the card from an event."""
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=CARD_HEIGHT,
            padding=(dp(14), dp(12)),
            spacing=dp(14),
            **kwargs,
        )
        self.event = event
        happening = is_happening(event, now)
        self.paint = Paint(
            self,
            NOW_TINT if happening else SURFACE,
            radius=14,
            border=None if happening else DIVIDER,
        )
        self.bind(on_release=lambda *_: open_event(event))

        times = BoxLayout(
            orientation="vertical", size_hint_x=None, width=dp(50), spacing=dp(2)
        )
        if event.all_day:
            tag = _text(
                "All day",
                font_name=FONT_SEMIBOLD,
                font_size="11sp",
                color=CORAL_DEEP_TEXT,
                padding=(dp(6), dp(3)),
            )
            Paint(tag, CORAL_TINT, radius=6)
            times.add_widget(tag)
            times.add_widget(Widget())
        else:
            start, end = event_clock(event)
            times.add_widget(_text(start, font_name=FONT_SEMIBOLD, font_size="15sp"))
            times.add_widget(_text(end, font_size="12sp", color=MUTED))
            times.add_widget(Widget())
        self.add_widget(times)

        details = BoxLayout(orientation="vertical", spacing=dp(4))
        summary = Label(
            text=event.summary or "Untitled event",
            font_name=FONT_SEMIBOLD,
            font_size="15sp",
            color=INK,
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
            size_hint_y=None,
            height=dp(20),
        )
        summary.bind(
            width=lambda label, width: setattr(label, "text_size", (width, None))
        )
        details.add_widget(summary)

        meta_parts: list[str] = []
        if calendar_name:
            meta_parts.append(calendar_name)
        day = event_date(event)
        if show_date:
            meta_parts.append(short_date(day))
        if event.all_day and all_day_last_day(event) > event.start.date():
            meta_parts.append(f"until {short_date(all_day_last_day(event))}")
        meta = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(16), spacing=dp(6)
        )
        if calendar_name:
            meta_box = BoxLayout(size_hint=(None, 1), width=dp(8), padding=(0, dp(4)))
            meta_box.add_widget(_dot(dot_color))
            meta.add_widget(meta_box)
        meta.add_widget(_text(" · ".join(meta_parts), font_size="12sp", color=MUTED))
        if event.queued:
            tag = _text(
                "Not synced yet",
                font_name=FONT_SEMIBOLD,
                font_size="11sp",
                color=CORAL_DEEP_TEXT,
                padding=(dp(6), dp(1)),
            )
            Paint(tag, CORAL_TINT, radius=6)
            meta.add_widget(tag)
        meta.add_widget(Widget())
        details.add_widget(meta)
        details.add_widget(Widget())
        self.add_widget(details)

        if happening:
            now_box = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(40))
            pill = _text(
                "Now",
                font_name=FONT_SEMIBOLD,
                font_size="11sp",
                color=SURFACE,
                padding=(dp(8), dp(3)),
            )
            Paint(pill, DEEP_SKY, radius=None)
            now_box.add_widget(pill)
            now_box.add_widget(Widget())
            self.add_widget(now_box)


class DateFilterChip(FlatButton):
    """A filter pill that opens the month picker; ``value`` is ISO or blank."""

    value = StringProperty("")

    def __init__(self, prefix: str, **kwargs: Any) -> None:
        """Create the chip, e.g. ``From 24 Nov`` or ``From date``."""
        super().__init__(
            text="",
            fill=SURFACE,
            border=BORDER,
            text_color=MUTED,
            radius=None,
            font_name=FONT,
            font_size="13sp",
            size_hint=(None, None),
            height=dp(34),
            **kwargs,
        )
        fit_width(self, 28)
        self.prefix = prefix
        self.picker: DatePicker | None = None
        self.bind(value=self._show_value, on_release=lambda *_: self.open_picker())
        self._show_value()

    def open_picker(self) -> None:
        """Open the month picker with a Clear button."""
        self.picker = DatePicker(
            parse_date_input(self.value), self._on_pick, allow_clear=True
        )
        if self.get_parent_window() is not None:
            self.picker.open()

    def _on_pick(self, day: date | None) -> None:
        """Store the picked day, or clear the filter."""
        self.picker = None
        self.value = day.isoformat() if day is not None else ""

    def _show_value(self, *_: Any) -> None:
        """Show the date and highlight the chip while a date is set."""
        day = parse_date_input(self.value)
        if day is not None:
            self.text = f"{self.prefix} {day.day} {day:%b}"
            self.set_colors(fill=SKY_SOFT, border=None, text=INK)
        else:
            self.text = f"{self.prefix} date" if not self.value else self.value
            self.set_colors(fill=SURFACE, border=BORDER, text=MUTED)


class MainScreen(Screen):
    """List calendar events and open the add-event screen."""

    def __init__(
        self,
        client: CalendarService | None,
        configuration_error: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the screen with a scrollable event list and an add button."""
        super().__init__(**kwargs)
        self.client = client
        self.configuration_error = configuration_error
        self.events: list[CalendarEvent] = []
        self._notice = ""
        # Calendar names and dot colors for the cards; loaded once, and the
        # list still works without them.
        self._calendar_names: dict[str, str] = {}
        self._calendar_dots: dict[str, Any] = {}
        self._calendars_loaded = False

        today = datetime.now()
        self.date_label = _text(
            f"{today:%A}, {today.day} {today:%B}", font_size="13sp", color=MUTED
        )
        self.title = _text("Calendar", font_name=FONT_BOLD, font_size="28sp")
        self.version_label = _text(f"v{__version__}", font_size="12sp", color=MUTED)
        # Sit the version on the title's baseline, to its right.
        version_box = BoxLayout(
            orientation="vertical", size_hint_x=None, padding=(0, 0, 0, dp(5))
        )
        version_box.add_widget(Widget())
        version_box.add_widget(self.version_label)
        self.version_label.bind(
            width=lambda _, width: setattr(version_box, "width", width)
        )
        version_box.width = self.version_label.width
        title_row = BoxLayout(orientation="horizontal", spacing=dp(8))
        title_row.add_widget(self.title)
        title_row.add_widget(version_box)
        title_row.add_widget(Widget())
        title_box = BoxLayout(orientation="vertical", spacing=dp(2))
        title_box.add_widget(self.date_label)
        title_box.add_widget(title_row)
        self.sync_button = icon_button("sync")
        self.sync_button.bind(on_press=lambda *_: self.sync_events())
        self.refresh_button = icon_button("refresh")
        self.refresh_button.bind(on_press=lambda *_: self.load_events())
        self.header = header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=HEADER_HEIGHT,
            spacing=dp(8),
        )
        header.add_widget(title_box)
        header.add_widget(self.sync_button)
        header.add_widget(self.refresh_button)

        self.status_label = StatusBanner(collapse=True)

        self.name_filter = plain_input("Filter by name", padding=(0, dp(9)))
        self.clear_filters_button = icon_button("close", radius=12, text_color=MUTED)
        self.search_row = search_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=SEARCH_HEIGHT,
            spacing=dp(8),
        )
        search_icon = BoxLayout(size_hint_x=None, width=dp(18), padding=(0, dp(10)))
        search_icon.add_widget(IconView("search"))
        search_row.add_widget(
            input_box(search_icon, self.name_filter, height=SEARCH_HEIGHT)
        )
        search_row.add_widget(self.clear_filters_button)

        self.date_from_filter = DateFilterChip("From")
        self.date_to_filter = DateFilterChip("To")
        self.sort_spinner = FlatSpinner(
            text=DEFAULT_SORT_LABEL,
            values=SORT_LABELS,
            radius=None,
            font_size="13sp",
            size_hint=(None, None),
            size=(SORT_CHIP_WIDTH, dp(34)),
        )
        self.sort_spinner.color = MUTED
        self.filter_panel = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=FILTER_PANEL_HEIGHT,
            spacing=dp(8),
        )
        self.filter_panel.add_widget(self.date_from_filter)
        self.filter_panel.add_widget(self.date_to_filter)
        self.filter_panel.add_widget(self.sort_spinner)
        self.filter_panel.add_widget(Widget())

        self.name_filter.bind(text=self._schedule_apply_filters)
        self.date_from_filter.bind(value=self._schedule_apply_filters)
        self.date_to_filter.bind(value=self._schedule_apply_filters)
        self.sort_spinner.bind(text=self._on_sort_changed)
        self.clear_filters_button.bind(on_press=lambda *_: self._clear_filters())
        self._sort_order: SortOrder = DEFAULT_SORT
        self._filter_debounce: Any = None

        self.event_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(8),
            # Room below the last card so the New event button never covers it.
            padding=(0, 0, 0, dp(96)),
        )
        self.event_list.bind(minimum_height=self.event_list.setter("height"))
        scroll_view = ScrollView(
            bar_width=dp(4),
            bar_color=(*DEEP_SKY[:3], 0.4),
            effect_cls=SteadyScrollEffect,
        )
        scroll_view.add_widget(self.event_list)

        self.content = content = BoxLayout(
            orientation="vertical",
            padding=(dp(20), CONTENT_TOP, dp(20), 0),
            spacing=CONTENT_SPACING,
        )
        # Views other than the list: name -> widget with ``set_events``.  The
        # list keeps its own rendering; every other view gets the events that
        # pass the name filter (see ``_rebuild_calendar_view``).
        self.views: dict[str, Widget] = {"list": scroll_view}
        self.current_view = "list"
        self._views_with_list_filters = {"list"}
        self.view_buttons: dict[str, FlatButton] = {}
        self.view_switcher = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=SWITCHER_HEIGHT,
            padding=dp(3),
            spacing=dp(2),
        )
        Paint(self.view_switcher, SKY_TINT, radius=None)
        for name, label in VIEW_LABELS.items():
            button = FlatButton(
                text=label,
                fill=SKY if name == self.current_view else CLEAR,
                text_color=INK if name == self.current_view else MUTED,
                radius=None,
                font_size="14sp",
                disabled=name != self.current_view,
            )
            button.bind(on_release=lambda _, view=name: self.show_view(view))
            self.view_buttons[name] = button
            self.view_switcher.add_widget(button)
        self.view_body = BoxLayout(orientation="vertical")
        self.view_body.add_widget(scroll_view)
        self.week_view = WeekView(
            self.open_event, self.open_add_event_at, colour_for=self._colour_for
        )
        self.register_view("week", self.week_view)
        self.month_view = MonthView(
            self.open_event,
            self.open_add_event_at,
            self.show_week_of,
            colour_for=self._colour_for,
        )
        self.register_view("month", self.month_view)

        content.add_widget(header)
        content.add_widget(self.view_switcher)
        content.add_widget(self.status_label)
        content.add_widget(search_row)
        content.add_widget(self.filter_panel)
        content.add_widget(self.view_body)

        self.add_button = primary_button(
            "New event",
            icon="plus",
            font_size="16sp",
            size_hint=(None, None),
            size=ADD_BUTTON_SIZE,
        )
        # BoxShadow has no colour of its own: it is drawn in whichever colour
        # was set last.  Behind the button that was the week grid's coral
        # time line, so set the shadow colour right before it.
        with self.add_button.canvas.before:
            self.shadow_colour = Color(*SHADOW_COLOUR)
            shadow = BoxShadow(
                blur_radius=dp(18),
                offset=(0, dp(-4)),
                border_radius=(dp(28), dp(28), dp(28), dp(28)),
            )
        # Draw the shadow beneath the button's fill.
        before = self.add_button.canvas.before
        before.remove(self.shadow_colour)
        before.remove(shadow)
        before.insert(0, shadow)
        before.insert(0, self.shadow_colour)

        def follow_button(*_: Any) -> None:
            shadow.pos = self.add_button.pos
            shadow.size = self.add_button.size

        self.add_button.bind(pos=follow_button, size=follow_button)
        self.add_button.bind(on_press=self.open_add_event)

        root = FloatLayout()
        root.add_widget(content)
        root.add_widget(self.add_button)

        def place_button(*_: Any) -> None:
            right = root.x + root.width
            self.add_button.pos = (
                right - self.add_button.width - dp(20),
                root.y + ADD_BUTTON_MARGIN,
            )

        root.bind(pos=place_button, size=place_button)
        self.add_widget(root)

        if self.client is None:
            self.add_button.disabled = True
            self._set_status(
                self.configuration_error or "Backend client is not configured.",
                error=True,
            )
        else:
            self._set_status("Events have not been loaded yet.")

    def register_view(
        self, name: str, widget: Widget, *, list_filters: bool = False
    ) -> None:
        """Make the view ``name`` (a key of ``VIEW_LABELS``) selectable.

        ``widget`` needs ``set_events(events)``.  The From/To chips and the
        sort spinner only show with the view when ``list_filters`` is true.
        """
        self.views[name] = widget
        if list_filters:
            self._views_with_list_filters.add(name)
        self.view_buttons[name].disabled = False

    def show_view(self, name: str) -> None:
        """Switch to the registered view ``name``; unknown names are ignored."""
        if name not in self.views:
            return
        self.current_view = name
        self.view_body.clear_widgets()
        self.view_body.add_widget(self.views[name])
        for view, button in self.view_buttons.items():
            chosen = view == name
            button.set_colors(
                fill=SKY if chosen else CLEAR, text=INK if chosen else MUTED
            )
        self._show_filter_panel(name in self._views_with_list_filters)
        self._reserve_button_room(name != "list")
        self._rebuild_view()

    def _reserve_button_room(self, grid: bool) -> None:
        """End grid views above the floating New event button.

        The list scrolls under the button (its own bottom padding); a grid
        fills the body, so the body itself stops above the button.  Only the
        bottom edge changes, never the header.
        """
        self.content.padding = (
            dp(20),
            CONTENT_TOP,
            dp(20),
            GRID_BOTTOM_ROOM if grid else 0,
        )

    def show_week_of(self, day: date) -> None:
        """Switch to the week view on the week containing ``day``."""
        self.week_view.show_week(day)
        self.show_view("week")

    def _show_filter_panel(self, visible: bool) -> None:
        """Show or hide the From/To chips and the sort spinner."""
        shown = self.filter_panel.parent is not None
        if visible and not shown:
            # Just above the view body, which is the last child added.
            self.view_body.parent.add_widget(self.filter_panel, index=1)
        elif shown and not visible:
            self.view_body.parent.remove_widget(self.filter_panel)

    def _colour_for(self, calendar_id: str) -> Any:
        """Return the colour of a calendar for the grid views."""
        return self._calendar_dots.get(calendar_id, CALENDAR_DOTS[0])

    @property
    def rows(self) -> list[EventRow]:
        """Return the event cards from top to bottom."""
        return [
            child
            for child in reversed(self.event_list.children)
            if isinstance(child, EventRow)
        ]

    def load_events(self) -> None:
        """Fetch events from the backend in a background thread."""
        client = self.client
        if client is None:
            self._set_status(
                self.configuration_error or "Backend client is not configured.",
                error=True,
            )
            return
        self._set_status("Loading events…")
        thread = threading.Thread(
            target=self._fetch_events,
            args=(client,),
            daemon=True,
        )
        thread.start()

    def _fetch_events(self, client: CalendarService) -> None:
        """Fetch events off the UI thread and hand them back to the UI."""
        try:
            events = client.list_events()
        except ServiceError as error:
            message = error.message
            Clock.schedule_once(
                lambda *_: self._set_status(
                    f"Could not load events: {message}",
                    error=True,
                )
            )
            return
        calendars: list[CalendarSummary] | None = None
        if not self._calendars_loaded:
            try:
                calendars = client.list_calendars()
            except ServiceError:
                # Names are a nicety; the cards simply leave them out.
                calendars = None
        Clock.schedule_once(lambda *_: self._show_events(events, calendars))

    def sync_events(self) -> None:
        """Rebuild the backend cache in a background thread."""
        client = self.client
        if client is None:
            self._set_status(
                self.configuration_error or "Backend client is not configured.",
                error=True,
            )
            return
        self.sync_button.disabled = True
        self._set_status("Syncing…")
        thread = threading.Thread(
            target=self._run_sync,
            args=(client,),
            daemon=True,
        )
        thread.start()

    def _run_sync(self, client: CalendarService) -> None:
        """Run the sync off the UI thread and hand the count back to the UI."""
        try:
            synced = client.sync()
        except ServiceError as error:
            message = error.message
            Clock.schedule_once(lambda *_: self._on_sync_failed(message))
            return
        Clock.schedule_once(lambda *_: self._on_synced(synced))

    def _on_sync_failed(self, message: str) -> None:
        """Re-enable the sync button and show the backend error."""
        self.sync_button.disabled = False
        self._set_status(f"Could not sync: {message}", error=True)

    def _on_synced(self, synced: int) -> None:
        """Show the synced count and reload the event list."""
        self.sync_button.disabled = False
        self.load_events()
        self._set_status(
            f"Synced {synced} event" + ("" if synced == 1 else "s"),
        )

    def set_notice(self, text: str) -> None:
        """Show a one-time note, e.g. that a change is queued for sync."""
        self._notice = text
        self._set_status(text)

    def _show_events(
        self,
        events: list[CalendarEvent],
        calendars: list[CalendarSummary] | None = None,
    ) -> None:
        """Replace the event list and re-apply the current filters."""
        self.events = events
        if calendars is not None:
            self._remember_calendars(calendars)
        self._rebuild_view()

    def _remember_calendars(self, calendars: list[CalendarSummary]) -> None:
        """Keep calendar names and give each calendar a dot color."""
        ordered = sorted(calendars, key=lambda calendar: not calendar.primary)
        for index, calendar in enumerate(ordered):
            dot = CALENDAR_DOTS[index % len(CALENDAR_DOTS)]
            self._calendar_names[calendar.id] = calendar.summary
            self._calendar_dots[calendar.id] = dot
            if calendar.primary:
                self._calendar_names["primary"] = calendar.summary
                self._calendar_dots["primary"] = dot
        self._calendars_loaded = True

    def _rebuild_view(self) -> None:
        """Filter, sort and render the events matching the current inputs."""
        if self.current_view != "list":
            self._rebuild_calendar_view()
            return
        date_from: date | None = None
        date_to: date | None = None
        date_from_text = self.date_from_filter.value.strip()
        date_to_text = self.date_to_filter.value.strip()
        if date_from_text or date_to_text:
            date_from = parse_date_input(date_from_text)
            date_to = parse_date_input(date_to_text)
            if (date_from_text and date_from is None) or (
                date_to_text and date_to is None
            ):
                self._set_status("Use dates like YYYY-MM-DD.", error=True)
                return
            if date_from is not None and date_to is not None and date_from > date_to:
                self._set_status(
                    "The From date must be on or before the To date.", error=True
                )
                return
        visible = sort_events(
            filter_events(
                self.events,
                name=self.name_filter.text,
                date_from=date_from,
                date_to=date_to,
            ),
            order=self._sort_order,
        )
        filtered = bool(
            self.name_filter.text.strip()
            or date_from_text
            or date_to_text
            or self._sort_order != DEFAULT_SORT,
        )
        self.event_list.clear_widgets()
        if not visible:
            empty_text = (
                "No events match the filters."
                if filtered
                else "No events yet. Tap New event to create one."
            )
            if self._notice:
                empty_text = self._notice
                self._notice = ""
            self._set_status(empty_text)
            return
        count_text = f"{len(visible)} event" + ("" if len(visible) == 1 else "s")
        plain = not self._notice
        if self._notice:
            count_text = f"{count_text}. {self._notice}"
            self._notice = ""
        # A plain count adds nothing; the banner folds away without a note.
        self._set_status("" if plain else count_text)
        by_name = self._sort_order == SORT_NAME
        today = date.today()
        now = datetime.now().astimezone()
        heading_day: date | None = None
        for event in visible:
            day = event_date(event)
            if not by_name and day != heading_day:
                heading_day = day
                self.event_list.add_widget(self._day_heading(day, today))
            self.event_list.add_widget(
                EventRow(
                    event,
                    self.open_event,
                    calendar_name=self._calendar_names.get(event.calendar_id, ""),
                    dot_color=self._calendar_dots.get(
                        event.calendar_id, CALENDAR_DOTS[0]
                    ),
                    show_date=by_name,
                    now=now,
                )
            )

    def _rebuild_calendar_view(self) -> None:
        """Give the shown grid view the events that pass the name filter."""
        visible = filter_events(self.events, name=self.name_filter.text)
        view: Any = self.views[self.current_view]
        view.set_events(visible)
        if not visible:
            empty_text = (
                "No events match the filters."
                if self.name_filter.text.strip()
                else "No events yet. Tap New event to create one."
            )
            count_text = self._notice or empty_text
        else:
            count_text = f"{len(visible)} event" + ("" if len(visible) == 1 else "s")
            if self._notice:
                count_text = f"{count_text}. {self._notice}"
        self._notice = ""
        # A plain count adds nothing; the banner then folds away.
        plain = visible and count_text == f"{len(visible)} event" + (
            "" if len(visible) == 1 else "s"
        )
        self._set_status("" if plain else count_text)

    @staticmethod
    def _day_heading(day: date, today: date) -> Label:
        """Return the heading shown above a day's events."""
        label = Label(
            text=day_heading(day, today),
            font_name=FONT_SEMIBOLD,
            font_size="13sp",
            color=MUTED,
            halign="left",
            valign="bottom",
            size_hint_y=None,
            height=dp(30),
        )
        label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        return label

    def _schedule_apply_filters(self, *args: Any) -> None:
        """Debounce text-input driven filtering before re-rendering."""
        if self._filter_debounce is not None:
            self._unschedule_filter()
        self._filter_debounce = Clock.schedule_once(self._apply_filters, 0.25)

    def _unschedule_filter(self) -> None:
        """Drop a pending filtered re-render."""
        if self._filter_debounce is not None:
            self._filter_debounce.cancel()
            self._filter_debounce = None

    def _apply_filters(self, *args: Any) -> None:
        """Recompute the filtered and sorted view from the current inputs."""
        self._filter_debounce = None
        self._rebuild_view()

    def _on_sort_changed(self, instance: Spinner, value: str) -> None:
        """Re-render when the user picks a sort order."""
        self._sort_order = SORT_BY_LABEL.get(value, DEFAULT_SORT)
        self._rebuild_view()

    def _clear_filters(self) -> None:
        """Reset every filter input and re-render the full list."""
        self.name_filter.text = ""
        self.date_from_filter.value = ""
        self.date_to_filter.value = ""
        self.sort_spinner.text = DEFAULT_SORT_LABEL
        self._sort_order = DEFAULT_SORT
        self._rebuild_view()

    def _set_status(self, text: str, *, error: bool = False) -> None:
        """Show a status or error message above the event list."""
        self.status_label.show(text, error=error)

    def open_event(self, event: CalendarEvent) -> None:
        """Open the event form for an existing event."""
        manager = self.manager
        if manager is None:
            return
        form = manager.get_screen("add_event")
        form.open_for(event)
        manager.current = "add_event"

    def open_add_event(self, *args: Any) -> None:
        """Open the event form for a new event."""
        manager = self.manager
        if manager is None:
            return
        form = manager.get_screen("add_event")
        form.open_for(None)
        manager.current = "add_event"

    def open_add_event_at(self, start: datetime, all_day: bool = False) -> None:
        """Open the event form for a new event starting at ``start``."""
        manager = self.manager
        if manager is None:
            return
        form = manager.get_screen("add_event")
        form.open_for(None, start=start, all_day=all_day)
        manager.current = "add_event"
