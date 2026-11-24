[app]

title = Kivy Calendar
package.name = kivycalendar
package.domain = io.github.wanday

# android/build.sh copies the app code here before every build.
source.dir = app
source.include_exts = py,ttf,txt

# The version comes from the client, which a test keeps equal to VERSION.
version.regex = __version__ = ['"](.*)['"]
version.filename = %(source.dir)s/kivy_calendar/__init__.py

# python3 and kivy versions come from the pinned python-for-android release
# (Python 3.14.2, Kivy 2.3.1). pydantic 2.12.3 is the release that matches its
# pydantic-core 2.41.4 recipe; tzdata gives zoneinfo the time zone database,
# which Python cannot read from Android itself.
requirements = python3,kivy,pydantic==2.12.3,pydantic-core,annotated-types,typing-extensions,typing-inspection,tzdata

orientation = portrait
fullscreen = 0

# No permissions yet: the 0.1.0 build runs on in-memory sample events.
# READ_CALENDAR and WRITE_CALENDAR arrive with the Android provider (0.2.0).
android.permissions =

android.api = 34
android.minapi = 26
# x86_64 runs on the emulator. Add arm64-v8a ("arm64-v8a, x86_64") to install
# on a phone; it roughly doubles build time and APK size.
android.archs = x86_64
android.accept_sdk_license = True
android.allow_backup = False

# Same release that was checked for the Python, Kivy and pydantic versions.
p4a.branch = v2026.05.09

[buildozer]

log_level = 2
warn_on_root = 1
