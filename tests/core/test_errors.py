"""Tests for the shared error-result convention."""

from core.errors import Error, ErrorCode, Result, is_retryable


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


def test_upstream_error_code_is_available() -> None:
    """Upstream calendar failures have a stable machine-readable code."""
    assert ErrorCode.UPSTREAM_ERROR == "upstream_error"


def test_only_transient_upstream_errors_are_retryable() -> None:
    """Retrying is reserved for failures that may heal on their own."""
    assert is_retryable(Error(ErrorCode.UPSTREAM_ERROR))

    permanent_codes = [
        ErrorCode.INVALID_ARGUMENT,
        ErrorCode.INVALID_EVENT,
        ErrorCode.NOT_FOUND,
        ErrorCode.ALREADY_EXISTS,
        ErrorCode.INVALID_STATE,
        ErrorCode.STORAGE_ERROR,
        ErrorCode.AUTH_ERROR,
    ]
    for code in permanent_codes:
        assert not is_retryable(Error(code))

