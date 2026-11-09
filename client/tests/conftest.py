"""Pytest configuration for the client test suite."""

import sys
from pathlib import Path

CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"

if str(CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(CLIENT_SRC))
