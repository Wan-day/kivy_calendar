"""Pytest configuration for the Android-only code (runs on desktop)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for source_dir in (
    ROOT / "android" / "src",
    ROOT / "shared" / "src",
    ROOT / "client" / "src",
):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
