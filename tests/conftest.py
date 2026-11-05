"""Pytest configuration for the backend test suite."""

import sys
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
