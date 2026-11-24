"""Kivy-free layout of events on a week grid.

The week view shows seven day columns.  This module decides which events go
into which column, where they start and end (in minutes since midnight) and
how overlapping events share a column side by side.

Times are shown in one zone for the whole grid: ``tz``, or the system's local
zone when ``tz`` is ``None``.  Placement uses wall-clock time in that zone, so
a day always spans 0 to 1440 minutes, even on a daylight-saving change.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo

from kivy_calendar.formatting import all_day_last_day
from kivy_calendar.models import CalendarEvent

DAY_MINUTES = 24 * 60
# Same first weekday as the date picker: Monday.
WEEK_START = 0
# Events shorter than this are drawn this tall, so they stay tappable.
MIN_MINUTES = 15


@dataclass(frozen=True)
class PlacedEvent:
    """A timed event's slice of one day column."""

    event: CalendarEvent
    day: date
    start_minute: int
    end_minute: int
    lane: int = 0
    lanes: int = 1


@dataclass
class WeekLayout:
    """Everything the week grid draws for one week."""

    days: list[date]
    timed: dict[date, list[PlacedEvent]] = field(default_factory=dict)
    all_day: dict[date, list[CalendarEvent]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Return whether the week has no events at all."""
        return not any(self.timed.values()) and not any(self.all_day.values())


def week_days(day: date) -> list[date]:
    """Return the seven days of the week containing ``day``, Monday first."""
    first = day - timedelta(days=(day.weekday() - WEEK_START) % 7)
    return [first + timedelta(days=offset) for offset in range(7)]


def week_title(days: Sequence[date]) -> str:
    """Return the date range of a week, e.g. ``9 – 15 Nov 2026``."""
    first, last = days[0], days[-1]
    if first.year != last.year:
        return f"{first.day} {first:%b %Y} – {last.day} {last:%b %Y}"
    if first.month != last.month:
        return f"{first.day} {first:%b} – {last.day} {last:%b %Y}"
    return f"{first.day} – {last.day} {last:%b %Y}"


def local_time(value: datetime, tz: tzinfo | None = None) -> datetime:
    """Return ``value`` in ``tz``, or in the system's local zone."""
    return value.astimezone(tz)


def at_local(day: date, minute: int, tz: tzinfo | None = None) -> datetime:
    """Return the aware datetime ``minute`` minutes after midnight of ``day``."""
    naive = datetime.combine(day, time()) + timedelta(minutes=minute)
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


def round_down(minute: int, step: int = 30) -> int:
    """Round ``minute`` down to a multiple of ``step``."""
    return minute - minute % step


def _wall_span(event: CalendarEvent, tz: tzinfo | None) -> tuple[datetime, datetime]:
    """Return the event's start and end as naive wall-clock in the grid zone."""
    start = local_time(event.start, tz).replace(tzinfo=None)
    end = local_time(event.end, tz).replace(tzinfo=None)
    return start, max(end, start + timedelta(minutes=MIN_MINUTES))


def _assign_lanes(items: list[PlacedEvent]) -> list[PlacedEvent]:
    """Give overlapping events of one day a lane and a lane count each."""
    result: list[PlacedEvent] = []
    cluster: list[tuple[PlacedEvent, int]] = []
    lane_ends: list[int] = []
    cluster_end = 0

    def close_cluster() -> None:
        lanes = len(lane_ends)
        result.extend(
            PlacedEvent(
                item.event, item.day, item.start_minute, item.end_minute, lane, lanes
            )
            for item, lane in cluster
        )
        cluster.clear()
        lane_ends.clear()

    for item in sorted(items, key=lambda p: (p.start_minute, -p.end_minute)):
        if cluster and item.start_minute >= cluster_end:
            close_cluster()
            cluster_end = 0
        for lane, end in enumerate(lane_ends):
            if end <= item.start_minute:
                lane_ends[lane] = item.end_minute
                break
        else:
            lane = len(lane_ends)
            lane_ends.append(item.end_minute)
        cluster_end = max(cluster_end, item.end_minute)
        cluster.append((item, lane))
    if cluster:
        close_cluster()
    return result


def build_week(
    events: Sequence[CalendarEvent],
    day: date,
    tz: tzinfo | None = None,
) -> WeekLayout:
    """Place ``events`` on the week containing ``day``.

    Timed events are clipped to each day they touch, so one that crosses
    midnight appears in both columns.  All-day events are listed on every day
    they cover.  Events outside the week are left out.
    """
    days = week_days(day)
    layout = WeekLayout(
        days=days,
        timed={d: [] for d in days},
        all_day={d: [] for d in days},
    )
    for event in sorted(events, key=lambda e: (e.start, e.summary)):
        if event.all_day:
            first = event.start.date()
            last = all_day_last_day(event)
            for d in days:
                if first <= d <= last:
                    layout.all_day[d].append(event)
            continue
        start, end = _wall_span(event, tz)
        for d in days:
            day_start = datetime.combine(d, time())
            day_end = day_start + timedelta(days=1)
            if start >= day_end or end <= day_start:
                continue
            begin = int((max(start, day_start) - day_start).total_seconds() // 60)
            finish = int((min(end, day_end) - day_start).total_seconds() // 60)
            layout.timed[d].append(PlacedEvent(event, d, begin, finish))
    for d in days:
        layout.timed[d] = _assign_lanes(layout.timed[d])
    return layout
