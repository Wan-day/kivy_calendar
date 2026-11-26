"""Repeat rules (RFC 5545 ``RRULE``) the app can show and edit.

:class:`RepeatRule` models the rules the event form offers: every N days,
weeks, months or years; chosen weekdays; a day of the month or the nth
weekday of the month; and an end date or a number of occurrences.  Rules
written by other apps can be richer; :func:`parse_rule` returns ``None`` for
those, and callers keep the original text unchanged.

Rule text here is the ``RRULE`` value without the ``RRULE:`` prefix, as
Android's calendar store keeps it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum

WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAY_LONG_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
MAX_INTERVAL = 999
MAX_COUNT = 999
LAST_WEEK = -1
RULE_PREFIX = "RRULE:"


class Frequency(StrEnum):
    """How often a rule repeats, before its interval."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


UNIT_NAMES = {
    Frequency.DAILY: ("day", "days"),
    Frequency.WEEKLY: ("week", "weeks"),
    Frequency.MONTHLY: ("month", "months"),
    Frequency.YEARLY: ("year", "years"),
}


@dataclass(frozen=True)
class RepeatRule:
    """A repeat rule the event form can show and edit.

    ``weekdays`` (0 = Monday) are the days of a weekly rule; empty means the
    weekday of the event's start.  A monthly rule repeats on ``month_day``,
    or on the ``week_of_month``-th (1-4, or -1 for the last) ``weekdays[0]``,
    or, with neither, on the start's day of the month.  ``until`` is the last
    day an occurrence may start on, in the event's own zone; ``count`` is the
    number of occurrences.  At most one of the two is set.
    """

    frequency: Frequency
    interval: int = 1
    weekdays: tuple[int, ...] = ()
    month_day: int | None = None
    week_of_month: int | None = None
    until: date | None = None
    count: int | None = None


def rule_text(recurrence: list[str] | None) -> str | None:
    """The ``RRULE`` value of an event's recurrence lines, if it has one."""
    for line in recurrence or []:
        if line.upper().startswith(RULE_PREFIX):
            return line[len(RULE_PREFIX) :]
    return None


def parse_rule(text: str, zone: tzinfo = UTC) -> RepeatRule | None:
    """Read ``text`` as a :class:`RepeatRule`; ``None`` when it has more.

    ``zone`` turns a UTC ``UNTIL`` into the event's own date.
    """
    if text.upper().startswith(RULE_PREFIX):
        text = text[len(RULE_PREFIX) :]
    parts: dict[str, str] = {}
    for part in text.strip().split(";"):
        if not part:
            continue
        key, sep, value = part.partition("=")
        key = key.strip().upper()
        if not sep or key in parts:
            return None
        parts[key] = value.strip().upper()
    if parts.pop("WKST", "MO") != "MO":
        return None
    try:
        frequency = Frequency(parts.pop("FREQ", ""))
        interval = int(parts.pop("INTERVAL", "1"))
        count = int(parts.pop("COUNT")) if "COUNT" in parts else None
        until = _parse_until(parts.pop("UNTIL"), zone) if "UNTIL" in parts else None
    except ValueError:
        return None
    if until is not None and count is not None:
        return None
    rule = RepeatRule(frequency, interval=interval, until=until, count=count)
    by_day = parts.pop("BYDAY", None)
    by_month_day = parts.pop("BYMONTHDAY", None)
    if parts:
        return None
    if frequency == Frequency.WEEKLY and by_month_day is None:
        if by_day is not None:
            weekdays = _plain_weekdays(by_day)
            if weekdays is None:
                return None
            rule = replace(rule, weekdays=weekdays)
    elif frequency == Frequency.MONTHLY and (by_day is None or by_month_day is None):
        if by_month_day is not None:
            if not by_month_day.isdigit() or not 1 <= int(by_month_day) <= 31:
                return None
            rule = replace(rule, month_day=int(by_month_day))
        elif by_day is not None:
            nth = _nth_weekday(by_day)
            if nth is None:
                return None
            rule = replace(rule, week_of_month=nth[0], weekdays=(nth[1],))
    elif by_day is not None or by_month_day is not None:
        return None
    return rule if rule_problem(rule) is None else None


