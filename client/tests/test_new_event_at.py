"""Tests for opening the event form at a given start time."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from test_screens import BERLIN, FakeClient, _make_screens, _sample_event  # noqa: E402


def test_open_for_prefills_start_and_one_hour_end() -> None:
    """A given start fills the start and an end one hour later."""
    _, _, form = _make_screens(FakeClient())
    form.open_for(None, start=datetime(2026, 11, 9, 14, 30, tzinfo=BERLIN))
    assert form.start.text == "2026-11-09T14:30"
    assert form.end.text == "2026-11-09T15:30"
    assert not form.all_day.active


def test_open_for_shows_start_in_form_time_zone() -> None:
    """A start in another zone is shown in the form's zone."""
    _, _, form = _make_screens(FakeClient())
    utc = datetime(2026, 11, 9, 13, 0, tzinfo=ZoneInfo("UTC"))
    form.open_for(None, start=utc)
    assert form.start.text == "2026-11-09T14:00"


def test_open_for_all_day_uses_start_date() -> None:
    """An all-day start gives a single-day all-day event."""
    _, _, form = _make_screens(FakeClient())
    form.open_for(
        None, start=datetime(2026, 11, 9, 14, 30, tzinfo=BERLIN), all_day=True
    )
    assert form.all_day.active
    assert form.start.text == "2026-11-09"
    assert form.end.text == "2026-11-09"
    event = form._build_event()
    assert event is not None
    assert event.all_day


def test_editing_ignores_start() -> None:
    """The start argument does not affect editing an existing event."""
    _, _, form = _make_screens(FakeClient())
    event = _sample_event()
    form.open_for(event, start=datetime(2030, 1, 1, 8, 0, tzinfo=BERLIN))
    assert form.start.text == "2026-11-09T09:00"
    assert form.end.text == "2026-11-09T10:00"


def test_start_in_spring_forward_gap_stays_valid() -> None:
    """A start in the skipped hour still builds a valid event."""
    _, _, form = _make_screens(FakeClient())
    gap = datetime(2026, 3, 29, 2, 30, tzinfo=BERLIN)
    form.open_for(None, start=gap)
    event = form._build_event()
    assert event is not None
    assert event.end > event.start
    assert form.start.text != form.end.text


def test_open_add_event_at_switches_to_form_with_time() -> None:
    """The main screen opens the form prefilled with the given time."""
    manager, main, form = _make_screens(FakeClient())
    main.open_add_event_at(datetime(2026, 11, 9, 16, 0, tzinfo=BERLIN))
    assert manager.current == "add_event"
    assert form.event is None
    assert form.start.text == "2026-11-09T16:00"
    assert form.end.text == "2026-11-09T17:00"


def test_open_add_event_at_all_day() -> None:
    """The all-day flag reaches the form."""
    manager, main, form = _make_screens(FakeClient())
    main.open_add_event_at(datetime(2026, 11, 9, 0, 0, tzinfo=BERLIN), all_day=True)
    assert manager.current == "add_event"
    assert form.all_day.active
    assert form.start.text == "2026-11-09"
