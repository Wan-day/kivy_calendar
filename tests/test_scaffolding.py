"""Smoke tests for the Phase 1 backend scaffolding."""

from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"
EXPECTED_MODULES = ("api", "google_calendar", "sync", "cache", "retry")


def test_backend_scaffolding_modules_exist() -> None:
    for module_name in EXPECTED_MODULES:
        module_path = BACKEND_SRC / module_name / "__init__.py"
        assert module_path.is_file(), f"missing backend/src/{module_name}/__init__.py"
