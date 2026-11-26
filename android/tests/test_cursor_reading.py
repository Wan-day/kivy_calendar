"""Reading rows from an Android cursor makes one pyjnius call per cell."""

from __future__ import annotations

from phone_calendar.store import read_rows


class FakeCursor:
    """The few ``android.database.Cursor`` methods the reader may use."""

    def __init__(self, names: list[str], rows: list[list[str | None]]) -> None:
        self._names = names
        self._rows = rows
        self._at = -1
        self.calls: list[str] = []

    def getColumnIndex(self, name: str) -> int:  # noqa: N802 - Android's name
        self.calls.append("getColumnIndex")
        return self._names.index(name) if name in self._names else -1

    def moveToNext(self) -> bool:  # noqa: N802 - Android's name
        self.calls.append("moveToNext")
        self._at += 1
        return self._at < len(self._rows)

    def getString(self, index: int) -> str | None:  # noqa: N802 - Android's name
        self.calls.append("getString")
        return self._rows[self._at][index]


def test_reads_text_numbers_and_nulls() -> None:
    cursor = FakeCursor(
        ["event_id", "title", "begin", "original_id", "rrule"],
        [["7", "Dentist", "1700000000000", None, None], ["8", "", "0", "7", "x"]],
    )

    rows = read_rows(cursor, ("event_id", "title", "begin", "original_id", "rrule"))

    assert rows == [
        {
            "event_id": 7,
            "title": "Dentist",
            "begin": 1700000000000,
            "original_id": None,
            "rrule": None,
        },
        {"event_id": 8, "title": "", "begin": 0, "original_id": 7, "rrule": "x"},
    ]


def test_text_columns_that_look_like_numbers_stay_text() -> None:
    cursor = FakeCursor(["title", "eventTimezone"], [["123", "007"]])

    assert read_rows(cursor, ("title", "eventTimezone")) == [
        {"title": "123", "eventTimezone": "007"}
    ]


def test_missing_columns_read_as_none() -> None:
    cursor = FakeCursor(["_id"], [["3"]])

    assert read_rows(cursor, ("_id", "calendar_color")) == [
        {"_id": 3, "calendar_color": None}
    ]


def test_integer_column_with_odd_text_is_kept() -> None:
    cursor = FakeCursor(["begin", "end"], [["2.5", "soon"]])

    assert read_rows(cursor, ("begin", "end")) == [{"begin": 2.5, "end": "soon"}]


def test_one_call_per_cell() -> None:
    columns = ("_id", "title", "begin")
    cursor = FakeCursor(list(columns), [["1", "a", "2"]] * 100)

    read_rows(cursor, columns)

    assert cursor.calls.count("getString") == 300
    assert cursor.calls.count("moveToNext") == 101
    assert cursor.calls.count("getColumnIndex") == 3
