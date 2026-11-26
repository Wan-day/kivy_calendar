"""Time the desktop side of "a filled list with about 1,000 events".

Fills the fake Android calendar store with about 1,000 events in the loaded
window (30 days back to 180 days ahead), then times each stage on its own:

* ``provider``: Calendars + Instances rows read and mapped to shared models;
* ``service``: the whole ``PhoneCalendarService.list_events`` call (the
  provider again, the unsynced ids and the client event conversion);
* ``list build``: the main screen building its day-grouped list;
* ``list frame``: the first frame after that (layout and textures);
* ``week`` and ``month``: the grid views rendering the same events.

Run it from the repository root, with a display like the client tests::

    DISPLAY=:0 .venv/bin/python scripts/bench_list.py --runs 5
    DISPLAY=:0 .venv/bin/python scripts/bench_list.py --profile 25

The numbers are desktop numbers; a phone is several times slower.
"""

from __future__ import annotations

import argparse
import cProfile
import os
import pstats
import random
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# This checkout's sources win over any editable install of another checkout.
for source in ("client/src", "shared/src", "android/src", "android/tests"):
    sys.path.insert(0, str(ROOT / source))

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

from fakes import (
    FakeCalendarStore,
    FakePermissions,
    calendar_row,
    instance_row,
    millis,
    utc_midnight,
)
from phone_calendar.provider import AndroidCalendarProvider
from phone_calendar.service import PhoneCalendarService

ZONES = ("Europe/Berlin", "Europe/London", "America/New_York")
TITLES = (
    "Standup",
    "Lunch with Sam",
    "Dentist",
    "Quarterly planning review with the whole platform and design team",
    "Pick up the parcel",
    "Gym",
    "1:1",
    "Birthday dinner at the little Italian place near the station",
)
NOTES = (None, None, "Bring the laptop.", "Agenda:\n- one\n- two\n- three\n" * 6)


def build_store(count: int, seed: int = 7) -> tuple[FakeCalendarStore, datetime]:
    """Return a fake store with about ``count`` instances in the default window."""
    rng = random.Random(seed)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    calendars = [
        calendar_row(1, "me@example.com", primary=1),
        calendar_row(2, "Work"),
        calendar_row(3, "Holidays", access=200),
    ]
    rows = []
    event_id = 1
    # Recurring series: each produces a weekly occurrence across the window.
    for series in range(3):
        first = now - timedelta(days=30) + timedelta(days=series, hours=series)
        for week in range(30):
            begin = first + timedelta(weeks=week)
            rows.append(
                instance_row(
                    event_id,
                    series % 3 + 1,
                    millis(begin),
                    millis(begin + timedelta(hours=1)),
                    f"Weekly {series}",
                    rrule="FREQ=WEEKLY",
                )
            )
        event_id += 1
    for _ in range(count // 7):
        day = (now - timedelta(days=30) + timedelta(days=rng.randrange(210))).date()
        span = rng.choice((1, 1, 1, 2, 3))
        rows.append(
            instance_row(
                event_id,
                rng.randint(1, 3),
                utc_midnight(day),
                utc_midnight(day + timedelta(days=span)),
                rng.choice(TITLES),
                allDay=1,
                eventTimezone="UTC",
                description=rng.choice(NOTES),
            )
        )
        event_id += 1
    while len(rows) < count:
        begin = now - timedelta(days=30) + timedelta(minutes=15 * rng.randrange(20160))
        rows.append(
            instance_row(
                event_id,
                rng.randint(1, 3),
                millis(begin),
                millis(begin + timedelta(minutes=rng.choice((15, 30, 60, 90, 180)))),
                rng.choice(TITLES),
                eventTimezone=rng.choice(ZONES),
                description=rng.choice(NOTES),
            )
        )
        event_id += 1
    store = FakeCalendarStore(calendars=calendars, instances=rows)
    # A few events are waiting for Android's account sync.
    unsynced = {rng.randint(10, event_id) for _ in range(15)}
    store.dirty_event_ids = lambda: set(unsynced)  # type: ignore[method-assign]
    return store, now


def timed[T](work: Callable[[], T]) -> tuple[float, T]:
    """Return the seconds ``work`` took and its result."""
    started = time.perf_counter()
    result = work()
    return time.perf_counter() - started, result


def one_run(count: int, screen: Any) -> dict[str, float]:
    """Run every stage once on ``screen`` and return seconds per stage."""
    from kivy.clock import Clock

    store, now = build_store(count)
    provider = AndroidCalendarProvider(store, time_zone="Europe/Berlin")
    service = PhoneCalendarService(
        provider,
        FakePermissions(),  # type: ignore[arg-type]
        now=lambda: now,
    )
    times: dict[str, float] = {}
    times["provider"], listed = timed(
        lambda: provider.list_events(
            now - timedelta(days=30), now + timedelta(days=180)
        )
    )
    assert listed.value is not None
    times["service (total)"], events = timed(service.list_events)
    assert len(events) > 0
    screen.event_list.clear_widgets()
    screen.events = events
    times["list build"], _ = timed(screen._render_view)
    times["list frame"], _ = timed(Clock.tick)
    # Week and month render their shown week/month from the same events; the
    # first call per screen only builds the widgets, so time the second.
    screen.week_view.set_events(events)
    times["week"], _ = timed(lambda: screen.week_view.set_events(events))
    screen.month_view.set_events(events)
    times["month"], _ = timed(lambda: screen.month_view.set_events(events))
    times["_count"] = float(len(events))
    return times


def main() -> None:
    """Run the benchmark and print the medians."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--profile", type=int, default=0, metavar="N", help="print the top N by cumtime"
    )
    args = parser.parse_args()
    from kivy_calendar.models import CalendarSummary
    from kivy_calendar.screens.main import MainScreen

    # One screen for all runs: every run clears and refills its list, so the
    # memory of old cards is freed instead of piling up.
    screen: Any = MainScreen(name="main", client=None)
    screen._remember_calendars(
        [
            CalendarSummary(id="1", summary="me@example.com", primary=True),
            CalendarSummary(id="2", summary="Work"),
        ]
    )
    one_run(min(args.events, 100), screen)  # warm up fonts and zone caches
    runs = [one_run(args.events, screen) for _ in range(args.runs)]
    print(f"events: {int(runs[0]['_count'])}, runs: {args.runs} (median, min, max)")
    for stage in runs[0]:
        if stage.startswith("_"):
            continue
        values = [run[stage] for run in runs]
        print(
            f"  {stage:<16} {statistics.median(values) * 1000:8.1f} ms"
            f"  {min(values) * 1000:8.1f}  {max(values) * 1000:8.1f}"
        )
    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        one_run(args.events, screen)
        profiler.disable()
        pstats.Stats(profiler).sort_stats("cumulative").print_stats(args.profile)


if __name__ == "__main__":
    main()
