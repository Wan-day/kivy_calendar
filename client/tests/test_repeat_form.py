"""Tests for repeating events in the event form.

Only services that set repeat rules (the phone calendar) get the Repeat row
and the "which occurrences?" question; the rules come from shared/.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from test_screens import FakeClient, _make_screens, _run_inline  # noqa: E402

from kivy_calendar.models import CalendarEvent, EditScope  # noqa: E402

PRAGUE = ZoneInfo("Europe/Prague")


def _phone_client() -> FakeClient:
    """A service like the phone calendar: rules and every scope."""
    client = FakeClient()
    client.edits_repeat_rules = True  # type: ignore[attr-defined]
    client.repeat_scopes = (  # type: ignore[attr-defined]
        EditScope.THIS,
        EditScope.FOLLOWING,
        EditScope.ALL,
    )
    return client


def _occurrence(rule: str = "FREQ=WEEKLY;BYDAY=TU") -> CalendarEvent:
    """The 8 Dec occurrence of a Tuesday class."""
    return CalendarEvent(
        id="20_1797325200000",
        summary="Yoga",
        start=datetime(2026, 12, 8, 10, 0, tzinfo=PRAGUE),
        end=datetime(2026, 12, 8, 11, 0, tzinfo=PRAGUE),
        start_timezone="Europe/Prague",
        end_timezone="Europe/Prague",
        calendar_id="primary",
        recurring_event_id="20",
        recurrence=[f"RRULE:{rule}"],
    )


def _new_event_form(client: FakeClient) -> Any:
    _, _, screen = _make_screens(client)
    screen.open_for(None)
    screen.summary.text = "Yoga"
    screen.start.text = "2026-12-01T10:00"
    screen.end.text = "2026-12-01T11:00"
    screen.repeat.set_start(datetime(2026, 12, 1).date())
    return screen


def test_services_without_repeat_rules_get_no_repeat_row() -> None:
    """The desktop backend keeps the form as it was."""
    _, _, screen = _make_screens(FakeClient())

    assert screen.repeat is None


def test_a_new_event_does_not_repeat_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_inline(monkeypatch)
    client = _phone_client()
    screen = _new_event_form(client)

    assert screen.repeat.text == "Does not repeat"
    screen.save_event()

    assert client.created[0].recurrence is None


def test_an_everyday_rule_is_saved_for_a_new_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The presets follow the start date: 1 Dec 2026 is a Tuesday."""
    _run_inline(monkeypatch)
    client = _phone_client()
    screen = _new_event_form(client)

    assert screen.repeat.values == [
        "Does not repeat",
        "Every day",
        "Every week on Tue",
        "Every month on day 1",
        "Every month on the 1st Tuesday",
        "Every year on 1 Dec",
        "Custom…",
    ]
    screen.repeat.text = "Every week on Tue"
    screen.save_event()

    assert client.created[0].recurrence == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]


def test_presets_follow_a_new_start_date() -> None:
    screen = _new_event_form(_phone_client())

    screen.start.select_date(datetime(2026, 12, 31).date())

    assert "Every week on Thu" in screen.repeat.values
    assert "Every month on the last Thursday" in screen.repeat.values


def test_the_custom_dialog_builds_any_modelled_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every 2 weeks on Tue and Thu, 6 times."""
    _run_inline(monkeypatch)
    client = _phone_client()
    screen = _new_event_form(client)

    screen.repeat.text = "Custom…"
    dialog = screen.repeat.dialog
    assert dialog is not None
    assert screen.repeat.text == "Does not repeat"
    dialog.interval.text = "2"
    dialog.toggle_weekday(3)
    dialog.ends.text = "After a number of times"
    dialog.count.text = "6"
    dialog.done()

    assert screen.repeat.dialog is None
    assert screen.repeat.text == "Every 2 weeks on Tue, Thu, 6 times"
    screen.save_event()
    assert client.created[0].recurrence == [
        "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH;COUNT=6"
    ]


def test_the_custom_dialog_shows_the_rows_of_its_unit() -> None:
    screen = _new_event_form(_phone_client())
    screen.repeat.open_dialog()
    dialog = screen.repeat.dialog

    assert dialog.weekday_row.parent is not None
    dialog.unit.text = "months"
    assert dialog.weekday_row.parent is None
    assert dialog.monthly_row.parent is not None
    assert dialog.monthly.values == ["On day 1", "On the 1st Tuesday"]
    dialog.ends.text = "On a date"
    assert dialog.until_row.parent is not None
    assert dialog.count_row.parent is None


def test_the_custom_dialog_reports_bad_values() -> None:
    """A zero interval or an end before the start keeps the dialog open."""
    screen = _new_event_form(_phone_client())
    screen.repeat.open_dialog()
    dialog = screen.repeat.dialog

    dialog.interval.text = "0"
    dialog.done()
    assert screen.repeat.dialog is dialog
    assert "Repeat every 1 to" in dialog.status.text

    dialog.interval.text = "1"
    dialog.ends.text = "On a date"
    dialog.until.text = "2026-11-30"
    dialog.done()
    assert "on or after the start date" in dialog.status.text

    dialog.cancel()
    assert screen.repeat.dialog is None
    assert screen.repeat.text == "Does not repeat"


def test_saving_an_occurrence_asks_which_occurrences_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_inline(monkeypatch)
    client = _phone_client()
    _, _, screen = _make_screens(client)
    screen.open_for(_occurrence())
    screen.summary.text = "Pilates"

    screen.save_event()

    assert client.updated == []
    assert list(screen.scope_buttons) == [
        EditScope.THIS,
        EditScope.FOLLOWING,
        EditScope.ALL,
    ]
    screen.scope_buttons[EditScope.ALL].dispatch("on_release")
    assert client.update_scopes == ["all"]
    assert client.updated[0].summary == "Pilates"
    assert screen.scope_popup is None


def test_an_untouched_rule_is_saved_exactly_as_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WKST and the order of parts survive, so the service sees no change."""
    _run_inline(monkeypatch)
    client = _phone_client()
    _, _, screen = _make_screens(client)
    screen.open_for(_occurrence("FREQ=WEEKLY;WKST=MO;BYDAY=TU"))

    assert screen.repeat.text == "Every week on Tue"
    screen.save_event()
    screen.scope_buttons[EditScope.THIS].dispatch("on_release")

    assert client.updated[0].recurrence == ["RRULE:FREQ=WEEKLY;WKST=MO;BYDAY=TU"]


