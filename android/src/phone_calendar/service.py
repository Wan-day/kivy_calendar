"""The calendar service the screens use on Android.

It implements the client's :class:`~kivy_calendar.service.CalendarService` on
top of :class:`~phone_calendar.provider.AndroidCalendarProvider`, and the
client's access gate, so the app can ask for calendar permission first.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from core.errors import ErrorCode, Result
from domain.event import Event
from domain.timezones import list_time_zones
from kivy_calendar.models import (
    CalendarEvent,
    CalendarSummary,
    EditScope,
    FreeSlot,
    ServiceError,
    TimeZoneOption,
)
from phone_calendar.account_sync import AccountSync, NoAccountSync
from phone_calendar.permissions import CalendarPermissions
from phone_calendar.provider import (
    DEFAULT_FUTURE,
    DEFAULT_PAST,
    AndroidCalendarProvider,
)
from slots.service import SlotService

logger = logging.getLogger(__name__)

_MAX_ERROR_LENGTH = 160
_JVM_PREFIX = "JVM exception occurred: "
MOVE_ONE_MESSAGE = (
    "one occurrence can't move to another calendar; choose "
    "\u201cThis and following events\u201d or \u201cAll events\u201d"
)


class PhoneCalendarService:
    """The phone's calendars for the screens: list, save, move and delete.

    Repeating events are changed and deleted for one occurrence, for an
    occurrence and the ones after it, or as a whole, and new events can
    repeat.
    """

    # Read by the event form: what it may offer for repeating events.
    repeat_scopes = (EditScope.THIS, EditScope.FOLLOWING, EditScope.ALL)
    edits_repeat_rules = True

    # Read by the event form after a save or delete: writes land in the phone's
    # calendar first and Android syncs them to the account later.
    saved_notice = "Saved on the phone. Android syncs it to your account."
    deleted_notice = "Deleted on the phone. Android syncs it to your account."

    def __init__(
        self,
        provider: AndroidCalendarProvider,
        permissions: CalendarPermissions,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        account_sync: AccountSync | None = None,
        sync_timeout: float = 30.0,
        sync_poll: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create the service.

        ``account_sync`` asks Android to sync (default: does nothing);
        ``sync()`` waits up to ``sync_timeout`` seconds, polling every
        ``sync_poll``. ``clock`` and ``sleep`` can be replaced in tests.
        """
        self._provider = provider
        self._permissions = permissions
        self._slots = SlotService(provider)
        self._now = now
        self._account_sync = account_sync or NoAccountSync()
        self._sync_timeout = sync_timeout
        self._sync_poll = sync_poll
        self._clock = clock
        self._sleep = sleep

    # Access gate -----------------------------------------------------------

    def has_access(self) -> bool:
        """Whether calendar permission is granted."""
        return self._permissions.granted()

    def request_access(self, on_result: Callable[[bool], None]) -> None:
        """Ask Android for calendar permission."""
        self._permissions.request(on_result)

    def open_settings(self) -> None:
        """Open the app's settings page so access can be granted there."""
        self._permissions.open_settings()

    # CalendarService ---------------------------------------------------------

    def list_events(self) -> list[CalendarEvent]:
        """Return occurrences from a year ago to a year ahead."""
        now = self._now()
        events = _value(
            self._provider.list_events(now - DEFAULT_PAST, now + DEFAULT_FUTURE)
        )
        # Not knowing which events are unsynced must not hide the events.
        unsynced = self._provider.unsynced_event_ids().value or set()
        return [
            _client_event(
                event, queued=(event.recurring_event_id or event.id) in unsynced
            )
            for event in events
        ]

    def list_calendars(self) -> list[CalendarSummary]:
        """Return the calendars events can be written to."""
        calendars = _value(self._provider.list_calendars())
        return [
            CalendarSummary(
                id=calendar.id, summary=calendar.summary, primary=calendar.primary
            )
            for calendar in calendars
        ]

    def list_time_zones(self) -> list[TimeZoneOption]:
        """Return the curated time zones the backend offers too."""
        return [
            TimeZoneOption(name=option.name, label=option.label)
            for option in list_time_zones(self._now())
        ]

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        """Save a new event in the phone's calendar."""
        saved = _value(self._provider.create_event(_domain_event(event)))
        return _client_event(saved)

    def update_event(
        self,
        event: CalendarEvent,
        source_calendar_id: str = "",
        scope: EditScope = EditScope.THIS,
    ) -> CalendarEvent:
        """Save changes; a different calendar moves the event there.

        The changes are written in the event's current calendar
        (``source_calendar_id``) first, then the event is moved. For an
        occurrence of a repeating event, ``scope`` picks the occurrences;
        a single occurrence cannot move to another calendar.
        """
        target = event.calendar_id
        current = source_calendar_id or target
        moving = bool(target and current and target != current)
        domain = _domain_event(event).model_copy(update={"calendar_id": current})
        provider = self._provider
        if event.recurring_event_id is None:
            saved = _value(provider.update_event(domain))
        elif scope == EditScope.FOLLOWING:
            return _client_event(
                _value(provider.update_following(domain, target if moving else ""))
            )
        elif scope == EditScope.ALL:
            saved = _value(provider.update_series(domain))
        else:
            if moving:
                raise ServiceError("invalid_state", MOVE_ONE_MESSAGE)
            saved = _value(provider.update_occurrence(domain))
        if moving:
            if saved.recurring_event_id is not None:
                saved = _value(provider.move_series(saved.id, target))
            else:
                saved = _value(provider.move_event(current, saved.id, target))
        return _client_event(saved)

    def delete_event(
        self,
        event_id: str,
        calendar_id: str = "",
        scope: EditScope = EditScope.THIS,
    ) -> bool:
        """Delete an event; phone writes are never queued.

        Occurrences of a series (ids ``<id>_<begin>``) go by ``scope``.
        """
        provider = self._provider
        if "_" not in event_id:
            _check(provider.delete_event(calendar_id, event_id))
        elif scope == EditScope.FOLLOWING:
            _check(provider.delete_following(event_id))
        elif scope == EditScope.ALL:
            _check(provider.delete_series(event_id))
        else:
            _check(provider.delete_occurrence(event_id))
        return False

    def sync(self) -> int:
        """Ask Android to sync the calendar accounts, then re-read.

        Waits until Android reports the sync finished or the timeout passes
        (the events are re-read either way). Local calendars never sync.
        """
        accounts = _value(self._provider.accounts())
        if accounts:
            self._sync_accounts(accounts)
        return len(self.list_events())

    def _sync_accounts(self, accounts: list[tuple[str, str]]) -> None:
        """Request a sync and wait for it.

        A failed request is an error. A failed "still busy?" check only stops
        the wait, because the request already went out and the list is
        re-read anyway.
        """
        try:
            self._account_sync.request(accounts)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            logger.exception("requesting an Android sync failed")
            raise ServiceError(
                "upstream_error",
                f"Android could not start a sync: {_short_error(error)}",
            ) from error
        try:
            deadline = self._clock() + self._sync_timeout
            # Android may not report a just-requested sync as pending yet, so
            # give it one poll before the first "still busy?" check.
            self._sleep(self._sync_poll)
            while self._account_sync.busy(accounts) and self._clock() < deadline:
                self._sleep(self._sync_poll)
        except Exception as error:  # noqa: BLE001 - JNI raises JavaException
            logger.warning(
                "checking the Android sync state failed (%s); not waiting",
                _short_error(error),
                exc_info=True,
            )

    def find_free_slots(
        self,
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        time_zone: str,
    ) -> list[FreeSlot]:
        """Find free windows in the phone's calendars."""
        slots = _value(
            self._slots.find_free_slots(
                duration=timedelta(minutes=duration_minutes),
                window_start=window_start,
                window_end=window_end,
                time_zone=time_zone,
            )
        )
        return [FreeSlot(start=slot.start, end=slot.end) for slot in slots]


