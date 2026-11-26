"""Tests for the repeat rules the event form can show and edit."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from domain.recurrence import (
    LAST_WEEK,
    Frequency,
    RepeatRule,
    describe,
    format_rule,
    parse_rule,
    preset_rules,
    rule_ending_before,
    rule_problem,
    rule_text,
)

PRAGUE = ZoneInfo("Europe/Prague")
# A Tuesday, the 1st of the month.
START = datetime(2026, 12, 1, 10, 0, tzinfo=PRAGUE)


def test_rule_text_finds_the_rrule_line() -> None:
    """Recurrence lines can also hold EXDATE lines; only RRULE is the rule."""
    lines = ["EXDATE:20261208T090000Z", "RRULE:FREQ=WEEKLY;BYDAY=TU"]
    assert rule_text(lines) == "FREQ=WEEKLY;BYDAY=TU"
    assert rule_text(None) is None
    assert rule_text(["EXDATE:20261208"]) is None


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("FREQ=DAILY", RepeatRule(Frequency.DAILY)),
        ("RRULE:FREQ=DAILY;INTERVAL=3", RepeatRule(Frequency.DAILY, interval=3)),
        (
            "FREQ=WEEKLY;BYDAY=WE,MO;WKST=MO",
            RepeatRule(Frequency.WEEKLY, weekdays=(0, 2)),
        ),
        ("FREQ=WEEKLY", RepeatRule(Frequency.WEEKLY)),
        (
            "FREQ=MONTHLY;BYMONTHDAY=15",
            RepeatRule(Frequency.MONTHLY, month_day=15),
        ),
        (
            "FREQ=MONTHLY;BYDAY=2TU",
            RepeatRule(Frequency.MONTHLY, week_of_month=2, weekdays=(1,)),
        ),
        (
            "FREQ=MONTHLY;BYDAY=-1FR",
            RepeatRule(Frequency.MONTHLY, week_of_month=LAST_WEEK, weekdays=(4,)),
        ),
        ("FREQ=YEARLY;COUNT=5", RepeatRule(Frequency.YEARLY, count=5)),
        (
            "FREQ=DAILY;UNTIL=20261231",
            RepeatRule(Frequency.DAILY, until=date(2026, 12, 31)),
        ),
    ],
)
def test_parses_the_rules_the_form_offers(text: str, rule: RepeatRule) -> None:
    """Each modelled rule reads back into its parts."""
    assert parse_rule(text) == rule


def test_a_utc_until_is_read_in_the_events_zone() -> None:
    """23:30 UTC on 31 Dec is already 1 Jan in Prague."""
    rule = parse_rule("FREQ=DAILY;UNTIL=20261231T233000Z", PRAGUE)
    assert rule is not None and rule.until == date(2027, 1, 1)


@pytest.mark.parametrize(
    "text",
    [
        "FREQ=HOURLY",
        "FREQ=MONTHLY;BYSETPOS=-1;BYDAY=MO,TU,WE,TH,FR",
        "FREQ=YEARLY;BYMONTH=11;BYMONTHDAY=26",
        "FREQ=WEEKLY;BYDAY=1MO",
        "FREQ=MONTHLY;BYDAY=MO,TU",
        "FREQ=DAILY;COUNT=3;UNTIL=20261231",
        "FREQ=WEEKLY;WKST=SU;INTERVAL=2",
        "FREQ=DAILY;INTERVAL=0",
        "FREQ=DAILY;FREQ=WEEKLY",
        "not a rule",
    ],
)
def test_richer_rules_are_left_to_the_caller(text: str) -> None:
    """Rules outside the model return None, so they are kept unchanged."""
    assert parse_rule(text) is None


def test_format_names_the_weekdays_of_weekly_rules() -> None:
    """A weekly rule without weekdays repeats on the start's weekday."""
    assert format_rule(RepeatRule(Frequency.WEEKLY), START, all_day=False) == (
        "FREQ=WEEKLY;BYDAY=TU"
    )
    rule = RepeatRule(Frequency.WEEKLY, interval=2, weekdays=(4, 0))
    assert format_rule(rule, START, all_day=False) == (
        "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR"
    )


def test_format_writes_monthly_and_count_rules() -> None:
    """The nth weekday, the day of the month and COUNT are written out."""
    nth = RepeatRule(Frequency.MONTHLY, week_of_month=LAST_WEEK, weekdays=(4,))
    day = RepeatRule(Frequency.MONTHLY, month_day=15, count=6)
    assert format_rule(nth, START, all_day=False) == "FREQ=MONTHLY;BYDAY=-1FR"
    assert format_rule(day, START, all_day=False) == (
        "FREQ=MONTHLY;BYMONTHDAY=15;COUNT=6"
    )