def format_rule(rule: RepeatRule, start: datetime, *, all_day: bool) -> str:
    """The ``RRULE`` value for ``rule`` on an event starting at ``start``.

    Weekly rules always name their weekdays.  ``UNTIL`` is a date for all-day
    events and the end of that day in the start's zone (as UTC) otherwise.
    """
    parts = [f"FREQ={rule.frequency.value}"]
    if rule.interval != 1:
        parts.append(f"INTERVAL={rule.interval}")
    if rule.frequency == Frequency.WEEKLY:
        weekdays = sorted(set(rule.weekdays)) or [start.weekday()]
        parts.append("BYDAY=" + ",".join(WEEKDAY_CODES[day] for day in weekdays))
    elif rule.frequency == Frequency.MONTHLY:
        if rule.week_of_month is not None and rule.weekdays:
            code = WEEKDAY_CODES[rule.weekdays[0]]
            parts.append(f"BYDAY={rule.week_of_month}{code}")
        elif rule.month_day is not None:
            parts.append(f"BYMONTHDAY={rule.month_day}")
    if rule.count is not None:
        parts.append(f"COUNT={rule.count}")
    elif rule.until is not None:
        parts.append(f"UNTIL={_until_value(rule.until, start, all_day)}")
    return ";".join(parts)


def rule_problem(rule: RepeatRule) -> str | None:
    """Why ``rule`` cannot be saved, or ``None`` when it is fine."""
    if not 1 <= rule.interval <= MAX_INTERVAL:
        return f"Repeat every 1 to {MAX_INTERVAL} {UNIT_NAMES[rule.frequency][1]}."
    if rule.count is not None and not 1 <= rule.count <= MAX_COUNT:
        return f"End after 1 to {MAX_COUNT} times."
    if rule.until is not None and rule.count is not None:
        return "Choose an end date or a number of times, not both."
    if any(not 0 <= day <= 6 for day in rule.weekdays):
        return "Unknown weekday."
    if rule.month_day is not None and not 1 <= rule.month_day <= 31:
        return "Choose a day of the month from 1 to 31."
    if rule.week_of_month is not None and (
        rule.week_of_month not in (1, 2, 3, 4, LAST_WEEK) or len(rule.weekdays) != 1
    ):
        return "Choose the first to fourth or the last weekday of the month."
    return None


def describe(rule: RepeatRule, start: date) -> str:
    """Words for ``rule`` on an event starting on ``start``.

    E.g. "Every 2 weeks on Mon, Wed, until 31 Dec 2026".
    """
    singular, plural = UNIT_NAMES[rule.frequency]
    if rule.interval == 1:
        every = f"Every {singular}"
    else:
        every = f"Every {rule.interval} {plural}"
    if rule.frequency == Frequency.WEEKLY:
        weekdays = sorted(set(rule.weekdays)) or [start.weekday()]
        if weekdays == [0, 1, 2, 3, 4]:
            text = f"{every} on weekdays"
        else:
            text = f"{every} on " + ", ".join(WEEKDAY_NAMES[day] for day in weekdays)
    elif rule.frequency == Frequency.MONTHLY:
        if rule.week_of_month is not None and rule.weekdays:
            nth = nth_weekday_name(rule.week_of_month, rule.weekdays[0])
            text = f"{every} on the {nth}"
        else:
            text = f"{every} on day {rule.month_day or start.day}"
    elif rule.frequency == Frequency.YEARLY:
        text = f"{every} on {start.day} {MONTH_NAMES[start.month - 1]}"
    else:
        text = every
    if rule.count is not None:
        text += ", once" if rule.count == 1 else f", {rule.count} times"
    elif rule.until is not None:
        text += f", until {format_day(rule.until)}"
    return text


