"""Smoke tests for the backend and shared package layout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
SHARED_SRC = ROOT / "shared" / "src"
BACKEND_MODULES = ("api", "google_calendar", "sync", "cache", "retry")
SHARED_MODULES = ("core", "domain", "slots")


def test_backend_scaffolding_modules_exist() -> None:
    for module_name in BACKEND_MODULES:
        module_path = BACKEND_SRC / module_name / "__init__.py"
        assert module_path.is_file(), f"missing backend/src/{module_name}/__init__.py"


def test_shared_modules_exist() -> None:
    for module_name in SHARED_MODULES:
        module_path = SHARED_SRC / module_name / "__init__.py"
        assert module_path.is_file(), f"missing shared/src/{module_name}/__init__.py"
    assert (SHARED_SRC / "calendar_provider.py").is_file()


def test_shared_code_has_no_backend_imports() -> None:
    """Shared code must not import FastAPI, Google clients or backend modules."""
    forbidden = (
        "fastapi",
        "google",
        "googleapiclient",
        "api",
        "cache",
        "retry",
        "sync",
        "google_calendar",
    )
    for path in SHARED_SRC.rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            module = stripped.split()[1].split(".")[0]
            assert module not in forbidden, f"{path}: {stripped}"