def test_rules_set_in_other_apps_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule the form cannot show stays unchanged unless another is picked."""
    _run_inline(monkeypatch)
    client = _phone_client()
    _, _, screen = _make_screens(client)
    rule = "FREQ=MONTHLY;BYSETPOS=-1;BYDAY=MO,TU,WE,TH,FR"
    screen.open_for(_occurrence(rule))

    assert screen.repeat.text == "Custom rule (kept as set)"
    screen.save_event()
    screen.scope_buttons[EditScope.ALL].dispatch("on_release")

    assert client.updated[0].recurrence == [f"RRULE:{rule}"]


def test_a_new_rule_or_calendar_cannot_apply_to_one_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only "this and following" and "all events" are offered then."""
    _run_inline(monkeypatch)
    _, _, screen = _make_screens(_phone_client())
    screen.open_for(_occurrence())

    screen.repeat.text = "Every day"
    screen.save_event()
    assert list(screen.scope_buttons) == [EditScope.FOLLOWING, EditScope.ALL]
    screen.scope_popup.dismiss()

    screen.open_for(_occurrence())
    screen.calendar.text = "Work"
    screen.save_event()
    assert list(screen.scope_buttons) == [EditScope.FOLLOWING, EditScope.ALL]


def test_cancelling_the_question_saves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _run_inline(monkeypatch)
    client = _phone_client()
    _, _, screen = _make_screens(client)
    screen.open_for(_occurrence())
    screen.save_event()

    cancel = screen.scope_popup.children[0].children[0]
    cancel.dispatch("on_release")

    assert client.updated == []
    assert screen.scope_popup is None
    assert not screen.save_button.disabled


def test_deleting_an_occurrence_asks_which_occurrences_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_inline(monkeypatch)
    client = _phone_client()
    _, _, screen = _make_screens(client)
    screen.open_for(_occurrence())

    screen.confirm_delete()
    screen.scope_buttons[EditScope.FOLLOWING].dispatch("on_release")

    assert client.deleted == ["20_1797325200000"]
    assert client.delete_scopes == ["following"]


def test_single_events_are_saved_and_deleted_without_a_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_inline(monkeypatch)
    client = _phone_client()
    _, _, screen = _make_screens(client)
    single = replace(_occurrence(), id="21", recurring_event_id=None, recurrence=None)
    screen.open_for(single)

    screen.repeat.text = "Every day"
    screen.save_event()

    assert screen.scope_popup is None
    assert client.update_scopes == ["this"]
    assert client.updated[0].recurrence == ["RRULE:FREQ=DAILY"]


def test_the_number_fields_center_their_text() -> None:
    """Equal padding above and below one line keeps the digits mid-box."""
    from kivy.metrics import dp

    screen = _new_event_form(_phone_client())
    screen.repeat.open_dialog()
    dialog = screen.repeat.dialog

    for field in (dialog.interval, dialog.count):
        field.height = dp(44)
        _, top, _, bottom = field.padding
        assert top == bottom
        assert top == pytest.approx((dp(44) - field.line_height) / 2)


def test_the_dialog_moves_above_the_keyboard_while_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a phone the keyboard would cover Cancel and Done otherwise."""
    from kivy.core.window import Window

    from kivy_calendar.screens import repeat_field
    from kivy_calendar.screens.keyboard import ASSUMED_KEYBOARD_SHARE

    monkeypatch.setattr(repeat_field, "platform", "android")
    screen = _new_event_form(_phone_client())
    screen.repeat.open_dialog()
    dialog = screen.repeat.dialog
    dialog.open(animation=False)
    try:
        dialog.count.focus = True
        keyboard = Window.height * ASSUMED_KEYBOARD_SHARE
        assert dialog.y >= keyboard
        dialog.count.focus = False
        assert dialog.center_y == pytest.approx(Window.center[1])
    finally:
        dialog.dismiss(animation=False)


def test_the_repeat_dropdown_uses_the_rows_free_width() -> None:
    """Long rules like "Every week on Mon, Fri, 6 times" fit on a phone."""
    from kivy.metrics import dp

    from kivy_calendar.screens.add_event import REPEAT_CAPTION, SPINNER_WIDTH

    screen = _new_event_form(_phone_client())
    row = screen.repeat.parent.parent.parent

    row.width = dp(380)
    assert screen.repeat.width == pytest.approx(dp(380) - REPEAT_CAPTION)
    row.width = dp(200)
    assert screen.repeat.width == SPINNER_WIDTH