def preset_rules(start: date) -> list[RepeatRule]:
    """The everyday rules offered for an event starting on ``start``.

    Daily, weekly on its weekday, monthly on its day, monthly on its nth
    weekday (and on the last one when it is the last), and yearly.
    """
    week = week_of_month(start)
    presets = [
        RepeatRule(Frequency.DAILY),
        RepeatRule(Frequency.WEEKLY, weekdays=(start.weekday(),)),
        RepeatRule(Frequency.MONTHLY, month_day=start.day),
    ]
    if week != LAST_WEEK:
        presets.append(
            RepeatRule(
                Frequency.MONTHLY, week_of_month=week, weekdays=(start.weekday(),)
            )
        )
    if is_last_weekday_of_month(start):
        presets.append(
            RepeatRule(
                Frequency.MONTHLY,
                week_of_month=LAST_WEEK,
                weekdays=(start.weekday(),),
            )
        )
    presets.append(RepeatRule(Frequency.YEARLY))
    return presets


def week_of_month(day: date) -> int:
    """Which ``day.weekday()`` of its month ``day`` is: 1-4, or -1 for a 5th."""
    week = (day.day - 1) // 7 + 1
    return LAST_WEEK if week == 5 else week


def is_last_weekday_of_month(day: date) -> bool:
    """Whether no later day of the month has the same weekday."""
    return (day + timedelta(days=7)).month != day.month


def nth_weekday_name(week: int, weekday: int) -> str:
    """E.g. "2nd Tuesday" or "last Friday"."""
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(week, "last")
    return f"{ordinal} {WEEKDAY_LONG_NAMES[weekday]}"


def format_day(day: date) -> str:
    """E.g. "31 Dec 2026"."""
    return f"{day.day} {MONTH_NAMES[day.month - 1]} {day.year}"


def rule_ending_before(text: str, occurrence: datetime, *, all_day: bool) -> str:
    """``text`` with its end moved to just before ``occurrence``.

    Any ``COUNT`` or ``UNTIL`` is replaced.  Works on any rule text, also on
    rules :func:`parse_rule` does not model.  ``occurrence`` is the start of
    the first occurrence to leave out (UTC midnight for all-day events).
    """
    parts = [
        part
        for part in text.split(";")
        if part and part.partition("=")[0].strip().upper() not in ("COUNT", "UNTIL")
    ]
    if all_day:
        last = occurrence.astimezone(UTC).date() - timedelta(days=1)
        parts.append(f"UNTIL={last:%Y%m%d}")
    else:
        last_moment = occurrence.astimezone(UTC) - timedelta(seconds=1)
        parts.append(f"UNTIL={last_moment:%Y%m%dT%H%M%SZ}")
    return ";".join(parts)


def _until_value(until: date, start: datetime, all_day: bool) -> str:
    """``UNTIL`` text: a date for all-day events, else the day's end as UTC."""
    if all_day:
        return f"{until:%Y%m%d}"
    end_of_day = datetime.combine(until, time(23, 59, 59), tzinfo=start.tzinfo)
    return f"{end_of_day.astimezone(UTC):%Y%m%dT%H%M%SZ}"


def _parse_until(value: str, zone: tzinfo) -> date:
    """The last start date of an ``UNTIL`` value, in the event's zone."""
    if len(value) == 8:
        return datetime.strptime(value, "%Y%m%d").date()
    if value.endswith("Z"):
        moment = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        return moment.astimezone(zone).date()
    return datetime.strptime(value, "%Y%m%dT%H%M%S").date()


def _plain_weekdays(value: str) -> tuple[int, ...] | None:
    """Weekdays of a ``BYDAY`` list without ordinals, e.g. ``MO,WE``."""
    weekdays: list[int] = []
    for code in value.split(","):
        if code not in WEEKDAY_CODES:
            return None
        weekdays.append(WEEKDAY_CODES.index(code))
    return tuple(sorted(set(weekdays)))


def _nth_weekday(value: str) -> tuple[int, int] | None:
    """``(week, weekday)`` of a single ``BYDAY`` like ``2TU`` or ``-1FR``."""
    code = value[-2:]
    ordinal = value[:-2].lstrip("+")
    if code not in WEEKDAY_CODES or ordinal not in ("1", "2", "3", "4", "-1"):
        return None
    return int(ordinal), WEEKDAY_CODES.index(code)
