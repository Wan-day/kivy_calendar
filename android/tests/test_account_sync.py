"""Tests for the Sync button's account sync on PhoneCalendarService."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fakes import FakeAccountSync, FakeCalendarStore, FakePermissions, calendar_row

from kivy_calendar.models import ServiceError
from phone_calendar.provider import AndroidCalendarProvider
from phone_calendar.service import PhoneCalendarService
from phone_calendar.store import Row

NOW = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)


class Clock:
    """A fake clock whose sleep advances time."""

    def __init__(self) -> None:
        self.time = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds


def _local_row(calendar_id: int) -> Row:
    row = calendar_row(calendar_id, "On phone", account="Phone")
    row["account_type"] = "LOCAL"
    return row


def _service(
    rows: list[Row], sync: FakeAccountSync, clock: Clock
) -> PhoneCalendarService:
    return PhoneCalendarService(
        AndroidCalendarProvider(FakeCalendarStore(calendars=rows)),
        FakePermissions(),
        now=lambda: NOW,
        account_sync=sync,
        sync_timeout=30,
        sync_poll=1,
        clock=clock.now,
        sleep=clock.sleep,
    )


def test_requests_only_distinct_non_local_accounts() -> None:
    sync = FakeAccountSync()
    rows = [
        calendar_row(1, "Main", account="a@example.com"),
        calendar_row(2, "Other", account="a@example.com"),
        calendar_row(3, "Work", account="b@example.com"),
        _local_row(4),
    ]
    assert _service(rows, sync, Clock()).sync() == 0
    assert sync.requests == [
        [("a@example.com", "com.google"), ("b@example.com", "com.google")]
    ]


def test_waits_until_not_busy() -> None:
    sync = FakeAccountSync(busy_polls=3)
    clock = Clock()
    _service([calendar_row(1, "Main")], sync, clock).sync()
    assert clock.sleeps == [1, 1, 1]
    assert sync.polls == 4


def test_gives_up_after_timeout_and_still_returns_count() -> None:
    sync = FakeAccountSync(forever=True)
    clock = Clock()
    assert _service([calendar_row(1, "Main")], sync, clock).sync() == 0
    assert clock.time == 30


def test_no_accounts_means_no_request() -> None:
    sync = FakeAccountSync()
    assert _service([_local_row(1)], sync, Clock()).sync() == 0
    assert sync.requests == []
    assert sync.polls == 0


def test_jni_failure_becomes_service_error() -> None:
    sync = FakeAccountSync(error=RuntimeError("JavaException: boom"))
    with pytest.raises(ServiceError, match="sync failed.*boom"):
        _service([calendar_row(1, "Main")], sync, Clock()).sync()


def test_busy_failure_becomes_service_error() -> None:
    class Broken(FakeAccountSync):
        def busy(self, accounts: list[tuple[str, str]]) -> bool:
            raise RuntimeError("nope")

    with pytest.raises(ServiceError):
        _service([calendar_row(1, "Main")], Broken(), Clock()).sync()
