"""Tests for the shared error-result convention."""

from core.errors import ErrorCode, Result


def test_result_ok_carries_value() -> None:
    """A successful result exposes its value and no error."""
    result: Result[int] = Result.ok(42)

    assert result.is_ok
    assert not result.is_error
    assert result.value == 42
    assert result.error is None


def test_result_fail_carries_error() -> None:
    """A failed result exposes an error code and message."""
    result: Result[int] = Result.fail(ErrorCode.NOT_FOUND, "event is missing")

    assert result.is_error
    assert not result.is_ok
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.NOT_FOUND
    assert result.error.message == "event is missing"


def test_result_fail_defaults_to_an_empty_message() -> None:
    """The error message is optional."""
    result: Result[int] = Result.fail(ErrorCode.INVALID_ARGUMENT)

    assert result.error is not None
    assert result.error.message == ""
