"""Pytest configuration for the client test suite."""

import sys
from pathlib import Path

CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"
# The phone build's repeat rules (domain.recurrence) for the event form.
SHARED_SRC = Path(__file__).resolve().parents[2] / "shared" / "src"

for source_dir in (SHARED_SRC, CLIENT_SRC):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