def test_until_is_a_date_for_all_day_events_and_the_days_end_otherwise() -> None:
    """Timed events end at 23:59:59 on the last day in their zone, as UTC."""
    rule = RepeatRule(Frequency.DAILY, until=date(2026, 12, 31))
    assert format_rule(rule, START, all_day=True) == "FREQ=DAILY;UNTIL=20261231"
    assert format_rule(rule, START, all_day=False) == (
        "FREQ=DAILY;UNTIL=20261231T225959Z"
    )


def test_format_and_parse_round_trip() -> None:
    """What the form saves reads back as the same rule."""
    rule = RepeatRule(
        Frequency.WEEKLY, interval=3, weekdays=(1, 3), until=date(2027, 3, 1)
    )
    assert parse_rule(format_rule(rule, START, all_day=False), PRAGUE) == rule


@pytest.mark.parametrize(
    ("rule", "words"),
    [
        (RepeatRule(Frequency.DAILY), "Every day"),
        (RepeatRule(Frequency.DAILY, interval=2), "Every 2 days"),
        (RepeatRule(Frequency.WEEKLY), "Every week on Tue"),
        (
            RepeatRule(Frequency.WEEKLY, weekdays=(0, 1, 2, 3, 4)),
            "Every week on weekdays",
        ),
        (
            RepeatRule(Frequency.WEEKLY, interval=2, weekdays=(0, 2)),
            "Every 2 weeks on Mon, Wed",
        ),
        (RepeatRule(Frequency.MONTHLY), "Every month on day 1"),
        (
            RepeatRule(Frequency.MONTHLY, week_of_month=2, weekdays=(1,)),
            "Every month on the 2nd Tuesday",
        ),
        (
            RepeatRule(Frequency.MONTHLY, week_of_month=LAST_WEEK, weekdays=(4,)),
            "Every month on the last Friday",
        ),
        (RepeatRule(Frequency.YEARLY, count=1), "Every year on 1 Dec, once"),
        (RepeatRule(Frequency.DAILY, count=10), "Every day, 10 times"),
        (
            RepeatRule(Frequency.DAILY, until=date(2026, 12, 31)),
            "Every day, until 31 Dec 2026",
        ),
    ],
)
def test_describe_puts_rules_into_words(rule: RepeatRule, words: str) -> None:
    """The form shows rules as short English phrases."""
    assert describe(rule, START.date()) == words


def test_presets_follow_the_start_date() -> None:
    """The last Thursday of the month also offers "the last Thursday"."""
    presets = preset_rules(date(2026, 11, 26))
    assert [describe(rule, date(2026, 11, 26)) for rule in presets] == [
        "Every day",
        "Every week on Thu",
        "Every month on day 26",
        "Every month on the 4th Thursday",
        "Every month on the last Thursday",
        "Every year on 26 Nov",
    ]


def test_a_fifth_weekday_is_offered_only_as_the_last() -> None:
    """There is no "5th Tuesday" preset: 29 Dec 2026 is the last Tuesday."""
    presets = preset_rules(date(2026, 12, 29))
    monthly = [rule for rule in presets if rule.week_of_month is not None]
    assert monthly == [
        RepeatRule(Frequency.MONTHLY, week_of_month=LAST_WEEK, weekdays=(1,))
    ]


@pytest.mark.parametrize(
    "rule",
    [
        RepeatRule(Frequency.DAILY, interval=0),
        RepeatRule(Frequency.DAILY, count=0),
        RepeatRule(Frequency.DAILY, count=2, until=date(2026, 12, 31)),
        RepeatRule(Frequency.MONTHLY, month_day=32),
        RepeatRule(Frequency.MONTHLY, week_of_month=5, weekdays=(1,)),
    ],
)
def test_rule_problem_reports_rules_that_cannot_be_saved(rule: RepeatRule) -> None:
    """Out-of-range numbers come back as a message for the form."""
    assert rule_problem(rule) is not None


def test_rule_ending_before_caps_a_timed_rule_one_second_early() -> None:
    """Splitting at the 15 Dec occurrence keeps 1 and 8 Dec (verified on a phone)."""
    occurrence = datetime(2026, 12, 15, 9, 0, tzinfo=UTC)
    assert (
        rule_ending_before("FREQ=WEEKLY;COUNT=5;BYDAY=TU", occurrence, all_day=False)
        == "FREQ=WEEKLY;BYDAY=TU;UNTIL=20261215T085959Z"
    )


def test_rule_ending_before_keeps_parts_it_does_not_model() -> None:
    """All-day rules end on the day before; unknown parts stay as they are."""
    occurrence = datetime(2026, 12, 4, tzinfo=UTC)
    assert (
        rule_ending_before(
            "FREQ=MONTHLY;BYSETPOS=-1;BYDAY=MO,FR;UNTIL=20271231",
            occurrence,
            all_day=True,
        )
        == "FREQ=MONTHLY;BYSETPOS=-1;BYDAY=MO,FR;UNTIL=20261203"
    )
