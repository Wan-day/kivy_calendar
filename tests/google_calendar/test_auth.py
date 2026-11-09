"""Tests for the Google OAuth credential helpers."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from core.errors import ErrorCode, Result
from google.oauth2.credentials import Credentials
from google_calendar import auth

ENVIRON = {
    "GOOGLE_CLIENT_ID": "client-id",
    "GOOGLE_CLIENT_SECRET": "client-secret",
    "GOOGLE_REFRESH_TOKEN": "refresh-token",
}


@pytest.mark.parametrize(
    "missing_name",
    [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
    ],
)
def test_build_credentials_reports_missing_variables(missing_name: str) -> None:
    """A missing OAuth variable is an error result, not an exception."""
    environ = dict(ENVIRON)
    del environ[missing_name]

    result = auth.build_credentials(environ)

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT
    assert missing_name in result.error.message


def test_build_credentials_returns_refreshable_credentials() -> None:
    """The environment is turned into refreshable OAuth credentials."""
    result = auth.build_credentials(ENVIRON, scopes=("scope-a", "scope-b"))

    assert result.is_ok
    credentials = result.value
    assert isinstance(credentials, Credentials)
    assert credentials.refresh_token == "refresh-token"
    assert credentials.client_id == "client-id"
    assert credentials.client_secret == "client-secret"
    assert credentials.token_uri == auth.GOOGLE_TOKEN_URI
    assert credentials.scopes == ["scope-a", "scope-b"]


def test_build_credentials_accepts_a_single_scope_string() -> None:
    """A single scope string is kept whole instead of split into characters."""
    result = auth.build_credentials(ENVIRON, scopes=auth.CALENDAR_EVENTS_SCOPE)

    assert result.is_ok
    credentials = result.value
    assert credentials is not None
    assert credentials.scopes == [auth.CALENDAR_EVENTS_SCOPE]


def test_obtain_refresh_token_runs_the_installed_app_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper uses the Desktop-app flow and returns the refresh token."""
    flow = Mock()
    credentials = Mock()
    credentials.refresh_token = "new-refresh-token"
    flow.run_local_server.return_value = credentials
    from_client_config = Mock(return_value=flow)
    monkeypatch.setattr(
        auth.InstalledAppFlow,
        "from_client_config",
        from_client_config,
    )

    result = auth.obtain_refresh_token(
        "client-id",
        "client-secret",
        open_browser=False,
    )

    assert result.value == "new-refresh-token"
    client_config, scopes = from_client_config.call_args.args
    assert client_config["installed"]["client_id"] == "client-id"
    assert client_config["installed"]["client_secret"] == "client-secret"
    assert scopes == list(auth.CALENDAR_SCOPES)
    flow.run_local_server.assert_called_once_with(
        port=0,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )


def test_obtain_refresh_token_requires_the_client_credentials() -> None:
    """The browser flow is not started without a client id and secret."""
    result = auth.obtain_refresh_token(environ={})

    assert result.error is not None
    assert result.error.code is ErrorCode.INVALID_ARGUMENT
    assert "GOOGLE_CLIENT_ID" in result.error.message
    assert "GOOGLE_CLIENT_SECRET" in result.error.message


def test_obtain_refresh_token_reports_a_missing_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consent without offline access is a clear upstream error."""
    flow = Mock()
    flow.run_local_server.return_value = Mock(refresh_token=None)
    monkeypatch.setattr(
        auth.InstalledAppFlow,
        "from_client_config",
        Mock(return_value=flow),
    )

    result = auth.obtain_refresh_token(
        "client-id",
        "client-secret",
        open_browser=False,
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert "refresh token" in result.error.message


def test_obtain_refresh_token_returns_errors_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed browser flow crosses the module boundary as a Result."""
    monkeypatch.setattr(
        auth.InstalledAppFlow,
        "from_client_config",
        Mock(side_effect=RuntimeError("browser failed")),
    )

    result = auth.obtain_refresh_token(
        "client-id",
        "client-secret",
        open_browser=False,
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.UPSTREAM_ERROR
    assert "browser failed" in result.error.message


def test_main_prints_the_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The one-time helper prints a copyable .env line."""
    monkeypatch.setattr(
        auth,
        "obtain_refresh_token",
        lambda **_: Result.ok("printed-token"),
    )

    exit_code = auth.main(environ=ENVIRON, open_browser=False)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "GOOGLE_REFRESH_TOKEN=printed-token" in output
