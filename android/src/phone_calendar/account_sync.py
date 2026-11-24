"""Ask Android to sync the accounts behind the phone's calendars.

Android's own sync adapters (Google's, for instance) carry calendar changes
to and from the account's server; this module only requests a sync and asks
whether one is still running. :class:`JniAccountSync` is Android only.
"""

from __future__ import annotations

from typing import Protocol

Account = tuple[str, str]
"""An ``(account_name, account_type)`` pair."""


class AccountSync(Protocol):
    """What the service needs from Android's account sync."""

    def request(self, accounts: list[Account]) -> None:
        """Ask Android to sync the calendars of each account now."""
        ...

    def busy(self, accounts: list[Account]) -> bool:
        """Whether any of the accounts is still syncing or waiting to."""
        ...


class NoAccountSync:
    """Does nothing; for builds and tests without Android's sync."""

    def request(self, accounts: list[Account]) -> None:
        """Ignore the request."""

    def busy(self, accounts: list[Account]) -> bool:
        """Never busy."""
        return False


class JniAccountSync:
    """:class:`AccountSync` backed by Android's ``ContentResolver``.

    Only importable on Android (it needs pyjnius). Calls raise pyjnius'
    ``JavaException`` on failure; the service turns those into errors.
    """

    def __init__(self) -> None:
        """Look up the Android classes once."""
        from jnius import autoclass  # type: ignore[import-not-found]

        self._resolver = autoclass("android.content.ContentResolver")
        self._account = autoclass("android.accounts.Account")
        self._bundle = autoclass("android.os.Bundle")
        self._authority = autoclass("android.provider.CalendarContract").AUTHORITY

    def request(self, accounts: list[Account]) -> None:
        """Request an immediate, user-initiated sync of each account."""
        for name, kind in accounts:
            extras = self._bundle()
            extras.putBoolean(self._resolver.SYNC_EXTRAS_MANUAL, True)
            extras.putBoolean(self._resolver.SYNC_EXTRAS_EXPEDITED, True)
            self._resolver.requestSync(
                self._account(name, kind), self._authority, extras
            )

    def busy(self, accounts: list[Account]) -> bool:
        """Whether any account's calendar sync is active or pending."""
        for name, kind in accounts:
            account = self._account(name, kind)
            if self._resolver.isSyncActive(account, self._authority):
                return True
            if self._resolver.isSyncPending(account, self._authority):
                return True
        return False
