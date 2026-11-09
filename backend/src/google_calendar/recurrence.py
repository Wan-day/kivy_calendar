"""Expansion of Google Calendar recurrence rules into concrete events.

Google returns recurring events as a single series resource that carries an
``RRULE`` and the time of its first occurrence.  The backend expands such rules
into one concrete timed event per occurrence so the client, the sync cache and
the free-slot search all see repeats as separate events.  All-day events stay
unsupported and are skipped by the provider before expansion runs.
"""

from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from domain.event import Event

RRULE_PREFIX = "RRULE:"
SUPPORTED_FREQUENCIES = frozenset({"DAILY", "WEEKLY", "MONTHLY", "YEARLY"})
_DEFAULT_HORIZON = timedelta(days=365)
_MAX_OCCURRENCES = 1000


@dataclass(frozen=True)
class _RecurrenceRule:
    """The parsed fields of a single ``RRULE`` string."""

    frequency: str
    interval: int
    count: int | None
    until: datetime | None


def expand_event(event: Event) -> list[Event]:
    """Return the concrete events covered by ``event``.

    A timed event without a recurrence maps to itself.  A recurring event maps
    to one concrete event per occurrence, in start order, so each repeat of the
    series is treated as its own event.  Rules with an unsupported frequency or
    unparsable fields fall back to the original event instead of failing the
    whole sync.
    """
    if event.recurrence is None:
        return [event]
    rule = next(
        (
            item
            for item in event.recurrence
            if item.strip().upper().startswith(RRULE_PREFIX)
        ),
        None,
    )
    if rule is None:
        return [event]
    parsed = _parse_rule(rule)
    if parsed is None or parsed.frequency not in SUPPORTED_FREQUENCIES:
        return [event]
    occurrences = _occurrences(event, parsed)
    return occurrences or [event]


def _parse_rule(rule: str) -> _RecurrenceRule | None:
    """Parse the supported ``RRULE`` fields of ``rule``."""
    body = rule.strip()
    if body[: len(RRULE_PREFIX)].upper() == RRULE_PREFIX:
        body = body[len(RRULE_PREFIX) :]
    fields: dict[str, str] = {}
    for part in body.split(";"):
        key, separator, value = part.partition("=")
        if not separator:
            continue
        fields[key.strip().upper()] = value.strip()
    frequency = fields.get("FREQ", "").upper()
    if not frequency:
        return None
    try:
        interval = max(1, int(fields.get("INTERVAL", "1")))
    except ValueError:
        return None
    count: int | None = None
    if fields.get("COUNT"):
        try:
            count = max(1, int(fields["COUNT"]))
        except ValueError:
            return None
    until = _parse_until(fields["UNTIL"]) if fields.get("UNTIL") else None
    if fields.get("UNTIL") and until is None:
        return None
    return _RecurrenceRule(
        frequency=frequency,
        interval=interval,
        count=count,
        until=until,
    )


def _parse_until(value: str) -> datetime | None:
    """Parse an ``UNTIL`` bound into an aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _occurrences(event: Event, rule: _RecurrenceRule) -> list[Event]:
    """Return the concrete occurrences of ``event`` covered by ``rule``."""
    start = event.start
    duration = event.end - start
    occurrences: list[Event] = []
    index = 0
    bounded = rule.count is not None or rule.until is not None
    horizon_end = None if bounded else start + _DEFAULT_HORIZON
    while True:
        occurrence_start = _shift(start, rule.frequency, rule.interval * index)
        if rule.until is not None and occurrence_start > rule.until:
            break
        if horizon_end is not None and occurrence_start > horizon_end:
            break
        if rule.count is not None and index >= rule.count:
            break
        occurrences.append(_occurrence(event, occurrence_start, duration))
        if rule.count is not None and index + 1 >= rule.count:
            break
        index += 1
        if len(occurrences) >= _MAX_OCCURRENCES:
            break
    return occurrences


def _occurrence(event: Event, start: datetime, duration: timedelta) -> Event:
    """Return one concrete copy of ``event`` starting at ``start``."""
    return Event(
        id=f"{event.id}:{start.astimezone(UTC).isoformat()}",
        calendar_id=event.calendar_id,
        summary=event.summary,
        description=event.description,
        start=start,
        end=start + duration,
        start_timezone=event.start_timezone,
        end_timezone=event.end_timezone,
        recurrence=None,
        extended_properties=event.extended_properties,
    )


def _shift(start: datetime, frequency: str, multiplier: int) -> datetime:
    """Return the occurrence ``multiplier`` periods after ``start``."""
    if frequency == "DAILY":
        return start + timedelta(days=multiplier)
    if frequency == "WEEKLY":
        return start + timedelta(weeks=multiplier)
    if frequency == "MONTHLY":
        return _add_months(start, multiplier)
    if frequency == "YEARLY":
        return _add_months(start, multiplier * 12)
    raise ValueError(f"unsupported recurrence frequency {frequency!r}")


def _add_months(moment: datetime, months: int) -> datetime:
    """Add calendar months, clamping the day like date arithmetic does."""
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, _calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)
