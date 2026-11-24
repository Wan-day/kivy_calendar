"""Pytest configuration for the backend test suite."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED_SRC = ROOT / "shared" / "src"
BACKEND_SRC = ROOT / "backend" / "src"
CLIENT_SRC = ROOT / "client" / "src"

for source_dir in (SHARED_SRC, BACKEND_SRC, CLIENT_SRC):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
