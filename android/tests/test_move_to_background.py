"""Back on the main screen sends the app to the background, never closes it."""

from __future__ import annotations

import sys
import types

import pytest

from phone_calendar import move_task_to_background


def test_without_android_it_reports_failure() -> None:
    """Off a device there is no activity; the call fails quietly."""
    assert move_task_to_background() is False


@pytest.mark.parametrize("accepted", [True, False])
def test_moves_the_task_to_the_back(
    monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    """The activity's moveTaskToBack(True) is called and its answer returned."""
    calls: list[bool] = []

    class Activity:
        def moveTaskToBack(self, non_root: bool) -> bool:  # noqa: N802 - Java name
            calls.append(non_root)
            return accepted

    module = types.ModuleType("android")
    module.mActivity = Activity()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "android", module)
    assert move_task_to_background() is accepted
    assert calls == [True]
