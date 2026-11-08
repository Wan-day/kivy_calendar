"""Pytest configuration for the backend test suite."""

import sys
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"
CLIENT_SRC = Path(__file__).resolve().parents[1] / "client" / "src"

for source_dir in (BACKEND_SRC, CLIENT_SRC):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
