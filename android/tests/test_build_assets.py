"""The icon and splash files that buildozer.spec points at."""

import configparser
import struct
from pathlib import Path

import pytest

ANDROID = Path(__file__).resolve().parents[1]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _spec() -> configparser.SectionProxy:
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(ANDROID / "buildozer.spec")
    return parser["app"]


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == PNG_SIGNATURE, f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", header[16:24])
    return width, height


@pytest.mark.parametrize(
    ("option", "size"),
    [
        ("icon.filename", (512, 512)),
        ("icon.adaptive_foreground.filename", (432, 432)),
        ("icon.adaptive_background.filename", (432, 432)),
        ("presplash.filename", (1080, 1080)),
    ],
)
def test_spec_images_exist_with_their_size(option: str, size: tuple[int, int]) -> None:
    # Buildozer reads these paths relative to android/.
    path = ANDROID / _spec()[option]
    assert path.is_file(), f"{option} points at a missing file"
    assert _png_size(path) == size
    assert path.with_suffix(".svg").is_file(), f"no source SVG for {path.name}"


def test_android_12_splash_uses_the_presplash_colour() -> None:
    spec = _spec()
    assert spec["android.add_resources"] == "res"
    styles = (ANDROID / "res" / "values-v31" / "styles.xml").read_text()
    colour = spec["android.presplash_color"]
    assert f'name="android:windowSplashScreenBackground">{colour}<' in styles
