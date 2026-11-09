"""Google OAuth credentials and the one-time refresh-token helper.

The backend authenticates one Google account with an OAuth refresh token.  Put
``GOOGLE_CLIENT_ID``, ``GOOGLE_CLIENT_SECRET`` and ``GOOGLE_REFRESH_TOKEN`` in
the process environment (for local development an untracked ``.env`` file is
loaded by the shell or deployment tool); :func:`build_credentials` turns them
into refreshable :class:`google.oauth2.credentials.Credentials`.

This module never reads ``.env`` itself and never writes secrets to disk.

Getting a refresh token
-----------------------
The OAuth client must be a *Desktop app* client in Google Cloud.  With its id
and secret exported, run the local browser flow from the repository root::

    PYTHONPATH=backend/src python -m google_calendar.auth

The helper starts a temporary server on localhost, opens the consent page, and
prints the refresh token.  Copy the printed value into ``GOOGLE_REFRESH_TOKEN``
in your untracked ``.env`` and keep it out of git.  The helper requests both
``https://www.googleapis.com/auth/calendar.events`` and
``https://www.googleapis.com/auth/calendar.calendarlist.readonly`` so the
backend can discover every calendar on the account.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

from core.errors import ErrorCode, Result

CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = (
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
)
CALENDAR_SCOPES: tuple[str, ...] = (CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE)

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

ENV_CLIENT_ID = "GOOGLE_CLIENT_ID"
ENV_CLIENT_SECRET = "GOOGLE_CLIENT_SECRET"
ENV_REFRESH_TOKEN = "GOOGLE_REFRESH_TOKEN"


def build_credentials(
    environ: Mapping[str, str] | None = None,
    *,
    scopes: str | Sequence[str] = CALENDAR_SCOPES,
) -> Result[Credentials]:
    """Build refreshable credentials from the Google OAuth environment.

    ``environ`` defaults to :data:`os.environ`.  Missing or blank variables are
    reported as ``INVALID_ARGUMENT`` instead of raising, because configuration
    errors are an expected failure at this boundary.  A single scope string is
    accepted and kept whole; it must not be split into individual characters.
    """
    environment = os.environ if environ is None else environ
    client_id = _environment_value(environment, ENV_CLIENT_ID)
    client_secret = _environment_value(environment, ENV_CLIENT_SECRET)
    refresh_token = _environment_value(environment, ENV_REFRESH_TOKEN)
    resolved_scopes = [scopes] if isinstance(scopes, str) else list(scopes)

    missing = [
        name
        for name, value in (
            (ENV_CLIENT_ID, client_id),
            (ENV_CLIENT_SECRET, client_secret),
            (ENV_REFRESH_TOKEN, refresh_token),
        )
        if not value
    ]
    if missing:
        return Result.fail(
            ErrorCode.INVALID_ARGUMENT,
            "missing Google OAuth environment variables: " + ", ".join(missing),
        )

    try:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=resolved_scopes,
        )
    except (TypeError, ValueError) as exc:
        return Result.fail(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid Google OAuth configuration: {exc}",
        )
    return Result.ok(credentials)


def obtain_refresh_token(
    client_id: str | None = None,
    client_secret: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    open_browser: bool = True,
) -> Result[str]:
    """Run the Desktop-app consent flow and return a refresh token.

    This is a one-time local helper, not part of the request path.  It uses
    :class:`google_auth_oauthlib.flow.InstalledAppFlow`, so it needs a real
    browser once and never exposes a web redirect endpoint.
    """
    environment = os.environ if environ is None else environ
    resolved_id = client_id or _environment_value(environment, ENV_CLIENT_ID)
    resolved_secret = client_secret or _environment_value(
        environment, ENV_CLIENT_SECRET
    )
    missing = [
        name
        for name, value in (
            (ENV_CLIENT_ID, resolved_id),
            (ENV_CLIENT_SECRET, resolved_secret),
        )
        if not value
    ]
    if missing:
        return Result.fail(
            ErrorCode.INVALID_ARGUMENT,
            "missing Google OAuth environment variables: " + ", ".join(missing),
        )
    assert resolved_id is not None
    assert resolved_secret is not None

    client_config = _desktop_client_config(resolved_id, resolved_secret)
    try:
        flow = InstalledAppFlow.from_client_config(
            client_config,
            list(CALENDAR_SCOPES),
        )
        credentials = flow.run_local_server(
            port=0,
            open_browser=open_browser,
            access_type="offline",
            prompt="consent",
        )
    except Exception as exc:  # boundary of the interactive browser flow
        return Result.fail(
            ErrorCode.UPSTREAM_ERROR,
            f"Google OAuth flow failed: {exc}",
        )

    refresh_token = credentials.refresh_token
    if not refresh_token:
        return Result.fail(
            ErrorCode.UPSTREAM_ERROR,
            "Google did not return a refresh token; revoke the app's access "
            "in your Google account and run the helper again",
        )
    return Result.ok(refresh_token)


def main(
    *,
    environ: Mapping[str, str] | None = None,
    open_browser: bool = True,
) -> int:
    """Print a refresh token for ``.env`` and return a process exit code."""
    result = obtain_refresh_token(environ=environ, open_browser=open_browser)
    if result.error is not None:
        print(
            f"error: {result.error.code.value}: {result.error.message}",
            file=sys.stderr,
        )
        return 1

    token = result.value
    if token is None:
        print("error: no refresh token was returned", file=sys.stderr)
        return 1
    print("Add this line to your untracked .env file:")
    print(f"{ENV_REFRESH_TOKEN}={token}")
    return 0


def _desktop_client_config(
    client_id: str,
    client_secret: str,
) -> dict[str, Any]:
    """Return the installed-app client config expected by ``InstalledAppFlow``."""
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }


def _environment_value(
    environ: Mapping[str, str],
    name: str,
) -> str | None:
    """Return a stripped environment value, or ``None`` when it is blank."""
    value = environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


if __name__ == "__main__":
    raise SystemExit(main())
