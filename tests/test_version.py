"""The app version is kept in VERSION and repeated in every package."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("shared", "backend", "client")


def _version() -> str:
    return (ROOT / "VERSION").read_text().strip()


def test_version_is_major_minor_patch() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", _version())


def test_every_package_uses_the_app_version() -> None:
    version = _version()
    for package in PACKAGES:
        data = tomllib.loads((ROOT / package / "pyproject.toml").read_text())
        assert data["project"]["version"] == version, (
            f"{package}/pyproject.toml has {data['project']['version']}, "
            f"VERSION has {version}"
        )


def test_client_reports_the_app_version() -> None:
    init = (ROOT / "client" / "src" / "kivy_calendar" / "__init__.py").read_text()
    match = re.search(r'^__version__ = "([^"]+)"$', init, re.MULTILINE)
    assert match is not None, "kivy_calendar/__init__.py has no __version__"
    assert match.group(1) == _version()
