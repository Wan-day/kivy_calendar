"""SQLite plumbing shared by the cache and the retry queue."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from core.errors import ErrorCode, Result

DEFAULT_DB_FILENAME = "kivy_calendar.db"


def default_database_path() -> Path:
    """Return the default local development database path.

    ``KIVY_CALENDAR_DB_PATH`` overrides the location.  Otherwise the database
    lives under the user's XDG data directory so the repository stays clean.
    """
    override = os.environ.get("KIVY_CALENDAR_DB_PATH")
    if override:
        return Path(override).expanduser()

    data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = (
        Path(data_home).expanduser()
        if data_home
        else Path.home() / ".local" / "share"
    )
    return base_dir / "kivy_calendar" / DEFAULT_DB_FILENAME


class Database:
    """Owns the SQLite file location and opens short-lived connections."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path).expanduser() if path is not None else default_database_path()
        )

    def connect(self) -> sqlite3.Connection:
        """Open a connection, creating the parent directory when needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def run_in_transaction[T](
    database: Database,
    schema: str,
    operation: Callable[[sqlite3.Connection], Result[T]],
) -> Result[T]:
    """Run ``operation`` in a connection after ensuring ``schema`` exists.

    Expected failures are returned as a failed ``Result``.  Writes from a
    failed operation are rolled back, while newly created tables are kept.
    """
    try:
        with closing(database.connect()) as connection:
            connection.executescript(schema)
            result = operation(connection)
            if result.is_error:
                connection.rollback()
                return result
            connection.commit()
            return result
    except sqlite3.Error as exc:
        return Result.fail(ErrorCode.STORAGE_ERROR, str(exc))
    except (TypeError, ValueError) as exc:
        return Result.fail(ErrorCode.STORAGE_ERROR, f"invalid stored data: {exc}")
