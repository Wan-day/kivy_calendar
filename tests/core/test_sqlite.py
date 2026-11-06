"""Tests for shared SQLite configuration."""

import sqlite3
from pathlib import Path

from core.errors import ErrorCode, Result
from core.sqlite import Database, default_database_path, run_in_transaction


def test_database_path_can_be_overridden_by_environment(
    monkeypatch, tmp_path: Path
) -> None:
    """KIVY_CALENDAR_DB_PATH selects a custom SQLite file."""
    custom_path = tmp_path / "custom" / "calendar.db"
    monkeypatch.setenv("KIVY_CALENDAR_DB_PATH", str(custom_path))

    assert default_database_path() == custom_path


def test_default_database_path_uses_the_xdg_data_directory(
    monkeypatch, tmp_path: Path
) -> None:
    """Without an override the database lives under XDG_DATA_HOME."""
    monkeypatch.delenv("KIVY_CALENDAR_DB_PATH", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert default_database_path() == (
        tmp_path / "xdg" / "kivy_calendar" / "kivy_calendar.db"
    )


def test_database_creates_its_parent_directory(tmp_path: Path) -> None:
    """Connecting creates missing directories for a configurable path."""
    database = Database(tmp_path / "nested" / "data" / "calendar.db")

    connection = database.connect()
    connection.close()

    assert database.path.is_file()


def test_run_in_transaction_reports_filesystem_errors(tmp_path: Path) -> None:
    """Unopenable database files become storage errors, not exceptions."""

    class UnavailableDatabase(Database):
        def connect(self) -> sqlite3.Connection:
            raise OSError("disk unavailable")

    result: Result[int] = run_in_transaction(
        UnavailableDatabase(tmp_path / "calendar.db"),
        "",
        lambda connection: Result.ok(0),
    )

    assert result.error is not None
    assert result.error.code is ErrorCode.STORAGE_ERROR
    assert result.error.message == "disk unavailable"
