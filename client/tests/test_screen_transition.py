"""The list/form slide is short and smooth, and the form stays still during it."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")

pytest.importorskip("kivy")

from kivy.clock import Clock  # noqa: E402
from test_form_scroll import FakeTime, fake_time  # noqa: E402, F401
from test_screens import FakeClient, _make_screens  # noqa: E402

from kivy_calendar.app import FormTransition  # noqa: E402
from kivy_calendar.models import TimeZoneOption  # noqa: E402


def _manager(client: FakeClient | None = None):
    manager, main, form = _make_screens(client or FakeClient())
    manager.transition = FormTransition()
    manager.size = (400, 800)
    Clock.tick()
    return manager, main, form


def _finish(fake: FakeTime, manager) -> None:  # type: ignore[no-untyped-def]
    for _ in range(40):
        fake.frame(0.016)
    assert not manager.transition.is_active


def test_transition_is_a_short_slide() -> None:
    """A slide of 0.3 s."""
    transition = FormTransition()
    assert transition.duration == pytest.approx(0.3)
    assert transition.direction in ("left", "right")


def test_opening_slides_left_and_returning_slides_right(
    fake_time: FakeTime,  # noqa: F811
) -> None:
    """The form comes in from the right and leaves to the right."""
    manager, _, _ = _manager()
    manager.current = "add_event"
    assert manager.transition.direction == "left"
    _finish(fake_time, manager)
    manager.current = "main"
    assert manager.transition.direction == "right"
    _finish(fake_time, manager)


def test_the_slide_eases_out(fake_time: FakeTime) -> None:  # noqa: F811
    """Halfway in time the screen is already most of the way in."""
    manager, _, form = _manager()
    manager.current = "add_event"
    manager.transition.on_progress(0.5)
    assert form.x == pytest.approx(manager.width * (1 - 0.875))
    manager.transition.on_progress(1.0)
    assert form.x == pytest.approx(manager.x)
    _finish(fake_time, manager)


def test_saving_keeps_the_form_intact_until_it_has_slid_out(
    fake_time: FakeTime,  # noqa: F811
) -> None:
    """The fields are cleared after the slide, not while the form moves."""
    manager, _, form = _manager()
    manager.current = "add_event"
    _finish(fake_time, manager)
    form.summary.text = "Team standup"
    form._on_saved()
    assert manager.transition.is_active
    assert form.summary.text == "Team standup"
    _finish(fake_time, manager)
    assert form.summary.text == ""


def test_dropdowns_are_not_rebuilt_during_the_slide(
    fake_time: FakeTime,  # noqa: F811
) -> None:
    """Time zones that arrive mid-slide are applied after it ends."""
    manager, main, form = _manager()
    rebuilt: list[str] = []
    form.start_timezone.bind(values=lambda *_: rebuilt.append("zones"))
    main.open_add_event()
    assert manager.transition.is_active
    form._on_time_zones_loaded([TimeZoneOption(name="Asia/Tokyo", label="Tokyo")])
    for _ in range(5):  # the fake client's own answer arrives mid-slide too
        fake_time.frame(0.016)
    assert manager.transition.is_active
    assert rebuilt == []
    assert form._after_slide  # held back until the slide ends
    _finish(fake_time, manager)
    assert not form._after_slide
    assert "Kolkata (UTC+05:30)" in form.start_timezone.values


def test_unchanged_dropdown_values_are_not_reassigned() -> None:
    """Setting equal values again must not rebuild Kivy's option widgets."""
    _, _, form = _make_screens(FakeClient())
    changes: list[int] = []
    form.start_timezone.bind(values=lambda *_: changes.append(1))
    zone = form.time_zone
    form._refresh_time_zone_choices(zone, zone)
    form._refresh_time_zone_choices(zone, zone)
    assert len(changes) <= 1