def _short_error(error: BaseException) -> str:
    """One short line for an exception, without JVM prefixes or stack trace."""
    text = str(error).strip()
    line = text.splitlines()[0] if text else ""
    line = line.replace(_JVM_PREFIX, "", 1)
    line = re.sub(r"\bjava\.lang\.", "", line, count=1)
    line = " ".join(line.split()) or type(error).__name__
    if len(line) > _MAX_ERROR_LENGTH:
        line = line[: _MAX_ERROR_LENGTH - 1].rstrip() + "…"
    return line


def _check[T](result: Result[T]) -> None:
    """Raise a failed result as a ServiceError for the screens."""
    if result.error is not None:
        code = result.error.code
        message = result.error.message or code.value
        if code == ErrorCode.PERMISSION_DENIED:
            message = "Calendar access is not granted. Allow it in the app settings."
        raise ServiceError(code.value, message)


def _value[T](result: Result[T]) -> T:
    """Return a result's value or raise it as a ServiceError for the screens."""
    _check(result)
    if result.value is None:
        raise ServiceError("upstream_error", "the phone calendar returned nothing")
    return result.value


def _domain_event(event: CalendarEvent) -> Event:
    """Turn the screens' event into the shared model, reporting bad input."""
    try:
        return Event(
            id=event.id,
            calendar_id=event.calendar_id,
            recurring_event_id=event.recurring_event_id,
            all_day=event.all_day,
            start=event.start,
            end=event.end,
            start_timezone=event.start_timezone,
            end_timezone=event.end_timezone,
            summary=event.summary,
            description=event.description,
            recurrence=event.recurrence,
            extended_properties=dict(event.extended_properties or {}),
        )
    except ValidationError as error:
        raise ServiceError(
            "invalid_event", f"the event is not valid: {error}"
        ) from error


def _client_event(event: Event, queued: bool = False) -> CalendarEvent:
    """Turn a shared event into the screens' event type.

    ``queued`` marks an event whose change has not reached the account yet.
    """
    return CalendarEvent(
        id=event.id,
        summary=event.summary,
        start=event.start,
        end=event.end,
        start_timezone=event.start_timezone,
        end_timezone=event.end_timezone,
        calendar_id=event.calendar_id,
        recurring_event_id=event.recurring_event_id,
        all_day=event.all_day,
        description=event.description,
        recurrence=list(event.recurrence) if event.recurrence else None,
        extended_properties=dict(event.extended_properties) or None,
        queued=queued,
    )
